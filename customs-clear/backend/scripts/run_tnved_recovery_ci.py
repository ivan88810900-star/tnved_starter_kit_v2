from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest
from typing import TextIO


DEFAULT_SUITE = "tests.test_tnved_recovery_ci"
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def run_suite(suite: unittest.TestSuite, *, stream: TextIO = sys.stderr) -> int:
    """Run the recovery subject tests and fail closed on an empty/skipped gate."""

    discovered = suite.countTestCases()
    if discovered == 0:
        print("RECOVERY_GATE_FAILED: no subject tests discovered", file=stream)
        return 2

    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    skipped = len(result.skipped)
    print(
        f"RECOVERY_GATE_SUMMARY: discovered={discovered} "
        f"executed={result.testsRun} skipped={skipped}",
        file=stream,
    )
    if result.testsRun != discovered:
        print("RECOVERY_GATE_FAILED: not every discovered subject test executed", file=stream)
        return 3
    if skipped == result.testsRun:
        print("RECOVERY_GATE_FAILED: all subject tests skipped", file=stream)
        return 4
    if not result.wasSuccessful():
        print("RECOVERY_GATE_FAILED: subject test failure", file=stream)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", default=DEFAULT_SUITE)
    args = parser.parse_args(argv)
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    suite = unittest.defaultTestLoader.loadTestsFromName(args.suite)
    return run_suite(suite)


if __name__ == "__main__":
    raise SystemExit(main())
