# CLAUDE.md

This project's agent instructions live in [`AGENTS.md`](AGENTS.md) — read and
follow that file. Summary of the non-negotiables:

1. Record every AI-assisted unit of work in the evidence journal
   (`python evaluation/evidence/record.py ...`) before committing.
2. Never fabricate numbers; verify against files/commands you actually ran.
3. Run `make validate` / `make eval` before committing; report honestly if
   you cannot.
4. Work on feature branches, never `main`.
