#!/usr/bin/env python3
"""Retain the actual index and its observed tariff notes for legal discovery.

This bounded two-document bootstrap does not capture chapter tables, establish
effective dates, or create a complete ETT acquisition receipt.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.encoders import jsonable_encoder
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_amendment_inventory import parse_amendment_inventory
from app.services.ett_index import INDEX_URL, parse_index
from app.services.ett_notes import extract_tariff_notes
from app.services.ett_transport import fetch_official


def _json(value):
    return (json.dumps(jsonable_encoder(value), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def capture_inputs(store, directory, *, fetch=fetch_official, extract=extract_tariff_notes):
    """Write only new artifacts; every observed URL derives from retained HTML."""
    def retain(name, data):
        if type(data) is not bytes or not 1 <= len(data) <= 64 * 1024 * 1024:
            raise ValueError("invalid input artifact size")
        digest = store.put(data)
        if digest != hashlib.sha256(data).hexdigest():
            raise ValueError("input artifact digest mismatch")
        fd = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        return {"sha256": digest, "size_bytes": len(data)}

    index_response = fetch(INDEX_URL, expected_media="text/html")
    if index_response.requested_url != INDEX_URL or index_response.media_type != "text/html":
        raise ValueError("unexpected index response")
    index = retain("index.html", index_response.content)
    discovery = parse_index(index_response.content)
    inventory = retain("inventory.json", _json(asdict(parse_amendment_inventory(index_response.content))))
    notes_response = fetch(discovery.tariff_notes.url, expected_media="application/pdf")
    if (notes_response.requested_url != discovery.tariff_notes.url
            or notes_response.media_type != "application/pdf"):
        raise ValueError("unexpected notes response")
    notes_source = retain("tariff-notes.pdf", notes_response.content)
    notes = retain("notes.json", _json(extract(notes_response.content, artifact_id="tariff-notes")))
    report = {
        "schema_version": 1, "kind": "ett_legal_discovery_inputs",
        "index": {**index, "requested_url": INDEX_URL, "response_url": index_response.url,
                  "retrieved_at": index_response.retrieved_at.isoformat()},
        "inventory_report": inventory,
        "notes_source": {**notes_source, "requested_url": discovery.tariff_notes.url,
                         "response_url": notes_response.url,
                         "retrieved_at": notes_response.retrieved_at.isoformat(),
                         "observed_reference": asdict(discovery.tariff_notes)},
        "notes_report": notes,
        "acquisition_complete": False, "legal_inventory_complete": False,
        "effective_dates_verified": False, "production_ready": False,
    }
    retain("inputs.json", _json(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        # An existing directory is deliberately not reused or overwritten.
        args.output_directory.mkdir(mode=0o700)
        report = capture_inputs(LocalArtifactStore(args.store_root), args.output_directory)
    except Exception:
        print(json.dumps({"status": "incomplete", "production_ready": False}))
        return 2
    print(json.dumps({"status": "inputs_captured", "index_sha256": report["index"]["sha256"],
                      "production_ready": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
