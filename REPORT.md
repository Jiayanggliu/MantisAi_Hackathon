# Diagnose is all your need

**Cut $308,700 — 21% of GPU spend — without touching a single job that was doing work.**

Four months of MIT SuperCloud: 225 machines, 74,849 jobs, 195 researchers, 594,004 GPU-hours,
**$1,485,010** at the price book's $2.50/GPU-hour.

---

## 1. Where the money is going

83% of allocated GPU time did not become completed work. That is the starting point, and it is
two different discounts stacked on one another — idle-while-allocated and did-not-complete — so a
job that was both is counted twice. We do not use it.

Instead every job lands in **exactly one** bucket, keyed on average and peak SM utilisation. The
buckets sum to 594,004 GPU-hours and 74,849 jobs by construction, so nothing is double counted.

| Where it went | Rule | Jobs | GPU-hours | Cost | Action |
|---|---|---:|---:|---:|---|
| **Paid for, never used** | avg **and** peak SM both exactly 0 | 19,887 | 97,196 | $242,991 | **Cut** |
| **Barely touched** | avg < 5%, peak ≤ 20% | 5,448 | 26,284 | $65,710 | **Cut** |
| Light but real use | avg < 5%, peak > 20% | 4,530 | 59,084 | $147,711 | Keep |
| Moderate use | avg 5–20% | 11,059 | 68,609 | $171,523 | Keep |
| Working hard | avg ≥ 20% | 33,925 | 342,830 | $857,075 | Keep |
| | | **74,849** | **594,004** | **$1,485,010** | |

**$308,700 bought nothing at all.**

### Why we do not add up the findings

The API ships 11,979 findings, each with an `impact_gpu_hours`. Summing that column gives
**931,607 GPU-hours — 157% of a cluster that only ever allocated 594,004.** Twenty-three rules run
over the same telemetry, 18% of flagged jobs trip more than one, and `impact_kind` mixes `lost`,
`consumed` and `unused_capacity`, which are not the same quantity. `impact_scope` mixes
denominators on top of that: a `user`-scope finding covers one person's whole four months and
overlaps every `job`-scope finding beneath it.

So we partition the jobs and use findings as **evidence**, not as arithmetic.

### The threshold that matters

The split between *Barely touched* and *Light but real use* is **peak** SM utilisation at 20%, and
it carries the whole argument. `sm_util_avg` is a lifetime mean: a job that loads data for an hour
and then computes hard reads as a low average. Peak is what separates a card that never worked
from one that did. Both thresholds (5%, 20%) are the ones the shipped rule catalogue already uses —
we invented no numbers.

---

## 2. Where to cut

Bucket A split by how the job ended. Each row is a policy someone owns, not "improve utilisation".

| # | Action | Who owns it | Saves | GPU-hours | Jobs |
|---|---|---|---:|---:|---:|
| 1 | Reclaim idle interactive sessions after 4 hours | Platform team — scheduler policy | $166,928 | 66,771 | 2,881 |
| 2 | Release the card when a job dies on startup | Platform team — scheduler policy | $42,663 | 17,065 | 12,171 |
| 3 | Route CPU-only work off the GPU queue | Research computing — intake | $30,751 | 12,301 | 4,817 |

1. **Idle interactive sessions.** 1,902 `LLSUB:INTERACTIVE` sessions held cards with the GPU at
   zero. 98% of bucket A's hours sit in jobs longer than four hours, so a 4-hour idle timeout
   reaches nearly all of it. Evidence: `rules::idle-interactive-session`,
   `rules::slow-cancel-of-idle-job`, `rules::wallclock-kill`.
2. **Fail fast.** 12,171 jobs failed without ever running a kernel. Most die within seconds; the
   hours are in the minority that sit holding a card after dying. Release the allocation if SM is
   still zero N minutes after start.
3. **Wrong queue.** 4,817 jobs *completed successfully* with the GPU at zero for their whole life.
   That is CPU work that asked for a GPU and got one. Evidence: `rules::gpu-not-needed`.

### Honest coverage

These three policies account for **96,137 of the 123,480 GPU-hours** we call recoverable — 78%.
The remaining **27,343 GPU-hours ($68,358)** sit in *Barely touched*, where we can see the waste
but have not named the mechanism that reclaims it. **Counting only what has a policy behind it,
the number is $240,343 — 16.2% of spend, short of the 20% target.** We report both.

**Nobody is ranked by waste.** Users are hashed in the source and we keep them that way. 57% of
the recoverable hours sit with 10 accounts, which is exactly why three policies reach most of it —
but these are platform policies, not people to chase.

---

## 3. What it costs if we are wrong

### Cutting a job that was working

A policy written as *"kill anything under 5% average utilisation"* is the obvious one and it is
wrong. It would hit **4,530 jobs holding 59,084 GPU-hours — $147,711 of research that did
compute**, at a low duty cycle. That is the cost we deliberately do not incur by requiring peak
≤ 20% as well. The dashboard exposes the threshold as a slider so you can see the trade move.

### Draining machines

The API's own `GET /v1/recommendations` proposes *"drain the top 5 underperforming nodes"* for a
claimed **$57,226**. **We recommend against it.** That ranking comes from
`/v1/resources/underperforming`, which sorts by how many findings name a machine and — by its own
documentation — does not read `rootCauses`. On this cluster the machines with the most findings
are mostly machines where one person ran a broken script repeatedly, or where a Slurm array failed
for reasons unrelated to hardware: those failures spread thinly across many machines, and the
spread is itself the evidence the machines are innocent. `POST /v1/causal` confirms none of it.
Draining 5 machines removes 10 V100s for a quarter of real capacity against evidence that does not
support it.

### The interval, and what we would stake it on

| | GPU-hours | USD |
|---|---:|---:|
| Pessimistic — only jobs that ran literally nothing | 97,196 | $242,991 |
| **Our estimate** | **123,480** | **$308,700** |
| Optimistic — counts light-but-real use too | 182,564 | $456,410 |

- **High confidence** on $242,991: those 19,887 jobs ran no kernel at all, average *and* peak
  exactly zero. There is no reading of that as useful work.
- **Lower confidence** on the 22% coverage gap above.
- **We do not count cancellations as waste.** CANCELLED is 203,930 GPU-hours, more than FAILED and
  TIMEOUT combined. A researcher killing a bad run is good practice. We count only cancelled jobs
  whose GPU never computed. Counting all of it would roughly double the headline and would be
  dishonest.
- **The data is a sample.** MIT states it is not appropriate for estimating system utilisation.
  Every figure describes these 74,849 jobs, not the cluster in general.

---

## What we found that we were not asked for

### The machine nobody marked down

`traps.md` says one machine broke for about a week without the scheduler noticing. We found it
independently: group FAILED jobs on (`primary_node`, `exit_code`), keep signatures shared by ≥ 3
distinct users where one machine holds > 50% of that code's cluster-wide failures. Exactly one
candidate survives.

**`r216287-n200569`**, `exit_code` 34560. Slurm stores exit_code as status << 8, so that is **exit
status 135 — SIGBUS**, a bus error. Three unrelated people hit it 23 + 5 + 86 = **114 times on this
machine and 0 times across 3,917 jobs on every other machine**, over 2026-02-27 to 2026-03-07. In
the trace its two cards show **97% of everything failing** while its rack neighbours sit at 25–55%.

Our method reproduces the shipped `rules::node-hardware-fault` finding exactly — same machine, same
signature, same 114. That is why we report the rationale as a reproducible procedure rather than a
guess. `hardware_attributable_failures = 145`: 31 scheduler-recorded (`hit_node_failure`, on any
attempt) plus these 114. We exclude the other ~18,400 failures because they carry no cross-user,
node-local signature, and attributing them to hardware would overstate what fixing hardware
recovers.

### 121 findings, one problem

The filesystem incident resolves through `POST /v1/causal` to a single volume,
`pvc/scratch-lustre-02` (culprit score 0.88, against 0.31 for every node). **The trap is draining
121 machines; the answer is fixing one volume and draining zero.** It is also the one synthetic
scenario in the corpus, and we label it as such.

### Calibration

`rules::node-job-failure-burst` runs causal analysis over 47 episodes and lands on **undetermined
26, user 20, hardware 1**. The rule documentation says `undetermined` is the most common verdict
and is correct. We take that as a calibration signal: returning a confident cause for all 113
`node-elevated-failure-rate` findings would be overfitting, so we do not.

### The cluster as a trace

We ship the cluster as a Perfetto trace — `pid` = machine, `tid` = card, so **450 tracks**, one
slice per job that held a card, coloured by bucket. 95,005 slices over 125 days. A cut-down version
(64 tracks, 8.4 days, 18 KB) tells the hardware-fault story on its own.

**A gap is not an idle GPU**, and the trace says so in its own metadata. Occupancy is 44% of
nominal, and reading idleness off that would be the obvious mistake: this is a sample, so empty
space means no *sampled* job held that card. `traps.md` is explicit that idle capacity has to come
from gaps in scheduling data — the trace makes those gaps visible without letting you mistake them
for a measurement.

### Live diagnosis, on the API's tools

The last section of the dashboard is a button. Pressing it gathers evidence live from the
MantisGrid AI API — `GET /v1/resources/underperforming`, `POST /v1/events/findings` for each
machine, and `POST /v1/causal` on any finding that carries `rootCauses` — sets it beside the
failure rate we measure ourselves from the scheduler log, and hands it to a GLM model with one
question: which of these machines should actually come out of service.

The evidence is the interesting part, and it is shown verbatim before the model sees it. The
API's eight "worst" machines, followed through `causal`, resolve to **a user's code on seven of
them and the shared storage volume on the eighth — none to the machine itself** — while
`r216287-n200569`, the one machine on the cluster that `causal` does attribute to hardware, is
not in the ranking at all. Ranking by finding count measures how much work a machine received,
not how broken it is; `causal` is what tells them apart, and the model is asked to reason from
that, not from the ranking.

The key comes from the environment (`FEATHERLESS_API_KEY`), so the judges' key drops in with
nothing to edit; without one the button is absent and the rest of the page is unaffected,
because everything else is computed rather than written by a model. The same three endpoints
are the `underperforming`, `list_findings` and `causal` tools in `mcp_layer/server.py`.

### A bug in the challenge

`bin/mantisgrid-generate` **segfaults on roughly half of cold runs** on arm64 under Docker Desktop,
part way through, after printing the shared-dependency line. We hit it on our first run and again
during a fresh-clone rehearsal, where `set -e` aborted the whole bootstrap. It is deterministic
when it completes — `findings.json` comes out byte-identical and matches `data/checksums.txt` — so
`scripts/bootstrap.sh` retries it up to five times, clearing partial output between attempts.

### Layer B, pushed back on

- `/v1/resources/underperforming` ranks by finding count and does not read `rootCauses`, so it
  reads one cause as many problems. `recommendations` then builds on it. Both need to collapse
  correlated findings through `causal` before they rank anything.
- `rules::gpu-pcie-saturated` is armed and has **never fired** — peak observed PCIe is 4,240 MB/s,
  27% of the gen3 x16 link. Data movement is not what holds these GPUs back. If an analysis
  concludes "fix the data pipeline", this silence is the evidence against it.

---

## Running it

```bash
git clone <this repository> && cd MantisAi_Hackathon
make setup          # download + prep + generate + verify checksums
docker compose up   # dashboard :3000, API :8000, JupyterLab :8888
```

`data/` is never committed: the source is CC BY-NC-ND and `docs/submission.md` asks us not to. The
dashboard container builds `out/` itself on first start, so no data derived from the MIT release is
in the repository and `docker compose up` still comes up unattended.

Verified end to end from a clean `git clone` into an empty directory.

## Reproducing the numbers

```bash
docker compose run --rm prep python scripts/spine_check.py
```

Prints every figure in sections 1–3 and section "What we found". The bucket totals must sum to
594,004 GPU-hours across 74,849 jobs; A = 97,196, B1 = 26,284, B2 = 59,084, C = 68,609,
D = 342,830.
