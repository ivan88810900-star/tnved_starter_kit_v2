"""Bind candidate evidence quotes to reproducibly extracted source PDF rows.

This is a structural, read-only check. A quote which exists in a source does not
prove that a normalized duty, condition or effective date interprets it correctly.
No approval, active-rate writes, acquisition or archival attestation occur here.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re
import time
from typing import Any, Iterator

from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_manifest import (
    ETTEvidence, ETTLegalPortalMetadataEvidence, ETTManifest, MAX_MANIFEST_BYTES, canonical_manifest_bytes,
    validate_manifest,
)
from app.services.ett_pdf_evidence import PDFEvidenceError, extract_pdf_evidence


MAX_REFERENCES = 250_000
MAX_REFERENCED_PDFS = 256
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_BINDING_SECONDS = 300
MAX_ISSUES = 1000
_ROW = re.compile(r"p([0-9]{4}):r([0-9]{5})\Z")


class EvidenceBindingError(ValueError):
    """Sanitized invalid-input failure; individual source failures become issues."""


def _references(manifest: ETTManifest) -> Iterator[tuple[str, ETTEvidence | ETTLegalPortalMetadataEvidence]]:
    for index, code in enumerate(manifest.codes):
        for field in ("evidence", "effective_evidence"):
            for reference_index, reference in enumerate(getattr(code, field)):
                yield f"codes[{index}].{field}[{reference_index}]", reference
    for index, footnote in enumerate(manifest.footnotes):
        for reference_index, reference in enumerate(footnote.evidence):
            yield f"footnotes[{index}].evidence[{reference_index}]", reference
    for index, rule in enumerate(manifest.rate_rules):
        for field in ("evidence", "effective_evidence"):
            for reference_index, reference in enumerate(getattr(rule, field)):
                yield f"rate_rules[{index}].{field}[{reference_index}]", reference


def verify_manifest_source_rows(
    manifest: ETTManifest | dict[str, Any] | bytes | str,
    store: LocalArtifactStore,
) -> dict[str, Any]:
    """Re-extract every referenced PDF once and verify every reference occurrence.

    The row locator, page, retained text and text hash must match exactly. HTML,
    XML and JSON evidence are unsupported and stay unverified. Unreferenced
    source artifacts are deliberately not attested by this bounded check.
    ``rows_verified`` never establishes semantic/legal correctness.
    """
    try:
        validated = validate_manifest(manifest)
        manifest_bytes = canonical_manifest_bytes(validated)
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise EvidenceBindingError("ETT manifest validation failed") from exc
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise EvidenceBindingError("ETT manifest exceeds the bounded input size")
    return _verify_source_rows(validated, manifest_bytes, _references(validated), store)


def _verify_source_rows(validated, manifest_bytes, selected_references, store) -> dict[str, Any]:
    """Shared strict native checker; callers select references, never failures.

    The mixed-source coordinator supplies every native reference unchanged. The
    public native-only check also sees typed HTML and explicitly rejects it.
    """
    grouped: dict[str, list[tuple[str, ETTEvidence | ETTLegalPortalMetadataEvidence]]] = defaultdict(list)
    reference_count = 0
    for where, reference in selected_references:
        reference_count += 1
        if reference_count > MAX_REFERENCES:
            raise EvidenceBindingError("ETT evidence reference count exceeds its limit")
        grouped[reference.artifact_id].append((where, reference))
    artifact_map = {artifact.artifact_id: artifact for artifact in validated.artifacts}
    issues: list[dict[str, Any]] = []
    failed = 0
    verified = 0
    extracted_artifacts: list[dict[str, Any]] = []
    parser_identities: dict[str, dict[str, Any]] = {}
    source_bytes = 0
    pdf_attempts = 0
    started = time.monotonic()

    def issue(where: str, reference: ETTEvidence | ETTLegalPortalMetadataEvidence, reason: str) -> None:
        nonlocal failed
        failed += 1
        if len(issues) < MAX_ISSUES:
            if isinstance(reference, ETTEvidence):
                detail = {"where": where, "artifact_id": reference.artifact_id,
                          "page": reference.page,
                          "row": reference.row if _ROW.fullmatch(reference.row) else "<invalid_locator>",
                          "reason": reason}
            else:
                detail = {"where": where, "artifact_id": reference.artifact_id, "reason": reason,
                          "kind": reference.kind, "locator": reference.locator}
            issues.append(detail)

    for artifact_id in sorted(grouped):
        artifact = artifact_map[artifact_id]
        references = grouped[artifact_id]
        failure = None
        report = None
        if artifact.media_type != "application/pdf":
            failure = "non_pdf_evidence_unsupported"
        elif pdf_attempts >= MAX_REFERENCED_PDFS:
            failure = "pdf_artifact_count_limit"
        elif source_bytes + artifact.size_bytes > MAX_SOURCE_BYTES:
            failure = "aggregate_source_size_limit"
        elif time.monotonic() - started >= MAX_BINDING_SECONDS:
            failure = "binding_time_limit"
        else:
            pdf_attempts += 1
            try:
                body = store.read(artifact.sha256)
                if not isinstance(body, bytes) or len(body) != artifact.size_bytes or hashlib.sha256(body).hexdigest() != artifact.sha256:
                    failure = "artifact_integrity_mismatch"
                else:
                    source_bytes += len(body)
                    report = extract_pdf_evidence(
                        body, artifact_id=artifact_id,
                        chapter=artifact.chapter if artifact.role == "chapter" else None,
                    )
            except (ArtifactIntegrityError, OSError):
                failure = "artifact_unavailable_or_corrupt"
            except PDFEvidenceError:
                failure = "pdf_extraction_failed"
        if failure is not None:
            for where, reference in references:
                issue(where, reference, failure)
            continue
        assert report is not None
        parser_key = json.dumps(report["parser"], sort_keys=True, separators=(",", ":"))
        parser_identities[parser_key] = report["parser"]
        extracted_artifacts.append({
            "artifact_id": artifact_id, "sha256": artifact.sha256,
            "page_count": report["page_count"], "word_count": report["word_count"],
        })
        rows = {
            (page["page"], row["row"]): row
            for page in report["pages"] for row in page["rows"]
        }
        for where, reference in references:
            locator = _ROW.fullmatch(reference.row)
            if locator is None or int(locator[1]) != reference.page or int(locator[2]) < 1:
                issue(where, reference, "invalid_or_inconsistent_row_locator")
                continue
            source_row = rows.get((reference.page, reference.row))
            if source_row is None:
                issue(where, reference, "source_row_not_found")
            elif source_row["raw_text"] != reference.raw_text or source_row["raw_text_sha256"] != reference.raw_text_sha256:
                issue(where, reference, "source_row_text_mismatch")
            else:
                verified += 1
    return {
        "schema_version": 1, "mode": "source_row_verification",
        "scope": "referenced_pdf_rows_only",
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "rows_verified": failed == 0 and verified == reference_count,
        "references_total": reference_count, "references_verified": verified,
        "references_failed": failed, "referenced_artifact_count": len(grouped),
        "unreferenced_artifact_count": len(validated.artifacts) - len(grouped),
        "pdf_artifacts_extracted": len(extracted_artifacts),
        "source_bytes_verified": source_bytes,
        "parser_identities": [parser_identities[key] for key in sorted(parser_identities)],
        "manifest_parser": validated.parser.model_dump(mode="json"),
        "extracted_artifacts": extracted_artifacts,
        "issues": issues, "issues_truncated": failed > len(issues),
        "complete_artifact_inventory_verified": False,
        "current_legal_inventory_verified": False,
        "effective_dates_verified": False, "duty_interpretation_verified": False,
        "footnote_interpretation_verified": False, "legal_approval_verified": False,
        "production_ready": False, "can_promote": False, "active_rates_written": False,
    }
