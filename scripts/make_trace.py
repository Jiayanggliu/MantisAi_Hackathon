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


# The focus trace tells a different story from the other two -- a machine failing,
# not capacity being wasted -- so it colours by outcome instead of by bucket.
STATE_CNAME = {"FAILED": "terrible", "TIMEOUT": "bad", "CANCELLED": "yellow",
               "NODE_FAIL": "terrible", "COMPLETED": "good"}


def build_focus(data_dir: Path, out_dir: Path, node: str, exit_code: int, pad_days: float) -> Path:
    """One machine, its rack, and the days around its failure signature.

    The full trace is 450 tracks over 125 days: correct, and unreadable without
    knowing where to look. This is the same data cut to one story.
    """
    jobs = pd.read_parquet(data_dir / "jobs.parquet")
    gpus = pd.read_parquet(data_dir / "gpus.parquet", columns=["id_job", "Node", "gpu_id"])

    sig = jobs[(jobs.primary_node == node) & (jobs.exit_code == exit_code)]
    if sig.empty:
        raise SystemExit(f"no jobs on {node} with exit_code {exit_code}")
    pad = pad_days * 86400
    w0, w1 = float(sig.time_start.min()) - pad, float(sig.time_end.max()) + pad

    rack = node.split("-")[-1]
    cols = ["id_job", "time_start", "time_end", "state_name", "gpu_hours",
            "sm_util_avg", "sm_util_max", "exit_code", "job_type", "id_user"]
    df = gpus.merge(jobs[cols], on="id_job", how="left")
    df = df[df.time_start.notna() & df.time_end.notna() & (df.time_end > df.time_start)]
    # Overlapping the window, on this rack.
    df = df[df.Node.str.endswith(rack) & (df.time_start < w1) & (df.time_end > w0)]

    # Failure rate per machine, so the track name carries the comparison that
    # makes the point: the focus node against the neighbours it sat next to.
    rate = (df.drop_duplicates("id_job").groupby("Node")
              .agg(jobs=("id_job", "size"), failed=("state_name", lambda s: (s == "FAILED").sum())))
    rate["pct"] = (rate.failed / rate.jobs * 100).round(0)
    # Focus node first, then the rest by failure rate.
    order = [node] + [n for n in rate.sort_values("failed", ascending=False).index if n != node]
    pid_of = {n: i + 1 for i, n in enumerate(order)}

    events: list[dict] = []
    for n in order:
        pid, r = pid_of[n], rate.loc[n]
        mark = "  <<< THE FAULT" if n == node else ""
        events += [
            {"ph": "M", "pid": pid, "tid": 0, "name": "process_name",
             "args": {"name": f"{n}   {r.pct:.0f}% failed ({int(r.failed)}/{int(r.jobs)}){mark}"}},
            {"ph": "M", "pid": pid, "tid": 0, "name": "process_sort_index",
             "args": {"sort_index": pid}},
        ]
        for gid in (0, 1):
            events.append({"ph": "M", "pid": pid, "tid": int(gid), "name": "thread_name",
                           "args": {"name": f"GPU {gid}"}})

    # Clamp to the window. A job that started days before it and ran on through
    # would otherwise stretch the timeline to weeks and flatten the very days the
    # trace exists to show.
    t0 = w0
    for r in df.itertuples(index=False):
        hit = int(r.exit_code) == exit_code if pd.notna(r.exit_code) else False
        lo, hi = max(float(r.time_start), w0), min(float(r.time_end), w1)
        events.append({
            "ph": "X", "pid": pid_of[r.Node], "tid": int(r.gpu_id),
            "ts": int((lo - t0) * 1e6),
            "dur": max(int((hi - lo) * 1e6), 1),
            "name": ("SIGBUS " if hit else "") + str(r.state_name),
            "cname": STATE_CNAME.get(r.state_name, "grey"),
            "args": {
                "job_id": int(r.id_job),
                "state": r.state_name,
                "exit_code": None if pd.isna(r.exit_code) else int(r.exit_code),
                "exit_status": None if pd.isna(r.exit_code) else int(r.exit_code) >> 8,
                "carries_the_fault_signature": hit,
                "owner": str(r.id_user),
                "measured_gpu_hours": round(float(r.gpu_hours), 2),
                "job_type": r.job_type,
            },
        })

    trace = {
        "traceEvents": events, "displayTimeUnit": "ms",
        "otherData": {
            "story": (
                f"{node} failed {rate.loc[node].pct:.0f}% of everything it ran for "
                f"{(w1 - w0 - 2 * pad) / 86400:.1f} days. Its rack neighbours, taking the same "
                f"kind of work in the same hours, are the tracks below it. The scheduler never "
                f"marked it down -- there is no NODE_FAIL here. Slices named SIGBUS carry exit "
                f"status {exit_code >> 8}, which three unrelated people hit on this machine and "
                f"on no other machine in 3,917 jobs."
            ),
            "colours": "red = FAILED, orange = TIMEOUT, yellow = CANCELLED, green = COMPLETED",
            "why_this_is_the_small_trace": (
                "trace.json.gz is the whole cluster: 450 tracks, 125 days, correct and "
                "unreadable unless you already know where to look. This is the same data "
                "cut to one machine and one week."
            ),
            "slices": len(df), "tracks": len(order) * 2,
            "source": "MIT SuperCloud TX-GAIA, HPCA'22 release, CC BY-NC-ND 4.0",
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "trace_fault.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(trace, fh, separators=(",", ":"))
    print(f"{path}  {path.stat().st_size / 1e3:.0f} KB  {len(df):,} slices on "
          f"{len(order) * 2} tracks  ({node} at {rate.loc[node].pct:.0f}% failed)")
    return path


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
    p.add_argument("--focus", metavar="NODE",
                   help="one machine, its rack and the days around its failure signature")
    p.add_argument("--exit-code", type=int, default=34560,
                   help="the failure signature to highlight (default 34560 = SIGBUS)")
    p.add_argument("--pad-days", type=float, default=2.0)
    a = p.parse_args()
    if a.focus:
        build_focus(a.data_dir, a.out_dir, a.focus, a.exit_code, a.pad_days)
    else:
        build(a.data_dir, a.out_dir, a.waste_only)
