from __future__ import annotations

import argparse
from pathlib import Path
import sys
import unittest
from typing import TextIO


DEFAULT_SUITE = "tests.test_tnved_recovery_ci"
MANDATORY_SUBJECT_IDS = (
    "tests.test_tnved_recovery_ci.TnvedRecoveryOfflineCiTest.test_builder_is_deterministic_integral_and_readable",
    "tests.test_tnved_recovery_ci.TnvedRecoveryOfflineCiTest.test_builder_rejects_bytes_outside_supplied_pins",
)
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _flatten(suite: unittest.TestSuite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def run_required_subjects(
    available_suite: unittest.TestSuite,
    *,
    required_ids: tuple[str, ...] = MANDATORY_SUBJECT_IDS,
    stream: TextIO = sys.stderr,
) -> int:
    """Select and execute only the explicitly mandatory product tests."""

    available = {test.id(): test for test in _flatten(available_suite)}
    missing = [test_id for test_id in required_ids if test_id not in available]
    if missing:
        print(
            "RECOVERY_GATE_FAILED: missing mandatory subject tests: " + ", ".join(missing),
            file=stream,
        )
        return 2
    return run_suite(
        unittest.TestSuite([available[test_id] for test_id in required_ids]),
        stream=stream,
    )


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
    return run_required_subjects(suite)


if __name__ == "__main__":
    raise SystemExit(main())
