# Evidence journal — AI/agent involvement

This directory is the auditable record of AI and agent usage during
development of this repository. Every AI-assisted unit of work gets an entry
**before it is committed**; commit messages reference the entry id.

## Recording an entry

```sh
python evaluation/evidence/record.py \
    --actor ai:<model>            # or "human" or "hybrid"
    --task "<what was asked>"
    --outcome "<what actually happened>"
    --files <paths...>            # optional
    --commands "<notable commands>"  # optional
    --reviewed                    # if a human reviewed the result
# or:
make evidence ACTOR=ai:glm-5.3 TASK="..." OUTCOME="..."
```

The command prints the entry id (`EV-NNNN`); put it in the commit message.

## Files

- `log.jsonl` — append-only machine-readable record (one JSON object per line).
- `JOURNAL.md` — human-readable rendering, regenerated per entry.
- `record.py` — the recorder (stdlib only, Windows/Linux).

## Entry schema

| Field | Meaning |
|---|---|
| `id` | Monotonic `EV-NNNN` |
| `timestamp` | ISO 8601 with local offset |
| `actor` | `human`, `hybrid`, or `ai:<model>` |
| `task` / `outcome` | What was asked; what actually happened |
| `files` / `commands` | Files touched; notable commands run |
| `reviewed_by_human` | Whether a human reviewed the result |
| `git.branch` / `git.sha` / `git.dirty` | Repo state at recording time |
| `notes` | Optional free text |

## Rules

1. Entries are append-only. Never edit, reorder, or delete an entry; correct
   mistakes with a follow-up entry.
2. `--actor` must name the actual model for AI work (e.g. `ai:glm-5.3`).
3. `reviewed_by_human` is false until a person has actually inspected the
   result — do not pre-mark it.
