"""The mixed verifier is usable offline and never hides native failures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests.test_ett_evidence_binding import source_fixture
from tests.test_ett_metadata_binding import mixed


@pytest.mark.parametrize('changed', [None, 'native', 'metadata'])
def test_mixed_cli_replays_originals_fails_on_either_kind_and_does_not_write(mixed, tmp_path, changed):
    data, store, _ = mixed
    if changed:
        reference = (data['rate_rules'][0]['evidence'][0] if changed == 'native'
                     else data['rate_rules'][0]['effective_evidence'][-1])
        reference['raw_text'] = ('A fabricated source row' if changed == 'native'
                                 else reference['raw_text'] + ' ')
        reference['raw_text_sha256'] = hashlib.sha256(reference['raw_text'].encode()).hexdigest()
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(data), encoding='utf-8')
    before = {p.name: p.read_bytes() for p in store._root.iterdir()}
    database = tmp_path / 'must-not-exist.db'
    result = subprocess.run(
        [sys.executable, 'scripts/ett_candidates.py', 'verify-evidence', str(manifest), '--store-root', str(store._root)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, 'DATABASE_URL': 'sqlite:///' + str(database),
             'PYTHONPATH': os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == (2 if changed else 0), result.stderr
    report = json.loads(result.stdout)
    assert report['source_evidence_verified'] is (changed is None)
    assert report['production_ready'] is report['effective_dates_verified'] is False
    assert report['references_failed'] == (1 if changed else 0)
    assert not database.exists()
    assert {p.name: p.read_bytes() for p in store._root.iterdir()} == before
