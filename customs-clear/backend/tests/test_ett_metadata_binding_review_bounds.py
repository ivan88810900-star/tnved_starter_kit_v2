"""Independent regressions for metadata replay limits and parser provenance."""
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest
import soupsieve

from app.services import ett_metadata_binding as binding
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_manifest import ETTEvidence, validate_manifest
from tests.ett_fixtures import synthetic_manifest_data
from tests.test_ett_metadata_binding import CASES, FIXTURES, make_reference, sha


APIS = ("verify_manifest_source_metadata", "verify_manifest_source_evidence")


@pytest.fixture
def single_metadata(tmp_path):
    """Keep native references synthetic and never run a PDF extraction worker."""
    data = synthetic_manifest_data()
    raw = (FIXTURES / (CASES[0]["stem"] + ".html")).read_bytes()
    pdf = b"%PDF-1.4\nSynthetic linked bytes for bounded metadata tests\n%%EOF"
    for artifact_id, body, url, media in (
        ("portal-66", raw, CASES[0]["url"], "text/html"),
        ("act-66", pdf, CASES[0]["pdf"], "application/pdf"),
    ):
        data["artifacts"].append({
            "artifact_id": artifact_id, "role": "amendment", "url": url,
            "sha256": sha(body), "size_bytes": len(body), "media_type": media,
            "retrieved_at": "2026-01-01T00:00:00Z",
        })
    reference = make_reference(raw)
    reference["pdf_binding"]["artifact_sha256"] = sha(pdf)
    data["codes"][0]["effective_evidence"].append(reference)
    validate_manifest(data)
    root = tmp_path / "objects"
    writable = LocalArtifactStore(root)
    writable.put(raw)
    writable.put(pdf)
    return data, LocalArtifactStore(root, create=False), sha(pdf)


def _stub_native(monkeypatch):
    def checked_partition(validated, encoded, references, store):
        assert references and all(type(reference) is ETTEvidence for _, reference in references)
        return {"rows_verified": True, "references_total": len(references),
                "references_verified": len(references), "references_failed": 0}
    monkeypatch.setattr(binding.native, "_verify_source_rows", checked_partition)
    monkeypatch.setattr(binding.native, "extract_pdf_evidence",
                        lambda *a, **k: pytest.fail("metadata bounds must not run a PDF worker"))


def _metadata_part(report, api):
    return report["portal_metadata"] if api == "verify_manifest_source_evidence" else report


@pytest.mark.parametrize("api", APIS)
@pytest.mark.parametrize("as_text", [False, True], ids=["bytes", "text"])
def test_deep_json_failure_is_sanitized_before_source_access(monkeypatch, api, as_text):
    raw = b"[" * 20_000 + b'"private-replay-marker"' + b"]" * 20_000
    assert len(raw) < 64 * 1024
    if as_text:
        raw = raw.decode()
    monkeypatch.setattr(binding.native, "_verify_source_rows",
                        lambda *a, **k: pytest.fail("invalid manifest must not start native replay"))

    class NoReads:
        def read(self, digest):
            pytest.fail("invalid manifest must not read source artifacts")

    with pytest.raises(binding.MetadataBindingError) as caught:
        getattr(binding, api)(raw, NoReads())
    assert "private-replay-marker" not in str(caught.value)
    assert caught.value.__suppress_context__ is True


@pytest.mark.parametrize("api", APIS)
@pytest.mark.parametrize("elapsed_offset", [-0.5, 0.0, 1.0], ids=["within-budget", "at-deadline", "after-deadline"])
def test_last_source_read_must_finish_inside_the_metadata_budget(single_metadata, monkeypatch, api, elapsed_offset):
    data, store, pdf_digest = single_metadata
    _stub_native(monkeypatch)
    clock = {"now": 0.0}
    monkeypatch.setattr(binding, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    finished_at = binding.MAX_BINDING_SECONDS + elapsed_offset
    reads = []

    class DelayedRead:
        def read(self, digest):
            reads.append(digest)
            body = store.read(digest)
            if digest == pdf_digest:
                clock["now"] = finished_at
            return body

    report = getattr(binding, api)(data, DelayedRead())
    metadata_report = _metadata_part(report, api)
    assert reads[-1] == pdf_digest
    if elapsed_offset < 0:
        assert metadata_report["metadata_verified"] is True
        assert metadata_report["references_verified"] == 1
        assert metadata_report["references_failed"] == 0
    else:
        assert metadata_report["metadata_verified"] is False
        assert metadata_report["references_verified"] == 0
        assert metadata_report["references_failed"] == 1
        assert metadata_report["verified_occurrences"] == []
        assert any(issue["reason"] == "metadata_binding_time_limit" for issue in metadata_report["issues"])
        if api == "verify_manifest_source_evidence":
            assert report["source_evidence_verified"] is False
    assert metadata_report["effective_dates_verified"] is False
    assert metadata_report["can_promote"] is False


def _selector_version(monkeypatch, version):
    # Permit either package metadata or the public module version as the pin's
    # source. Both describe the same installed selector-engine dependency.
    original = metadata.version
    monkeypatch.setattr(soupsieve, "__version__", version)
    monkeypatch.setattr(metadata, "version", lambda name: version if name.lower().replace("-", "") == "soupsieve" else original(name))


def test_selector_engine_version_changes_the_supported_parser_identity(monkeypatch):
    before = binding.supported_metadata_parser_identity()
    assert binding.supported_metadata_parser_identity() == before
    _selector_version(monkeypatch, "999.0.review")
    after = binding.supported_metadata_parser_identity()
    assert after.name == before.name and after.version == before.version
    assert after.sha256 != before.sha256
    assert binding.supported_metadata_parser_identity() == after


@pytest.mark.parametrize("filename", ["ett_legal_metadata.py", "ett_manifest.py", "ett_evidence_binding.py"])
def test_projection_schema_and_reference_selection_code_changes_invalidate_the_pin(monkeypatch, filename):
    before = binding.supported_metadata_parser_identity()
    component = Path(binding.__file__).parent / filename
    original = Path.read_bytes

    def changed_bytes(path):
        raw = original(path)
        return raw + b"\n# Simulated source drift; no file is modified.\n" if path == component else raw

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    assert binding.supported_metadata_parser_identity().sha256 != before.sha256


@pytest.mark.parametrize("api", APIS)
def test_selector_drift_during_the_last_read_invalidates_the_occurrence(single_metadata, monkeypatch, api):
    data, store, pdf_digest = single_metadata
    _stub_native(monkeypatch)

    class ChangedSelector:
        def read(self, digest):
            raw = store.read(digest)
            if digest == pdf_digest:
                _selector_version(monkeypatch, "999.0.review")
            return raw

    report = getattr(binding, api)(data, ChangedSelector())
    metadata_report = _metadata_part(report, api)
    assert metadata_report["metadata_verified"] is False
    assert metadata_report["parser_unchanged_during_replay"] is False
    assert metadata_report["references_verified"] == 0
    assert metadata_report["references_failed"] == 1
    assert metadata_report["verified_occurrences"] == []
    assert {issue["reason"] for issue in metadata_report["issues"]} == {"metadata_parser_changed_during_replay"}
    if api == "verify_manifest_source_evidence":
        assert report["source_evidence_verified"] is False
