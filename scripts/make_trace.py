#!/usr/bin/env python3
"""Build a Perfetto/Chrome trace of GPU occupancy from the prepped tables.

One track per (node, GPU) -- 450 of them -- and one slice per job that held that
card, coloured by the utilisation bucket. Gaps are the negative space: stretches
where no sampled job held the card.

    python scripts/make_trace.py                 # out/trace.json.gz, every job
    python scripts/make_trace.py --waste-only    # out/trace_waste.json.gz, A+B1

Open the file at https://ui.perfetto.dev (drag it in).
"""
from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# Slice colour per bucket. These are the Chrome trace format's named colours,
# which Perfetto honours; an arbitrary hex value would be ignored.
CNAME = {"A": "terrible", "B1": "bad", "B2": "yellow", "C": "olive", "D": "good"}
BUCKET_LABEL = {
    "A": "never computed",
    "B1": "barely used",
    "B2": "low duty cycle, did compute",
    "C": "low utilisation",
    "D": "working",
}
# The window's real start, from GET /v1/efficiency/summary. The tables carry
# relative offsets, so this is what t=0 means.
WINDOW_START = datetime(2026, 2, 25, tzinfo=timezone.utc)


def build(data_dir: Path, out_dir: Path, waste_only: bool) -> Path:
    jobs = pd.read_parquet(data_dir / "jobs.parquet")
    gpus = pd.read_parquet(data_dir / "gpus.parquet", columns=["id_job", "Node", "gpu_id"])
    buckets = pd.read_parquet(out_dir / "jobs_bucketed.parquet", columns=["id_job", "bucket"])

    cols = ["id_job", "time_start", "time_end", "state_name", "gpu_hours",
            "sm_util_avg", "sm_util_max", "mem_used_frac", "gpu_count",
            "job_type", "partition", "n_nodes_listed"]
    df = gpus.merge(jobs[cols], on="id_job", how="left").merge(buckets, on="id_job", how="left")

    # A slice needs a real interval. 1.9% of card-rows have none: the scheduler
    # never recorded a start, or start == end.
    before = len(df)
    df = df[df.time_start.notna() & df.time_end.notna() & (df.time_end > df.time_start)]
    dropped = before - len(df)

    if waste_only:
        df = df[df.bucket.isin(["A", "B1"])]

    # Tracks: pid per node, tid per card. Nodes are named rXXXXXXX-nYYYYYY and
    # the suffix is the rack group, so sorting on it keeps a rack together.
    nodes = sorted(df.Node.unique(), key=lambda n: (n.split("-")[-1], n))
    pid_of = {n: i + 1 for i, n in enumerate(nodes)}

    t0 = float(df.time_start.min())
    events: list[dict] = []

    for node in nodes:
        pid = pid_of[node]
        rack = node.split("-")[-1]
        events.append({"ph": "M", "pid": pid, "tid": 0, "name": "process_name",
                       "args": {"name": f"{node}  [rack {rack}]"}})
        events.append({"ph": "M", "pid": pid, "tid": 0, "name": "process_sort_index",
                       "args": {"sort_index": pid}})
        for gid in (0, 1):
            events.append({"ph": "M", "pid": pid, "tid": int(gid), "name": "thread_name",
                           "args": {"name": f"GPU {gid}"}})

    for r in df.itertuples(index=False):
        bucket = r.bucket if isinstance(r.bucket, str) else "?"
        events.append({
            "ph": "X",
            "pid": pid_of[r.Node],
            "tid": int(r.gpu_id),
            "ts": int((float(r.time_start) - t0) * 1e6),
            "dur": int((float(r.time_end) - float(r.time_start)) * 1e6),
            "name": f"{bucket} · {r.state_name} · {r.gpu_hours:.1f}h",
            "cname": CNAME.get(bucket, "grey"),
            "args": {
                "job_id": int(r.id_job),
                "bucket": f"{bucket} — {BUCKET_LABEL.get(bucket, '')}",
                "state": r.state_name,
                "sm_util_avg_pct": None if pd.isna(r.sm_util_avg) else round(float(r.sm_util_avg), 1),
                "sm_util_max_pct": None if pd.isna(r.sm_util_max) else round(float(r.sm_util_max), 1),
                "measured_gpu_hours": round(float(r.gpu_hours), 2),
                "gpu_mem_used_frac": None if pd.isna(r.mem_used_frac) else round(float(r.mem_used_frac), 3),
                "gpus_in_job": None if pd.isna(r.gpu_count) else int(r.gpu_count),
                "nodes_in_job": None if pd.isna(r.n_nodes_listed) else int(r.n_nodes_listed),
                "job_type": r.job_type,
                "partition": r.partition,
            },
        })

    span_days = (df.time_end.max() - t0) / 86400
    trace = {
        "traceEvents": events,
        "displayTimeUnit": "ms",
        "otherData": {
            "READ_THIS_FIRST": (
                "A gap is NOT an idle GPU. This is a SAMPLE of the cluster's workload, so a "
                "stretch with no slice means no SAMPLED job held that card -- jobs outside the "
                "sample ran in some of that space. MIT states the release is not appropriate "
                "for estimating system utilisation. Do not read occupancy off this trace."
            ),
            "what_a_slice_is": (
                "The scheduler's allocation window (time_start to time_end) for one job on one "
                "card -- how long the card was HELD. What happened inside it is in the args: "
                "measured_gpu_hours is DCGM's execution time, sm_util_avg/max the utilisation."
            ),
            "colours": "terrible/red = A never computed, red = B1 barely used, "
                       "yellow = B2 did compute at low duty cycle, olive = C, green = D working",
            "t_zero_utc": WINDOW_START.isoformat(),
            "window_end_utc": (WINDOW_START + timedelta(days=span_days)).isoformat(),
            "slices": len(df),
            "tracks": len(nodes) * 2,
            "card_rows_dropped_no_interval": dropped,
            "scope": "waste only (buckets A and B1)" if waste_only else "every job",
            "source": "MIT SuperCloud TX-GAIA, HPCA'22 release, CC BY-NC-ND 4.0",
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / ("trace_waste.json.gz" if waste_only else "trace.json.gz")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(trace, fh, separators=(",", ":"))
    print(f"{path}  {path.stat().st_size / 1e6:.1f} MB  "
          f"{len(df):,} slices on {len(nodes) * 2} tracks  ({dropped:,} card-rows had no interval)")
    return path


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, default=Path("data/prepped"))
    p.add_argument("--out-dir", type=Path, default=Path("out"))
    p.add_argument("--waste-only", action="store_true")
    a = p.parse_args()
    build(a.data_dir, a.out_dir, a.waste_only)
