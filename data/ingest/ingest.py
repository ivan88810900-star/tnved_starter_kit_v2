import argparse
import pathlib
import yaml
from datetime import datetime

from data.ingest.utils import sha256_bytes
from backend.app.db import SessionLocal
from backend.app import models

RAW = pathlib.Path(__file__).resolve().parents[1] / "raw"
BASE = pathlib.Path(__file__).resolve().parents[1]

def ingest_dataset(key: str, meta: dict, db_session):
    version = meta["version"]
    file_type = meta.get("file_type", "").upper()

    if key == "tariff_cet" and file_type == "PDF":
        from data.ingest.parsers import tariff_pdf
        pdf_dir = RAW / key / version
        tariff_pdf.parse_tariff_pdfs(pdf_dir, version, db_session)

    if key == "tnved_tree":
        from data.ingest.parsers import tnved_tree, pdf_codes_enhanced
        count_html = tnved_tree.parse_tnved_tree(RAW / key / version, db_session)
        if count_html == 0:  # если html/xml нет
            pdf_codes_enhanced.parse_pdf_codes_enhanced(RAW / key / version, db_session)

    if key in ("section_notes","chapter_notes","notes"):
        from data.ingest.parsers import notes, pdf_notes
        count_html = notes.parse_notes_html(RAW / key / version, db_session)
        if count_html == 0:
            pdf_notes.parse_pdf_notes(RAW / key / version, db_session)

    if key == "vat_10_food_children":
        from data.ingest.parsers import vat_rules
        vat_rules.load_vat_rules(RAW / key / version, rate=10, source="PP-908", db_session=db_session)

    if key == "vat_10_med":
        from data.ingest.parsers import vat_rules
        vat_rules.load_vat_rules(RAW / key / version, rate=10, source="PP-688", db_session=db_session)

    if key == "vat_0_med":
        from data.ingest.parsers import vat_rules
        vat_rules.load_vat_rules(RAW / key / version, rate=0, source="PP-1042", db_session=db_session)

    # здесь позже добавим ntm, eco и т.д.

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated dataset keys")
    ap.add_argument("--download", action="store_true", help="run downloader before ingest")
    args = ap.parse_args()

    cfg_path = BASE / "sources.yml"
    if not cfg_path.exists():
        print("sources.yml not found, please create it first.")
        return
    cfg = yaml.safe_load(open(cfg_path, "r", encoding="utf-8"))

    datasets = cfg.get("datasets", {})
    targets = [k.strip() for k in (args.only.split(",") if args.only else datasets.keys()) if k.strip()]

    if args.download:
        import subprocess, sys
        dl = BASE / "ingest" / "fetch_tariff_eec.py"
        cmd = [sys.executable, str(dl)]
        subprocess.run(cmd, check=True)

    db = SessionLocal()
    try:
        for key in targets:
            print(f"\n=== Importing {key} ===")
            meta = datasets[key]
            ingest_dataset(key, meta, db)

            # зафиксируем источник в таблице DataSource
            existing_ds = db.query(models.DataSource).filter_by(key=key).first()
            if existing_ds:
                existing_ds.version = meta.get("version")
                existing_ds.authority = meta.get("authority")
                existing_ds.url = ";".join(meta.get("urls", []))
                existing_ds.checksum = str(meta.get("checksum", ""))
                existing_ds.imported_at = datetime.utcnow()
            else:
                ds = models.DataSource(
                    key=key,
                    version=meta.get("version"),
                    authority=meta.get("authority"),
                    url=";".join(meta.get("urls", [])),
                    checksum=str(meta.get("checksum", "")),
                    imported_at=datetime.utcnow(),
                )
                db.add(ds)
            db.commit()
            print(f"✓ {key} imported")
    finally:
        db.close()

if __name__ == "__main__":
    main()

