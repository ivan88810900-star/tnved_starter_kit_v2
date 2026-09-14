"""Deterministic, source-replayed ETT dossiers for a documented review scope.

The immutable value contains canonical manifest bytes and freshly regenerated
checks. Construction reads an explicit object store and uses the existing bounded
PDF workers; it is not a filesystem-free operation. No source objects, database,
network, approval, retention attestation or production state are written.

Additional legal captures are checked only for the selected candidate sources.
Their original discovery/search plan is deliberately NOT attested by this narrow
builder. An assembly-ready dossier is not a legally ready or source-complete set.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any

from app.services.ett_acquisition import (
    DownloadRecord, ExpandedAcquisitionReceipt, canonical_bytes, load_acquisition,
    read_json,
)
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_derived_inventory import verify_derived_amendment_inventory
from app.services.ett_discovery_audit import canonical_json_bytes
from app.services.ett_legal_attachments import parse_legal_attachments
from app.services.ett_legal_capture import _canonical_page, _page_identity
from app.services.ett_manifest import (
    ETTLegalActIdentity, ETTManifest, MAX_MANIFEST_BYTES, canonical_manifest_bytes,
    manifest_sha256, validate_manifest,
)
from app.services.ett_metadata_binding import verify_manifest_source_evidence
from app.services.ett_notes import extract_tariff_notes
from app.services.ett_transport import _validate_document

MAX_PACKAGE_BYTES = 64 * 1024 * 1024
MAX_INPUT_REPORT_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_SOURCE_OBJECTS = 4096
MAX_BUILD_SECONDS = 600
MAX_ASSUMPTIONS = 128
MAX_ASSUMPTION_LENGTH = 8192
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DOWNLOAD_FIELDS = tuple(DownloadRecord.model_fields)
_BINDING_FIELDS = {"page_sha256", "page_url", "attachment_discovery_sha256", "reference_index"}


class ReviewPackageError(ValueError):
    """The bounded dossier cannot be constructed or replayed from its inputs."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReviewPackageError(reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _encode(value: Any) -> bytes:
    output = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8")
        _require(len(output) + len(encoded) <= MAX_PACKAGE_BYTES, "review_package_size_limit")
        output.extend(encoded)
    return bytes(output)


def _json(raw: bytes, maximum: int, reason: str) -> dict:
    _require(type(raw) is bytes and 0 < len(raw) <= maximum, reason)
    value = read_json(raw)
    _require(type(value) is dict, reason)
    return value


@dataclass(frozen=True, slots=True)
class ETTReviewPackage:
    """Immutable encoded value. Only verify_review_package attests full replay."""
    canonical_bytes: bytes

    def __post_init__(self):
        _require(type(self.canonical_bytes) is bytes and 0 < len(self.canonical_bytes) <= MAX_PACKAGE_BYTES,
                 "invalid_review_package_bytes")

    @property
    def sha256(self) -> str:
        return _sha(self.canonical_bytes)

    def as_dict(self) -> dict:
        """Return an independent decoding; callers cannot mutate this value."""
        return _json(self.canonical_bytes, MAX_PACKAGE_BYTES, "invalid_review_package_bytes")


class _ReadContext:
    """One bounded read-only closure; never accepts caller-provided green flags."""
    def __init__(self, store):
        self.store, self.raw, self.total = store, {}, 0
        self.started = time.monotonic()

    def check_time(self):
        _require(time.monotonic() - self.started <= MAX_BUILD_SECONDS, "review_package_time_limit")

    def read(self, digest):
        self.check_time()
        _require(type(digest) is str and _HASH.fullmatch(digest) is not None, "invalid_object_digest")
        if digest not in self.raw:
            _require(len(self.raw) < MAX_SOURCE_OBJECTS, "review_package_object_count_limit")
            raw = self.store.read(digest)
            _require(type(raw) is bytes and 0 < len(raw) <= MAX_MANIFEST_BYTES and _sha(raw) == digest,
                     "source_object_integrity_failure")
            _require(self.total + len(raw) <= MAX_SOURCE_BYTES, "review_package_source_byte_limit")
            self.raw[digest] = raw
            self.total += len(raw)
        return self.raw[digest]

    def verify(self, digest, size):
        _require(type(size) is int and 0 < size <= MAX_MANIFEST_BYTES, "invalid_source_size")
        _require(len(self.read(digest)) == size, "source_object_size_mismatch")

    def closure(self):
        return [{"sha256": digest, "size_bytes": len(self.raw[digest])} for digest in sorted(self.raw)]


def _builder_identity():
    names = ("ett_review_package.py", "ett_acquisition.py", "ett_derived_inventory.py", "ett_notes.py",
             "ett_metadata_binding.py", "ett_evidence_binding.py", "ett_manifest.py", "ett_legal_capture.py",
             "ett_legal_attachments.py", "ett_index.py", "ett_transport.py")
    directory = Path(__file__).parent
    components = {name: _sha((directory / name).read_bytes()) for name in names}
    return {"name": "ett-review-package", "version": "1", "sha256": _sha(canonical_bytes(components)),
            "components": components}


def _semantic_diff(before: ETTManifest | None, after: ETTManifest) -> dict:
    """Pure equivalent of repository.semantic_diff; imports no repository/ORM."""
    result = {
        "before_manifest_sha256": manifest_sha256(before) if before is not None else None,
        "after_manifest_sha256": manifest_sha256(after), "review_required": True,
        "coverage_changed": before is None or (before.coverage_from, before.coverage_to) != (after.coverage_from, after.coverage_to),
        "parser_changed": before is None or before.parser != after.parser,
        "derived_amendment_inventory_changed": before is None or before.derived_amendment_inventory != after.derived_amendment_inventory,
    }
    for collection, key in (("artifacts", "artifact_id"), ("codes", "code"),
                            ("footnotes", "footnote_id"), ("rate_rules", "rule_id")):
        def values(manifest):
            if manifest is None:
                return {}
            return {(f"{getattr(item, key)}@{item.valid_from.isoformat()}" if collection == "codes" else getattr(item, key)):
                    item.model_dump(mode="json") for item in getattr(manifest, collection)}
        old, new = values(before), values(after)
        shared = old.keys() & new.keys()
        result[collection] = {
            "added": sorted(new.keys() - old.keys()), "removed": sorted(old.keys() - new.keys()),
            "changed": sorted(key for key in shared if _sha(canonical_bytes(old[key])) != _sha(canonical_bytes(new[key]))),
        }
    return result


def _same_response(artifact, record):
    return (artifact.url == record.url and artifact.sha256 == record.sha256
            and artifact.size_bytes == record.size_bytes and artifact.media_type == record.media_type
            and artifact.retrieved_at == record.retrieved_at)


def _core_bindings(manifest, receipt, discovery):
    chapters = {ref.chapter: ref for ref in discovery.chapters}
    notes = {"tariff_notes": discovery.tariff_notes, "nomenclature_notes": discovery.nomenclature_notes}
    amendments = {ref.url: ref for ref in discovery.amendment_links}
    results, extras = [], []
    for artifact in manifest.artifacts:
        options = []
        if artifact.role == "index":
            options = [("index_start", receipt.index_start, None), ("index_end", receipt.index_end, None)]
        elif artifact.role in {"chapter", "tariff_notes", "nomenclature_notes"}:
            ref = chapters[artifact.chapter] if artifact.role == "chapter" else notes[artifact.role]
            options = [(f"downloads[{index}]", record, asdict(ref)) for index, record in enumerate(receipt.downloads)
                       if record.requested_url == ref.url]
        elif artifact.role == "amendment":
            options = [(f"downloads[{index}]", record, asdict(amendments[record.requested_url]))
                       for index, record in enumerate(receipt.downloads) if record.requested_url in amendments]
            options += [(f"attachment_downloads[{index}]", record, None)
                        for index, record in enumerate(receipt.attachment_downloads)]
        matches = [{"receipt_locator": where, "download": record.model_dump(mode="json"), "discovery_reference": ref}
                   for where, record, ref in options if _same_response(artifact, record)]
        if matches:
            results.append({"artifact_id": artifact.artifact_id, "role": artifact.role,
                            "status": "core_v2_capture_bound", "capture_bindings": matches})
        else:
            extras.append(artifact)
    return results, extras


def _supplemental(manifest, extras, digest, context):
    result = {"capture_report_sha256": digest, "scope": "selected_candidate_additional_sources_only",
              "discovery_plan_replayed": False, "whole_capture_report_replayed": False,
              "selected_sources": [], "unsupported_references": [], "unbound_artifact_ids": [],
              "unselected_capture_records_verified": False, "original_retrieval_timestamps_preserved": True}
    if digest is None:
        result["unbound_artifact_ids"] = [item.artifact_id for item in extras]
        return result
    raw = context.read(digest)
    capture = _json(raw, MAX_INPUT_REPORT_BYTES, "invalid_supplemental_capture_report")
    _require(type(capture.get("schema_version")) is int and capture["schema_version"] == 1
             and capture.get("kind") == "ett_observed_legal_document_capture",
             "invalid_supplemental_capture_report")
    for field, limit in (("documents", 110), ("pdfs", 256)):
        _require(type(capture.get(field)) is list and len(capture[field]) <= limit,
                 "invalid_supplemental_capture_records")
    result["capture_report_size_bytes"] = len(raw)
    result["reported_document_records"] = len(capture["documents"])
    result["reported_pdf_records"] = len(capture["pdfs"])
    pages, pdfs = {}, []
    for artifact in extras:
        if artifact.role != "amendment" or artifact.media_type not in {"text/html", "application/pdf"}:
            result["unbound_artifact_ids"].append(artifact.artifact_id)
            continue
        field = "documents" if artifact.media_type == "text/html" else "pdfs"
        candidates = []
        for index, row in enumerate(capture[field]):
            _require(type(row) is dict, "invalid_supplemental_capture_record")
            if row.get("url") != artifact.url:
                continue
            _require(row.get("status") == "captured", "selected_additional_source_not_captured")
            record = DownloadRecord.model_validate({key: row[key] for key in _DOWNLOAD_FIELDS})
            if _same_response(artifact, record):
                candidates.append((index, row, record))
        _require(len(candidates) <= 1, "ambiguous_selected_additional_source")
        if not candidates:
            result["unbound_artifact_ids"].append(artifact.artifact_id)
            continue
        index, row, record = candidates[0]
        original = context.read(artifact.sha256)
        _validate_document(original, artifact.media_type)
        selected = {"artifact_id": artifact.artifact_id, "capture_locator": f"{field}[{index}]",
                    "download": record.model_dump(mode="json")}
        if artifact.media_type == "text/html":
            expected = ETTLegalActIdentity.model_validate(row["expected_identity"]).model_dump(mode="json")
            _canonical_page(record.requested_url)
            _require(record.requested_url == record.url, "selected_portal_final_url_changed")
            identity = _page_identity(original, expected)
            # This expected identity came from one supplied capture record;
            # unlike capture_legal_documents, this builder did not replay the
            # complete discovery plan that originally authorized that record.
            identity.pop("metadata_matches_discovery_identity")
            identity.update(metadata_matches_supplied_capture_identity=True,
                            expected_identity_origin="selected_capture_record_not_replayed_discovery_plan")
            attachments = parse_legal_attachments(original, artifact.url)
            attachment_raw = canonical_json_bytes(asdict(attachments))
            _require(_sha(attachment_raw) == row["attachment_discovery_sha256"]
                     and context.read(row["attachment_discovery_sha256"]) == attachment_raw,
                     "selected_attachment_discovery_does_not_replay")
            selected.update(identity=identity, attachment_discovery_sha256=row["attachment_discovery_sha256"],
                            observed_pdf_references=[asdict(ref) for ref in attachments.documents])
            result["unsupported_references"].extend({"page_url": artifact.url, "page_sha256": artifact.sha256, **asdict(ref)}
                                                     for ref in attachments.unsupported_references)
            pages[artifact.url] = (artifact, row, attachments)
            result["selected_sources"].append(selected)
        else:
            pdfs.append((artifact, row, record, selected))
    for artifact, row, record, selected in pdfs:
        references = row.get("source_references")
        _require(type(references) is list and 0 < len(references) <= 1024, "missing_selected_pdf_parent_bindings")
        matched = []
        for reference in references:
            _require(type(reference) is dict and set(reference) == _BINDING_FIELDS, "invalid_selected_pdf_parent_binding")
            parent = pages.get(reference["page_url"])
            if parent is None:
                continue
            page_artifact, page_record, attachments = parent
            index = reference["reference_index"]
            _require(type(index) is int and 0 <= index < len(attachments.documents), "invalid_selected_pdf_anchor_index")
            observed = attachments.documents[index]
            _require(reference["page_sha256"] == page_artifact.sha256
                     and reference["attachment_discovery_sha256"] == page_record["attachment_discovery_sha256"]
                     and observed.url == record.requested_url, "selected_pdf_parent_binding_mismatch")
            matched.append({"capture_binding": reference, "observed_reference": asdict(observed)})
        if not matched:
            result["unbound_artifact_ids"].append(artifact.artifact_id)
            continue
        _require(len({_sha(canonical_bytes(ref)) for ref in matched}) == len(matched), "duplicate_selected_pdf_parent_binding")
        selected["parent_bindings"] = matched
        selected["other_parent_bindings_not_replayed"] = len(references) - len(matched)
        result["selected_sources"].append(selected)
    result["selected_sources"].sort(key=lambda item: item["artifact_id"])
    return result


def build_review_package(manifest: ETTManifest | dict | bytes | str, store: LocalArtifactStore, *,
                         acquisition_receipt_sha256: str, prior_manifest: ETTManifest | dict | bytes | str | None,
                         supplemental_capture_report_sha256: str | None = None,
                         assumptions: tuple[str, ...] = ()) -> ETTReviewPackage:
    """Replay originals and return an immutable narrow review dossier.

    ``prior_manifest=None`` explicitly means an initial candidate. Assumptions
    are unreviewed text supplied for review, not accepted verification reports.
    Every structural/source check is recomputed; there is no report override.
    """
    try:
        context = _ReadContext(store)
        _require(type(assumptions) is tuple and len(assumptions) <= MAX_ASSUMPTIONS
                 and all(type(item) is str and 0 < len(item) <= MAX_ASSUMPTION_LENGTH
                         and item.strip() and "\x00" not in item for item in assumptions), "invalid_review_assumptions")
        current = validate_manifest(manifest)
        before = validate_manifest(prior_manifest) if prior_manifest is not None else None
        encoded = canonical_manifest_bytes(current)
        prior_bytes = canonical_manifest_bytes(before) if before is not None else None
        _require(len(encoded) + (len(prior_bytes) if prior_bytes is not None else 0) <= MAX_PACKAGE_BYTES // 2,
                 "review_package_manifest_byte_limit")
        # Every comparison uses the canonical manifests actually embedded in
        # this dossier, including canonical exact-decimal serialization.
        current = validate_manifest(encoded)
        before = validate_manifest(prior_bytes) if prior_bytes is not None else None
        builder = _builder_identity()
        receipt_raw = context.read(acquisition_receipt_sha256)
        _json(receipt_raw, MAX_INPUT_REPORT_BYTES, "invalid_acquisition_receipt")
        receipt, discovery = load_acquisition(context, acquisition_receipt_sha256)
        _require(isinstance(receipt, ExpandedAcquisitionReceipt) and receipt.schema_version == 2,
                 "complete_v2_acquisition_receipt_required")
        # A content hash authenticates retained bytes, not their declared
        # document type. Replay the transport's shape gate for every complete
        # core capture record, including chapters absent from this code slice.
        for record in (receipt.index_start, *receipt.downloads, *receipt.attachment_downloads, receipt.index_end):
            _validate_document(context.read(record.sha256), record.media_type)
        for artifact in current.artifacts:
            context.verify(artifact.sha256, artifact.size_bytes)
        core, extras = _core_bindings(current, receipt, discovery)
        additional = _supplemental(current, extras, supplemental_capture_report_sha256, context)
        blockers = [f"candidate_source_capture_or_role_unbound:{item}" for item in additional["unbound_artifact_ids"]]
        derived = current.derived_amendment_inventory
        if derived is not None:
            verify_derived_amendment_inventory(current, context)
            inventory = {"mode": "derived_index_inventory", "replayed": True,
                         "descriptor": derived.model_dump(mode="json"),
                         "report": _json(context.read(derived.report_sha256), MAX_INPUT_REPORT_BYTES, "invalid_derived_inventory")}
        else:
            inventory = {"mode": "official_inventory_artifact", "replayed": False,
                         "reason": "separate_official_inventory_role_has_no_supported_semantic_replay"}
            blockers.append("official_amendment_inventory_replay_unsupported")
        note_artifact = next(item for item in current.artifacts if item.role == "tariff_notes")
        note_report = extract_tariff_notes(context.read(note_artifact.sha256), artifact_id=note_artifact.artifact_id)
        evidence = verify_manifest_source_evidence(current, context)
        _require(evidence["manifest_sha256"] == _sha(encoded), "source_evidence_manifest_identity_mismatch")
        if evidence["source_evidence_verified"] is not True:
            blockers.append("candidate_source_evidence_does_not_replay")
        attachments = _json(b'{"items":' + context.read(receipt.legal_attachment_inventory_sha256) + b'}',
                            MAX_INPUT_REPORT_BYTES, "invalid_core_attachment_inventory")["items"]
        unresolved = ["complete_legal_inventory_not_verified", "legal_date_and_code_version_interpretation_not_approved",
                      "rate_and_footnote_interpretation_not_approved", "local_storage_is_not_retention_attestation",
                      "no_legal_approval_or_production_promotion"]
        if extras or supplemental_capture_report_sha256 is not None:
            unresolved.append("selected_additional_source_discovery_plan_not_replayed")
        if assumptions:
            unresolved.append("supplied_review_assumptions_are_unverified")
        result = {
            "schema_version": 1, "kind": "ett_manifest_bound_review_package", "builder": builder,
            "inputs": {"candidate_manifest_canonical_json": encoded.decode("utf-8"),
                       "prior_manifest_canonical_json": prior_bytes.decode("utf-8") if prior_bytes is not None else None,
                       "acquisition_receipt_sha256": acquisition_receipt_sha256,
                       "supplemental_capture_report_sha256": supplemental_capture_report_sha256,
                       "assumptions": list(assumptions)},
            "candidate": {"manifest_sha256": _sha(encoded), "canonical_size_bytes": len(encoded),
                          "snapshot_id": current.snapshot_id, "code_count": len(current.codes),
                          "rate_rule_count": len(current.rate_rules), "artifact_count": len(current.artifacts)},
            "prior_manifest": {"manifest_sha256": _sha(prior_bytes) if prior_bytes is not None else None,
                               "canonical_size_bytes": len(prior_bytes) if prior_bytes is not None else None,
                               "source_objects_replayed": False, "scope": "canonical_manifest_and_semantic_diff_only"},
            "core_acquisition": {"receipt_sha256": acquisition_receipt_sha256, "receipt_size_bytes": len(receipt_raw),
                                 "schema_version": 2, "complete_supported_plan_replayed": True,
                                 "receipt": receipt.model_dump(mode="json"),
                                 "discovery": json.loads(canonical_json_bytes(asdict(discovery))),
                                 "attachment_inventory": attachments, "legal_inventory_complete": False},
            "source_bindings": core,
            "supplemental_sources": additional,
            "derived_inventory": inventory,
            "tariff_notes": {"recomputed_from_original": True, "report_sha256": _sha(canonical_bytes(note_report)),
                             "report": note_report},
            "source_evidence": evidence,
            "source_evidence_report_sha256": _sha(canonical_bytes(evidence)),
            "semantic_diff": _semantic_diff(before, current),
            "assumptions": {"status": "unreviewed_supplied_text", "items": list(assumptions), "verified": False},
            "required_object_closure": context.closure(),
            "required_objects_read": len(context.raw), "required_bytes_read": context.total,
            "required_original_bytes_verified": True,
            "assembly_scope": "core_v2_plan_and_candidate_sources_with_selected_additional_capture_bindings",
            "assembly_blockers": sorted(set(blockers)), "unresolved": unresolved,
            "assembly_ready": not blockers, "package_ready": not blockers,
            "source_complete": False, "all_source_acquisition_verified": False,
            "legal_ready": False, "legal_inventory_complete": False, "legal_approval_verified": False,
            "effective_dates_verified": False, "duty_interpretation_verified": False,
            "footnote_interpretation_verified": False, "retention_attested": False,
            "production_ready": False, "can_promote": False, "active_rates_written": False,
        }
        raw_package = _encode(result)
        context.check_time()
        _require(_builder_identity() == builder, "review_package_builder_changed_during_replay")
        return ETTReviewPackage(raw_package)
    except ReviewPackageError:
        raise
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError, OverflowError, AttributeError):
        raise ReviewPackageError("review_package_source_replay_failed") from None


def verify_review_package(package: ETTReviewPackage | bytes, store: LocalArtifactStore) -> ETTReviewPackage:
    """Rebuild every check and compare the entire exact canonical dossier."""
    try:
        raw = package.canonical_bytes if isinstance(package, ETTReviewPackage) else package
        value = _json(raw, MAX_PACKAGE_BYTES, "invalid_review_package")
        inputs = value["inputs"]
        _require(type(inputs) is dict and set(inputs) == {
            "candidate_manifest_canonical_json", "prior_manifest_canonical_json", "acquisition_receipt_sha256",
            "supplemental_capture_report_sha256", "assumptions"}, "invalid_review_package_inputs")
        _require(type(inputs["candidate_manifest_canonical_json"]) is str
                 and (inputs["prior_manifest_canonical_json"] is None or type(inputs["prior_manifest_canonical_json"]) is str)
                 and type(inputs["assumptions"]) is list, "invalid_review_package_inputs")
        rebuilt = build_review_package(
            inputs["candidate_manifest_canonical_json"], store,
            acquisition_receipt_sha256=inputs["acquisition_receipt_sha256"],
            prior_manifest=inputs["prior_manifest_canonical_json"],
            supplemental_capture_report_sha256=inputs["supplemental_capture_report_sha256"],
            assumptions=tuple(inputs["assumptions"]),
        )
        _require(rebuilt.canonical_bytes == raw, "review_package_does_not_match_full_replay")
        return rebuilt
    except ReviewPackageError:
        raise
    except (ValueError, TypeError, KeyError, OSError, UnicodeError, RecursionError, OverflowError, AttributeError):
        raise ReviewPackageError("review_package_replay_failed") from None
