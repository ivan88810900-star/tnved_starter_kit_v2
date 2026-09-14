"""Offline candidate workflow; synthetic evidence never proves current law."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api import ett_candidates as api
from app.db import Base
from app.models.ett import ETTArtifact, ETTCodeVersion, ETTFootnote, ETTRateRule, ETTSnapshot
from app.services.ett_artifacts import LocalArtifactStore
from app.services.ett_manifest import validate_manifest, manifest_sha256
from app.services.ett_repository import ETTCandidateError, candidate_readiness, load_candidate, semantic_diff, stage_candidate
from tests.ett_fixtures import artifact_bytes, synthetic_manifest_data


@pytest.fixture
def workspace(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "candidates.db"), connect_args={"timeout": 10})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    tables = [model.__table__ for model in (ETTSnapshot, ETTArtifact, ETTCodeVersion, ETTFootnote, ETTRateRule)]
    Base.metadata.create_all(engine, tables=tables)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE hs_rates (sentinel TEXT)"))
        connection.execute(text("INSERT INTO hs_rates VALUES ('existing production rate unchanged')"))
    store = LocalArtifactStore(tmp_path / "objects")
    manifest = validate_manifest(synthetic_manifest_data())
    for artifact in manifest.artifacts:
        assert store.put(artifact_bytes(artifact.artifact_id)) == artifact.sha256
    yield engine, store, manifest
    engine.dispose()


def stage(workspace):
    engine, store, manifest = workspace
    with Session(engine) as db:
        return stage_candidate(db, store, manifest)["manifest_sha256"]


def test_stage_round_trip_idempotency_and_production_isolation(workspace):
    engine, store, manifest = workspace
    digest = stage(workspace)
    with Session(engine) as db:
        assert stage_candidate(db, store, manifest)["created"] is False
        restored = load_candidate(db, store, digest)
        assert restored == manifest
        assert db.scalar(text("SELECT sentinel FROM hs_rates")) == "existing production rate unchanged"
        readiness = candidate_readiness(restored)
        assert not readiness["production_ready"] and not readiness["can_promote"]
        assert "manifest_bound_legal_review_missing" in readiness["blockers"]


def test_no_db_rows_when_source_object_missing(workspace, monkeypatch):
    engine, store, manifest = workspace
    monkeypatch.setattr(LocalArtifactStore, "verify", lambda *args: (_ for _ in ()).throw(ValueError("missing")))
    with Session(engine) as db:
        with pytest.raises(ValueError):
            stage_candidate(db, store, manifest)
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 0


def test_failure_in_final_projection_rolls_back_every_table(workspace):
    engine, store, manifest = workspace
    def fail_last(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO ett_rate_rules"):
            raise RuntimeError("injected failure")
    event.listen(engine, "before_cursor_execute", fail_last)
    with Session(engine) as db:
        with pytest.raises(RuntimeError):
            stage_candidate(db, store, manifest)
    event.remove(engine, "before_cursor_execute", fail_last)
    with Session(engine) as db:
        for table in ("ett_snapshots", "ett_artifacts", "ett_code_versions", "ett_footnotes", "ett_rate_rules"):
            assert db.scalar(text(f"SELECT count(*) FROM {table}")) == 0


def test_same_snapshot_name_cannot_change_content(workspace):
    engine, store, manifest = workspace
    stage(workspace)
    data = manifest.model_dump(mode="json")
    data["rate_rules"][0]["duty"]["ad_valorem_percent"] = "6"
    with Session(engine) as db:
        with pytest.raises(ETTCandidateError, match="reused"):
            stage_candidate(db, store, validate_manifest(data))
        assert db.scalar(text("SELECT count(*) FROM ett_snapshots")) == 1


def test_concurrent_staging_one_complete_snapshot(workspace):
    engine, store, manifest = workspace
    def run(_):
        with Session(engine) as db:
            return stage_candidate(db, store, manifest)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(result["created"] for result in results) == [False, True]
    with Session(engine) as db:
        assert load_candidate(db, store, manifest_sha256(manifest)) == manifest


def test_two_nonoverlapping_code_versions_survive_roundtrip(workspace):
    engine, store, manifest = workspace
    data = manifest.model_dump(mode="json")
    later_code, later_rule = deepcopy(data["codes"][0]), deepcopy(data["rate_rules"][0])
    data["codes"][0]["valid_to"] = data["rate_rules"][0]["valid_to"] = "2026-07-01"
    later_code["valid_from"] = later_rule["valid_from"] = "2026-07-01"
    later_code["description"] = "Synthetic revised code description"
    later_rule["rule_id"] = "test-rule-2"
    later_rule["duty"]["ad_valorem_percent"] = "7"
    data["codes"].append(later_code)
    data["rate_rules"].append(later_rule)
    manifest = validate_manifest(data)
    with Session(engine) as db:
        digest = stage_candidate(db, store, manifest)["manifest_sha256"]
        assert load_candidate(db, store, digest) == manifest
        assert db.scalar(text("SELECT count(*) FROM ett_code_versions")) == 2


@pytest.mark.parametrize("tamper", ["manifest", "missing_code", "rule_payload", "rule_index", "snapshot_metadata"])
def test_corrupt_database_fails_preview(workspace, tamper):
    engine, store, manifest = workspace
    digest = stage(workspace)
    with Session(engine) as db:
        if tamper == "manifest":
            snapshot = db.get(ETTSnapshot, digest)
            payload = deepcopy(snapshot.manifest_json)
            payload["snapshot_id"] = "changed"
            snapshot.manifest_json = payload
        elif tamper == "missing_code":
            db.execute(text("DELETE FROM ett_rate_rules"))
            db.execute(text("DELETE FROM ett_code_versions"))
        elif tamper == "snapshot_metadata":
            db.get(ETTSnapshot, digest).coverage_to = date(2028, 1, 1)
        else:
            row = db.scalar(select(ETTRateRule))
            if tamper == "rule_payload":
                payload = deepcopy(row.payload)
                payload["duty"]["ad_valorem_percent"] = "7"
                row.payload = payload
            else:
                row.valid_to = date(2028, 1, 1)
        db.commit()
    with Session(engine) as db:
        with pytest.raises(ValueError):
            load_candidate(db, store, digest)


def test_approval_cannot_be_set_even_by_accidental_direct_sql(workspace):
    engine, _, _ = workspace
    stage(workspace)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(text("UPDATE ett_snapshots SET status = 'approved'"))


def test_read_session_cannot_be_reused_for_stage(workspace):
    engine, store, manifest = workspace
    with Session(engine) as db:
        db.scalar(text("SELECT 1"))
        with pytest.raises(ETTCandidateError, match="fresh"):
            stage_candidate(db, store, manifest)


def test_review_diff_includes_rate_and_provenance_change(workspace):
    _, _, manifest = workspace
    changed = manifest.model_dump(mode="json")
    changed["rate_rules"][0]["duty"]["ad_valorem_percent"] = "6"
    changed["parser"]["version"] = "0.0.1"
    diff = semantic_diff(manifest, validate_manifest(changed))
    assert diff["rate_rules"]["changed"] == ["test-rule-1"]
    assert diff["codes"]["changed"] == []
    assert diff["parser_changed"] and diff["review_required"]
    assert diff["before_manifest_sha256"] != diff["after_manifest_sha256"]


def test_admin_api_preview_and_unavailable_boundaries(workspace, monkeypatch, tmp_path):
    engine, _, _ = workspace
    digest = stage(workspace)
    monkeypatch.setenv("ETT_CANDIDATE_STORE", str(tmp_path / "objects"))
    app = FastAPI()
    app.include_router(api.router, prefix="/ett")
    def database():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[api.candidate_db] = database
    app.dependency_overrides[api.require_authenticated_user] = lambda: {"role": "viewer"}
    with TestClient(app) as client:
        assert client.get("/ett").status_code == 403
        app.dependency_overrides[api.require_authenticated_user] = lambda: {"role": "admin"}
        assert client.get("/ett").json()["production_ready"] is False
        readiness = client.get(f"/ett/{digest}/readiness")
        assert readiness.status_code == 200 and not readiness.json()["can_promote"]
        request = {"code": "0101210000", "as_of": "2026-09-01", "destination": "RU"}
        response = client.post(f"/ett/{digest}/preview", json=request)
        assert response.status_code == 200, response.text
        assert response.json()["mode"] == "candidate_preview"
        assert response.json()["duty"]["ad_valorem_percent"] == "5"
        request["as_of"] = "2027-01-01"
        assert client.post(f"/ett/{digest}/preview", json=request).json()["status"] == "unavailable"
        request["as_of"] = 1788220800
        assert client.post(f"/ett/{digest}/preview", json=request).status_code == 422
        request["as_of"] = "2026-09-01"
        request["facts"] = {"quantity": 0.1}
        assert client.post(f"/ett/{digest}/preview", json=request).status_code == 422
        assert client.post(f"/ett/{digest}/approve", json={}).status_code == 404
        monkeypatch.delenv("ETT_CANDIDATE_STORE")
        assert client.get(f"/ett/{digest}/readiness").status_code == 503


def test_json_cli_rejects_duplicate_keys_and_nonfinite(tmp_path):
    spec = importlib.util.spec_from_file_location("ett_cli_test", Path(__file__).parents[1] / "scripts/ett_candidates.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for content in ('{"schema_version":2,"schema_version":1}', '{"value":NaN}'):
        source = tmp_path / "bad.json"
        source.write_text(content)
        with pytest.raises(ValueError):
            module.read_json(source)


def test_cli_staging_and_read_only_preview(workspace, tmp_path, capsys):
    _, _, manifest = workspace
    spec = importlib.util.spec_from_file_location("ett_cli_roundtrip", Path(__file__).parents[1] / "scripts/ett_candidates.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(manifest.model_dump_json())
    common = ["--database", str(tmp_path / "candidates.db"), "--store-root", str(tmp_path / "objects")]
    assert module.main(["stage", str(manifest_path), *common]) == 0
    result = json.loads(capsys.readouterr().out)
    before = (tmp_path / "candidates.db").read_bytes()
    assert module.main(["preview", result["manifest_sha256"], "--code", "0101210000", "--as-of", "2026-09-01", "--destination", "RU", *common]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "candidate_preview"
    assert (tmp_path / "candidates.db").read_bytes() == before


def test_candidate_reader_pins_sqlite_snapshot(workspace):
    engine, store, _ = workspace
    digest = stage(workspace)
    with Session(engine) as db:
        assert not db.connection().connection.driver_connection.in_transaction
        load_candidate(db, store, digest)
        assert db.connection().connection.driver_connection.in_transaction


def test_missing_posix_capability_fails_only_optional_store(tmp_path, monkeypatch):
    import app.services.ett_artifacts as artifacts
    monkeypatch.setattr(artifacts, "fcntl", None)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="POSIX"):
        artifacts.LocalArtifactStore(tmp_path / "objects")
