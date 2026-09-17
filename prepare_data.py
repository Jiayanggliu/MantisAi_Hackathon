#!/usr/bin/env python3
"""Prepare Track 2 parquet inputs from the supplied raw CSV files."""
from pathlib import Path
import pandas as pd

ROOT = Path.cwd()
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "prepped"

def main():
    sched = pd.read_csv(RAW / "scheduler_data.csv")
    dcgm = pd.read_csv(RAW / "dcgm.csv")
    required_s = {"id_job", "state", "time_start", "time_end", "job_type", "id_user"}
    required_g = {"id_job", "gpu_id", "smutilization_pct_avg", "smutilization_pct_max", "totalexecutiontime_sec"}
    missing = (required_s - set(sched.columns)) | (required_g - set(dcgm.columns))
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    dcgm["gpu_hours"] = pd.to_numeric(dcgm["totalexecutiontime_sec"], errors="coerce").fillna(0) / 3600
    gpu_cols = ["id_job", "gpu_id", "gpu_hours", "smutilization_pct_avg", "smutilization_pct_max"]
    gpus = dcgm[gpu_cols].copy()
    agg = gpus.groupby("id_job", as_index=False).agg(
        gpu_hours=("gpu_hours", "sum"),
        sm_util_avg=("smutilization_pct_avg", "mean"),
        sm_util_max=("smutilization_pct_max", "max"),
        gpu_count=("gpu_id", "nunique"),
    )
    jobs = sched.merge(agg, on="id_job", how="inner")
    jobs["walltime_sec"] = (pd.to_numeric(jobs["time_end"], errors="coerce") - pd.to_numeric(jobs["time_start"], errors="coerce")).clip(lower=0)
    jobs["state_name"] = jobs["state"].map({3: "COMPLETED", 4: "CANCELLED", 5: "FAILED", 6: "TIMEOUT"}).fillna("OTHER")
    jobs["primary_node"] = jobs.get("nodelist", pd.Series(index=jobs.index, dtype="object"))
    OUT.mkdir(parents=True, exist_ok=True)
    jobs.to_parquet(OUT / "jobs.parquet", index=False)
    gpus.to_parquet(OUT / "gpus.parquet", index=False)
    print(f"Wrote {len(jobs):,} jobs and {len(gpus):,} GPU records to {OUT}")

if __name__ == "__main__":
    main()
