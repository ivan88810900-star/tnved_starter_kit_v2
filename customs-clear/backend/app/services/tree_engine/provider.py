"""Canonical read-path provider — in-memory кэш CanonicalModel (ADR-0001, Этап 3).

Держит **один** экземпляр ``CanonicalModel`` в памяти и строит его **один раз**
на ревизию входных данных (build-once under lock). Пайплайн построения —
``TreeParser -> TreeBuilder.build_model`` (validator gate уже внутри
``build_model``; здесь его **не** обходим).

Инвалидация кэша по ``revision`` (ADR I19 «snapshot-консистентность»). Ревизия
учитывает **минимум** те входы, что влияют на структуру дерева:

- ``tnved_commodities`` — множество кодов / объём (структура узлов);
- ``hs_rates`` — строки, влияющие на leaf-флаги (``is_leaf_hs_code`` для
  неоднозначных «…0000» кодов), т.к. от них зависит синтез бескодовых L6/L8.

Отказоустойчивость (ADR §9, «не 500 при доступном legacy»): если модель не
строится или validator падает — ошибка **логируется**, провайдер возвращает
``None``, и вызывающий код обязан сделать fallback на legacy path.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Callable

from sqlalchemy import func

from ...db import SessionLocal
from ...models import HsRate
from ...models.tnved import Commodity
from .builder import TreeBuilder
from .canonical_model import CanonicalModel
from .parser import TreeParser

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], object]


class CanonicalTreeProvider:
    """Потокобезопасный singleton-кэш ``CanonicalModel`` c инвалидацией по ревизии."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model: CanonicalModel | None = None
        self._revision: str | None = None
        self._build_count = 0

    # -- public API --------------------------------------------------------

    def get_model(self, *, session_factory: SessionFactory = SessionLocal) -> CanonicalModel | None:
        """Вернуть кэшированную модель или собрать её один раз под локом.

        При ошибке чтения ревизии / построения возвращает ``None`` (fallback на
        legacy), НЕ поднимая исключение наружу.
        """
        try:
            revision = self._compute_revision(session_factory)
        except Exception:  # noqa: BLE001 — ревизия не должна ронять запрос
            logger.exception("CANONICAL_TREE: не удалось вычислить revision; fallback legacy")
            return None

        cached = self._model
        if cached is not None and self._revision == revision:
            return cached

        with self._lock:
            # double-checked locking: пока ждали лок, другой поток мог собрать.
            if self._model is not None and self._revision == revision:
                return self._model
            try:
                model = self._build(session_factory)
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
        builder = TreeBuilder()
        db = session_factory()
        try:
            parsed = parser.parse(db)  # type: ignore[arg-type]
        finally:
            db.close()  # type: ignore[attr-defined]
        # validator gate — внутри build_model (не обходим).
        return builder.build_model(parsed)

    def _compute_revision(self, session_factory: SessionFactory) -> str:
        """Короткая ревизия входов, влияющих на структуру дерева.

        - commodities: count + max(id) (детект импорта/усечения);
        - hs_rates leaf-relevant: множество ``hs_code`` с суффиксом «0000»
          (только они влияют на ``is_leaf_hs_code`` → синтез бескодовых узлов),
          свёрнутое в хеш. Существование строки, а не её значение, определяет
          leaf-флаг, поэтому хеш множества кодов точен для этого входа.
        """
        db = session_factory()
        try:
            nc = db.query(func.count()).select_from(Commodity).scalar() or 0  # type: ignore[attr-defined]
            mxc = db.query(func.max(Commodity.id)).scalar() or 0  # type: ignore[attr-defined]
            leaf_rows = (
                db.query(HsRate.hs_code)  # type: ignore[attr-defined]
                .filter(HsRate.hs_code.like("%0000"))
                .all()
            )
        finally:
            db.close()  # type: ignore[attr-defined]
        leaf_codes = sorted(code for (code,) in leaf_rows if code)
        leaf_hash = hashlib.sha1("\n".join(leaf_codes).encode("utf-8")).hexdigest()[:16]
        return f"c={nc}:{mxc}|hr={len(leaf_codes)}:{leaf_hash}"


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
