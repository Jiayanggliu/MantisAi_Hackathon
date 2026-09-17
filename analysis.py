#!/usr/bin/env python3
"""Build Track 2's cluster-efficiency dashboard data.

Run from the project root (the directory that contains data/prepped):
    python analysis.py

    It writes out/analysis.json, out/jobs_bucketed.parquet, and
    out/jobs_actionable.parquet (A/B1 excluded). All utilisation
and cost figures use DCGM-measured ``gpu_hours``, never allocated GPU time.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd


PRICE_USD_PER_GPU_HOUR = 2.5
TARGET_PCT = 0.20
BUCKET_ORDER = ("A", "B1", "B2", "C", "D")
BUCKET_META = {
    "A": {"label": "Never computed", "confidence": "high", "recoverable": True},
    "B1": {"label": "Low use; never meaningfully computed", "confidence": "medium-high", "recoverable": True},
    "B2": {"label": "Low average use; did compute", "confidence": "low", "recoverable": False},
    "C": {"label": "Low utilization (5–20%)", "confidence": "low", "recoverable": False},
    "D": {"label": "Working (≥20%)", "confidence": "high", "recoverable": False},
}


def number(value: float | int) -> float | int:
    """Make numpy/pandas scalars and whole values safe, compact JSON."""
    value = float(value)
    return int(round(value)) if value.is_integer() else round(value, 6)


def validate_columns(frame: pd.DataFrame, required: set[str], source: Path) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{source} is missing required columns: {', '.join(missing)}")


def assign_buckets(jobs: pd.DataFrame) -> pd.Series:
    avg, peak = jobs.sm_util_avg, jobs.sm_util_max
    never = (avg == 0) & (peak == 0)
    b1 = ~never & (avg < 5) & (peak <= 20)
    b2 = ~never & (avg < 5) & (peak > 20)
    c = ~never & (avg >= 5) & (avg < 20)
    d = avg >= 20
    membership = pd.DataFrame({"A": never, "B1": b1, "B2": b2, "C": c, "D": d})
    if not (membership.sum(axis=1) == 1).all():
        bad = jobs.loc[membership.sum(axis=1) != 1, "id_job"].head(10).tolist()
        raise ValueError(f"Bucket predicates are not mutually exclusive and complete; example jobs: {bad}")
    return membership.idxmax(axis=1)


def state_summary(frame: pd.DataFrame) -> dict[str, dict[str, int | float]]:
    return {
        str(state): {"jobs": int(len(group)), "gpu_hours": number(group.gpu_hours.sum())}
        for state, group in frame.groupby("state_name", dropna=False, sort=True)
    }


def make_recommendations(jobs: pd.DataFrame) -> list[dict]:
    a = jobs[jobs.bucket == "A"]
    cancelled_timeout = a[a.state_name.isin(["CANCELLED", "TIMEOUT"])]
    completed = a[a.state_name == "COMPLETED"]
    failed = a[a.state_name == "FAILED"]
    interactive = a[a.job_type == "LLSUB:INTERACTIVE"]
    over_4h = a[a.walltime_sec > 4 * 3600].gpu_hours.sum()
    a_hours = a.gpu_hours.sum()

    def recommendation(identifier: str, title: str, frame: pd.DataFrame, evidence: dict, rule_ids: list[str]) -> dict:
        hours = frame.gpu_hours.sum()
        return {
            "id": identifier,
            "title": title,
            "gpu_hours": number(hours),
            "usd": number(hours * PRICE_USD_PER_GPU_HOUR),
            "jobs": int(len(frame)),
            "evidence": evidence,
            "rule_ids": rule_ids,
        }

    return [
        recommendation(
            "idle_timeout", "Interactive-session idle timeout", cancelled_timeout,
            {
                "interactive_sessions": int(len(interactive)),
                "interactive_gpu_hours": number(interactive.gpu_hours.sum()),
                "share_a_hours_over_4h": number(over_4h / a_hours) if a_hours else 0,
            },
            ["rules::idle-interactive-session", "rules::slow-cancel-of-idle-job", "rules::wallclock-kill"],
        ),
        recommendation("cpu_queue", "Route GPU-free completed jobs to the CPU queue", completed, {}, ["rules::gpu-not-needed"]),
        recommendation("fail_fast", "Fail fast when startup produces no GPU work", failed, {}, ["rules::gpu-never-computed", "rules::array-mass-failure"]),
    ]


def build_analysis(jobs: pd.DataFrame) -> dict:
    jobs = jobs.copy()
    jobs["bucket"] = assign_buckets(jobs)
    total_hours = jobs.gpu_hours.sum()
    buckets = []
    for bucket_id in BUCKET_ORDER:
        group = jobs[jobs.bucket == bucket_id]
        hours = group.gpu_hours.sum()
        buckets.append({
            "id": bucket_id, **BUCKET_META[bucket_id], "jobs": int(len(group)),
            "gpu_hours": number(hours), "usd": number(hours * PRICE_USD_PER_GPU_HOUR),
            "share": number(hours / total_hours) if total_hours else 0,
            "by_state": state_summary(group),
            **({"note": "False-positive risk: these jobs reached >20% SM at peak."} if bucket_id == "B2" else {}),
        })

    recoverable = jobs[jobs.bucket.isin(["A", "B1"])]
    conservative = jobs[jobs.bucket == "A"]
    high = jobs[jobs.bucket.isin(["A", "B1", "B2"])]
    b2 = jobs[jobs.bucket == "B2"]
    rec_hours = recoverable.gpu_hours.sum()
    target_hours = total_hours * TARGET_PCT
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "sample_scope": "Allocated GPU-hours in this telemetry sample; not total cluster capacity.",
        "price_usd_per_gpu_hour": PRICE_USD_PER_GPU_HOUR,
        "total_gpu_hours": number(total_hours),
        "target_pct": TARGET_PCT,
        "target_gpu_hours": number(target_hours),
        "buckets": buckets,
        "recoverable": {"gpu_hours": number(rec_hours), "usd": number(rec_hours * PRICE_USD_PER_GPU_HOUR), "share": number(rec_hours / total_hours)},
        "claims": {
            "recoverable_gpu_hours": {
                "point": number(rec_hours), "low": number(conservative.gpu_hours.sum()), "high": number(high.gpu_hours.sum()), "confidence": 0.7,
                "basis": "Mutually exclusive partition by SM average and peak. Point includes jobs whose GPU never exceeded 20% SM at peak; GPU-hours are DCGM-measured.",
            },
            "recoverable_usd": {"point": number(rec_hours * PRICE_USD_PER_GPU_HOUR), "low": number(conservative.gpu_hours.sum() * PRICE_USD_PER_GPU_HOUR), "high": number(high.gpu_hours.sum() * PRICE_USD_PER_GPU_HOUR), "confidence": 0.7},
            "cancelled_is_waste": False,
            "cancelled_rationale": "Only cancelled jobs in A/B1 are counted. Cancelling a job that was computing can be good practice, not waste.",
        },
        "recommendations": make_recommendations(jobs),
        "cost_if_wrong": {"b2_gpu_hours": number(b2.gpu_hours.sum()), "b2_usd": number(b2.gpu_hours.sum() * PRICE_USD_PER_GPU_HOUR), "b2_jobs": int(len(b2)), "note": "Jobs an average-only idle policy would hit even though they did compute (peak >20%)."},
    }
    return payload, jobs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/prepped"))
    parser.add_argument("--out-dir", type=Path, default=Path("out"))
    args = parser.parse_args()
    jobs_path = args.data_dir / "jobs.parquet"
    if not jobs_path.exists():
        raise SystemExit(
            f"Input telemetry not found: {jobs_path}\n"
            "Prepare the telemetry first (the project's prep step should create "
            "data/prepped/jobs.parquet), or pass its location explicitly, e.g. "
            "--data-dir /path/to/data/prepped."
        )
    jobs = pd.read_parquet(jobs_path)
    validate_columns(jobs, {"id_job", "gpu_hours", "sm_util_avg", "sm_util_max", "state_name", "job_type", "walltime_sec"}, jobs_path)
    analysis, bucketed_jobs = build_analysis(jobs)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")
    bucketed_jobs.to_parquet(args.out_dir / "jobs_bucketed.parquet", index=False)
    # A and B1 are the two categories marked as not useful for the requested
    # dashboard view. Keep the complete bucketed table above for audit/drilldown,
    # and write a separate, non-destructive actionable view.
    actionable = bucketed_jobs[~bucketed_jobs.bucket.isin(["A", "B1"])].copy()
    actionable.to_parquet(args.out_dir / "jobs_actionable.parquet", index=False)
    analysis["dashboard_filter"] = {
        "excluded_buckets": ["A", "B1"],
        "included_buckets": ["B2", "C", "D"],
        "excluded_jobs": int(len(bucketed_jobs) - len(actionable)),
        "excluded_gpu_hours": number(bucketed_jobs.loc[bucketed_jobs.bucket.isin(["A", "B1"]), "gpu_hours"].sum()),
        "note": "A and B1 are retained in jobs_bucketed.parquet but omitted from the actionable dashboard view.",
    }
    (args.out_dir / "analysis.json").write_text(json.dumps(analysis, indent=2) + "\n")
    print(f"Wrote {args.out_dir / 'analysis.json'}, {args.out_dir / 'jobs_bucketed.parquet'}, and {args.out_dir / 'jobs_actionable.parquet'}")


if __name__ == "__main__":
    main()
