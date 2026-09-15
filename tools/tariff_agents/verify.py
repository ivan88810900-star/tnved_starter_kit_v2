"""Run exact repository suites; fail on missing or substituted security tests."""
import importlib.util
from pathlib import Path
import stat
import unittest

REQUIRED = ('test_control', 'test_runtime', 'test_audit', 'test_lease',
            'test_a5_independent', 'test_a6_provider_timeout')
BRIDGE_TEST = 'test_audit_bridge'
BRIDGE_ARTIFACTS = (
    '.github/workflows/tariff-a6-live.yml',
    'tools/tariff_agents/audit_bridge.py',
    'tests/agent_orchestration/test_audit_bridge.py',
    '.ai/orchestration/A6_LIVE_BRIDGE.md',
)


def _required_names(root, directory):
    """Admit optional features only with their complete required test suite."""
    names = list(REQUIRED)
    bridge_present = False
    for artifact in BRIDGE_ARTIFACTS:
        path = root / artifact
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode) or path.is_symlink() or path.resolve() != path.absolute():
            raise RuntimeError('Invalid bridge artifact: ' + artifact)
        bridge_present = True
    if bridge_present:
        names.append(BRIDGE_TEST)
    names.extend(sorted(path.stem for path in directory.glob('test_a5_*.py')
                        if path.stem not in names))
    return names


def _load_required(directory, name, loader):
    """Load one suite from its exact regular repository file, never import state."""
    path = directory / (name + '.py')
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise RuntimeError('Required test module missing: ' + name) from None
    if not stat.S_ISREG(mode) or path.is_symlink() or path.resolve() != path.absolute():
        raise RuntimeError('Invalid required test file: ' + name)
    isolated_name = '_tariff_required_' + name
    spec = importlib.util.spec_from_file_location(isolated_name, path)
    if spec is None or spec.loader is None or Path(spec.origin or '').resolve() != path:
        raise RuntimeError('Required test module path mismatch: ' + name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if Path(getattr(module, '__file__', '')).resolve() != path:
        raise RuntimeError('Required test module path mismatch: ' + name)
    tests = loader.loadTestsFromModule(module)
    if tests.countTestCases() == 0:
        raise RuntimeError('Required test module collected zero tests: ' + name)
    return tests


def main():
    root = Path(__file__).resolve().parents[2]
    directory = root / 'tests' / 'agent_orchestration'
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in _required_names(root, directory):
        suite.addTests(_load_required(directory, name, loader))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
