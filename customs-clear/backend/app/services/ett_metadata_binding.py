"""Replay typed portal metadata against original HTML and linked PDF bytes.

This opt-in, read-only evidence check observes exact source fields and attachment
links. A portal date is not independent proof of publication or legal effect.
Native PDF rows retain their own strict verifier and cannot be replaced by HTML.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import html.parser
import json
from pathlib import Path
import re
import sys
import time
from typing import Any
from urllib.parse import unquote

import bs4
from bs4 import BeautifulSoup
import soupsieve

from app.services import ett_evidence_binding as native
from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_detail_identity import (
    ETTDetailIdentityError, _anchor_identity, _category, _text, _title_status,
)
from app.services.ett_index import MAX_INDEX_BYTES, _visible
from app.services.ett_legal_attachments import _AttachmentGuard, _attachment_target
from app.services.ett_legal_metadata import parse_legal_metadata
from app.services.ett_manifest import (
    ETTEvidence, ETTLegalPortalMetadataEvidence, ETTManifest, ETTParserIdentity,
    MAX_MANIFEST_BYTES, canonical_manifest_bytes, validate_manifest,
)
from app.services.ett_transport import _validate_document

MAX_HTML_ARTIFACTS = 256
MAX_LINKED_PDFS = 256
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_BINDING_SECONDS = 300
MAX_ISSUES = 1000
MAX_VERIFIED_DETAILS = 1000
MAX_PRIMARY_ANCHORS = 128
_COMPONENTS = (
    "ett_metadata_binding.py", "ett_legal_metadata.py", "ett_detail_identity.py",
    "ett_legal_attachments.py", "ett_index.py", "ett_transport.py",
    "ett_manifest.py", "ett_evidence_binding.py",
)


class MetadataBindingError(native.EvidenceBindingError):
    """Sanitized input or parser identity failure, without raw source text."""


def supported_metadata_parser_identity() -> ETTParserIdentity:
    """Pin the DOM projection, attachment/identity replay and parser dependencies."""
    try:
        root = Path(__file__).parent
        components = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in _COMPONENTS}
        components["stdlib_html_parser"] = hashlib.sha256(Path(html.parser.__file__).read_bytes()).hexdigest()
        components["beautifulsoup_version"] = bs4.__version__
        components["soupsieve_version"] = soupsieve.__version__
        components["python_version"] = ".".join(map(str, sys.version_info[:3]))
    except OSError:
        raise MetadataBindingError("metadata parser identity is unavailable") from None
    encoded = json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
    return ETTParserIdentity(name="ett_legal_metadata", version="1", sha256=hashlib.sha256(encoded).hexdigest())


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MetadataBindingError(reason)


def _original_primary_anchors(raw: bytes, metadata: dict) -> list[dict]:
    """Replay only the metadata container's own primary document attachment group."""
    _require(metadata["container_count"] == 1 and not any(row["issues"] for row in metadata["rows"]),
             "ambiguous_metadata_structure")
    labels = [row["labels"][0]["text"] for row in metadata["rows"]]
    _require(len(labels) == len(set(labels)), "duplicate_metadata_label")
    source = raw.decode("utf-8-sig", errors="strict")
    guard = _AttachmentGuard()
    guard.feed(source)
    guard.close()
    guard.verify()
    soup = BeautifulSoup(source, "html.parser")
    info = next(node for node in soup.select(".DocDetail_Info") if _visible(node))
    detail = info.find_parent(class_="DocDetail")
    _require(detail is not None, "metadata_has_no_own_document_scope")
    files = [node for node in detail.select(".DocDetail_Files") if _visible(node)
             and node.find_parent(class_="DocDetail") is detail]
    _require(len(files) == 1, "ambiguous_document_attachment_scope")
    groups = []
    for group in files[0].select(".DocDetail_Files_Group"):
        if not _visible(group) or group.find_parent(class_="DocDetail_Files") is not files[0]:
            continue
        _require(group.find_parent(class_="DocDetail_Files_Group") is None, "nested_attachment_group")
        titles = [node for node in group.select(".DocDetail_Files_Title") if _visible(node)]
        if len(titles) == 1 and _text(titles[0]) == "Документ":
            groups.append(group)
    _require(len(groups) == 1, "ambiguous_or_missing_primary_document_group")
    references = []
    for position, anchor in enumerate(soup.body.find_all("a"), 1):
        if (not _visible(anchor) or anchor.find_parent(class_="DocDetail_Files_Group") is not groups[0]
                or anchor.find_parent(class_="DocDetail") is not detail
                or anchor.find_parent(class_="DocDetail_Files") is not files[0]):
            continue
        href = anchor.get("href")
        if not isinstance(href, str) or not re.search(r"\.pdf(?:$|[?#])", unquote(href).strip(), re.I):
            continue
        target, text = _attachment_target(href, metadata["source_url"]), _text(anchor)
        _require(len(text) <= 8192 and len(references) < MAX_PRIMARY_ANCHORS, "primary_anchor_limit")
        raw_href = guard.href_literals.get((anchor.sourceline, anchor.sourcepos))
        _require(isinstance(raw_href, str), "primary_anchor_literal_missing")
        described = _anchor_identity(text)
        if described is None and re.search(r"Решени[ея]|Распоряжение|Протокол", text, re.I):
            raise MetadataBindingError("unsupported_descriptive_primary_anchor")
        references.append({
            "url": target, "href": href, "raw_href": raw_href, "text": text,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "locator": f"html:a:{position}:line:{anchor.sourceline}:column:{anchor.sourcepos}",
            "described_identity": described,
        })
    return references


def _verify_occurrence(reference, metadata, anchors) -> str:
    expected = reference.expected_identity.model_dump(mode="json")
    fields = metadata["fields"]
    for name in ("short_title", "document_number", "adoption_date", "document_type", reference.field):
        _require(fields[name]["status"] == "observed", "metadata_field_missing_or_ambiguous")
    _require(fields["document_number"]["observed_text"] == expected["number"]
             and fields["adoption_date"]["observed_iso_date"] == expected["adoption_date"],
             "metadata_identity_mismatch")
    try:
        _category(fields["document_type"]["observed_text"], expected, "metadata")
        title_status = _title_status(fields["short_title"]["observed_text"], expected, "metadata")
    except ETTDetailIdentityError:
        raise MetadataBindingError("metadata_identity_mismatch") from None
    positions = fields[reference.field]["observation_rows"]
    _require(len(positions) == 1, "metadata_field_missing_or_ambiguous")
    row = metadata["rows"][positions[0] - 1]
    projections = (
        (row["row_evidence"], reference),
        (row["labels"][0], reference.label),
        (row["values"][0], reference.value),
    )
    for original, claimed in projections:
        _require(original["locator"] == claimed.locator, "metadata_locator_mismatch")
        _require(original["raw_text"] == claimed.raw_text
                 and original["raw_text_sha256"] == claimed.raw_text_sha256, "metadata_text_mismatch")
    qualifying = [anchor for anchor in anchors if anchor["described_identity"] is not None]
    _require(qualifying and all(anchor["described_identity"] == expected for anchor in qualifying),
             "primary_anchor_identity_mismatch")
    _require(len({anchor["url"] for anchor in qualifying}) == 1, "ambiguous_primary_pdf_target")
    asserted = reference.pdf_binding.model_dump(exclude={"artifact_id", "artifact_sha256"})
    matches = [anchor for anchor in qualifying if anchor["locator"] == asserted["locator"]]
    _require(len(matches) == 1, "primary_anchor_locator_mismatch")
    _require({key: matches[0][key] for key in asserted} == asserted, "primary_anchor_projection_mismatch")
    return title_status


def _validated(manifest):
    try:
        validated = validate_manifest(manifest)
        encoded = canonical_manifest_bytes(validated)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise MetadataBindingError("ETT manifest validation failed") from None
    _require(len(encoded) <= MAX_MANIFEST_BYTES, "ETT manifest exceeds the bounded input size")
    references = []
    for item in native._references(validated):
        _require(len(references) < native.MAX_REFERENCES, "ETT evidence reference count exceeds its limit")
        references.append(item)
    return validated, encoded, references


def _verify_metadata(validated, encoded, references, store):
    identity = supported_metadata_parser_identity()
    artifact_map = {artifact.artifact_id: artifact for artifact in validated.artifacts}
    grouped = defaultdict(list)
    for where, reference in references:
        grouped[reference.artifact_id].append((where, reference))
    issues, verified_occurrences = [], []
    failures, verified, source_bytes, html_attempts = 0, 0, 0, 0
    linked_pdfs: dict[str, str | None] = {}
    parsed_sources = []
    started = time.monotonic()

    def issue(where, reference, reason):
        nonlocal failures
        failures += 1
        if len(issues) < MAX_ISSUES:
            issues.append({"where": where, "artifact_id": reference.artifact_id,
                           "artifact_sha256": reference.artifact_sha256,
                           "field": reference.field, "locator": reference.locator, "reason": reason})

    def read(artifact, *, html_source=False):
        nonlocal source_bytes
        _require(time.monotonic() - started < MAX_BINDING_SECONDS, "metadata_binding_time_limit")
        _require(not html_source or artifact.size_bytes <= MAX_INDEX_BYTES, "metadata_html_size_limit")
        _require(source_bytes + artifact.size_bytes <= MAX_SOURCE_BYTES, "aggregate_source_size_limit")
        try:
            body = store.read(artifact.sha256)
        except (ArtifactIntegrityError, OSError):
            raise MetadataBindingError("artifact_unavailable_or_corrupt") from None
        _require(time.monotonic() - started < MAX_BINDING_SECONDS, "metadata_binding_time_limit")
        _require(type(body) is bytes and len(body) == artifact.size_bytes
                 and hashlib.sha256(body).hexdigest() == artifact.sha256, "artifact_integrity_mismatch")
        source_bytes += len(body)
        return body

    for artifact_id in sorted(grouped):
        occurrences = grouped[artifact_id]
        artifact = artifact_map[artifact_id]
        try:
            _require(html_attempts < MAX_HTML_ARTIFACTS, "metadata_html_artifact_count_limit")
            html_attempts += 1
            raw = read(artifact, html_source=True)
            metadata = parse_legal_metadata(raw, artifact.url)
            anchors = _original_primary_anchors(raw, metadata)
            _require(time.monotonic() - started < MAX_BINDING_SECONDS, "metadata_binding_time_limit")
        except MetadataBindingError as exc:
            for where, reference in occurrences:
                issue(where, reference, str(exc))
            continue
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, StopIteration, RecursionError):
            for where, reference in occurrences:
                issue(where, reference, "metadata_source_parse_failed")
            continue
        parsed_sources.append({"artifact_id": artifact_id, "sha256": artifact.sha256,
                               "metadata_rows": len(metadata["rows"]), "primary_pdf_anchor_count": len(anchors)})
        for where, reference in occurrences:
            try:
                _require(time.monotonic() - started < MAX_BINDING_SECONDS, "metadata_binding_time_limit")
                _require(reference.parser == identity, "metadata_parser_identity_mismatch")
                title_status = _verify_occurrence(reference, metadata, anchors)
                pdf = artifact_map[reference.pdf_binding.artifact_id]
                if pdf.artifact_id not in linked_pdfs:
                    _require(len(linked_pdfs) < MAX_LINKED_PDFS, "linked_pdf_artifact_count_limit")
                    try:
                        body = read(pdf)
                        _validate_document(body, "application/pdf")
                        linked_pdfs[pdf.artifact_id] = None
                    except MetadataBindingError as exc:
                        linked_pdfs[pdf.artifact_id] = str(exc)
                    except ValueError:
                        linked_pdfs[pdf.artifact_id] = "linked_pdf_document_shape_failed"
                _require(linked_pdfs[pdf.artifact_id] is None, linked_pdfs[pdf.artifact_id] or "linked_pdf_unverified")
                verified += 1
                if len(verified_occurrences) < MAX_VERIFIED_DETAILS:
                    verified_occurrences.append({
                        "where": where, "artifact_id": artifact_id, "artifact_sha256": artifact.sha256,
                        "field": reference.field, "locator": reference.locator,
                        "raw_text_sha256": reference.raw_text_sha256,
                        "label_sha256": reference.label.raw_text_sha256,
                        "value_sha256": reference.value.raw_text_sha256,
                        "linked_pdf_artifact_id": pdf.artifact_id, "linked_pdf_sha256": pdf.sha256,
                        "primary_anchor_locator": reference.pdf_binding.locator,
                        "short_title_status": title_status,
                    })
            except MetadataBindingError as exc:
                issue(where, reference, str(exc))
            except (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError):
                issue(where, reference, "metadata_occurrence_replay_failed")
    identity_unchanged = supported_metadata_parser_identity() == identity
    time_limit_reached = time.monotonic() - started >= MAX_BINDING_SECONDS
    if not identity_unchanged or time_limit_reached:
        # Invalidate every occurrence when the global replay contract no longer
        # holds, including prior matches. Never leave a partial positive result.
        issues, failures, verified, verified_occurrences = [], 0, 0, []
        for where, reference in references:
            issue(where, reference, "metadata_parser_changed_during_replay" if not identity_unchanged
                  else "metadata_binding_time_limit")
    return {
        "schema_version": 1, "mode": "legal_portal_metadata_verification",
        "scope": "referenced_html_metadata_and_primary_pdf_byte_bindings_only",
        "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
        "metadata_verified": failures == 0 and verified == len(references),
        "references_total": len(references), "references_verified": verified,
        "references_failed": failures, "html_artifacts_parsed": len(parsed_sources),
        "linked_pdf_artifacts_verified": sum(reason is None for reason in linked_pdfs.values()),
        "source_bytes_verified": source_bytes, "parser": identity.model_dump(mode="json"),
        "parser_unchanged_during_replay": identity_unchanged,
        "parsed_sources": parsed_sources, "verified_occurrences": verified_occurrences,
        "verified_occurrences_truncated": verified > len(verified_occurrences),
        "issues": issues, "issues_truncated": failures > len(issues),
        **_unverified_flags(),
    }


def _unverified_flags() -> dict[str, bool]:
    return {name: False for name in (
        "complete_artifact_inventory_verified", "current_legal_inventory_verified",
        "official_publication_event_verified", "primary_pdf_body_identity_verified",
        "adoption_dates_verified", "effective_dates_verified", "duty_interpretation_verified",
        "footnote_interpretation_verified", "legal_approval_verified", "production_ready",
        "can_promote", "active_rates_written",
    )}


def verify_manifest_source_metadata(manifest: ETTManifest | dict[str, Any] | bytes | str,
                                    store: LocalArtifactStore) -> dict[str, Any]:
    """Replay typed metadata occurrences only; never attest native PDF rows."""
    validated, encoded, references = _validated(manifest)
    selected = [(where, ref) for where, ref in references if isinstance(ref, ETTLegalPortalMetadataEvidence)]
    return _verify_metadata(validated, encoded, selected, store)


def verify_manifest_source_evidence(manifest: ETTManifest | dict[str, Any] | bytes | str,
                                    store: LocalArtifactStore) -> dict[str, Any]:
    """Coordinate both exact source projections without discarding PDF failures.

    References are partitioned by their validated type before either check. No
    issue filtering or inference from truncated issue arrays is performed.
    """
    validated, encoded, references = _validated(manifest)
    pdf_refs = [(where, ref) for where, ref in references if isinstance(ref, ETTEvidence)]
    metadata_refs = [(where, ref) for where, ref in references if isinstance(ref, ETTLegalPortalMetadataEvidence)]
    _require(len(pdf_refs) + len(metadata_refs) == len(references), "unsupported_evidence_type")
    pdf_report = native._verify_source_rows(validated, encoded, pdf_refs, store)
    metadata_report = _verify_metadata(validated, encoded, metadata_refs, store)
    return {
        "schema_version": 1, "mode": "source_evidence_verification",
        "scope": "referenced_native_pdf_rows_and_typed_portal_metadata_only",
        "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
        "source_evidence_verified": pdf_report["rows_verified"] and metadata_report["metadata_verified"],
        "references_total": len(references),
        "references_verified": pdf_report["references_verified"] + metadata_report["references_verified"],
        "references_failed": pdf_report["references_failed"] + metadata_report["references_failed"],
        "pdf_rows": pdf_report, "portal_metadata": metadata_report,
        **_unverified_flags(),
    }
