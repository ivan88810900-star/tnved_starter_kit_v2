"""Synthetic ETT records, deliberately NOT an official/current-law dataset.

The 100 placeholder artifacts exercise only the manifest shape. No downloaded
official document, real catalog completeness or legal interpretation is asserted.
"""
from __future__ import annotations

import hashlib

from app.services.ett_manifest import EXPECTED_CHAPTERS, ETTManifest, validate_manifest


def artifact_bytes(artifact_id: str) -> bytes:
    return ("synthetic ETT test fixture only: " + artifact_id).encode("utf-8")


def evidence_for(artifact: dict, text: str = "Synthetic source row; validity 2026-01-01 through 2027-01-01 exclusive", *, row: str = "table:1:row:1") -> dict:
    return {"artifact_id": artifact["artifact_id"], "artifact_sha256": artifact["sha256"],
            "page": 1, "row": row, "raw_text": text,
            "raw_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def synthetic_manifest_data() -> dict:
    artifacts = []
    for role, chapter in [("index", None), ("nomenclature_notes", None),
                          ("tariff_notes", None), ("amendment_inventory", None),
                          *(("chapter", chapter) for chapter in EXPECTED_CHAPTERS)]:
        artifact_id = f"chapter-{chapter}" if chapter else role
        body = artifact_bytes(artifact_id)
        artifact = {"artifact_id": artifact_id, "role": role,
                    "url": "https://eec.eaeunion.org/synthetic-fixture/" + artifact_id + (".pdf" if chapter else ".html"),
                    "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body),
                    "media_type": "application/pdf" if chapter else "text/html",
                    "retrieved_at": "2026-09-01T00:00:00Z"}
        if chapter:
            artifact["chapter"] = chapter
        artifacts.append(artifact)
    source = next(artifact for artifact in artifacts if artifact.get("chapter") == "01")
    effective_source = next(artifact for artifact in artifacts if artifact["role"] == "tariff_notes")
    evidence, effective_evidence = evidence_for(source), evidence_for(effective_source)
    return {
        "schema_version": 2, "source_kind": "official_eec_ett", "snapshot_id": "synthetic-test-only",
        "created_at": "2026-09-01T01:00:00Z", "coverage_from": "2026-01-01", "coverage_to": "2027-01-01",
        "parser": {"name": "synthetic-test-parser", "version": "0.0.0", "sha256": "a" * 64},
        "artifacts": artifacts,
        "codes": [{"code": "0101210000", "description": "Synthetic test commodity; no legal interpretation",
                   "valid_from": "2026-01-01", "valid_to": "2027-01-01",
                   "evidence": [evidence], "effective_evidence": [effective_evidence]}],
        "footnotes": [],
        "rate_rules": [{"rule_id": "test-rule-1", "code": "0101210000",
                        "valid_from": "2026-01-01", "valid_to": "2027-01-01",
                        "destinations": ["AM", "BY", "KZ", "KG", "RU"], "conditions": [],
                        "duty": {"kind": "ad_valorem", "ad_valorem_percent": "5"}, "footnote_ids": [],
                        "evidence": [evidence], "effective_evidence": [effective_evidence]}],
    }


def synthetic_manifest() -> ETTManifest:
    return validate_manifest(synthetic_manifest_data())
