"""Hermetic self-checks run by ``python -m evaluation eval``.

These verify the framework's own contract (exit codes, prerequisite
detection, parser wiring) deterministically, with no data, filesystem, or
network access. Metric-level synthetic checks (matching, scoring edge cases)
will be added per the implementation sequence in evaluation/README.md.
"""

from __future__ import annotations

import contextlib
import io
from contextlib import redirect_stderr
from pathlib import Path
from typing import Callable

from . import EXIT_FAILURE, EXIT_MISSING_PREREQUISITES, EXIT_OK
from . import cli

# True while the check suite is on the stack. The eval-mode self-check
# invokes cmd_eval -> run() again; that nested run must not re-run the suite.
_running = False


def _run_cli(mode: str) -> int:
    """Invoke cli.main in-process, silencing stderr, and return its exit code."""
    with redirect_stderr(io.StringIO()):
        code = cli.main([mode])
    assert isinstance(code, int)
    return code


def _stubbed_prepped_files(files: list[Path]) -> contextlib.AbstractContextManager:
    """Stub cli._check_prepped_data to return ``files`` for the context."""
    class _Stub(contextlib.AbstractContextManager):
        def __enter__(self) -> None:
            self._original = cli._check_prepped_data
            cli._check_prepped_data = lambda: files

        def __exit__(self, *_exc: object) -> None:
            cli._check_prepped_data = self._original

    return _Stub()


def check_exit_constants() -> None:
    """Exit-code constants match the documented 0/1/2 contract."""
    assert (EXIT_OK, EXIT_FAILURE, EXIT_MISSING_PREREQUISITES) == (0, 1, 2)


def check_eval_mode_passes() -> None:
    """Offline eval mode completes successfully without prerequisites."""
    with contextlib.redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        assert cli.cmd_eval(None) == EXIT_OK


def check_eval_data_missing_prereqs() -> None:
    """eval-data exits 2 when no prepared parquet files exist."""
    with _stubbed_prepped_files([]):
        assert _run_cli("eval-data") == EXIT_MISSING_PREREQUISITES


def check_eval_data_unimplemented_fails_clearly() -> None:
    """eval-data never passes silently when data exists but metrics are absent.

    With prerequisites present but the report unimplemented, the mode must
    report failure (1), not success.
    """
    with _stubbed_prepped_files([Path("data/prepped/sample.parquet")]):
        assert _run_cli("eval-data") == EXIT_FAILURE


def check_eval_live_missing_prereqs() -> None:
    """eval-live exits 2 until the adapter and credentials exist."""
    assert _run_cli("eval-live") == EXIT_MISSING_PREREQUISITES


def check_unknown_mode_rejected() -> None:
    """An unknown mode is rejected by the parser, never silently ignored."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            cli.main(["no-such-mode"])
    except SystemExit as exc:
        assert exc.code != EXIT_OK
        return
    raise AssertionError("unknown mode did not cause a nonzero exit")


# --- Synthetic-fixture checks of the scoring primitives ---------------------


def check_detection_fixtures() -> None:
    """Detection matching produces the hand-computed counts on fixtures."""
    from . import fixtures
    from .scoring import match_issues, precision_recall

    result = match_issues(fixtures.PREDICTED_ISSUES, fixtures.REFERENCE_ISSUES)
    exp = fixtures.DETECTION_EXPECTED
    assert len(result.tp) == exp["tp"], f"TP {len(result.tp)} != {exp['tp']}"
    fp = len(result.unmatched_predictions) + len(result.duplicate_predictions)
    assert fp == exp["fp"], f"FP {fp} != {exp['fp']}"
    assert len(result.duplicate_predictions) == exp["duplicates"]
    assert len(result.unmatched_references) == exp["fn"]
    precision, recall = precision_recall(result)
    assert precision.value == 2 / 4, precision.value
    assert recall.value == 2 / 3, recall.value
    assert any("duplicate" in n for n in precision.notes)


def check_zero_denominator_unavailable() -> None:
    """Zero denominators report unavailable, never a perfect score."""
    from . import fixtures
    from .scoring import match_issues, precision_recall

    # No predictions at all: precision unavailable; recall 0 (all missed).
    result = match_issues(fixtures.EMPTY_PREDICTIONS, fixtures.REFERENCE_ISSUES)
    precision, recall = precision_recall(result)
    assert precision.value is None and precision.denominator == 0
    assert recall.value == 0.0 and recall.denominator == 3
    # No references (e.g., fully reviewed healthy scope): recall unavailable.
    result = match_issues(fixtures.PREDICTED_ISSUES, fixtures.EMPTY_REFERENCES)
    precision, recall = precision_recall(result)
    assert precision.value == 0.0  # every prediction is a false alert
    assert recall.value is None and recall.denominator == 0


def check_root_cause_fixtures() -> None:
    """Root-cause scoring matches the hand-computed counts on fixtures."""
    from . import fixtures
    from .scoring import root_cause_accuracy

    r = root_cause_accuracy(fixtures.ROOT_CAUSE_CASES)
    exp = fixtures.ROOT_CAUSE_EXPECTED
    assert (r.overall.numerator, r.overall.denominator) == exp["overall"], r.overall
    assert r.overall.value == 1 / 3, r.overall.value
    assert (r.conditional_on_detection.numerator,
            r.conditional_on_detection.denominator) == exp["conditional"]
    assert r.unknown_label_cases == exp["unknown_cases"]
    assert r.acknowledged_unknown == exp["acknowledged"]
    assert r.invented_diagnosis_on_unknown == exp["invented"]
    # the conditional score must carry its secondary label
    assert any("secondary" in n for n in r.conditional_on_detection.notes)


def check_action_fixtures() -> None:
    """Action scoring matches the hand-computed counts on fixtures."""
    from . import fixtures
    from .scoring import score_actions

    r = score_actions(fixtures.ACTION_CASES)
    exp = fixtures.ACTIONS_EXPECTED
    assert len(r.passed) == exp["pass"], r.passed
    assert len(r.failed) == exp["fail"], r.failed
    assert len(r.harmful) == exp["harmful_entries"], r.harmful
    assert r.acceptable_rate.value == 2 / 5, r.acceptable_rate.value
    # the single harmful entry is A3's terminate_job with its evidence
    assert r.harmful[0]["actions"] == ["terminate_job"]
    assert r.harmful[0]["evidence"], "harmful entry must carry evidence"
    # A5 (no reviewed expectation) is excluded from the denominator
    assert r.acceptable_rate.denominator == 5


CHECKS: list[tuple[str, Callable[[], None]]] = [
    ("exit-constants", check_exit_constants),
    ("eval-mode-passes", check_eval_mode_passes),
    ("eval-data-missing-prereqs", check_eval_data_missing_prereqs),
    ("eval-data-unimplemented-fails-clearly",
     check_eval_data_unimplemented_fails_clearly),
    ("eval-live-missing-prereqs", check_eval_live_missing_prereqs),
    ("unknown-mode-rejected", check_unknown_mode_rejected),
    ("detection-fixtures", check_detection_fixtures),
    ("zero-denominator-unavailable", check_zero_denominator_unavailable),
    ("root-cause-fixtures", check_root_cause_fixtures),
    ("action-fixtures", check_action_fixtures),
]


def run() -> list[tuple[str, str]]:
    """Run all checks; return a list of (name, error) failures (empty = pass)."""
    global _running
    if _running:  # nested run triggered by the eval-mode self-check
        return []
    _running = True
    failures: list[tuple[str, str]] = []
    try:
        for name, fn in CHECKS:
            try:
                fn()
            except AssertionError as exc:
                failures.append((name, str(exc) or "assertion failed"))
            except Exception as exc:  # noqa: BLE001 - a crash is a failed check
                failures.append((name, f"{type(exc).__name__}: {exc}"))
    finally:
        _running = False
    return failures
