#!/usr/bin/env python3
"""Единый загрузчик официальных открытых данных: TROIS, ФСА, справочники ФТС."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.opendata_customs import (  # noqa: E402
    MASK44_DATASET_ID,
    sync_customs_catalog,
    sync_mask44,
)
from app.services.opendata_fsa import (  # noqa: E402
    FSA_RDS_ID,
    FSA_RSS_ID,
    sync_fsa_certificates,
)
from app.services.opendata_trois import TROIS_DATASET_ID, sync_trois_opendata  # noqa: E402
from app.services.normative_store import append_sync_log, upsert_source_status  # noqa: E402


def _positive_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed > 0 else 0


def _fsa_summary(payload: dict) -> tuple[bool, int, str]:
    rows = 0
    revisions: list[str] = []
    ok = (
        payload.get("aggregate_status") == "ok"
        and payload.get("official_source_verified") is True
    )
    for key, expected_dataset_id in (("rss", FSA_RSS_ID), ("rds", FSA_RDS_ID)):
        items = payload.get(key)
        if not isinstance(items, list) or not items:
            ok = False
            continue
        for item in items:
            if not isinstance(item, dict):
                ok = False
                continue
            item_ok = bool(
                item.get("status") in {"ok", "skipped"}
                and item.get("official_source_verified") is True
                and item.get("dataset_id") == expected_dataset_id
            )
            if not item_ok:
                ok = False
                continue
            revision = str(item.get("snapshot_id") or "").strip()
            if revision:
                revisions.append(revision)
            else:
                ok = False
            count = _positive_int(item.get("parsed") or item.get("rows"))
            # A skipped snapshot is green only after the service verified that
            # the corresponding live table still contains positive evidence.
            if count <= 0:
                ok = False
            rows += max(0, count)
    return ok, rows, ",".join(sorted(set(revisions))) or "unknown"


def _single_summary(
    payload: dict,
    *,
    count_keys: tuple[str, ...],
    expected_dataset_id: str,
) -> tuple[bool, int, str]:
    if not isinstance(payload, dict):
        return False, 0, "unknown"
    rows = 0
    for key in count_keys:
        if payload.get(key) is not None:
            rows = _positive_int(payload.get(key))
            break
    revision = str(payload.get("snapshot_id") or "").strip()
    ok = bool(
        payload.get("status") in {"ok", "skipped"}
        and payload.get("official_source_verified") is True
        and payload.get("dataset_id") == expected_dataset_id
        and revision
        and rows > 0
    )
    return ok, rows, revision or "unknown"


def _record_status(source_code: str, source_name: str, source_url: str, *, ok: bool, revision: str, rows: int) -> None:
    note = f"opendata sync status={'ok' if ok else 'error'}; rows={rows}; revision={revision}"
    upsert_source_status(
        source_code=source_code,
        source_name=source_name,
        source_url=source_url,
        revision=revision if ok else "unavailable",
        is_stale=not ok,
        note=note,
    )
    append_sync_log(source_code, "OK" if ok else "ERROR", revision, rows, note)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync official opendata registries into local DB")
    parser.add_argument(
        "--source",
        choices=("trois", "fsa", "customs", "all"),
        default="all",
        help="Which source to sync",
    )
    parser.add_argument("--all", action="store_true", help="Alias for --source all")
    parser.add_argument("--force", action="store_true", help="Re-import even if snapshot already loaded")
    parser.add_argument(
        "--fsa-backfill",
        action="store_true",
        help="Import all monthly FSA 7z archives from meta.xml (large, slow)",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on nested errors, empty or invalid snapshots")
    args = parser.parse_args()
    source = "all" if args.all else args.source
    out: dict = {}

    if source in ("trois", "all"):
        try:
            out["trois"] = sync_trois_opendata(force=args.force)
        except Exception as exc:
            out["trois"] = {"status": "error", "error": str(exc)}
    if source in ("fsa", "all"):
        try:
            out["fsa"] = sync_fsa_certificates(
                backfill_all=args.fsa_backfill,
                force=args.force,
            )
        except Exception as exc:
            out["fsa"] = {"aggregate_status": "error", "error": str(exc)}
    if source in ("customs", "all"):
        try:
            out["mask44"] = sync_mask44(force=args.force)
        except Exception as exc:
            out["mask44"] = {"status": "error", "error": str(exc)}
        try:
            out["catalog"] = sync_customs_catalog()
        except Exception as exc:
            out["catalog"] = {"status": "error", "error": str(exc)}

    status_rows: list[dict] = []
    if source in ("fsa", "all"):
        ok, rows, revision = _fsa_summary(out.get("fsa") or {})
        _record_status(
            "FSA_REGISTRY",
            "Реестры сертификатов и деклараций Росаккредитации",
            "https://fsa.gov.ru/opendata/",
            ok=ok,
            revision=revision,
            rows=rows,
        )
        status_rows.append({
            "source_id": "fsa_registry_evidence",
            "status": "ok" if ok else "error",
            "official_source_verified": ok,
            "rows": rows,
            "revision": revision,
        })
    if source in ("trois", "all"):
        ok, rows, revision = _single_summary(
            out.get("trois") or {},
            count_keys=("parsed_rows", "rows"),
            expected_dataset_id=TROIS_DATASET_ID,
        )
        _record_status(
            "FTS_TROIS",
            "ТРОИС ФТС России",
            "https://customs.gov.ru/opendata/7730176610-trois",
            ok=ok,
            revision=revision,
            rows=rows,
        )
        status_rows.append({
            "source_id": "fts_trois_registry",
            "status": "ok" if ok else "error",
            "official_source_verified": ok,
            "rows": rows,
            "revision": revision,
        })
    if source in ("customs", "all"):
        mask_ok, mask_rows, mask_revision = _single_summary(
            out.get("mask44") or {},
            count_keys=("rows",),
            expected_dataset_id=MASK44_DATASET_ID,
        )
        catalog = out.get("catalog") or {}
        catalog_rows = _positive_int(catalog.get("total")) if isinstance(catalog, dict) else 0
        catalog_ok = (
            isinstance(catalog, dict)
            and catalog.get("status") == "ok"
            and catalog.get("official_source_verified") is True
            and set(catalog.get("managed_dataset_ids") or ())
            == {MASK44_DATASET_ID, TROIS_DATASET_ID}
            and catalog_rows > 0
        )
        ok = mask_ok and catalog_ok
        rows = mask_rows + catalog_rows
        _record_status(
            "FTS_CUSTOMS_DOCS",
            "Справочники документов ФТС России",
            "https://customs.gov.ru/opendata",
            ok=ok,
            revision=mask_revision,
            rows=rows,
        )
        status_rows.append({
            "source_id": "fts_customs_document_masks",
            "status": "ok" if ok else "error",
            "official_source_verified": ok,
            "rows": rows,
            "revision": mask_revision,
        })

    contract_ok = bool(status_rows) and all(row["status"] == "ok" for row in status_rows)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("REGULATORY_SYNC_RESULT=" + json.dumps({
        "status": "ok" if contract_ok else "error",
        "source_ids": [row["source_id"] for row in status_rows],
        "official_source": bool(
            status_rows
            and all(row.get("official_source_verified") is True for row in status_rows)
        ),
        "snapshot_kind": "full",
        "sources": status_rows,
    }, ensure_ascii=False, separators=(",", ":")))
    return 0 if contract_ok or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
