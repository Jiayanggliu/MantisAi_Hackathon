# Dashboard Is All You Need

**MantisGrid Hackathon 2026 — Track 2, cluster efficiency.**

> Cut **$308,700** — 21% of GPU spend — without touching a single job that was doing work.

Four months of MIT SuperCloud: 225 machines, 74,849 jobs, 195 researchers, 594,004 GPU-hours,
$1,485,010 at $2.50/GPU-hour.

[**REPORT.md**](REPORT.md) is the writeup. [**claims.json**](claims.json) is the numbers.

## Run it

```bash
make setup          # download the raw data, build the tables, verify checksums (~2 min)
docker compose up   # dashboard :3000, API :8000, JupyterLab :8888
```

Then open **http://localhost:3000**.

`data/` is not in this repository: the MIT release is CC BY-NC-ND and `docs/submission.md` asks us
not to commit anything derived from it. `make setup` generates it locally and checks all five files
against `data/checksums.txt`. The dashboard container builds `out/` itself on first start, so
`docker compose up` is still one unattended command.

> `bin/mantisgrid-generate` (shipped with the challenge) segfaults on roughly half of cold runs on
> arm64. `scripts/bootstrap.sh` retries it; it is deterministic when it completes.

## Live diagnosis (optional — needs a Featherless key)

The bottom of the dashboard has a **Run live diagnosis** button. It gathers evidence live from
the MantisGrid AI API — the ranking of underperforming machines, the findings on each, what
`POST /v1/causal` resolves them to — puts it beside the failure rate we measure from the
scheduler log, and hands the lot to a GLM model, which says which machines should actually come
out of service.

The model runs on [Featherless](https://featherless.ai). The key is read from the environment,
never from the repository, so use your own:

```bash
export FEATHERLESS_API_KEY=...                        # required for the button
export FEATHERLESS_MODEL=zai-org/GLM-4.7-Flash        # optional; this is the default
export FEATHERLESS_BASE_URL=https://api.featherless.ai/v1   # optional; this is the default
docker compose up
```

`docker-compose.yml` passes those three variables through to the dashboard container. **Without
the key the button is simply absent and everything else on the page works** — the three tiles
and the evidence behind them are computed from the API and the data, not written by a model.
A busy model comes back as HTTP 200 with an `error` body; the client checks for that, and the
page shows a warning rather than failing.

## What's here

| | |
|---|---|
| `dashboard/` | the three tiles, Streamlit, served on `:3000` |
| `analysis.py` | the mutually exclusive job partition → `out/analysis.json` |
| `scripts/make_trace.py` | the cluster as a Perfetto trace, 450 tracks |
| `scripts/spine_check.py` | reproduces every number in the report, one command |
| `scripts/bootstrap.sh` | what `make setup` runs |
| `dashboard/agent.py` | the live-diagnosis model call (Featherless, key from the environment) |
| `docs/team/FINDINGS.md` | the working notes behind the report |
| `api/`, `mcp_layer/`, `starter/`, `docs/` | the challenge's own scaffolding, unchanged |

## AI disclosure

This project was built with heavy AI assistance, as the challenge expects.

**Models and tools.** Built with Claude Opus 5 and Claude Fable 5.1, via Claude Code (Anthropic's
CLI, running in the Claude desktop app). At runtime, the optional live-diagnosis button calls
`zai-org/GLM-4.7-Flash` on Featherless (overridable with `FEATHERLESS_MODEL`); nothing else on
the page is model-generated. No other AI models, coding assistants or agent frameworks were used.

**What the AI wrote.** Substantially all of the code in this repository that is ours:
`dashboard/app.py`, `scripts/make_trace.py`, `scripts/bootstrap.sh`, `scripts/spine_check.py`,
`claims.json`, `REPORT.md`, `docs/team/`, and this README. `analysis.py` and
`notebooks/exploration.ipynb` were written by a team member working with the same assistant against
a written specification (`docs/team/01-headline-buckets.md`, itself AI-drafted).

**What the team did.** Chose the track and the framing; set the direction at every step and
redirected it when it drifted off the brief; decided that no data derived from the MIT release
would be committed; named the project; reviewed and accepted or rejected each change. Every number
reported was cross-checked by two independent implementations before it was published — that check
is what caught a broken data-preparation script whose output disagreed with the challenge's own
published cluster total.

**Not ours.** `api/`, `mcp_layer/`, `starter/`, `docs/api.md`, `docs/data.md`, `docs/rules.md`,
`docs/traps.md`, `docs/submission.md`, `bin/`, the `Makefile` (except its `setup` target) and
`scripts/prep_data.py`, `scripts/checksum_data.py`, `scripts/validate_submission.py` ship with the
challenge and are unmodified.

## Data attribution

Workload telemetry is MIT SuperCloud TX-GAIA, HPCA'22 release, licensed
[CC BY-NC-ND 4.0](http://creativecommons.org/licenses/by-nc-nd/4.0/). See
[`ATTRIBUTION.md`](ATTRIBUTION.md). The data is a **sample** of the cluster's workload; MIT states
it is not appropriate for estimating system utilisation, and every figure here describes these
74,849 jobs rather than the cluster in general.
