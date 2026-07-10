"""Canonical read-path provider — in-memory кэш CanonicalModel (ADR-0001, Этап 3).

Держит **один** экземпляр ``CanonicalModel`` в памяти и строит его **один раз**
на ревизию входных данных (build-once under lock). Пайплайн построения —
``TreeParser -> TreeBuilder.build_model`` (validator gate уже внутри
``build_model``; здесь его **не** обходим).

Инвалидация кэша по отдельной content-revision (ADR I19): значимые поля
``tnved_commodities``, Section/Chapter metadata и leaf-relevant ``hs_rates``.
Это cache-key runtime, а не неполный ``CanonicalModel.snapshot_id``.

Отказоустойчивость (ADR §9, «не 500 при доступном legacy»): если модель не
строится или validator падает — ошибка **логируется**, провайдер возвращает
``None``, и вызывающий код обязан сделать fallback на legacy path.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import threading
from typing import Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from ...db import SessionLocal
from ...models import HsRate
from ...models.tnved import Chapter, Commodity, Section
from .builder import TreeBuilder
from .canonical_model import CanonicalModel
from .parser import TreeParser

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]

_REVISION_VERSION = "v2"
_MAX_CONSISTENT_BUILD_ATTEMPTS = 3


class CanonicalTreeProvider:
    """Потокобезопасный singleton-кэш ``CanonicalModel`` c инвалидацией по ревизии."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._model: CanonicalModel | None = None
        self._revision: str | None = None
        self._source_token: tuple | None = None
        self._source_revision: str | None = None
        self._build_count = 0

    # -- public API --------------------------------------------------------

    def get_model(self, *, session_factory: SessionFactory = SessionLocal) -> CanonicalModel | None:
        """Вернуть кэшированную модель или собрать её один раз под локом.

        При ошибке чтения ревизии / построения возвращает ``None`` (fallback на
        legacy), НЕ поднимая исключение наружу.
        """
        try:
            revision = self._get_revision(session_factory)
        except Exception:  # noqa: BLE001 — ревизия не должна ронять запрос
            logger.exception("CANONICAL_TREE: не удалось вычислить revision; fallback legacy")
            return None

        cached = self._model
        if cached is not None and self._revision == revision:
            return cached

        with self._lock:
            try:
                # Пока ждали lock, данные или кэш могли измениться. Повторное
                # вычисление не даёт сохранить модель под устаревшим ключом.
                revision = self._get_revision(session_factory)
                if self._model is not None and self._revision == revision:
                    return self._model
                model, revision = self._build_consistent(
                    session_factory,
                    initial_revision=revision,
                )
            except Exception:  # noqa: BLE001 — валидатор/сборка не должны ронять запрос
                logger.exception(
                    "CANONICAL_TREE: сборка CanonicalModel не удалась; fallback legacy"
                )
                return None
            self._model = model
            self._revision = revision
            self._build_count += 1
            logger.info(
                "CANONICAL_TREE: модель собрана (revision=%s, nodes=%d, build#%d)",
                revision,
                len(model),
                self._build_count,
            )
            return model

    def reset(self) -> None:
        """Сбросить кэш (тесты / принудительная инвалидация)."""
        with self._lock:
            self._model = None
            self._revision = None
            with self._probe_lock:
                self._source_token = None
                self._source_revision = None

    @property
    def build_count(self) -> int:
        """Сколько раз реально строилась модель (для проверки build-once)."""
        return self._build_count

    @property
    def current_revision(self) -> str | None:
        return self._revision

    # -- internals ---------------------------------------------------------

    def _build(self, session_factory: SessionFactory) -> CanonicalModel:
        parser = TreeParser()
        builder = TreeBuilder(session_factory=session_factory)
        db = session_factory()
        try:
            parsed = parser.parse(db)
        finally:
            db.close()
        # validator gate — внутри build_model (не обходим).
        return builder.build_model(parsed)

    def _build_consistent(
        self,
        session_factory: SessionFactory,
        *,
        initial_revision: str,
    ) -> tuple[CanonicalModel, str]:
        """Собрать модель только для стабильного снимка входов.

        Revision проверяется после build. Если ingestion изменил данные между
        pre-check и сборкой, результат отбрасывается и строится заново. Это
        предотвращает публикацию новой модели под старым cache-key.
        """
        revision_before = initial_revision
        for attempt in range(1, _MAX_CONSISTENT_BUILD_ATTEMPTS + 1):
            model = self._build(session_factory)
            revision_after = self._get_revision(session_factory)
            if revision_before == revision_after:
                return model, revision_after
            logger.warning(
                "CANONICAL_TREE: входы изменились во время сборки "
                "(attempt=%d/%d, before=%s, after=%s); retry",
                attempt,
                _MAX_CONSISTENT_BUILD_ATTEMPTS,
                revision_before,
                revision_after,
            )
            revision_before = revision_after
        raise RuntimeError(
            "CanonicalModel inputs kept changing during build; consistent snapshot unavailable"
        )

    def _get_revision(self, session_factory: SessionFactory) -> str:
        """Вернуть exact revision, не сканируя каталог при отсутствии DB writes.

        Для SQLite дешёвый token — stat основного файла и WAL; для PostgreSQL —
        текущий WAL LSN. Если token не изменился, ранее вычисленный content hash
        остаётся точным. При смене token полный hash пересчитывается и проверяется
        повторным token-read, чтобы не кэшировать смешанный снимок.
        """
        token_before = self._read_source_token(session_factory)
        if token_before is None:
            return self._compute_revision(session_factory)

        cached_token = self._source_token
        cached_revision = self._source_revision
        if cached_revision is not None and cached_token == token_before:
            return cached_revision

        with self._probe_lock:
            token_before = self._read_source_token(session_factory)
            if self._source_revision is not None and self._source_token == token_before:
                return self._source_revision
            for _ in range(_MAX_CONSISTENT_BUILD_ATTEMPTS):
                revision = self._compute_revision(session_factory)
                token_after = self._read_source_token(session_factory)
                if token_before == token_after:
                    self._source_token = token_after
                    self._source_revision = revision
                    return revision
                token_before = token_after
        raise RuntimeError("Database kept changing while canonical revision was computed")

    def _read_source_token(self, session_factory: SessionFactory) -> tuple | None:
        """Дешёвый cross-process маркер записи, не заменяющий content hash."""
        db = session_factory()
        try:
            bind = db.get_bind()
            dialect = bind.dialect.name
            if dialect == "sqlite":
                database = bind.url.database
                if not database or database == ":memory:":
                    return None
                path = Path(database).expanduser().resolve()
                stats: list[tuple[str, int, int, int, int] | tuple[str]] = []
                for candidate in (path, Path(f"{path}-wal")):
                    try:
                        stat = candidate.stat()
                    except OSError:
                        stats.append((candidate.name,))
                    else:
                        stats.append(
                            (
                                candidate.name,
                                stat.st_ino,
                                stat.st_size,
                                stat.st_mtime_ns,
                                stat.st_ctime_ns,
                            )
                        )
                return ("sqlite", str(path), *stats)
            if dialect == "postgresql":
                lsn = db.execute(text("SELECT pg_current_wal_lsn()::text")).scalar()
                return ("postgresql", str(lsn))
            return None
        finally:
            db.close()

    def _compute_revision(self, session_factory: SessionFactory) -> str:
        """Точный content fingerprint всех входов CanonicalModel.

        ``count + max(id)`` недостаточен: UPDATE существующей строки оставлял
        cache-key прежним и runtime отдавал устаревшие name/import_duty/notes.
        Здесь хешируются только выбранные скалярные колонки (без ORM-объектов):

        - все поля ``tnved_commodities``, которые читает ``TreeParser``;
        - Section/Chapter metadata, формирующие ``chapter_notes``;
        - множество leaf-relevant ``hs_rates`` для неоднозначных ``*0000``.

        Порядок строк фиксирован. Любой insert/delete/in-place update значимого
        входа меняет digest; изменение ставки у уже подтверждённого leaf — нет,
        потому что на структуру влияет существование строки, а не значение ставки.
        """
        db = session_factory()
        try:
            digest = hashlib.sha256()
            digest.update(f"canonical-revision:{_REVISION_VERSION}".encode("ascii"))

            commodity_rows = (
                db.query(
                    Commodity.code,
                    Commodity.description,
                    Commodity.import_duty,
                    Commodity.chapter_id,
                    Commodity.unit,
                    Commodity.supp_unit,
                    Commodity.weight_coeff,
                )
                .order_by(Commodity.code.asc())
            )
            commodity_count = self._hash_rows(digest, "commodities", commodity_rows)

            section_rows = (
                db.query(
                    Section.id,
                    Section.roman_number,
                    Section.title,
                    Section.notes,
                )
                .order_by(Section.id.asc())
            )
            section_count = self._hash_rows(digest, "sections", section_rows)

            chapter_rows = (
                db.query(
                    Chapter.id,
                    Chapter.section_id,
                    Chapter.code,
                    Chapter.title,
                    Chapter.notes,
                )
                .order_by(Chapter.id.asc())
            )
            chapter_count = self._hash_rows(digest, "chapters", chapter_rows)

            leaf_rows = (
                db.query(HsRate.hs_code)
                .join(Commodity, Commodity.code == HsRate.hs_code)
                .filter(Commodity.code.like("%0000"))
                .distinct()
                .order_by(HsRate.hs_code.asc())
            )
            leaf_count = self._hash_rows(digest, "leaf_rates", leaf_rows)
        finally:
            db.close()
        return (
            f"{_REVISION_VERSION}:c={commodity_count}:s={section_count}:"
            f"ch={chapter_count}:hr={leaf_count}:{digest.hexdigest()[:24]}"
        )

    @classmethod
    def _hash_rows(cls, digest, label: str, rows) -> int:  # noqa: ANN001
        """Добавить ordered rows в length-delimited hash без коллизий разделителя."""
        cls._hash_value(digest, label)
        count = 0
        for row in rows:
            count += 1
            cls._hash_value(digest, count)
            for value in row:
                cls._hash_value(digest, value)
        cls._hash_value(digest, f"/{label}:{count}")
        return count

    @staticmethod
    def _hash_value(digest, value) -> None:  # noqa: ANN001
        if value is None:
            payload = b"<null>"
        elif isinstance(value, float):
            payload = format(value, ".17g").encode("ascii")
        else:
            payload = str(value).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)


# Модульный singleton (in-memory на процесс).
_provider = CanonicalTreeProvider()


def get_canonical_model(*, session_factory: SessionFactory = SessionLocal) -> CanonicalModel | None:
    """Фасад: кэшированная CanonicalModel или ``None`` (→ fallback legacy)."""
    return _provider.get_model(session_factory=session_factory)


def reset_canonical_provider() -> None:
    """Сброс кэша singleton-провайдера (тесты / ручная инвалидация)."""
    _provider.reset()


def get_provider() -> CanonicalTreeProvider:
    """Доступ к singleton-провайдеру (диагностика / тесты build-once)."""
    return _provider
