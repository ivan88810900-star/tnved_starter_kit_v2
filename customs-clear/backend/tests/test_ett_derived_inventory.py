"""Derived index inventories bind bytes; synthetic candidates imply no law."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import ett_derived_inventory as subject
from app.services.ett_artifacts import ArtifactIntegrityError, LocalArtifactStore
from app.services.ett_index import INDEX_URL
from app.services.ett_manifest import canonical_manifest_bytes, manifest_sha256, validate_manifest
from app.services.ett_repository import candidate_readiness, load_candidate, semantic_diff, stage_candidate
from tests.ett_fixtures import synthetic_manifest_data
from tests.ett_index_fixtures import synthetic_index_html
from tests.test_ett_repository import workspace


def derived_data(store, *, original=None):
    raw = synthetic_index_html() if original is None else original
    data = synthetic_manifest_data()
    data["artifacts"] = [item for item in data["artifacts"] if item["role"] != "amendment_inventory"]
    source = next(item for item in data["artifacts"] if item["role"] == "index")
    source.update(url=INDEX_URL, sha256=store.put(raw), size_bytes=len(raw))
    report = subject.canonical_inventory_report_bytes(raw)
    data["derived_amendment_inventory"] = {
        "derivation_kind": "eec_index_amendment_inventory_v1", "source_artifact_id": source["artifact_id"],
        "source_artifact_sha256": source["sha256"], "report_sha256": store.put(report),
        "report_size_bytes": len(report), "parser": subject.supported_inventory_parser_identity().model_dump(mode="json"),
    }
    return data


def replace_report(data, store, report):
    binding = data["derived_amendment_inventory"]
    binding["report_sha256"] = store.put(report)
    binding["report_size_bytes"] = len(report)


def test_old_schema_v2_canonical_bytes_and_payload_are_unchanged():
    old = validate_manifest(synthetic_manifest_data())
    raw = canonical_manifest_bytes(old)
    assert len(raw) == 30973
    assert hashlib.sha256(raw).hexdigest() == "dfc7093f5fe87bd39a3bebee633808f725a725c84e8b009a705d8687e5580af3"
    assert "derived_amendment_inventory" not in old.model_dump()
    assert "derived_amendment_inventory" not in old.model_dump(mode="json")
    data = synthetic_manifest_data()
    data["derived_amendment_inventory"] = None
    assert canonical_manifest_bytes(data) == raw


def test_derived_mode_stages_99_official_sources_and_roundtrips_without_migration(workspace):
    engine, store, _ = workspace
    manifest = validate_manifest(derived_data(store))
    assert len(manifest.artifacts) == 99
    assert not any(item.role == "amendment_inventory" for item in manifest.artifacts)
    assert "url" not in manifest.derived_amendment_inventory.model_dump()
    with Session(engine) as db:
        result = stage_candidate(db, store, manifest)
        assert result["created"] is True
        assert load_candidate(db, store, result["manifest_sha256"]) == manifest
        assert db.scalar(text("SELECT count(*) FROM ett_artifacts")) == 99
        assert db.scalar(text("SELECT sentinel FROM hs_rates")) == "existing production rate unchanged"
        readiness = candidate_readiness(manifest)
        assert readiness["production_ready"] is readiness["can_promote"] is readiness["active_rates_written"] is False
        assert "complete_current_legal_inventory_not_independently_verified" in readiness["blockers"]


@pytest.mark.parametrize("mode", ["both", "neither"])
def test_inventory_modes_are_exactly_one(workspace, mode):
    _, store, _ = workspace
    data = derived_data(store)
    if mode == "both":
        data["artifacts"].append(next(item for item in synthetic_manifest_data()["artifacts"] if item["role"] == "amendment_inventory"))
    else:
        del data["derived_amendment_inventory"]
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("change", [
    lambda d: d["derived_amendment_inventory"].update(source_artifact_id="chapter-01"),
    lambda d: d["derived_amendment_inventory"].update(source_artifact_sha256="b" * 64),
    lambda d: d["derived_amendment_inventory"].update(report_size_bytes=True),
    lambda d: d["derived_amendment_inventory"].update(report_size_bytes=16 * 1024 * 1024 + 1),
    lambda d: d["derived_amendment_inventory"].update(derivation_kind="unsupported"),
    lambda d: d["derived_amendment_inventory"].update(url=INDEX_URL),
    lambda d: d["derived_amendment_inventory"].update(legal_inventory_complete=True),
    lambda d: next(item for item in d["artifacts"] if item["role"] == "index").update(media_type="application/json"),
])
def test_descriptor_is_strictly_bound_and_cannot_supply_official_url_or_legal_flags(workspace, change):
    _, store, _ = workspace
    data = derived_data(store)
    change(data)
    with pytest.raises(ValidationError):
        validate_manifest(data)


@pytest.mark.parametrize("change", [
    lambda report: report.update(named_count=999),
    lambda report: report.update(legal_inventory_complete=True),
    lambda report: report.update(legal_inventory_complete=0),
    lambda report: report.update(extra_field="invented"),
    lambda report: report["amendments"][0].update(adoption_date="2030-01-01"),
    lambda report: report["amendments"].pop(),
])
def test_fabricated_report_with_recomputed_digest_fails_before_db_writes(workspace, change):
    engine, store, _ = workspace
    data = derived_data(store)
    report = json.loads(store.read(data["derived_amendment_inventory"]["report_sha256"]))
    change(report)
    replace_report(data, store, json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    with Session(engine) as db:
        with pytest.raises(subject.DerivedInventoryError, match="complete replayed result"):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


@pytest.mark.parametrize("alter", [
    lambda raw: raw + b"\n",
    lambda raw: raw.replace(b'"legal_inventory_complete":false', b'"legal_inventory_complete":false,"legal_inventory_complete":false'),
])
def test_exact_canonical_bytes_reject_noncanonical_and_duplicate_key_reports(workspace, alter):
    _, store, _ = workspace
    data = derived_data(store)
    replace_report(data, store, alter(store.read(data["derived_amendment_inventory"]["report_sha256"])))
    with pytest.raises(subject.DerivedInventoryError, match="complete replayed result"):
        subject.verify_derived_amendment_inventory(validate_manifest(data), store)


def test_rehashed_source_change_cannot_reuse_old_report(workspace):
    engine, store, _ = workspace
    data = derived_data(store)
    source = next(item for item in data["artifacts"] if item["role"] == "index")
    changed = synthetic_index_html().replace(b"11.08.2026", b"12.08.2026")
    source.update(sha256=store.put(changed), size_bytes=len(changed))
    data["derived_amendment_inventory"]["source_artifact_sha256"] = source["sha256"]
    with Session(engine) as db:
        with pytest.raises(subject.DerivedInventoryError, match="complete replayed result"):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


def test_wrong_official_index_url_fails_before_db_writes(workspace):
    engine, store, _ = workspace
    data = derived_data(store)
    next(item for item in data["artifacts"] if item["role"] == "index")["url"] = "https://eec.eaeunion.org/unrelated-index"
    with Session(engine) as db:
        with pytest.raises(subject.DerivedInventoryError, match="actual official ETT index"):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


@pytest.mark.parametrize("field,value", [("name", "unsupported"), ("version", "2"), ("sha256", "b" * 64)])
def test_unsupported_parser_identity_fails_before_db_writes(workspace, field, value):
    engine, store, _ = workspace
    data = derived_data(store)
    data["derived_amendment_inventory"]["parser"][field] = value
    with Session(engine) as db:
        with pytest.raises(subject.DerivedInventoryError, match="supported parser"):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


@pytest.mark.parametrize("object_kind", ["source", "report"])
def test_missing_retained_object_fails_before_db_writes(workspace, tmp_path, object_kind):
    engine, store, _ = workspace
    data = derived_data(store)
    binding = data["derived_amendment_inventory"]
    digest = binding["report_sha256"] if object_kind == "report" else binding["source_artifact_sha256"]
    (tmp_path / "objects" / (digest + ".blob")).unlink()
    with Session(engine) as db:
        with pytest.raises(ArtifactIntegrityError):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


@pytest.mark.parametrize("failure", ["missing_report", "corrupt_report", "parser_drift"])
def test_each_stored_preview_reverifies_report_and_parser(workspace, tmp_path, monkeypatch, failure):
    engine, store, _ = workspace
    manifest = validate_manifest(derived_data(store))
    with Session(engine) as db:
        digest = stage_candidate(db, store, manifest)["manifest_sha256"]
    report = tmp_path / "objects" / (manifest.derived_amendment_inventory.report_sha256 + ".blob")
    if failure == "missing_report":
        report.unlink()
    elif failure == "corrupt_report":
        report.chmod(0o600)
        report.write_bytes(b"changed retained report")
        report.chmod(0o400)
    else:
        changed = subject.supported_inventory_parser_identity().model_copy(update={"sha256": "b" * 64})
        monkeypatch.setattr(subject, "supported_inventory_parser_identity", lambda: changed)
    with Session(engine) as db:
        with pytest.raises((ArtifactIntegrityError, subject.DerivedInventoryError)):
            load_candidate(db, store, digest)


def test_parser_component_read_failure_is_sanitized(workspace, monkeypatch):
    _, store, _ = workspace
    manifest = validate_manifest(derived_data(store))
    original = Path.read_bytes
    def fail(path):
        if path.name == "ett_index.py":
            raise OSError("private source path")
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", fail)
    with pytest.raises(subject.DerivedInventoryError, match="identity is unavailable") as error:
        subject.verify_derived_amendment_inventory(manifest, store)
    assert "private source path" not in str(error.value)


def test_declared_report_size_must_match_the_retained_object(workspace):
    engine, store, _ = workspace
    data = derived_data(store)
    data["derived_amendment_inventory"]["report_size_bytes"] += 1
    with Session(engine) as db:
        with pytest.raises(subject.DerivedInventoryError, match="integrity failure"):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


def test_parser_change_during_replay_is_rejected(workspace, monkeypatch):
    _, store, _ = workspace
    manifest = validate_manifest(derived_data(store))
    identity = subject.supported_inventory_parser_identity()
    values = iter([identity, identity.model_copy(update={"sha256": "b" * 64})])
    monkeypatch.setattr(subject, "supported_inventory_parser_identity", lambda: next(values))
    with pytest.raises(subject.DerivedInventoryError, match="changed during replay"):
        subject.verify_derived_amendment_inventory(manifest, store)


def test_verification_is_read_only_and_all_unresolved_source_details_survive(workspace, monkeypatch):
    _, store, _ = workspace
    manifest = validate_manifest(derived_data(store))
    def forbidden(*args, **kwargs):
        pytest.fail("Replay must not write an object")
    monkeypatch.setattr(LocalArtifactStore, "put", forbidden)
    subject.verify_derived_amendment_inventory(manifest, store)
    report = json.loads(store.read(manifest.derived_amendment_inventory.report_sha256))
    assert report["missing_link_count"] == 2
    assert report["legal_inventory_complete"] is report["act_bodies_verified"] is report["effective_dates_resolved"] is False


def test_actual_retained_index_replays_without_creating_a_normative_candidate(tmp_path):
    raw = (Path(__file__).parent / "fixtures/ett_index/eec_run_34235767121.html").read_bytes()
    store = LocalArtifactStore(tmp_path / "objects")
    # Rates/dates remain explicitly synthetic; this test establishes only that
    # the genuine retained index can supply the derived inventory binding.
    manifest = validate_manifest(derived_data(store, original=raw))
    subject.verify_derived_amendment_inventory(manifest, store)
    report = json.loads(store.read(manifest.derived_amendment_inventory.report_sha256))
    assert report["named_count"] == 105 and report["missing_link_count"] == 103
    assert report["legal_inventory_complete"] is False


def test_nested_descriptor_is_immutable_and_changes_are_visible_in_semantic_diff(workspace):
    _, store, _ = workspace
    data = derived_data(store)
    before = validate_manifest(data)
    with pytest.raises(ValidationError, match="frozen"):
        before.derived_amendment_inventory.parser.sha256 = "b" * 64
    after_data = deepcopy(data)
    after_data["derived_amendment_inventory"]["parser"]["sha256"] = "b" * 64
    after = validate_manifest(after_data)
    difference = semantic_diff(before, after)
    assert difference["derived_amendment_inventory_changed"] is True
    assert difference["parser_changed"] is False
    assert difference["artifacts"]["changed"] == []
    assert manifest_sha256(before) != manifest_sha256(after)


def test_derived_json_cannot_replace_legal_row_evidence(workspace):
    _, store, _ = workspace
    data = derived_data(store)
    evidence = data["rate_rules"][0]["evidence"][0]
    evidence.update(artifact_id="index", artifact_sha256=data["derived_amendment_inventory"]["source_artifact_sha256"])
    with pytest.raises(ValidationError, match="cannot establish normalized legal rows"):
        validate_manifest(data)
