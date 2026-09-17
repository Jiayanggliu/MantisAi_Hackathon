# Track 2 Findings — GPU Cluster Efficiency

*As of 2026-09-17. Every number below was computed on this machine from `data/prepped/` and
verified against `data/checksums.txt`. Reproduce with `scripts/spine_check.py` (section 8).*

## 1. The headline

**The 20% cut is reachable by touching only jobs whose GPU never exceeded 20% SM utilization
at peak. Not one job that was actually computing has to be touched.**

- The cluster allocated **594,004 GPU-hours** over four months (MIT SuperCloud TX-GAIA: 225 nodes,
  2 × V100-32GB each, 74,849 GPU jobs, 195 users). At the price book's $2.50/GPU-hour that is
  **$1,485,010**.
- A 20% cut is **118,801 GPU-hours = $297,002**.
- We find **123,480 GPU-hours = 20.8% = $308,700** recoverable at high-to-medium confidence,
  every hour traceable to a specific `id_job`.
- 97,196 of those GPU-hours (16.4% of the cluster) are jobs whose GPU **never ran a single kernel**:
  average and peak SM utilization both exactly zero.

Caveat that goes on every tile: these figures describe a four-month *job sample*, not the cluster in
general. MIT states the release is a subset and not suitable for estimating whole-system utilization.
Also, telemetry is per job — unallocated idle GPUs emit nothing, so 594,004 is *allocated* time, not
capacity.

## 2. Why we partition jobs instead of summing findings

The API ships 11,979 findings from 23 rules, each carrying `metadata.impact_gpu_hours`. Summing that
column gives **931,607 GPU-hours — 157% of a cluster that only allocated 594,004**. Rules overlap by
design (an idle interactive session is usually also a job that never computed; 18% of flagged jobs
carry more than one finding), and `impact_kind` (lost / consumed / unused_capacity / degraded) and
`impact_scope` (job / node / user) are different denominators that cannot be added.

So we do not add findings. We take `jobs.parquet` (one row per job, DCGM-measured `gpu_hours`) and put
**every job in exactly one bucket**. The buckets sum to 594,004 by construction. Findings are used only
for drill-down: click a bucket, see which rules those jobs tripped.

## 3. The five buckets

Predicates, applied in order (first match wins), on `jobs.parquet`:

```python
A  = (sm_util_avg == 0) & (sm_util_max == 0)            # never computed
B1 = ~A & (sm_util_avg < 5) & (sm_util_max <= 20)       # barely used, never really ran
B2 = ~A & (sm_util_avg < 5) & (sm_util_max >  20)       # low duty cycle, but DID compute
C  = ~A & (sm_util_avg >= 5) & (sm_util_avg < 20)
D  = (sm_util_avg >= 20)
```

| Bucket | Meaning | Jobs | GPU-hours | Share | USD | Confidence / action |
|---|---|---:|---:|---:|---:|---|
| **A — never computed** | avg and peak SM both 0; the GPU physically ran nothing | 19,887 | **97,196** | 16.4% | $242,991 | **High** — recover |
| **B1 — barely used, never ran** | avg < 5%, peak ≤ 20% | 5,448 | **26,284** | 4.4% | $65,710 | **Medium-high** — recover |
| B2 — low duty cycle, did compute | avg < 5%, peak > 20% | 4,530 | 59,084 | 9.9% | $147,711 | **Low** — this is the false-positive risk (section 5) |
| C — low | 5–20% | 11,059 | 68,609 | 11.6% | | Leave alone |
| D — working | ≥ 20% | 33,925 | 342,830 | 57.7% | | The research lives here. Leave alone |
| **Total** | | 74,849 | 594,004 | 100% | | |

**Recoverable = A + B1 = 123,480 GPU-hours = 20.8%.**

Why these thresholds:
- **A uses `== 0`, not `< 1`.** It is the exact definition of the shipped rules
  `gpu-never-computed` and `gpu-not-needed`. A job whose peak reached 35% *did* compute.
- **The A/B split uses peak SM 20%.** `sm_util_avg` is a lifetime mean; a data-loader-bound or
  communication-bound job has a low mean but a real peak (this is the API's own caveat on
  `/v1/efficiency/summary`). Peak ≤ 20% means it never seriously ran; peak > 20% means it did, and
  cutting it cuts research. This split is the hinge of the cost-of-being-wrong argument.
- 5% and 20% are the thresholds `rules.md` already uses (`idle-interactive-session`,
  `multi-node-low-utilization`, `node-under-utilization-slo`). We invented no numbers.

## 4. Where to cut — three concrete recommendations

Bucket A split by how the job ended. Each row is one policy, not "improve utilization":

| # | Outcome | Jobs | GPU-hours | USD | Recommendation | Rules for drill-down |
|---|---|---:|---:|---:|---|---|
| 1 | CANCELLED + TIMEOUT | 2,047 + 834 | 36,101 + 30,670 = **66,771** | $166,928 | **Idle timeout on interactive allocations.** Bucket A holds 1,902 `LLSUB:INTERACTIVE` sessions = 32,775 GPU-hours. 98% of bucket A's hours come from jobs longer than 4 h, so a **4-hour idle timeout** covers nearly all of it. | `idle-interactive-session`, `slow-cancel-of-idle-job`, `wallclock-kill` |
| 2 | COMPLETED | 4,817 | **12,301** | $30,751 | **Wrong queue.** The job succeeded with the GPU at zero for its whole life — it was CPU work that asked for a GPU. Route to the CPU partition; require a justification for GPU requests. | `gpu-not-needed` |
| 3 | FAILED | 12,171 | **17,065** | $42,663 | **Fail fast.** Most of these 12k jobs die in seconds (median walltime ≈ 0), but a minority sits holding cards. Release the allocation if SM is still zero N minutes after start. | `gpu-never-computed`, `array-mass-failure` |

Supporting facts:
- Multi-GPU jobs in bucket A: 3,295 jobs, 33,887 GPU-hours. An idle wide job multiplies one idle card
  by its GPU count.
- 57% of bucket A's hours sit with 10 users. **Say "highly concentrated — a few policies cover most of
  it." Do not rank or name users.** `traps.md` is explicit that a dashboard ranking people by waste
  scores lower; users are hashed and stay that way.

## 5. What it costs if we are wrong

**Cutting too deep.** A naive idle-kill policy at avg < 5% would also hit bucket B2: **4,530 jobs,
59,084 GPU-hours, $147,711** of research that *did* compute, at low duty cycle. That is the number
on the tile. Move the threshold (5% → 1%, with or without the peak condition) and the false-positive
mass changes — the dashboard should expose it as a slider.

**The other wrong answer: draining nodes.** Layer B's `GET /v1/recommendations` proposes
`rec_drain_nodes`, "drain the top 5 underperforming nodes", claiming $57,226. The ranking behind it
(`/v1/resources/underperforming`) sorts by finding *count* and, per the API's own docs, does not read
`rootCauses`. On this cluster the machines with the most findings are mostly machines where one
person ran a broken script repeatedly, or where an array failed for reasons unrelated to hardware
(the array's failures spread thinly across many nodes — that spread is the evidence the nodes are
innocent). Draining 5 nodes removes ~5 × 2 cards × 4 months of capacity for a reliability gain that
`POST /v1/causal` does not confirm. We recommend against it and show why.

**PCIe is not the bottleneck.** `rules::gpu-pcie-saturated` is armed and has never fired; peak observed
PCIe is 4,240 MB/s, 27% of the gen3 x16 link. "Fix the data pipeline" is not supported by this data.

## 6. Two more findings

**The silent hardware fault.** `traps.md` says one machine broke for about a week without ever being
marked down. One query finds it: group FAILED jobs by (`primary_node`, `exit_code`), keep signatures
shared by ≥ 3 distinct users where > 50% of that exit code's cluster-wide failures land on one machine.

| Node | exit_code | Distinct users | Failures here | Failures cluster-wide | Share here |
|---|---:|---:|---:|---:|---:|
| **r216287-n200569** | 34560 | 3 | 114 | 129 | **88%** |

Three unrelated people, one exit code, almost never anywhere else. Only 10 jobs in the whole dataset
end in `NODE_FAIL`, and 31 hit a node failure on some attempt (`hit_node_failure`); the scheduler
never saw this machine.

**Our independent method reproduces the shipped answer exactly.** The API's single
`rules::node-hardware-fault` finding names the same machine. It reports `exit status 135 (SIGBUS)`;
we found `exit_code 34560`, and Slurm stores exit_code as status << 8, so 135 x 256 = 34560 — the same
signature. Its evidence lists three users with 23 + 5 + 86 = **114** crashes on this node and **0**
across 3,917 jobs on every other machine. Window 2026-02-27 to 2026-03-07, about one week, matching
`traps.md`. Impact as the rule scores it: 76.6 GPU-hours lost, 140 of 144 jobs on the node failing
while it stayed in service.

That agreement is worth showing in the demo: the rationale is a reproducible method, not a guess.

**Calibration warning for `node_triage`.** `rules::node-job-failure-burst` runs the same kind of
causal analysis over 47 episodes and lands on **undetermined 26, user 20, hardware 1**. The rule docs
say `undetermined` is the most common verdict and is correct. If we return a confident cause for all
113 `node-elevated-failure-rate` findings, we are overfitting. Answer the handful we can defend and
mark the rest `cannot_determine`.

**Card imbalance** (invisible in `jobs.parquet`, whose `sm_util_avg` averages across cards). Pivoting
`gpus.parquet` per `gpu_id` with the rule's own thresholds (≥ 2 cards, busiest ≥ 20%, spread > 30
points, walltime > 1 h) gives **689 jobs — exactly the rule's count — over 31,613 GPU-hours, with an
idle-card equivalent of ≈ 13,652 GPU-hours** (the rule reports 14,559).

## 7. Numbers for `claims.json`

```jsonc
"recoverable_gpu_hours": {
  "point": 123480, "low": 97196, "high": 182564, "confidence": 0.7,
  "basis": "Mutually exclusive partition of jobs.parquet by (sm_util_avg, sm_util_max). Point = jobs whose GPU never exceeded 20% SM at peak (avg==0 & max==0, plus 0<avg<5 & max<=20). Low = only avg==0 & max==0. High adds jobs with avg<5 but max>20, which did compute at low duty cycle. gpu_hours is DCGM-measured, not gpu_count x walltime. Findings' impact_gpu_hours were NOT summed (naive sum is 157% of the cluster)."
},
"recoverable_usd": { "point": 308700, "low": 242991, "high": 456410, "confidence": 0.7 },
"cancelled_is_waste": false,
"cancelled_rationale": "Not as a category. CANCELLED is 203,930 GPU-h; we count only the 36,101 GPU-h of cancelled jobs whose GPU never computed (avg==0 & max==0) plus the B1 slice. Cancelling a job that was computing is a user correctly killing a bad run — good practice, not waste.",
"card_imbalance_gpu_hours": { "point": 13652, "low": 10000, "high": 16000, "confidence": 0.6 },
"card_imbalance_rationale": "gpus.parquet pivoted per gpu_id; rule thresholds (>=2 cards, busiest>=20%, spread>30, walltime>1h) reproduce the rule's 689 jobs; idle-card equivalent = gpu_hours x (1 - mean_card_util / busiest_card_util).",
"hardware_attributable_failures": 145,
"hardware_attributable_confidence": 0.6,
"hardware_attributable_rationale": "31 jobs with hit_node_failure (scheduler-recorded, any attempt) + 114 FAILED jobs on r216287-n200569 with exit_code 34560 (= exit status 135, SIGBUS, shifted 8 bits), shared by 3 users who produce that status 0 times across 3,917 jobs on every other machine. Found independently by grouping FAILED jobs on (primary_node, exit_code) and keeping signatures with >=3 distinct users and >50% of that code's cluster-wide failures on one node; it matches the shipped node-hardware-fault finding. Excludes the other ~18,400 failures: no cross-user, node-local signature.",

"incident_root_cause": "pvc/scratch-lustre-02",
"incident_action_scope": "single_resource",
"incident_nodes_to_drain": 0,
"incident_confidence": 0.74,
"incident_degraded_gpu_hours": { "point": 8654, "low": 7000, "high": 10000, "confidence": 0.6 }
```

On the incident: 121 `filesystem-latency-degraded` findings across 121 nodes resolve, via
`POST /v1/causal`, to one volume (`pvc/scratch-lustre-02`, p99 latency up 30.3x, culprit score 0.88
against 0.31 for every node). **The trap is draining 121 machines. The answer is fixing one volume and
draining zero.** This is the clearest "count the problems, not the findings" example in the corpus —
and it is the one synthetic scenario, so label it as such on the dashboard.

Intervals are deliberately wide: calibration is scored on whether the interval contains the truth.

## 8. Reproduce

```bash
cd MantisAi_Hackathon
docker compose run --rm prep python scripts/spine_check.py
```

Prints every number in sections 3–6. Acceptance: bucket GPU-hours sum to 594,004 (±1), jobs sum to
74,849, A = 97,196 / B1 = 26,284 / B2 = 59,084 / C = 68,609 / D = 342,830.

Traps that bite this analysis specifically (`docs/traps.md`, `docs/rules.md` have the rest):
- Use measured `gpu_hours`, never `gpu_hours_alloc` — they differ by > 10% on 7% of jobs, worst case 19.5×.
- Weight by GPU-hours, never by rows — a third of job records are 0.012% of the compute.
- `sm_util_avg` is the mean across a job's cards; card imbalance needs `gpus.parquet`.
- A job's final node is usually *not* the one that failed; use `nodefail_nodes`, not `primary_node`, for
  scheduler-recorded failures.
