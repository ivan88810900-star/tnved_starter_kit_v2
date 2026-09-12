"""Run the required offline suites; fail if a module disappears or collects zero tests."""
import importlib
from pathlib import Path
import sys
import unittest

REQUIRED = ('test_control', 'test_runtime', 'test_audit', 'test_lease')


def main():
    directory = Path(__file__).resolve().parents[2] / 'tests' / 'agent_orchestration'
    sys.path.insert(0, str(directory))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in REQUIRED:
        tests = loader.loadTestsFromModule(importlib.import_module(name))
        if tests.countTestCases() == 0:
            raise RuntimeError('Required test module collected zero tests: '+name)
        suite.addTests(tests)
    # Independent A5 cases, when present, are required through this discovery too.
    suite.addTests(loader.discover(str(directory), pattern='test_a5_*.py'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
