#!/usr/bin/env python3
"""Append an evidence-journal entry for AI/agent-assisted work.

Usage (from repo root):
    python evaluation/evidence/record.py \
        --actor ai:glm-5.3 \
        --task "Build evidence harness" \
        --outcome "Added AGENTS.md, CLAUDE.md, recorder" \
        --files AGENTS.md CLAUDE.md \
        --commands "git checkout -b codex/evaluation-framework" \
        --reviewed

Writes one JSON line to evaluation/evidence/log.jsonl (append-only) and one
section to evaluation/evidence/JOURNAL.md. Both files are committed; the
entry id printed on stdout (EV-NNNN) should be referenced in the commit
message. Stdlib only; runs on Windows and Linux.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).resolve().parent
LOG = EVIDENCE_DIR / "log.jsonl"
JOURNAL = EVIDENCE_DIR / "JOURNAL.md"
REPO_ROOT = EVIDENCE_DIR.parents[1]

JOURNAL_HEADER = """# Evidence journal — AI/agent involvement in development

Human-readable view of `log.jsonl`. Entries are append-only; never edit or
reorder previous entries. See `evaluation/evidence/README.md` for the schema.
"""


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _local_timestamp() -> str:
    offset = datetime.now().astimezone().strftime("%z")  # +0800
    offset = f"{offset[:3]}:{offset[3:]}" if offset else "Z"
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds").replace("+00:00", offset if offset != "Z" else "+00:00")


def next_id() -> str:
    highest = 0
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8").splitlines():
            try:
                highest = max(highest, int(json.loads(line).get("id", "EV-0")[3:]))
            except (ValueError, json.JSONDecodeError):
                continue
    return f"EV-{highest + 1:04d}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Record an evidence-journal entry.")
    parser.add_argument("--actor", required=True,
                        help="human | ai:<model> | hybrid")
    parser.add_argument("--task", required=True, help="what was asked / attempted")
    parser.add_argument("--outcome", required=True, help="what actually happened")
    parser.add_argument("--files", nargs="*", default=[], help="files touched")
    parser.add_argument("--commands", nargs="*", default=[], help="notable commands run")
    parser.add_argument("--reviewed", action="store_true",
                        help="a human reviewed the result of this work")
    parser.add_argument("--notes", default="", help="optional free-text notes")
    args = parser.parse_args()

    if not args.actor.strip():
        parser.error("--actor must not be empty")

    entry = {
        "id": next_id(),
        "timestamp": _local_timestamp(),
        "actor": args.actor,
        "task": args.task,
        "outcome": args.outcome,
        "files": args.files,
        "commands": args.commands,
        "reviewed_by_human": args.reviewed,
        "git": {
            "branch": _git(["branch", "--show-current"]) or None,
            "sha": _git(["rev-parse", "HEAD"]) or None,
            "dirty": bool(_git(["status", "--porcelain"])),
        },
    }
    if args.notes:
        entry["notes"] = args.notes

    with LOG.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    if not JOURNAL.exists():
        JOURNAL.write_text(JOURNAL_HEADER, encoding="utf-8")
    review = "yes" if args.reviewed else "**NO**"
    section = (
        f"\n## {entry['id']} — {entry['timestamp']}\n\n"
        f"- **Actor:** `{entry['actor']}` (human reviewed: {review})\n"
        f"- **Task:** {entry['task']}\n"
        f"- **Outcome:** {entry['outcome']}\n"
        f"- **Git:** `{entry['git']['branch']}` @ `{(entry['git']['sha'] or '')[:12]}`"
        f"{'' if entry['git']['dirty'] is False else ' (dirty tree)'}\n"
    )
    if entry["files"]:
        section += f"- **Files:** {', '.join(f'`{f}`' for f in entry['files'])}\n"
    if entry["commands"]:
        section += f"- **Commands:** {'; '.join(entry['commands'])}\n"
    if args.notes:
        section += f"- **Notes:** {args.notes}\n"
    with JOURNAL.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(section)

    print(entry["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
