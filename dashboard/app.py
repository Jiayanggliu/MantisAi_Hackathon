"""Diagnose is all your need — Track 2 cluster efficiency dashboard.

Reads out/analysis.json and out/jobs_bucketed.parquet, produced by analysis.py.
Serves on :3000.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out"

st.set_page_config(page_title="Diagnose is all your need", layout="wide")


# ---------------------------------------------------------------- data

@st.cache_data(show_spinner=False)
def load_analysis() -> dict:
    return json.loads((OUT / "analysis.json").read_text())


@st.cache_data(show_spinner=False)
def load_jobs() -> pd.DataFrame:
    return pd.read_parquet(OUT / "jobs_bucketed.parquet")


if not (OUT / "analysis.json").exists():
    st.error(
        "`out/analysis.json` is missing. Generate the data first "
        "(`data/README.md` steps 1–4), then run `python analysis.py` from the repo root."
    )
    st.stop()

a = load_analysis()
price = a["price_usd_per_gpu_hour"]
total_h = a["total_gpu_hours"]
rec = a["recoverable"]


# ---------------------------------------------------------------- header

st.title("Diagnose is all your need")
st.markdown(
    f"**The 20% cut is reachable by touching only jobs whose GPU never exceeded 20% "
    f"utilization at peak — not one job that was actually computing has to be touched.**"
)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Allocated", f"{total_h:,.0f} GPU-h", f"${total_h * price:,.0f}")
c2.metric("20% target", f"{a['target_gpu_hours']:,.0f} GPU-h", f"${a['target_gpu_hours'] * price:,.0f}")
c3.metric(
    "Recoverable found",
    f"{rec['gpu_hours']:,.0f} GPU-h",
    f"${rec['usd']:,.0f} · {rec['share']:.1%}",
)
c4.metric(
    "Cost if we cut too deep",
    f"{a['cost_if_wrong']['b2_gpu_hours']:,.0f} GPU-h",
    f"-${a['cost_if_wrong']['b2_usd']:,.0f}",
    delta_color="inverse",
)

st.caption(a["sample_scope"] + f"  Priced at ${price:.2f}/GPU-hour (price book 2026-Q3).")
st.divider()


# ---------------------------------------------------------------- the table

st.subheader("Every GPU-hour, in exactly one bucket")
st.caption(
    "Each job falls in one bucket only, so these sum to the cluster total. "
    "Finding `impact_gpu_hours` are deliberately not summed — 23 rules overlap and "
    "a naive sum reaches 157% of the cluster."
)

DEFN = {
    "A": "sm_avg == 0 and sm_max == 0",
    "B1": "0 < sm_avg < 5% and sm_max ≤ 20%",
    "B2": "0 < sm_avg < 5% and sm_max > 20%",
    "C": "5% ≤ sm_avg < 20%",
    "D": "sm_avg ≥ 20%",
}
VERDICT = {
    "A": "Recover — the GPU never ran a kernel",
    "B1": "Recover — never meaningfully computed",
    "B2": "Leave — did compute; this is the false-positive risk",
    "C": "Leave alone",
    "D": "Leave alone — the research lives here",
}

table = pd.DataFrame(
    [
        {
            "Bucket": f"{b['id']} — {b['label']}",
            "Definition": DEFN.get(b["id"], ""),
            "Jobs": b["jobs"],
            "GPU-hours": b["gpu_hours"],
            "Share": b["share"] * 100,
            "USD": b["usd"],
            "Confidence": b["confidence"],
            "What to do": VERDICT.get(b["id"], ""),
        }
        for b in a["buckets"]
    ]
)

st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Bucket": st.column_config.TextColumn(width="medium"),
        "Definition": st.column_config.TextColumn(width="medium"),
        "Jobs": st.column_config.NumberColumn(format="%,d", width="small"),
        "GPU-hours": st.column_config.NumberColumn(format="%,.0f", width="small"),
        "Share": st.column_config.ProgressColumn(
            "Share of cluster", format="%.1f%%", min_value=0, max_value=100, width="small"
        ),
        "USD": st.column_config.NumberColumn(format="$%,.0f", width="small"),
        "Confidence": st.column_config.TextColumn(width="small"),
        "What to do": st.column_config.TextColumn(width="large"),
    },
)

st.markdown(
    f"**A + B1 = {rec['gpu_hours']:,.0f} GPU-hours = {rec['share']:.1%} = ${rec['usd']:,.0f}.** "
    f"The target is {a['target_pct']:.0%}."
)

st.divider()


# ---------------------------------------------------------------- drill-down

st.subheader("The jobs behind the number")

jobs = load_jobs()

left, right = st.columns([1, 3])
with left:
    picked = st.multiselect(
        "Bucket",
        options=[b["id"] for b in a["buckets"]],
        default=["A", "B1"],
        help="A and B1 are what we propose cutting.",
    )
    states = st.multiselect(
        "Outcome",
        options=sorted(jobs.state_name.dropna().unique()),
        default=[],
    )
    min_h = st.slider("Minimum GPU-hours", 0, 500, 0, step=10)

view = jobs[jobs.bucket.isin(picked)] if picked else jobs
if states:
    view = view[view.state_name.isin(states)]
view = view[view.gpu_hours >= min_h]

with right:
    st.metric(
        "Selected",
        f"{len(view):,} jobs · {view.gpu_hours.sum():,.0f} GPU-h",
        f"${view.gpu_hours.sum() * price:,.0f}",
    )

cols = [
    "id_job", "bucket", "state_name", "gpu_count", "gpu_hours",
    "sm_util_avg", "sm_util_max", "mem_used_frac", "walltime_sec",
    "job_type", "partition", "primary_node",
]
st.dataframe(
    view[cols].sort_values("gpu_hours", ascending=False).head(500),
    hide_index=True,
    width="stretch",
    column_config={
        "id_job": st.column_config.NumberColumn("Job ID", format="%d"),
        "gpu_hours": st.column_config.NumberColumn("GPU-h", format="%.1f"),
        "sm_util_avg": st.column_config.NumberColumn("SM avg %", format="%.1f"),
        "sm_util_max": st.column_config.NumberColumn("SM peak %", format="%.0f"),
        "mem_used_frac": st.column_config.NumberColumn("GPU mem", format="%.2f"),
        "walltime_sec": st.column_config.NumberColumn("Walltime (s)", format="%,.0f"),
        "primary_node": "Primary node",
    },
)
st.caption(
    f"Showing the 500 largest of {len(view):,} matching jobs. "
    "Users are hashed in the source data and are not shown: these tiles locate recoverable "
    "capacity, not people."
)


# ---------------------------------------------------------------- trace

st.divider()
st.subheader("Open the cluster as a trace")
st.caption(
    "One track per GPU — 450 of them — and one slice per job that held the card, "
    "coloured by bucket. Built for [ui.perfetto.dev](https://ui.perfetto.dev): "
    "download, then drag the file in."
)

st.warning(
    "**A gap is not an idle GPU.** This release is a *sample* of the cluster's workload, "
    "so empty space means no *sampled* job held that card — unsampled jobs ran in some of "
    "it. MIT states the data is not appropriate for estimating system utilisation. "
    "The same warning is embedded in the trace's own metadata."
)

TRACES = [
    ("out/trace_waste.json.gz", "Waste only (buckets A + B1)",
     "31,435 slices. The smaller, sharper picture."),
    ("out/trace.json.gz", "Every job", "95,005 slices across the full 125 days."),
]

tcols = st.columns(len(TRACES))
for col, (rel, label, blurb) in zip(tcols, TRACES):
    path = ROOT / rel
    with col:
        st.markdown(f"**{label}**")
        st.caption(blurb)
        if path.exists():
            col.download_button(
                f"Download ({path.stat().st_size / 1e6:.1f} MB)",
                data=path.read_bytes(),
                file_name=path.name,
                mime="application/gzip",
                width="stretch",
            )
        else:
            st.caption("Not built yet — run `python scripts/make_trace.py`.")

st.markdown(
    "**What to look for.** Search the track list for `r216287-n200569`: for about a week "
    "from 2026-02-27 its two cards are a dense band of failures (217 of its 488 slices) "
    "while the rest of its rack runs green. The scheduler never marked that machine down. "
    "Three unrelated people hit SIGBUS on it and on no other machine in 3,917 jobs."
)
