"""The LLM half of the triage agent.

Reads its key and endpoint from the environment, never from the repository: the
judges swap in their own key, and a hard-coded one fails there.
"""
from __future__ import annotations

import os
import requests

BASE = os.environ.get("FEATHERLESS_BASE_URL", "https://api.featherless.ai/v1")
# Flash: a call like this costs cents. Overridable so a judge can point at a
# bigger model without editing anything.
MODEL = os.environ.get("FEATHERLESS_MODEL", "zai-org/GLM-4.7-Flash")

SYSTEM = """You are an SRE triaging GPU cluster machines for a capacity review.

You are given, for each machine: how many findings the MantisGrid AI API raised
against it, what that API's causal analysis resolved those findings to, and the
machine's real failure rate measured independently from the scheduler log.

Your job is to say which machines should actually be taken out of service.

Hold to these:
- A high finding count is not evidence of a fault. A machine that receives a lot
  of work, or that one person ran a broken script on repeatedly, collects many
  findings while being perfectly healthy.
- Evidence of a fault is a failure signature shared by several unrelated people
  on one machine and absent elsewhere.
- Draining a healthy machine destroys real capacity. Say so when the evidence
  does not support it.
- "Cannot determine from this" is a correct answer. Prefer it to a confident guess.
- Never blame a named account. Accounts are hashed and this review is about
  capacity, not people.

Answer in under 180 words: which machine to drain if any, which to leave, and the
one sentence of evidence behind each call."""


def available() -> bool:
    return bool(os.environ.get("FEATHERLESS_API_KEY"))


def triage(evidence: str, timeout: int = 90) -> tuple[str, str]:
    """Return (answer, model). Raises RuntimeError with a readable message."""
    key = os.environ.get("FEATHERLESS_API_KEY")
    if not key:
        raise RuntimeError("FEATHERLESS_API_KEY is not set in this container's environment.")

    r = requests.post(
        f"{BASE}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": MODEL, "max_tokens": 700, "temperature": 0.2,
              "messages": [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": evidence}]},
        timeout=timeout,
    )
    # A busy model answers 200 with an error body, so the status code is not
    # enough -- check for `error` before touching `choices`.
    try:
        body = r.json()
    except ValueError:
        raise RuntimeError(f"HTTP {r.status_code}, and the body was not JSON.")
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        raise RuntimeError(str(err.get("message", err)) if isinstance(err, dict) else str(err))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {str(body)[:200]}")
    try:
        return body["choices"][0]["message"]["content"].strip(), MODEL
    except (KeyError, IndexError):
        raise RuntimeError(f"No completion in the response: {str(body)[:200]}")
