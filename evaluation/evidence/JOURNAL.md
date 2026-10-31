# Evidence journal — AI/agent involvement in development

Human-readable view of `log.jsonl`. Entries are append-only; never edit or
reorder previous entries. See `evaluation/evidence/README.md` for the schema.

## EV-0001 — 2026-10-31T14:43:14+08:00

- **Actor:** `ai:glm-5.3` (human reviewed: yes)
- **Task:** Build the AI-usage evidence harness (agent docs + journal) before starting eval-framework work
- **Outcome:** Created AGENTS.md and CLAUDE.md at repo root, evaluation/evidence/{record.py,README.md}, added 'make evidence' target. Recorder tested and first entry recorded.
- **Git:** `codex/evaluation-framework` @ `4db38e422090` (dirty tree)
- **Files:** `AGENTS.md`, `CLAUDE.md`, `evaluation/evidence/record.py`, `evaluation/evidence/README.md`, `Makefile`
- **Commands:** git checkout codex/evaluation-framework
