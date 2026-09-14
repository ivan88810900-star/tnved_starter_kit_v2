"""Импорт реестров СС/ДС Росаккредитации из opendata (7736638268-rss / 7736638268-rds)."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from loguru import logger
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models.tnved import FsaCertificate, OpendataSyncLog
from .opendata_client import (
    FSA_BASE,
    backend_opendata_dir,
    download_bytes,
    download_file,
    fetch_fsa_meta,
    ordered_versions,
    require_no_snapshot_rollback,
    snapshot_date_from_id,
)
from .opendata_snapshot_evidence import (
    acquire_opendata_write_lock,
    canonical_rows_fingerprint,
    encode_fsa_snapshot_details,
    fsa_structure_sha_from_details,
    fsa_snapshot_details_match,
    require_immutable_snapshot_hash,
)
from .permits_service import normalize_number
from .snapshot_safety import configured_minimum_rows, validate_full_snapshot
from .safe_fsa_archive import extract_fsa_csvs

FSA_RSS_ID = "7736638268-rss"
FSA_RDS_ID = "7736638268-rds"
_FSA_MINIMUM_ROWS = 1_000

_NUMBER_COLS = {
    "СС": ("Номер СС", "Номер сертификата", "reg_number"),
    "ДС": ("Номер ДС", "Номер декларации", "reg_number"),
}

_SEMANTIC_COLUMN_GROUPS: dict[str, tuple[str, ...]] = {
    "product": (
        "Общее наименование продукции",
        "Группа продукции",
        "product_name",
    ),
    "status": ("Статус", "cert_status"),
    "applicant": ("Заявитель", "applicant_name"),
    "manufacturer": ("Изготовитель", "manufacturer_name"),
    "tn_ved": ("Коды ОКПД2/ТНВЭД", "product_tn_ved", "Коды ТН ВЭД"),
    "technical_regulation": ("Тех регламенты", "product_tech_reg"),
    "issue_date": ("Дата рег", "date_begining", "Дата регистрации"),
    "expiry_date": ("Срок действия", "date_finish", "Дата окончания действия"),
}
_MEANINGFUL_MAPPED_FIELDS = (
    "status",
    "applicant",
    "manufacturer",
    "product_name",
    "tn_ved_codes",
    "tr_ts",
    "issue_date",
    "expiry_date",
)
_STRUCTURE_FIELD_HEADERS = {
    "field",
    "fieldname",
    "column",
    "columnname",
    "code",
    "кодполя",
    "имяполя",
    "названиеполя",
    "наименованиеполя",
    "идентификаторполя",
}


def _sha256_file(path: Path) -> str:
    """Hash the exact staged bytes without loading a large archive in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class FsaStructureContract:
    doc_type: str
    url: str
    sha256: str
    declared_fields: frozenset[str]
    groups: frozenset[str]


def _normalize_schema_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^0-9a-zа-яё]+", "", normalized)


def _field_groups(
    values: set[str],
    *,
    doc_type: str,
) -> set[str]:
    normalized_values = {_normalize_schema_name(value) for value in values if value}

    def matches(alias: str) -> bool:
        normalized_alias = _normalize_schema_name(alias)
        return bool(normalized_alias and normalized_alias in normalized_values)

    groups: set[str] = set()
    if any(matches(alias) for alias in _NUMBER_COLS.get(doc_type, ("reg_number",))):
        groups.add("registry_number")
    for group, aliases in _SEMANTIC_COLUMN_GROUPS.items():
        if any(matches(alias) for alias in aliases):
            groups.add(group)
    return groups


def _known_schema_aliases(doc_type: str) -> set[str]:
    aliases = set(_NUMBER_COLS.get(doc_type, ("reg_number",)))
    for values in _SEMANTIC_COLUMN_GROUPS.values():
        aliases.update(values)
    return {_normalize_schema_name(alias) for alias in aliases}


def _decode_fsa_csv(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    raise RuntimeError("FSA structure artifact is not a supported text CSV")


def _parse_fsa_structure_contract(
    raw: bytes,
    *,
    doc_type: str,
    url: str,
) -> FsaStructureContract:
    text = _decode_fsa_csv(raw)
    try:
        dialect = csv.Sniffer().sniff(text[:16_384], delimiters=";,\t")
        parsed_rows = list(csv.reader(io.StringIO(text), dialect))
    except csv.Error:
        parsed_rows = list(csv.reader(io.StringIO(text), delimiter=";"))
    rows = [
        [str(cell or "").strip().lstrip("\ufeff") for cell in row]
        for row in parsed_rows
        if any(str(cell or "").strip() for cell in row)
    ]
    if not rows:
        raise RuntimeError(f"FSA {doc_type} structure artifact is empty")

    normalized_header = [_normalize_schema_name(cell) for cell in rows[0]]
    header_candidates = [
        index
        for index, value in enumerate(normalized_header)
        if value in _STRUCTURE_FIELD_HEADERS
    ]
    known_aliases = _known_schema_aliases(doc_type)

    horizontal_declarations = {
        _normalize_schema_name(cell)
        for cell in rows[0]
        if _normalize_schema_name(cell) in known_aliases
    }
    horizontal_groups = _field_groups(horizontal_declarations, doc_type=doc_type)
    if (
        not header_candidates
        and "registry_number" in horizontal_groups
        and horizontal_groups - {"registry_number"}
    ):
        declared_fields = horizontal_declarations
    else:
        candidate_columns = header_candidates or list(
            range(max(len(row) for row in rows))
        )

        def declarations_for_column(index: int) -> set[str]:
            start = 1 if header_candidates else 0
            return {
                _normalize_schema_name(row[index])
                for row in rows[start:]
                if index < len(row) and _normalize_schema_name(row[index])
            }

        scored_columns = [
            (
                len(declarations_for_column(index).intersection(known_aliases)),
                -index,
                index,
            )
            for index in candidate_columns
        ]
        _, _, declaration_index = max(scored_columns)
        declared_fields = declarations_for_column(declaration_index)
    declared_known_fields = declared_fields.intersection(known_aliases)
    groups = _field_groups(declared_known_fields, doc_type=doc_type)
    semantic_groups = groups - {"registry_number"}
    if "registry_number" not in groups or not semantic_groups:
        raise RuntimeError(
            f"FSA {doc_type} structure artifact does not declare a registry number "
            "and a supported semantic field"
        )
    return FsaStructureContract(
        doc_type=doc_type,
        url=url,
        sha256=hashlib.sha256(raw).hexdigest(),
        declared_fields=frozenset(declared_fields),
        groups=frozenset(groups),
    )


def _cell(row: dict[str, str], *keys: str) -> str:
    for k in keys:
        if k in row and (row[k] or "").strip():
            return (row[k] or "").strip().strip('"')
    return ""


def _map_fsa_row(row: dict[str, str], *, doc_type: str) -> dict[str, str] | None:
    num_keys = _NUMBER_COLS.get(doc_type, ("reg_number",))
    reg_raw = _cell(row, *num_keys)
    if not reg_raw:
        return None
    reg = normalize_number(reg_raw)
    if not reg:
        return None
    product = _cell(row, "Общее наименование продукции", "Группа продукции", "product_name")
    mapped = {
        "registry_number": reg,
        "doc_type": doc_type,
        "status": _cell(row, "Статус", "cert_status"),
        "applicant": _cell(row, "Заявитель", "applicant_name")[:500],
        "manufacturer": _cell(row, "Изготовитель", "manufacturer_name")[:500],
        "product_name": product[:4000],
        "tn_ved_codes": _cell(row, "Коды ОКПД2/ТНВЭД", "product_tn_ved", "Коды ТН ВЭД"),
        "tr_ts": _cell(row, "Тех регламенты", "product_tech_reg"),
        "issue_date": _cell(row, "Дата рег", "date_begining", "Дата регистрации"),
        "expiry_date": _cell(row, "Срок действия", "date_finish", "Дата окончания действия"),
        "fsa_record_id": _cell(row, "id", "id_cert"),
    }
    if not any(mapped[field] for field in _MEANINGFUL_MAPPED_FIELDS):
        return None
    return mapped


def _fsa_csv_fieldnames(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        return {
            str(name or "").strip().lstrip("\ufeff")
            for name in (reader.fieldnames or ())
        }


def _validate_fsa_csv_schema(
    path: Path,
    *,
    doc_type: str,
    structure_contract: FsaStructureContract | None = None,
) -> None:
    fieldnames = _fsa_csv_fieldnames(path)
    groups = _field_groups(fieldnames, doc_type=doc_type)
    semantic_groups = groups - {"registry_number"}
    if "registry_number" not in groups or not semantic_groups:
        raise RuntimeError(
            f"FSA {doc_type} snapshot has an unexpected CSV schema in "
            f"{path.name}: a registry number and a supported semantic field are required"
        )
    if structure_contract is not None:
        if structure_contract.doc_type != doc_type:
            raise RuntimeError(
                f"FSA {doc_type} snapshot is bound to a structure for "
                f"{structure_contract.doc_type}"
            )
        actual_known_fields = {
            _normalize_schema_name(field)
            for field in fieldnames
            if _normalize_schema_name(field) in _known_schema_aliases(doc_type)
        }
        declared_known_fields = structure_contract.declared_fields.intersection(
            _known_schema_aliases(doc_type)
        )
        schema_difference = actual_known_fields.symmetric_difference(
            declared_known_fields
        )
        if "registry_number" not in structure_contract.groups or schema_difference:
            raise RuntimeError(
                f"FSA {doc_type} CSV schema in {path.name} is not semantically "
                "identical to the metadata structure artifact; differing fields: "
                + ", ".join(sorted(schema_difference))
            )


def _iter_csv_rows(path: Path) -> Iterator[dict[str, str]]:
    csv.field_size_limit(min(sys.maxsize, 10_000_000))
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            yield row


def _apply_fsa_rows(
    db: Session,
    rows: list[dict[str, str]],
    *,
    snapshot_id: str,
) -> dict[str, int]:
    """Upsert по registry_number; дубликаты в одном снимке схлопываются (последняя строка)."""
    by_reg: dict[str, dict[str, str]] = {}
    skipped = 0
    for row in rows:
        reg = row.get("registry_number") or ""
        if not reg:
            skipped += 1
            continue
        by_reg[reg] = row

    created = updated = 0
    for reg, row in by_reg.items():
        existing = (
            db.query(FsaCertificate).filter(FsaCertificate.registry_number == reg).one_or_none()
        )
        if existing:
            existing.doc_type = row.get("doc_type") or existing.doc_type
            existing.status = row.get("status") or existing.status
            existing.applicant = row.get("applicant") or existing.applicant
            existing.manufacturer = row.get("manufacturer") or existing.manufacturer
            existing.product_name = row.get("product_name") or existing.product_name
            existing.tn_ved_codes = row.get("tn_ved_codes") or existing.tn_ved_codes
            existing.tr_ts = row.get("tr_ts") or existing.tr_ts
            existing.issue_date = row.get("issue_date") or existing.issue_date
            existing.expiry_date = row.get("expiry_date") or existing.expiry_date
            existing.fsa_record_id = row.get("fsa_record_id") or existing.fsa_record_id
            existing.source_snapshot = snapshot_id
            updated += 1
        else:
            db.add(
                FsaCertificate(
                    registry_number=reg,
                    doc_type=row.get("doc_type") or "СС",
                    status=row.get("status") or "",
                    applicant=row.get("applicant") or "",
                    manufacturer=row.get("manufacturer") or "",
                    product_name=row.get("product_name") or "",
                    tn_ved_codes=row.get("tn_ved_codes") or "",
                    tr_ts=row.get("tr_ts") or "",
                    issue_date=row.get("issue_date") or "",
                    expiry_date=row.get("expiry_date") or "",
                    fsa_record_id=row.get("fsa_record_id") or "",
                    source_snapshot=snapshot_id,
                )
            )
            created += 1
    return {"created": created, "updated": updated, "skipped": skipped}


def _upsert_fsa_rows(rows: list[dict[str, str]], *, snapshot_id: str) -> dict[str, int]:
    """Backward-compatible transactional batch upsert used by focused tests/tools."""
    with SessionLocal() as db:
        try:
            result = _apply_fsa_rows(db, rows, snapshot_id=snapshot_id)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise


def _import_7z(
    path: Path,
    *,
    doc_type: str,
    snapshot_id: str,
    db: Session | None = None,
    minimum_rows: int = 1,
    structure_contract: FsaStructureContract | None = None,
) -> dict[str, int]:
    """Validate and atomically replace one FSA document-type snapshot.

    ``minimum_rows`` defaults to one for focused/manual callers.  Scheduled
    synchronization passes the production floor.  When ``db`` is supplied,
    the caller owns the transaction so RSS and RDS can commit together.
    """
    totals = {"created": 0, "updated": 0, "skipped": 0, "parsed": 0}
    with tempfile.TemporaryDirectory(prefix="fsa_opendata_") as tmp:
        tmp_path = Path(tmp)
        csv_files = extract_fsa_csvs(path, tmp_path)
        for csv_file in csv_files:
            _validate_fsa_csv_schema(
                csv_file,
                doc_type=doc_type,
                structure_contract=structure_contract,
            )
        owns_session = db is None
        work_db = db or SessionLocal()
        try:
            # First pass: prove completeness before deleting a single live row.
            # Remember the last occurrence so cross-file/batch duplicates retain
            # the same "last row wins" behavior as the small batch helper.
            last_position: dict[str, int] = {}
            valid_position = 0
            invalid_rows = 0
            for csv_file in csv_files:
                for raw in _iter_csv_rows(csv_file):
                    mapped = _map_fsa_row(raw, doc_type=doc_type)
                    if not mapped:
                        invalid_rows += 1
                        continue
                    valid_position += 1
                    last_position[mapped["registry_number"]] = valid_position

            candidate_count = len(last_position)
            if candidate_count <= 0:
                raise RuntimeError(
                    f"FSA {doc_type} snapshot contains zero valid registry rows; "
                    "live table preserved"
                )
            existing_count = (
                work_db.query(FsaCertificate)
                .filter(FsaCertificate.doc_type == doc_type)
                .count()
            )
            source_id = "fsa_rss_registry" if doc_type == "СС" else "fsa_rds_registry"
            validate_full_snapshot(
                source_id=source_id,
                candidate_count=candidate_count,
                existing_count=existing_count,
                minimum_rows=minimum_rows,
            )

            work_db.query(FsaCertificate).filter(
                FsaCertificate.doc_type == doc_type
            ).delete(synchronize_session=False)

            batch: list[dict[str, str]] = []
            batch_size = 500
            valid_position = 0
            duplicate_rows = 0

            def flush_batch() -> None:
                if not batch:
                    return
                stats = _apply_fsa_rows(work_db, batch, snapshot_id=snapshot_id)
                for key in ("created", "updated", "skipped"):
                    totals[key] += stats[key]
                totals["parsed"] += len(batch)
                batch.clear()

            for csv_file in csv_files:
                for raw in _iter_csv_rows(csv_file):
                    mapped = _map_fsa_row(raw, doc_type=doc_type)
                    if not mapped:
                        continue
                    valid_position += 1
                    if last_position[mapped["registry_number"]] != valid_position:
                        duplicate_rows += 1
                        continue
                    batch.append(mapped)
                    if len(batch) >= batch_size:
                        flush_batch()
            flush_batch()
            totals["skipped"] += invalid_rows + duplicate_rows
            if totals["parsed"] != candidate_count:
                raise RuntimeError(
                    f"FSA {doc_type} parsed_rows={totals['parsed']} does not match "
                    f"validated_rows={candidate_count}; live table preserved"
                )
            if owns_session:
                work_db.commit()
        except Exception:
            if owns_session:
                work_db.rollback()
            raise
        finally:
            if owns_session:
                work_db.close()
    return totals


def _successful_snapshot_ids(
    db: Session,
    *,
    source_key: str,
    dataset_id: str,
    doc_type: str,
) -> list[str]:
    logged = [
        str(snapshot_id or "").strip()
        for (snapshot_id,) in db.query(OpendataSyncLog.snapshot_id)
        .filter(
            OpendataSyncLog.source_key == source_key,
            OpendataSyncLog.dataset_id == dataset_id,
            OpendataSyncLog.status == "ok",
            OpendataSyncLog.row_count > 0,
        )
        .all()
    ]
    live = [
        str(snapshot_id or "").strip()
        for (snapshot_id,) in db.query(FsaCertificate.source_snapshot)
        .filter(
            FsaCertificate.doc_type == doc_type,
            FsaCertificate.source_snapshot != "",
        )
        .distinct()
        .all()
    ]
    return [snapshot_id for snapshot_id in [*logged, *live] if snapshot_id]


def _fsa_live_fingerprint(db: Session, *, doc_type: str) -> tuple[int, str]:
    rows = (
        db.query(
            FsaCertificate.registry_number,
            FsaCertificate.doc_type,
            FsaCertificate.status,
            FsaCertificate.applicant,
            FsaCertificate.manufacturer,
            FsaCertificate.product_name,
            FsaCertificate.tn_ved_codes,
            FsaCertificate.tr_ts,
            FsaCertificate.issue_date,
            FsaCertificate.expiry_date,
            FsaCertificate.fsa_record_id,
            FsaCertificate.source_snapshot,
        )
        .filter(FsaCertificate.doc_type == doc_type)
        .order_by(FsaCertificate.registry_number)
        .yield_per(2_000)
    )
    return canonical_rows_fingerprint(tuple(row) for row in rows)


def _sync_fsa_dataset(
    dataset_id: str,
    *,
    doc_type: str,
    source_key: str,
    backfill_all: bool = False,
    force: bool = False,
    db: Session | None = None,
) -> list[dict[str, Any]]:
    meta = fetch_fsa_meta(dataset_id)
    referer = f"{FSA_BASE}/opendata/{dataset_id}/"
    dest_root = backend_opendata_dir() / source_key
    dest_root.mkdir(parents=True, exist_ok=True)

    # Metadata row order is not a trust signal.  Historical replay must finish
    # with the chronologically newest snapshot, otherwise a backfill can leave
    # the live table stale.
    versions = ordered_versions(meta.versions, oldest_first=backfill_all)
    if not backfill_all:
        versions = versions[:1]
    if not versions:
        raise RuntimeError(f"FSA {source_key}: official metadata contains no snapshots")
    final_live_snapshot_id = (
        versions[-1].snapshot_id if backfill_all else versions[0].snapshot_id
    )
    if db is None:
        # Fast fail before downloading large archives.  This is only a
        # preflight; the authoritative check is repeated after the write lock.
        with SessionLocal() as preflight_db:
            require_no_snapshot_rollback(
                final_live_snapshot_id,
                _successful_snapshot_ids(
                    preflight_db,
                    source_key=source_key,
                    dataset_id=dataset_id,
                    doc_type=doc_type,
                ),
                source_key=source_key,
            )

    prepared: dict[str, dict[str, Any]] = {}
    staged_paths: list[Path] = []

    def unique_staging_path(*, snapshot_id: str, suffix: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{source_key}-{snapshot_id}-",
            suffix=suffix,
            dir=dest_root,
            delete=False,
        )
        path = Path(handle.name)
        handle.close()
        staged_paths.append(path)
        return path

    try:
        for version in versions:
            snapshot_id = version.snapshot_id.strip()
            dest_file = unique_staging_path(snapshot_id=snapshot_id, suffix=".7z")
            artifact = download_file(
                version.url,
                referer=referer,
                dest=dest_file,
                for_fsa=True,
                expected_kind="7z",
                dataset_id=dataset_id,
                expected_suffix=".7z",
            )
            structure_url = str(getattr(version, "structure_url", "") or "").strip()
            if not structure_url:
                raise RuntimeError(
                    f"FSA {source_key}: snapshot {snapshot_id!r} has no structure artifact"
                )
            structure_dest = unique_staging_path(
                snapshot_id=snapshot_id,
                suffix=".structure.csv",
            )
            structure_raw = download_bytes(
                structure_url,
                referer=referer,
                dest=structure_dest,
                for_fsa=True,
                expected_kind="csv",
                dataset_id=dataset_id,
                expected_suffix=".csv",
            )
            prepared[snapshot_id] = {
                "dest_file": dest_file,
                "structure_file": structure_dest,
                "artifact_sha256": artifact.sha256,
                "structure": _parse_fsa_structure_contract(
                    structure_raw,
                    doc_type=doc_type,
                    url=structure_url,
                ),
            }
    except Exception:
        for path in staged_paths:
            path.unlink(missing_ok=True)
        raise

    results: list[dict[str, Any]] = []
    owns_session = db is None
    work_db = db or SessionLocal()
    try:
        acquire_opendata_write_lock(
            work_db,
            source_key=source_key,
            dataset_id=dataset_id,
        )
        require_no_snapshot_rollback(
            final_live_snapshot_id,
            _successful_snapshot_ids(
                work_db,
                source_key=source_key,
                dataset_id=dataset_id,
                doc_type=doc_type,
            ),
            source_key=source_key,
        )
        imported = {
            r.snapshot_id: int(r.row_count or 0)
            for r in work_db.query(OpendataSyncLog.snapshot_id, OpendataSyncLog.row_count)
            .filter(
                OpendataSyncLog.source_key == source_key,
                OpendataSyncLog.dataset_id == dataset_id,
                OpendataSyncLog.status == "ok",
            )
            .all()
        }

        missing_historical = backfill_all and any(
            version.snapshot_id.strip() not in imported for version in versions[:-1]
        )
        for index, version in enumerate(versions):
            snapshot_id = version.snapshot_id.strip()
            artifact_sha = str(prepared[snapshot_id]["artifact_sha256"])
            structure_contract = prepared[snapshot_id]["structure"]
            if not isinstance(structure_contract, FsaStructureContract):
                raise RuntimeError("internal FSA structure preparation error")
            staged_artifact = Path(prepared[snapshot_id]["dest_file"])
            staged_structure = Path(prepared[snapshot_id]["structure_file"])
            if _sha256_file(staged_artifact) != artifact_sha:
                raise RuntimeError(
                    f"FSA {source_key}: staged archive changed before import; "
                    "live data preserved"
                )
            if (
                _sha256_file(staged_structure)
                != structure_contract.sha256
            ):
                raise RuntimeError(
                    f"FSA {source_key}: staged structure changed before import; "
                    "live data preserved"
                )
            same_revision_logs = (
                work_db.query(OpendataSyncLog)
                .filter(
                    OpendataSyncLog.source_key == source_key,
                    OpendataSyncLog.dataset_id == dataset_id,
                    OpendataSyncLog.snapshot_id == snapshot_id,
                    OpendataSyncLog.status == "ok",
                )
                .order_by(OpendataSyncLog.id.desc())
                .all()
            )
            require_immutable_snapshot_hash(
                artifact_sha,
                (row.file_sha256 for row in same_revision_logs),
                source_key=source_key,
                snapshot_id=snapshot_id,
            )
            require_immutable_snapshot_hash(
                structure_contract.sha256,
                (
                    fsa_structure_sha_from_details(row.details)
                    for row in same_revision_logs
                ),
                source_key=source_key,
                snapshot_id=snapshot_id,
                artifact_kind="structure",
            )
            # If an old archive is replayed, always replay the newest one too,
            # even when it has an existing success log.
            replay_latest = missing_historical and index == len(versions) - 1
            if not force and not replay_latest and snapshot_id in imported:
                done = same_revision_logs[0] if same_revision_logs else None
                logged_rows = int(done.row_count or 0) if done is not None else 0
                live_rows, live_fingerprint = _fsa_live_fingerprint(
                    work_db,
                    doc_type=doc_type,
                )
                exact_snapshot_rows = (
                    work_db.query(FsaCertificate)
                    .filter(
                        FsaCertificate.doc_type == doc_type,
                        FsaCertificate.source_snapshot == snapshot_id,
                    )
                    .count()
                )
                snapshot_must_match_live = not backfill_all or index == len(versions) - 1
                complete_live_evidence = bool(
                    done is not None
                    and logged_rows > 0
                    and live_rows > 0
                    and str(done.file_sha256 or "").casefold() == artifact_sha
                    and fsa_snapshot_details_match(
                        done.details,
                        source_key=source_key,
                        dataset_id=dataset_id,
                        snapshot_id=snapshot_id,
                        artifact_url=version.url,
                        artifact_sha256=artifact_sha,
                        structure_url=str(getattr(version, "structure_url", "") or ""),
                        structure_sha256=structure_contract.sha256,
                        live_rows=live_rows,
                        live_fingerprint_sha256=live_fingerprint,
                        require_live=snapshot_must_match_live,
                    )
                    and (
                        not snapshot_must_match_live
                        or (
                            exact_snapshot_rows == logged_rows
                            and live_rows == logged_rows
                        )
                    )
                )
                if (
                    not complete_live_evidence
                ):
                    logger.warning(
                        "FSA {}: snapshot {} has a success log without positive "
                        "and complete matching live evidence "
                        "(logged={}, live={}, exact_snapshot={}); re-importing",
                        source_key,
                        snapshot_id,
                        logged_rows,
                        live_rows,
                        exact_snapshot_rows,
                    )
                else:
                    logger.info("FSA {}: snapshot {} уже импортирован", source_key, snapshot_id)
                    results.append(
                        {
                            "status": "skipped",
                            "official_source_verified": bool(
                                getattr(meta, "provenance_verified", False)
                            ),
                            "dataset_id": dataset_id,
                            "snapshot_id": snapshot_id,
                            "rows": live_rows,
                            "parsed": live_rows,
                            "verified_live_rows": live_rows,
                        }
                    )
                    continue
            # Repeat the high-water check immediately before the destructive
            # replacement.  ``force`` may refresh one revision, never roll it
            # back.  For an atomic historical replay we compare its final
            # target, not the transient old archive.
            require_no_snapshot_rollback(
                final_live_snapshot_id,
                _successful_snapshot_ids(
                    work_db,
                    source_key=source_key,
                    dataset_id=dataset_id,
                    doc_type=doc_type,
                ),
                source_key=source_key,
            )
            source_id = "fsa_rss_registry" if doc_type == "СС" else "fsa_rds_registry"
            stats = _import_7z(
                prepared[snapshot_id]["dest_file"],
                doc_type=doc_type,
                snapshot_id=snapshot_id,
                db=work_db,
                minimum_rows=configured_minimum_rows(source_id, _FSA_MINIMUM_ROWS),
                structure_contract=structure_contract,
            )
            work_db.flush()
            live_rows, live_fingerprint = _fsa_live_fingerprint(
                work_db,
                doc_type=doc_type,
            )
            exact_snapshot_rows = (
                work_db.query(FsaCertificate)
                .filter(
                    FsaCertificate.doc_type == doc_type,
                    FsaCertificate.source_snapshot == snapshot_id,
                )
                .count()
            )
            if (
                live_rows <= 0
                or live_rows != int(stats.get("parsed", 0))
                or exact_snapshot_rows != live_rows
            ):
                raise RuntimeError(
                    f"FSA {source_key}: persisted live snapshot identity/count "
                    "does not match the validated archive; transaction rolled back"
                )
            data_as_of = snapshot_date_from_id(snapshot_id) or meta.modified
            structure_url = structure_contract.url
            work_db.add(
                OpendataSyncLog(
                    source_key=source_key,
                    dataset_id=dataset_id,
                    snapshot_id=snapshot_id,
                    file_url=version.url,
                    file_sha256=artifact_sha,
                    row_count=live_rows,
                    synced_at=datetime.now(timezone.utc).isoformat(),
                    data_as_of=data_as_of,
                    status="ok",
                    details=encode_fsa_snapshot_details(
                        source_key=source_key,
                        dataset_id=dataset_id,
                        snapshot_id=snapshot_id,
                        artifact_url=version.url,
                        artifact_sha256=artifact_sha,
                        structure_url=structure_url,
                        structure_sha256=structure_contract.sha256,
                        live_rows=live_rows,
                        live_fingerprint_sha256=live_fingerprint,
                        stats=stats,
                    ),
                )
            )
            results.append(
                {
                    "status": "ok",
                    "official_source_verified": bool(
                        getattr(meta, "provenance_verified", False)
                    ),
                    "dataset_id": dataset_id,
                    "snapshot_id": snapshot_id,
                    "data_as_of": data_as_of,
                    "structure_sha256": structure_contract.sha256,
                    **stats,
                }
            )
        if owns_session:
            work_db.commit()
        return results
    except Exception:
        if owns_session:
            work_db.rollback()
        raise
    finally:
        if owns_session:
            work_db.close()
        for path in staged_paths:
            path.unlink(missing_ok=True)


def _record_fsa_aggregate_failure(exc: Exception) -> None:
    """Persist failure evidence after the aggregate data transaction rolls back."""
    synced_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as db:
        for dataset_id, source_key in ((FSA_RSS_ID, "fsa_rss"), (FSA_RDS_ID, "fsa_rds")):
            db.add(
                OpendataSyncLog(
                    source_key=source_key,
                    dataset_id=dataset_id,
                    snapshot_id="aggregate-failed",
                    synced_at=synced_at,
                    status="error",
                    error_message=str(exc)[:2000],
                )
            )
        db.commit()


def sync_fsa_certificates(*, backfill_all: bool = False, force: bool = False) -> dict[str, Any]:
    """Synchronize RSS and RDS as one aggregate database transaction."""
    try:
        with SessionLocal() as db:
            try:
                rss = _sync_fsa_dataset(
                    FSA_RSS_ID,
                    doc_type="СС",
                    source_key="fsa_rss",
                    backfill_all=backfill_all,
                    force=force,
                    db=db,
                )
                rds = _sync_fsa_dataset(
                    FSA_RDS_ID,
                    doc_type="ДС",
                    source_key="fsa_rds",
                    backfill_all=backfill_all,
                    force=force,
                    db=db,
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {
            "aggregate_status": "ok",
            "official_source_verified": bool(
                rss
                and rds
                and all(
                    row.get("official_source_verified") is True
                    for row in [*rss, *rds]
                )
            ),
            "rss": rss,
            "rds": rds,
        }
    except Exception as exc:
        logger.exception("FSA aggregate opendata import failed; RSS and RDS preserved")
        try:
            _record_fsa_aggregate_failure(exc)
        except Exception:
            logger.exception("Unable to persist FSA aggregate failure log")
        failure = {"status": "error", "snapshot_id": "aggregate-failed", "error": str(exc)}
        return {
            "aggregate_status": "error",
            "official_source_verified": False,
            "rss": [dict(failure)],
            "rds": [dict(failure)],
        }
