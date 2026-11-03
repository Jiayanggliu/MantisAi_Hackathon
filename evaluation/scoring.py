"""Scoring primitives for detection, root-cause, and action quality.

Implements the metric definitions from evaluation/README.md sections 2-5:

- Detection: 1:1 prediction/reference matching with a documented contract,
  precision and recall with explicit "unavailable" on zero denominators,
  duplicate alerts reported separately (they count as unmatched predictions).
- Root cause: correct cause AND causal resource over all determinate cases;
  a conditional (detected-only) score is labeled secondary.
- Actions: a case passes only when required actions are covered, every
  proposed action is acceptable, and none is harmful; harmful proposals are
  always listed with evidence.

All functions are pure and deterministic: they take plain data and return
plain data, so they can be checked against synthetic fixtures offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Iterable, Mapping, Sequence

# A prediction or reference issue. Times are datetime objects (UTC expected).
# The matching contract: same issue type, same resource, and temporal overlap
# within `tolerance` of each other's window.
Issue = Mapping[str, Any]


@dataclass(frozen=True)
class MatchResult:
    tp: list[tuple[int, int]]  # (prediction_index, reference_index) pairs
    unmatched_predictions: list[int]  # false positives (incl. duplicates)
    unmatched_references: list[int]  # false negatives (missed issues)
    duplicate_predictions: list[int]  # extra alerts on an already-matched ref


def _overlaps_within_tolerance(pred: Issue, ref: Issue, tolerance: timedelta) -> bool:
    p_start, p_end = pred["start"], pred["end"]
    r_start, r_end = ref["start"], ref["end"]
    return p_start <= r_end + tolerance and r_start <= p_end + tolerance


def match_issues(
    predictions: Sequence[Issue],
    references: Sequence[Issue],
    tolerance: timedelta = timedelta(minutes=10),
) -> MatchResult:
    """Match predictions to reviewed reference issues 1:1.

    Contract: a prediction matches a reference when issue type and resource
    are equal and their time windows overlap within ``tolerance``. Each
    prediction matches at most one reference and vice versa. A prediction
    that only matches an already-matched reference is a duplicate: it is
    counted in ``duplicate_predictions`` and in ``unmatched_predictions``
    (duplicates are never true positives).
    """
    used_refs: set[int] = set()
    tp: list[tuple[int, int]] = []
    unmatched_predictions: list[int] = []
    duplicates: list[int] = []
    for p_idx, pred in enumerate(predictions):
        best_ref = None
        for r_idx, ref in enumerate(references):
            if r_idx in used_refs:
                continue
            if (
                pred["issue_type"] == ref["issue_type"]
                and pred["resource"] == ref["resource"]
                and _overlaps_within_tolerance(pred, ref, tolerance)
            ):
                best_ref = r_idx  # deterministic: first unused match in order
                break
        if best_ref is not None:
            used_refs.add(best_ref)
            tp.append((p_idx, best_ref))
        else:
            # Distinguish duplicates: does it overlap any *already-used* ref?
            is_duplicate = any(
                pred["issue_type"] == references[r]["issue_type"]
                and pred["resource"] == references[r]["resource"]
                and _overlaps_within_tolerance(pred, references[r], tolerance)
                for r in used_refs
            )
            (duplicates if is_duplicate else unmatched_predictions).append(p_idx)
    unmatched_references = [r for r in range(len(references)) if r not in used_refs]
    # Duplicates count as unmatched predictions too (README section 2).
    return MatchResult(tp, unmatched_predictions + [], unmatched_references, duplicates)


@dataclass(frozen=True)
class Rate:
    """A rate with its raw counts; value is None when the denominator is 0.

    A zero denominator means "unavailable", never a perfect score.
    """

    value: float | None
    numerator: int
    denominator: int
    notes: tuple[str, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "status": "unavailable" if self.denominator == 0 else "measured",
            "notes": list(self.notes),
        }


def _rate(numerator: int, denominator: int, notes: Iterable[str] = ()) -> Rate:
    value = (numerator / denominator) if denominator else None
    return Rate(value, numerator, denominator, tuple(notes))


def precision_recall(result: MatchResult) -> tuple[Rate, Rate]:
    """Precision = TP/(TP+FP); recall = TP/(TP+FN) over matched 1:1 pairs."""
    tp = len(result.tp)
    fp = len(result.unmatched_predictions) + len(result.duplicate_predictions)
    fn = len(result.unmatched_references)
    notes = (
        [f"{len(result.duplicate_predictions)} duplicate prediction(s) counted as unmatched"]
        if result.duplicate_predictions
        else ()
    )
    return _rate(tp, tp + fp, notes), _rate(tp, tp + fn)


# --- Root cause -----------------------------------------------------------


@dataclass(frozen=True)
class RootCauseResult:
    overall: Rate  # correct cause+resource / determinate reviewed cases
    conditional_on_detection: Rate  # secondary score, detected cases only
    unknown_label_cases: int  # genuinely uncertain cause, excluded above
    acknowledged_unknown: int  # of those, system said "insufficient evidence"
    invented_diagnosis_on_unknown: int  # system diagnosed despite unknown label


def root_cause_accuracy(cases: Sequence[Mapping[str, Any]]) -> RootCauseResult:
    """Score cause and causal resource against reviewed determinate labels.

    ``cases`` items carry: expected_cause (None = unknown label),
    expected_resource, predicted_cause (None = no diagnosis / abstained),
    predicted_resource, detected (bool). A missed detection or missing
    diagnosis counts as incorrect in the overall denominator.
    """
    determinate = [c for c in cases if c.get("expected_cause") is not None]
    unknown = [c for c in cases if c.get("expected_cause") is None]
    correct = sum(
        1
        for c in determinate
        if c.get("detected")
        and c.get("predicted_cause") == c["expected_cause"]
        and c.get("predicted_resource") == c["expected_resource"]
    )
    detected_determinate = [c for c in determinate if c.get("detected")]
    correct_detected = sum(
        1
        for c in detected_determinate
        if c.get("predicted_cause") == c["expected_cause"]
        and c.get("predicted_resource") == c["expected_resource"]
    )
    return RootCauseResult(
        overall=_rate(correct, len(determinate)),
        conditional_on_detection=_rate(correct_detected, len(detected_determinate),
                                       notes=("secondary: restricted to detected cases",)),
        unknown_label_cases=len(unknown),
        acknowledged_unknown=sum(1 for c in unknown if c.get("predicted_cause") is None),
        invented_diagnosis_on_unknown=sum(1 for c in unknown if c.get("predicted_cause") is not None),
    )


# --- Recommendations -------------------------------------------------------


@dataclass(frozen=True)
class ActionResult:
    acceptable_rate: Rate  # passing cases / cases with reviewed expectations
    passed: list[int]
    failed: list[int]
    harmful: list[dict[str, Any]]  # every harmful proposal, with case evidence


def score_actions(cases: Sequence[Mapping[str, Any]]) -> ActionResult:
    """Score complete proposed action sets against reviewed expectations.

    ``cases`` items carry: required_actions, acceptable_actions, harmful_actions
    (sets/lists of action labels; exact-label matching — a documented review
    rubric may alias equivalents when real benchmarks arrive), proposed_actions
    (what the system proposed), requires_action (bool). A case passes when all
    required actions are proposed, every proposed action is acceptable, and no
    proposed action is harmful. A case that requires action but proposes
    nothing fails; an explicit "no_action" proposal is acceptable only when it
    is listed in acceptable_actions.
    """
    passed: list[int] = []
    failed: list[int] = []
    harmful: list[dict[str, Any]] = []
    scored = 0
    for idx, case in enumerate(cases):
        expected = case.get("acceptable_actions")
        if expected is None:  # no reviewed action expectation: not scored
            continue
        scored += 1
        required = set(case.get("required_actions", ()))
        acceptable = set(expected)
        harmful_set = set(case.get("harmful_actions", ()))
        proposed = set(case.get("proposed_actions", ()))
        case_harmful = sorted(proposed & harmful_set)
        if case_harmful:
            harmful.append({
                "case_index": idx,
                "actions": case_harmful,
                "evidence": case.get("evidence", ""),
            })
        ok = (
            required <= proposed
            and proposed <= acceptable
            and not case_harmful
            and not (case.get("requires_action") and not proposed)
        )
        (passed if ok else failed).append(idx)
    return ActionResult(_rate(len(passed), scored), passed, failed, harmful)
