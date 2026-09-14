"""Run the required offline suites; fail if a module disappears or collects zero tests."""
import importlib
from pathlib import Path
import sys
import unittest

REQUIRED = ('test_control', 'test_runtime', 'test_audit', 'test_lease',
            'test_a5_independent')


def main():
    directory = Path(__file__).resolve().parents[2] / 'tests' / 'agent_orchestration'
    sys.path.insert(0, str(directory))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    names = list(REQUIRED)
    names.extend(sorted(path.stem for path in directory.glob('test_a5_*.py')
                        if path.stem not in REQUIRED))
    for name in names:
        tests = loader.loadTestsFromModule(importlib.import_module(name))
        if tests.countTestCases() == 0:
            raise RuntimeError('Required test module collected zero tests: '+name)
        suite.addTests(tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
