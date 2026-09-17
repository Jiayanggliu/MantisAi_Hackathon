"""Diagnose is all your need — Track 2 cluster efficiency dashboard.

Three tiles: where the money goes, where to cut, what it costs if we are wrong.
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


@st.cache_data(show_spinner=False)
def load_analysis() -> dict:
    return json.loads((OUT / "analysis.json").read_text())


@st.cache_data(show_spinner=False)
def load_jobs() -> pd.DataFrame:
    return pd.read_parquet(OUT / "jobs_bucketed.parquet")


if not (OUT / "analysis.json").exists():
    st.error(
        "`out/analysis.json` is missing. Generate the data first (`make setup`), "
        "then bring the stack up with `docker compose up`."
    )
    st.stop()

a = load_analysis()
jobs = load_jobs()
price = a["price_usd_per_gpu_hour"]
total_h = a["total_gpu_hours"]
total_usd = total_h * price
rec = a["recoverable"]
bucket = {b["id"]: b for b in a["buckets"]}

# Plain English for the CFO. The predicate behind each row is an engineering fact
# and lives in the expander under the tile, not on it.
PLAIN = {
    "A": ("Paid for, never used", "The GPU was reserved and never ran a single calculation."),
    "B1": ("Barely touched", "Reserved, and whatever ran on it never got going."),
    "B2": ("Light but real use", "Genuinely computing, just not flat out."),
    "C": ("Moderate use", "Normal research work."),
    "D": ("Working hard", "This is the research. Do not touch it."),
}
ACT = {"A": "Recover", "B1": "Recover", "B2": "Leave", "C": "Leave", "D": "Leave"}

st.title("Diagnose is all your need")
st.markdown(
    f"### Cut **${rec['usd']:,.0f}** — {rec['share']:.0%} of GPU spend — without touching "
    f"a single job that was doing work."
)
st.caption(
    f"Four months of MIT SuperCloud: 225 machines, 74,849 jobs, 195 researchers, "
    f"{total_h:,.0f} GPU-hours, **\\${total_usd:,.0f}** at \\$2.50/GPU-hour. "
    f"Figures describe this telemetry sample, not total cluster capacity."
)

# ============================================================ TILE 1
st.divider()
st.header("1 · Where the money is going")

t1 = pd.DataFrame([
    {"Where it went": PLAIN[b["id"]][0],
     "What that means": PLAIN[b["id"]][1],
     "Cost": b["usd"],
     "Share of spend": b["share"] * 100,
     "Verdict": ACT[b["id"]]}
    for b in a["buckets"]
])
st.dataframe(
    t1, hide_index=True, width="stretch",
    column_config={
        "Where it went": st.column_config.TextColumn(width="medium"),
        "What that means": st.column_config.TextColumn(width="large"),
        "Cost": st.column_config.NumberColumn(format="$%,.0f", width="small"),
        "Share of spend": st.column_config.ProgressColumn(
            format="%.1f%%", min_value=0, max_value=100, width="medium"),
        "Verdict": st.column_config.TextColumn(width="small"),
    },
)

waste_usd = bucket["A"]["usd"] + bucket["B1"]["usd"]
st.markdown(
    f"**\\${waste_usd:,.0f} of the \\${total_usd:,.0f} bought nothing at all.** "
    f"The two rows marked *Recover* are GPUs that were reserved and never meaningfully used — "
    f"not research that merely ran slowly."
)

with st.expander("How each row is defined, and why we do not add up the API's findings"):
    st.markdown(
        "Every job lands in exactly one row, so the rows sum to the cluster total and no job "
        "is counted twice.\n\n"
        "| Row | Rule |\n| --- | --- |\n"
        "| Paid for, never used | average **and** peak SM utilisation both exactly 0 |\n"
        "| Barely touched | average < 5%, peak ≤ 20% |\n"
        "| Light but real use | average < 5%, peak > 20% — it *did* compute |\n"
        "| Moderate use | average 5–20% |\n"
        "| Working hard | average ≥ 20% |\n\n"
        "The API ships 11,979 findings, each with an `impact_gpu_hours`. Adding that column "
        "gives **931,607 GPU-hours — 157% of a cluster that only allocated 594,004** — because "
        "23 rules overlap on the same jobs and mix `lost`, `consumed` and `unused_capacity`, "
        "which are different quantities. We partition the jobs instead, and use the findings "
        "as evidence rather than as arithmetic."
    )

# ============================================================ TILE 2
st.divider()
st.header("2 · Where to cut")

recs = a["recommendations"]
OWNER = {
    "idle_timeout": "Platform team — scheduler policy",
    "cpu_queue": "Research computing — intake",
    "fail_fast": "Platform team — scheduler policy",
}
TITLE = {
    "idle_timeout": "Reclaim idle interactive sessions after 4 hours",
    "cpu_queue": "Route CPU-only work off the GPU queue",
    "fail_fast": "Release the card when a job dies on startup",
}
EVIDENCE = {
    "idle_timeout": "1,902 interactive sessions held cards with the GPU at zero. 98% of these "
                    "hours are in jobs that ran longer than 4 hours, so a 4-hour idle timeout "
                    "reaches nearly all of it.",
    "cpu_queue": "4,817 jobs **completed successfully** with the GPU at zero for their whole "
                 "life. That is CPU work which asked for a GPU and got one.",
    "fail_fast": "12,171 jobs failed without ever running a kernel. Most die within seconds; "
                 "the hours are in the minority that sit holding a card after dying.",
}

ranked = sorted(recs, key=lambda r: -r["gpu_hours"])
t2 = pd.DataFrame([
    {"#": i + 1,
     "Action": TITLE.get(r["id"], r["id"]),
     "Who owns it": OWNER.get(r["id"], "—"),
     "Saves": r["gpu_hours"] * price,
     "GPU-hours": r["gpu_hours"],
     "Jobs": r.get("jobs", 0)}
    for i, r in enumerate(ranked)
])
st.dataframe(
    t2, hide_index=True, width="stretch",
    column_config={
        "#": st.column_config.NumberColumn(width="small"),
        "Action": st.column_config.TextColumn(width="large"),
        "Who owns it": st.column_config.TextColumn(width="medium"),
        "Saves": st.column_config.NumberColumn(format="$%,.0f", width="small"),
        "GPU-hours": st.column_config.NumberColumn(format="%,.0f", width="small"),
        "Jobs": st.column_config.NumberColumn(format="%,d", width="small"),
    },
)

for i, r in enumerate(ranked):
    st.markdown(f"**{i + 1}. {TITLE.get(r['id'], r['id'])}** — {EVIDENCE.get(r['id'], '')}")

mech = sum(r["gpu_hours"] for r in recs)
st.info(
    f"**Honest coverage.** These three policies account for **{mech:,.0f} of the "
    f"{rec['gpu_hours']:,.0f} GPU-hours** we call recoverable — {mech / rec['gpu_hours']:.0%}. "
    f"The remaining {rec['gpu_hours'] - mech:,.0f} GPU-hours "
    f"(\\${(rec['gpu_hours'] - mech) * price:,.0f}) sit in *Barely touched*, where the waste is "
    f"visible but we have not yet named the mechanism that reclaims it. Counting only what has "
    f"a policy behind it, the number is **\\${mech * price:,.0f} — {mech / total_h:.1%} of "
    f"spend**, short of the 20% target."
)

st.markdown(
    "**Nobody is ranked by waste here.** Users are hashed in the source data and we keep them "
    "that way — these are policies the platform team owns, not people to chase. 57% of the "
    "recoverable hours sit with 10 accounts, which is precisely why three policies reach most "
    "of it."
)

# ============================================================ TILE 3
st.divider()
st.header("3 · What it costs if we are wrong")
st.caption("The tile most teams skip.")

claims = a.get("claims", {})
rg = claims.get("recoverable_gpu_hours", {})
c1, c2, c3 = st.columns(3)
c1.metric("Our estimate", f"${rec['usd']:,.0f}", f"{rec['share']:.1%} of spend")
if rg:
    c2.metric("If we are pessimistic", f"${rg.get('low', 0) * price:,.0f}",
              "only jobs that ran literally nothing", delta_color="off")
    c3.metric("If we are optimistic", f"${rg.get('high', 0) * price:,.0f}",
              "counts light-but-real use too", delta_color="off")

st.subheader("The expensive mistake: cutting a job that was working")
st.markdown(
    "A policy written as *“kill anything under 5% average utilisation”* is the obvious one to "
    "write, and it is wrong. Average utilisation is a whole-lifetime mean: a job that loads "
    "data for an hour and then computes hard reads as a low average. **Peak** utilisation is "
    "what separates a card that never worked from one that did."
)

thresh = st.slider(
    "Kill jobs under 5% average utilisation whose peak never exceeded …",
    min_value=0, max_value=60, value=20, step=5, format="%d%% peak SM",
    help="Our recommendation draws the line at 20%. Drag it to see what a different line costs.",
)
low_avg = jobs[(jobs.sm_util_avg > 0) & (jobs.sm_util_avg < 5)]
wrongly, safely = low_avg[low_avg.sm_util_max > thresh], low_avg[low_avg.sm_util_max <= thresh]

m1, m2 = st.columns(2)
m1.metric("Research we would destroy", f"${wrongly.gpu_hours.sum() * price:,.0f}",
          f"{len(wrongly):,} jobs that did compute", delta_color="inverse")
m2.metric("Capacity we would reclaim", f"${safely.gpu_hours.sum() * price:,.0f}",
          f"{len(safely):,} jobs that never got going")
st.caption(
    f"At our chosen line of 20% peak, **\\${bucket['B2']['usd']:,.0f} of real research "
    f"({bucket['B2']['jobs']:,} jobs) stays untouched** — the cost we are deliberately not "
    f"incurring. Drag to 0% and every one of those jobs is killed."
)

st.subheader("The other expensive mistake: draining machines")
st.markdown(
    "The API's own `GET /v1/recommendations` proposes **“drain the top 5 underperforming "
    "nodes”** for a claimed **\\$57,226**. We recommend against it.\n\n"
    "That ranking comes from `/v1/resources/underperforming`, which sorts by how many findings "
    "name a machine and — by its own documentation — does not read `rootCauses`. On this "
    "cluster the machines carrying the most findings are mostly machines where one person ran "
    "a broken script repeatedly, or where a Slurm array failed for reasons unrelated to "
    "hardware: those failures spread thinly across many machines, and the spread is itself the "
    "evidence the machines are innocent. `POST /v1/causal` confirms none of it.\n\n"
    "Draining 5 machines removes 10 V100s for a quarter — real capacity — against evidence "
    "that does not support it. **There is exactly one machine on this cluster worth pulling, "
    "and it is not on that list** (see the trace below)."
)

st.subheader("What we would stake the number on")
st.markdown(
    f"- **High confidence** on \\${bucket['A']['usd']:,.0f}: those {bucket['A']['jobs']:,} jobs "
    f"ran no kernel at all — average *and* peak exactly zero. There is no reading of that as "
    f"useful work.\n"
    f"- **Lower confidence** on the coverage gap above: the waste in *Barely touched* is "
    f"visible, but the policy that reclaims it is not yet written.\n"
    f"- **We do not count cancellations as waste.** CANCELLED is 203,930 GPU-hours, more than "
    f"failed and timed-out combined. A researcher killing a bad run is good practice. We count "
    f"only cancelled jobs whose GPU never computed; counting all of it would roughly double the "
    f"headline and would be dishonest.\n"
    f"- **The data is a sample.** MIT states it is not appropriate for estimating system "
    f"utilisation. Every figure here describes these 74,849 jobs, not the cluster in general."
)

# ============================================================ EVIDENCE
st.divider()
st.header("The evidence, one click down")

left, right = st.columns([1, 3])
with left:
    picked = st.multiselect(
        "Bucket", options=[b["id"] for b in a["buckets"]], default=["A", "B1"],
        format_func=lambda k: f"{k} — {PLAIN[k][0]}",
    )
    states = st.multiselect("Outcome", options=sorted(jobs.state_name.dropna().unique()), default=[])
    min_h = st.slider("Minimum GPU-hours", 0, 500, 0, step=10)

view = jobs[jobs.bucket.isin(picked)] if picked else jobs
if states:
    view = view[view.state_name.isin(states)]
view = view[view.gpu_hours >= min_h]

with right:
    st.metric("Selected", f"{len(view):,} jobs · {view.gpu_hours.sum():,.0f} GPU-h",
              f"${view.gpu_hours.sum() * price:,.0f}")

cols = ["id_job", "bucket", "state_name", "gpu_count", "gpu_hours", "sm_util_avg",
        "sm_util_max", "mem_used_frac", "walltime_sec", "job_type", "partition", "primary_node"]
st.dataframe(
    view[cols].sort_values("gpu_hours", ascending=False).head(500),
    hide_index=True, width="stretch",
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
st.caption(f"The 500 largest of {len(view):,} matching jobs.")

# ============================================================ BEYOND
st.divider()
st.header("Past the three tiles — the cluster as a trace")
st.caption(
    "One track per GPU, one slice per job that held it. Download, then drag into "
    "[ui.perfetto.dev](https://ui.perfetto.dev)."
)
st.warning(
    "**A gap is not an idle GPU.** This release is a *sample*, so empty space means no "
    "*sampled* job held that card. MIT states the data is not appropriate for estimating "
    "system utilisation. The same warning is embedded in the trace metadata."
)

TRACES = [
    ("out/trace_fault.json.gz", "Start here — one machine, one week",
     "64 tracks, 8.4 days, coloured by outcome. A machine that failed 97% of its work while "
     "its rack neighbours ran fine. The scheduler never marked it down."),
    ("out/trace_waste.json.gz", "The waste", "450 tracks, 31,435 slices, coloured by bucket."),
    ("out/trace.json.gz", "Everything",
     "95,005 slices over 125 days. Correct, and unreadable unless you know where to look."),
]
for col, (rel, label, blurb) in zip(st.columns(len(TRACES)), TRACES):
    path = ROOT / rel
    with col:
        st.markdown(f"**{label}**")
        st.caption(blurb)
        if path.exists():
            n = path.stat().st_size
            col.download_button(
                f"Download ({n / 1e3:.0f} KB)" if n < 1e6 else f"Download ({n / 1e6:.1f} MB)",
                data=path.read_bytes(), file_name=path.name,
                mime="application/gzip", width="stretch",
            )
        else:
            st.caption("Not built — run `python scripts/make_trace.py`.")
