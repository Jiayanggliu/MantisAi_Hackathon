"""CLI dispatch for ``python -m evaluation <mode>``.

Contract (evaluation/README.md, "Execution modes"):
- 0 = completed with no configured acceptance failures
- 1 = evaluation failure, invalid input, or failed acceptance criterion
- 2 = missing prerequisites

Data and live modes must fail clearly when prerequisites are missing; they
never silently fall back to mocks.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import EXIT_FAILURE, EXIT_MISSING_PREREQUISITES, EXIT_OK

PREPPED_DIR = Path("data") / "prepped"


def _check_prepped_data() -> list[Path]:
    """Return prepared parquet files, empty list if the directory has none."""
    if not PREPPED_DIR.is_dir():
        return []
    return sorted(PREPPED_DIR.glob("*.parquet"))


def cmd_eval(_args: argparse.Namespace) -> int:
    """Offline deterministic checks on synthetic fixtures (hermetic)."""
    import json

    from . import fixtures, selfchecks
    from .scoring import (match_issues, precision_recall, root_cause_accuracy,
                          score_actions)

    failures = selfchecks.run()

    # Recompute the fixture metrics for the summary/report (selfchecks assert
    # the exact expected counts, so these numbers are verified, not trusted).
    det = match_issues(fixtures.PREDICTED_ISSUES, fixtures.REFERENCE_ISSUES)
    precision, recall = precision_recall(det)
    rc = root_cause_accuracy(fixtures.ROOT_CAUSE_CASES)
    act = score_actions(fixtures.ACTION_CASES)
    report = {
        "mode": "eval",
        "source": "synthetic fixtures (evaluation/fixtures.py); verified "
                  "against hand-computed expectations in selfchecks",
        "acceptance": "measured; acceptance not configured",
        "detection": {
            "precision": precision.as_dict(),
            "recall": recall.as_dict(),
            "tp": len(det.tp),
            "fp": len(det.unmatched_predictions) + len(det.duplicate_predictions),
            "fn": len(det.unmatched_references),
            "duplicates": len(det.duplicate_predictions),
        },
        "root_cause": {
            "overall": rc.overall.as_dict(),
            "conditional_on_detection": rc.conditional_on_detection.as_dict(),
            "unknown_label_cases": rc.unknown_label_cases,
            "acknowledged_unknown": rc.acknowledged_unknown,
            "invented_diagnosis_on_unknown": rc.invented_diagnosis_on_unknown,
        },
        "actions": {
            "acceptable_rate": act.acceptable_rate.as_dict(),
            "passed": act.passed,
            "failed": act.failed,
            "harmful": act.harmful,
        },
        "selfcheck_failures": [{"name": n, "error": e} for n, e in failures],
    }

    def _fmt(rate) -> str:
        return "unavailable" if rate.value is None else f"{rate.value:.3f}"

    print("eval: synthetic-fixture metrics (measured; acceptance not configured)")
    print(f"  detection  precision={_fmt(precision)} recall={_fmt(recall)} "
          f"(tp={len(det.tp)} fp={report['detection']['fp']} "
          f"fn={len(det.unmatched_references)} dup={len(det.duplicate_predictions)})")
    print(f"  root cause overall={_fmt(rc.overall)} "
          f"conditional(detected)={_fmt(rc.conditional_on_detection)} "
          f"unknown-label cases={rc.unknown_label_cases}")
    print(f"  actions    acceptable={_fmt(act.acceptable_rate)} "
          f"harmful listed={len(act.harmful)}")

    try:
        out_dir = Path("out")
        out_dir.mkdir(exist_ok=True)
        (out_dir / "eval-report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("eval: report written to out/eval-report.json")
    except OSError as exc:
        print(f"eval: warning: could not write out/eval-report.json: {exc}",
              file=sys.stderr)

    if failures:
        for name, error in failures:
            print(f"FAIL {name}: {error}", file=sys.stderr)
        print(f"eval: {len(failures)} check(s) failed", file=sys.stderr)
        return EXIT_FAILURE
    print("eval: all deterministic checks passed")
    return EXIT_OK


def cmd_eval_data(_args: argparse.Namespace) -> int:
    """Telemetry data-quality report; requires data/prepped/*.parquet."""
    files = _check_prepped_data()
    if not files:
        print(
            "eval-data: missing prerequisites: no parquet files found under "
            f"{PREPPED_DIR}. Run `make prep` first (see data/README.md). "
            "This mode never falls back to synthetic data.",
            file=sys.stderr,
        )
        return EXIT_MISSING_PREREQUISITES
    print(
        f"eval-data: found {len(files)} prepared parquet file(s), but the "
        "data-quality report is not implemented yet; nothing was measured. "
        "Reported as an evaluation failure rather than a silent pass.",
        file=sys.stderr,
    )
    return EXIT_FAILURE


def cmd_eval_live(_args: argparse.Namespace) -> int:
    """Live model evaluation; requires credentials, labels, and an adapter."""
    print(
        "eval-live: missing prerequisites: not implemented yet. A live run "
        "requires prepared data, reviewed benchmark labels, and endpoint/"
        "model credentials for the system adapter. No mock fallback is "
        "performed.",
        file=sys.stderr,
    )
    return EXIT_MISSING_PREREQUISITES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation",
        description="Evaluation framework (see evaluation/README.md)",
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("eval", help="offline deterministic checks on synthetic fixtures")
    sub.add_parser(
        "eval-data", help="telemetry data-quality report (needs data/prepped)"
    )
    sub.add_parser(
        "eval-live", help="live model evaluation (needs credentials + labels)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "eval": cmd_eval,
        "eval-data": cmd_eval_data,
        "eval-live": cmd_eval_live,
    }
    try:
        return handlers[args.mode](args)
    except KeyError:
        parser.error(f"unknown mode: {args.mode}")
        return EXIT_FAILURE  # unreachable; parser.error exits 2 by argparse convention


if __name__ == "__main__":
    raise SystemExit(main())
