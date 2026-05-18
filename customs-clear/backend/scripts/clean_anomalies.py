from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal


def _build_chapter_condition(include_50_60: bool) -> str:
    chapter_expr = "CAST(SUBSTR(COALESCE(commodity_code, ''), 1, 2) AS INTEGER)"
    ranges: list[tuple[int, int]] = [
        (61, 63),  # текстильная одежда (без шелка/шерсти 50-51)
        (68, 97),  # камень/стекло/металлы + техника/транспорт/инструменты
    ]
    if include_50_60:
        ranges.insert(0, (50, 60))
    return " OR ".join(f"({chapter_expr} BETWEEN {start} AND {end})" for start, end in ranges)


def _count_vet_phyto_candidates(db, include_50_60: bool) -> int:
    chapter_cond = _build_chapter_condition(include_50_60)
    sql = text(
        f"""
        SELECT COUNT(*)
        FROM non_tariff_measures
        WHERE LOWER(COALESCE(measure_type, '')) IN ('vet_control', 'phyto_control')
          AND LENGTH(COALESCE(commodity_code, '')) = 10
          AND ({chapter_cond})
        """
    )
    return int(db.execute(sql).scalar() or 0)


def _delete_vet_phyto_candidates(db, include_50_60: bool) -> int:
    chapter_cond = _build_chapter_condition(include_50_60)
    sql = text(
        f"""
        DELETE FROM non_tariff_measures
        WHERE LOWER(COALESCE(measure_type, '')) IN ('vet_control', 'phyto_control')
          AND LENGTH(COALESCE(commodity_code, '')) = 10
          AND ({chapter_cond})
        """
    )
    result = db.execute(sql)
    return int(result.rowcount or 0)


def _count_duplicate_candidates(db) -> int:
    sql = text(
        """
        SELECT COUNT(*)
        FROM (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY
                        COALESCE(commodity_code, ''),
                        LOWER(COALESCE(measure_type, '')),
                        COALESCE(regulatory_act, '')
                    ORDER BY id DESC
                ) AS rn
            FROM non_tariff_measures
        ) t
        WHERE rn > 1
        """
    )
    return int(db.execute(sql).scalar() or 0)


def _delete_duplicate_candidates(db) -> int:
    sql = text(
        """
        DELETE FROM non_tariff_measures
        WHERE id IN (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY
                            COALESCE(commodity_code, ''),
                            LOWER(COALESCE(measure_type, '')),
                            COALESCE(regulatory_act, '')
                        ORDER BY id DESC
                    ) AS rn
                FROM non_tariff_measures
            ) d
            WHERE rn > 1
        )
        """
    )
    result = db.execute(sql)
    return int(result.rowcount or 0)


def run(mode: str, dry_run: bool, include_50_60: bool) -> None:
    with SessionLocal() as db:
        total_candidates = 0
        total_deleted = 0

        print(f"mode={mode}")
        print(f"dry_run={dry_run}")
        print(f"include_50_60={include_50_60}")

        if mode in {"vet_phyto", "all"}:
            vet_count = _count_vet_phyto_candidates(db, include_50_60)
            total_candidates += vet_count
            print(f"[vet_phyto] candidates_to_delete={vet_count}")
            if not dry_run and vet_count > 0:
                deleted = _delete_vet_phyto_candidates(db, include_50_60)
                # Для некоторых БД rowcount может быть 0/-1 при complex-delete.
                if deleted <= 0:
                    deleted = vet_count
                total_deleted += deleted
                print(f"[vet_phyto] deleted={deleted}")

        if mode in {"dedupe", "all"}:
            dedupe_count = _count_duplicate_candidates(db)
            total_candidates += dedupe_count
            print(f"[dedupe] candidates_to_delete={dedupe_count}")
            if not dry_run and dedupe_count > 0:
                deleted = _delete_duplicate_candidates(db)
                if deleted <= 0:
                    deleted = dedupe_count
                total_deleted += deleted
                print(f"[dedupe] deleted={deleted}")

        if dry_run:
            db.rollback()
            print(f"summary_candidates={total_candidates}")
            print("summary_deleted=0 (dry-run)")
            return

        db.commit()
        print(f"summary_candidates={total_candidates}")
        print(f"summary_deleted={total_deleted}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Очистка аномалий в non_tariff_measures.")
    parser.add_argument(
        "--mode",
        choices=("vet_phyto", "dedupe", "all"),
        default="all",
        help="Режим очистки: vet_phyto | dedupe | all (по умолчанию all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только показать количество строк к удалению, без commit.",
    )
    parser.add_argument(
        "--include-50-60",
        action="store_true",
        help="Расширить очистку vet/phyto на главы 50-60 (по умолчанию чистим 61-63 и 68-97).",
    )
    args = parser.parse_args()
    run(mode=args.mode, dry_run=args.dry_run, include_50_60=bool(args.include_50_60))


if __name__ == "__main__":
    main()

