# AGENTS.md — working guide for AI agents in this repository

Any AI coding agent (Claude Code, Codex, Cursor, Copilot, this DSH session, …)
working in this repo must read this file first and follow it. `CLAUDE.md` and
other tool-specific instruction files point here; this file is canonical.

## What this repo is

Track-2 hackathon project: cluster-efficiency analysis of GPU telemetry.
`analysis.py` builds dashboard data from `data/prepped/*.parquet` into `out/`;
`api/` is a FastAPI service; `dashboard/` serves it; `claims.json` is the
submission artifact whose numbers must stay reproducible.

## Ground rules

1. **Never fabricate numbers.** Every figure you write must come from a file
   you have actually read or a command you have actually run. If you cannot
   verify it, say so.
2. **`make validate` and `make eval` must pass** before you commit. If you
   cannot run them, say why instead of claiming success.
3. **Do not commit anything under `data/` derived from the gated MIT release**
   or under `out/` (generated). `data/checksums.txt` and `data/README.md` are
   the exceptions.
4. **Branches:** work happens on feature branches (`codex/<topic>` or
   `<agent>/<topic>`), merged to `main` via PR. Never commit to `main`.
5. **Keep changes reviewable:** small commits, clear messages, no drive-by
   refactors unrelated to the task.

## Evidence protocol (required)

This repository keeps an auditable record of AI/agent involvement in
development. **Every AI-assisted unit of work gets a journal entry before it
is committed.**

- Record entries with:
  `python evaluation/evidence/record.py --actor ai:<model> --task "<what was asked>" --outcome "<what happened>" [--files f1 f2] [--commands "cmd"] [--reviewed]`
- or via `make evidence ACTOR=... TASK=... OUTCOME=...`
- Entries capture timestamp, git branch/SHA, actor (`human` / `ai:<model>` /
  `hybrid`), task, outcome, files touched, and whether a human reviewed.
- Storage: `evaluation/evidence/JOURNAL.md` (human-readable) and
  `evaluation/evidence/log.jsonl` (append-only, machine-readable). Both are
  committed — reviewers see the trail in the PR.
- See `evaluation/evidence/README.md` for the full schema.

If you are an agent making a commit, the commit message should reference the
journal entry id (e.g. `EV-0007`).

## Evaluation modes (being built)

| Command | What it runs | Prerequisites |
|---|---|---|
| `make eval` | Deterministic checks on synthetic fixtures | None (offline, hermetic) |
| `make eval-data` | Checks against prepared telemetry | `data/prepped/*.parquet` |
| `make eval-live` | Real model evaluation | Credentials + prepped data |

A data or live run must **fail clearly** when prerequisites are missing —
never silently fall back to mocks.

## Windows note

Development happens on Windows. Anything under `evaluation/` must be
invokable both via `make` and directly via `python -m` / `python <script>`
so Linux CI and local runs behave identically.
