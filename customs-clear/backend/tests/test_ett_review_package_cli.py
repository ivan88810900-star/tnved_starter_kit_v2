"""Real offline CLI behavior, using retained synthetic sources rather than mocks."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.ett_manifest import canonical_manifest_bytes
from tests.test_ett_review_package import case, prepared, add_unbound_portal

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/ett_review_package.py"


def invoke(arguments, *, guard=False, timeout=60):
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)}
    prefix = [sys.executable, str(SCRIPT)]
    if guard:
        # The real CLI imports and runs under a database/network rejection gate.
        script = '''
import importlib.abc, socket, runpy, sys
class RejectDatabaseImports(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname == "app.db" or fullname.startswith("app.db.") or fullname == "sqlalchemy" or fullname.startswith("sqlalchemy.") or fullname == "app.services.ett_repository":
   raise AssertionError("Database import attempted")
sys.meta_path.insert(0, RejectDatabaseImports())
def reject(*args, **kwargs):
 raise AssertionError("Network access attempted")
socket.create_connection = reject
socket.socket.connect = reject
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''
        prefix = [sys.executable, "-c", script, str(SCRIPT)]
    result = subprocess.run(prefix + list(map(str, arguments)), cwd=SCRIPT.parents[1], env=environment,
                            text=True, capture_output=True, timeout=timeout)
    return result


def inputs(case, tmp_path):
    manifest = tmp_path / "candidate.json"
    manifest.write_bytes(canonical_manifest_bytes(case[0]))
    output = tmp_path / "review.json"
    args = ["build", manifest, "--store-root", case[1]._root,
            "--acquisition-receipt-sha256", case[2], "--initial", "--output", output]
    return args, output


def snapshot(store):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in store._root.iterdir()}


def test_cli_build_and_exact_verify_are_offline_and_sources_are_read_only(case, tmp_path):
    args, output = inputs(case, tmp_path)
    before = snapshot(case[1])
    result = invoke(args, guard=True)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not result.stderr
    report = json.loads(result.stdout)
    assert report["package_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert not output.read_bytes().endswith(b"\n")
    verified = invoke(["verify", output, "--store-root", case[1]._root], guard=True)
    assert verified.returncode == 0, verified.stderr + verified.stdout
    assert json.loads(verified.stdout)["package_sha256"] == report["package_sha256"]
    assert report["assembly_ready"] is True
    assert report["source_complete"] is report["legal_ready"] is report["can_promote"] is False
    assert snapshot(case[1]) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["candidate.json", "objects", "review.json"]


@pytest.mark.parametrize("existing", ["file", "symlink"])
def test_cli_refuses_to_replace_existing_output_or_symlink(case, tmp_path, existing):
    args, output = inputs(case, tmp_path)
    target = tmp_path / "keep-me.txt"
    target.write_bytes(b"existing bytes")
    if existing == "file":
        output.write_bytes(b"existing package")
    else:
        output.symlink_to(target)
    result = invoke(args)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "ERROR"
    assert target.read_bytes() == b"existing bytes"
    assert output.read_bytes() == (b"existing package" if existing == "file" else b"existing bytes")
    assert not list(tmp_path.glob(".ett-review-*"))


def test_cli_requires_an_explicit_prior_or_initial_decision(case, tmp_path):
    args, output = inputs(case, tmp_path)
    args.remove("--initial")
    result = invoke(args)
    assert result.returncode == 2
    assert not output.exists()


def test_cli_unbound_sources_cannot_create_a_ready_output(case, tmp_path):
    add_unbound_portal(case)
    args, output = inputs(case, tmp_path)
    result = invoke(args)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "ERROR"
    assert not output.exists()


def test_cli_replay_failure_is_sanitized_and_does_not_touch_sources(case, tmp_path):
    _, output = inputs(case, tmp_path)
    secret = "private-source-payload-must-not-be-echoed"
    output.write_text('{"inputs":{"assumptions":["' + secret + '"]}}')
    before = snapshot(case[1])
    result = invoke(["verify", output, "--store-root", case[1]._root])
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "ERROR"
    assert not result.stderr
    assert secret not in result.stdout
    assert str(tmp_path) not in result.stdout
    assert snapshot(case[1]) == before


def test_cli_rejects_a_named_pipe_without_waiting_for_a_writer(case, tmp_path):
    args, output = inputs(case, tmp_path)
    manifest = Path(args[1])
    manifest.unlink()
    os.mkfifo(manifest)
    result = invoke(args, timeout=5)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "ERROR"
    assert not result.stderr
    assert not output.exists()
