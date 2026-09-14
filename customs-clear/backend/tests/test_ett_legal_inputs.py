from datetime import datetime, timezone
import hashlib
import json

import pytest

from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_index import INDEX_URL, parse_index
from app.services.ett_transport import OfficialResponse
from scripts.capture_ett_legal_inputs import capture_inputs
from tests.ett_index_fixtures import synthetic_index_html


def test_bootstrap_fetches_only_index_and_exact_observed_notes(tmp_path):
    raw = synthetic_index_html()
    notes = b"synthetic extraction input, not a normative PDF"
    calls = []
    def fetch(url, *, expected_media):
        calls.append((url, expected_media))
        return OfficialResponse(url=url, requested_url=url, media_type=expected_media,
                                content=raw if url == INDEX_URL else notes,
                                retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc))
    output = tmp_path / "inputs"
    output.mkdir(mode=0o700)
    store = LocalArtifactStore(tmp_path / "store")
    report = capture_inputs(store, output, fetch=fetch,
                            extract=lambda data, **kw: {"fixture": "synthetic", "source_sha256": hashlib.sha256(data).hexdigest()})
    assert calls == [(INDEX_URL, "text/html"), (parse_index(raw).tariff_notes.url, "application/pdf")]
    assert store.read(report["index"]["sha256"]) == raw
    assert store.read(report["notes_source"]["sha256"]) == notes
    assert json.loads((output / "inventory.json").read_text())["named_count"] == 3
    assert report["acquisition_complete"] is report["production_ready"] is False
    with pytest.raises(FileExistsError):
        capture_inputs(store, output, fetch=fetch)


def test_extraction_failure_preserves_originals_without_complete_report(tmp_path):
    raw = synthetic_index_html()
    notes = b"synthetic failing PDF"
    def fetch(url, *, expected_media):
        return OfficialResponse(url=url, requested_url=url, media_type=expected_media,
                                content=raw if url == INDEX_URL else notes,
                                retrieved_at=datetime(2026, 9, 8, tzinfo=timezone.utc))
    def fail(*args, **kwargs):
        raise ValueError("unreadable source")
    output = tmp_path / "inputs"
    output.mkdir(mode=0o700)
    store = LocalArtifactStore(tmp_path / "store")
    with pytest.raises(ValueError, match="unreadable source"):
        capture_inputs(store, output, fetch=fetch, extract=fail)
    assert (output / "index.html").read_bytes() == raw
    assert (output / "tariff-notes.pdf").read_bytes() == notes
    assert not (output / "inputs.json").exists()
