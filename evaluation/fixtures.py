"""Synthetic fixtures with known expected outcomes, checked by ``make eval``.

Every number asserted in selfchecks is derived by hand from these fixtures —
they are constructed so the expected counts are unambiguous. These are
coverage requirements from evaluation/README.md: missed issues, false alerts,
duplicates, healthy cases, abstentions, unknown labels, and empty
denominators.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

UTC = timezone.utc


def _t(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, 0, tzinfo=UTC)


# --- Detection: predictions vs reviewed reference issues -------------------
# Expected by hand: P0<->R0 TP, P1 duplicate of R0, P2<->R1 TP, P3 false
# alert (gpu-9 has no reviewed issue), R2 missed (no prediction).
# => TP=2, FP=2 (P3 + duplicate P1), FN=1; precision=2/4, recall=2/3.

REFERENCE_ISSUES: list[dict[str, Any]] = [
    {"issue_type": "idle_allocation", "resource": "gpu-7",
     "start": _t(10), "end": _t(11)},
    {"issue_type": "shared_storage_slowdown", "resource": "storage-a",
     "start": _t(12), "end": _t(13)},
    {"issue_type": "node_local_fault", "resource": "gpu-3",
     "start": _t(14), "end": _t(15)},
]

PREDICTED_ISSUES: list[dict[str, Any]] = [
    # TP: matches R0 within tolerance
    {"issue_type": "idle_allocation", "resource": "gpu-7",
     "start": _t(10) + timedelta(minutes=5), "end": _t(11) - timedelta(minutes=5)},
    # duplicate alert on the already-matched R0
    {"issue_type": "idle_allocation", "resource": "gpu-7",
     "start": _t(10) + timedelta(minutes=10), "end": _t(11) - timedelta(minutes=10)},
    # TP: matches R1
    {"issue_type": "shared_storage_slowdown", "resource": "storage-a",
     "start": _t(12), "end": _t(13)},
    # false alert: gpu-9 has no reviewed issue anywhere near this window
    {"issue_type": "idle_allocation", "resource": "gpu-9",
     "start": _t(9), "end": _t(10)},
    # note: no prediction for R2 (node fault on gpu-3) => missed issue (FN)
]

DETECTION_EXPECTED = {"tp": 2, "fp": 2, "fn": 1, "duplicates": 1}

# Empty inputs: both metrics must report unavailable (zero denominators),
# never a perfect score.
EMPTY_PREDICTIONS: list[dict[str, Any]] = []
EMPTY_REFERENCES: list[dict[str, Any]] = []


# --- Root cause -------------------------------------------------------------
# Expected by hand: determinate cases C0-C2; C0 correct; C1 wrong cause;
# C2 not detected => incorrect. Overall 1/3. Conditional (detected C0,C1)
# 1/2. C3 unknown-label acknowledged; C4 unknown-label invented diagnosis.

ROOT_CAUSE_CASES: list[dict[str, Any]] = [
    {"case_id": "C0", "expected_cause": "storage_io", "expected_resource": "storage-a",
     "predicted_cause": "storage_io", "predicted_resource": "storage-a", "detected": True},
    {"case_id": "C1", "expected_cause": "thermal_throttle", "expected_resource": "gpu-3",
     "predicted_cause": "idle_allocation", "predicted_resource": "gpu-3", "detected": True},
    {"case_id": "C2", "expected_cause": "thermal_throttle", "expected_resource": "gpu-4",
     "predicted_cause": None, "predicted_resource": None, "detected": False},
    {"case_id": "C3", "expected_cause": None, "expected_resource": None,
     "predicted_cause": None, "predicted_resource": None, "detected": False},
    {"case_id": "C4", "expected_cause": None, "expected_resource": None,
     "predicted_cause": "network_contention", "predicted_resource": "switch-1",
     "detected": True},
]

ROOT_CAUSE_EXPECTED = {"overall": (1, 3), "conditional": (1, 2),
                       "unknown_cases": 2, "acknowledged": 1, "invented": 1}


# --- Recommendations ----------------------------------------------------------
# Expected by hand: A0 pass; A1 healthy pass (explicit no-op acceptable);
# A2 fail (required action not covered); A3 fail + harmful listed;
# A4 fail (requires action, proposes nothing); A5 not scored.
# => acceptable rate 2/5, one harmful proposal entry.

ACTION_CASES: list[dict[str, Any]] = [
    {"case_id": "A0", "required_actions": ["drain_node"],
     "acceptable_actions": ["drain_node", "investigate"],
     "harmful_actions": ["terminate_job"],
     "proposed_actions": ["drain_node"], "requires_action": True,
     "evidence": "reviewed: gpu-7 hardware fault requires drain"},
    {"case_id": "A1", "required_actions": [],
     "acceptable_actions": ["no_action", "investigate"],
     "harmful_actions": ["drain_node"],
     "proposed_actions": [], "requires_action": False,
     "evidence": "reviewed healthy: bursty but legitimate workload"},
    {"case_id": "A2", "required_actions": ["migrate_job"],
     "acceptable_actions": ["migrate_job", "investigate"],
     "harmful_actions": ["drain_node"],
     "proposed_actions": ["investigate"], "requires_action": True,
     "evidence": "reviewed: job must move off degraded node"},
    {"case_id": "A3", "required_actions": [],
     "acceptable_actions": ["no_action", "investigate"],
     "harmful_actions": ["terminate_job", "drain_node"],
     "proposed_actions": ["terminate_job"], "requires_action": False,
     "evidence": "reviewed healthy: terminating wastes useful work"},
    {"case_id": "A4", "required_actions": [],
     "acceptable_actions": ["investigate"],
     "harmful_actions": [],
     "proposed_actions": [], "requires_action": True,
     "evidence": "reviewed: action required, empty response is not a no-op"},
    {"case_id": "A5", "acceptable_actions": None, "proposed_actions": [],
     "requires_action": False, "evidence": "no reviewed action expectation"},
]

ACTIONS_EXPECTED = {"pass": 2, "fail": 3, "harmful_entries": 1}
