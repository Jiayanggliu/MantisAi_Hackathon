# Evaluation framework: implementation brief

## Purpose and status

Build an evaluation framework that answers five questions:

1. Is there enough trustworthy telemetry?
2. Are the problems reported by the system real?
3. Are important problems being missed?
4. Does the system identify the right cause?
5. Does it recommend a sensible action?

This README is the agreed starting scope for implementation by DeepSeek, GLM,
or another coding agent. It describes intended behavior, not measured results
or a claim that these features already exist. Read the repository's AGENTS.md
before implementing.

The existing framework contains synthetic analysis checks, a telemetry headline
reproduction check, and an unimplemented live mode. Inspect that code before
extending it. Keep the reproducibility checks, but report them separately from
data quality and system performance.

## Initial metrics

| Evaluation question | Core metric | Why it matters |
|---|---|---|
| Is the data trustworthy? | Telemetry coverage; missing/invalid-record rate | Missing measurements can make an active GPU look idle. |
| Are reported problems real? | Detection precision | False findings waste investigation time and can trigger unnecessary actions. |
| Are problems being missed? | Detection recall | A system can report convincing findings while overlooking genuine faults. |
| Is the cause correct? | Root-cause accuracy | Slow jobs may be caused by shared storage rather than the compute nodes. |
| Is the advice sensible? | Acceptable-action rate; harmful actions listed separately | A correct finding can still lead to an unnecessary drain or termination. |

### 1. Data quality

Evaluate both source telemetry and the prepared tables used by the system.
Inspect the actual schemas and documented measurement semantics before writing
validation rules; do not assume column names, sampling intervals, or units.

Report:

- Missing-value counts and rates for each required field.
- Invalid-record count and rate: a record with one or more schema, range,
  identity, or consistency violations. Count each affected record once in the
  total and also break down violations by reason.
- Telemetry coverage: observed valid GPU sampling intervals divided by expected
  GPU sampling intervals during the evaluation window. Deduplicate overlapping
  observations and document how expected intervals are obtained from allocation
  records and the sampling schedule.
- Job coverage: eligible jobs with usable telemetry divided by all eligible jobs.

Missingness and invalid-record rates use all input records as their denominator,
before filtering. Publish the eligibility and usability rules and the number of
excluded records. Never silently drop records to improve a quality score.

If expected sampling intervals cannot be established, mark interval coverage
unavailable and explain why; job coverage is a separate measurement, not a
substitute for temporal coverage. Distinguish measured zero utilization from
absent telemetry. Show affected jobs/resources and, where computable, GPU-hours.

### 2. Detection precision

Precision = TP / (TP + FP).

A true positive (TP) is a predicted issue matched to an independently reviewed
issue. A false positive (FP) is an unmatched prediction within the benchmark's
fully reviewed scope.

Define the matching contract before scoring: issue type, affected resource,
evaluation window, and any permitted time tolerance. Match one prediction to at
most one reference issue and vice versa. Report duplicate alerts separately;
extra duplicate predictions count as unmatched predictions.

### 3. Detection recall

Recall = TP / (TP + FN).

A false negative (FN) is a reviewed issue with no matching prediction. Use the
same matching contract as precision. Report precision and recall together, both
overall and by issue type. Include reviewed healthy cases to expose false alarms.

If a denominator is zero, report the metric as unavailable with its counts,
rather than assigning a perfect score. Unreviewed outcomes are unknown, not
negative labels. An abstention on a known issue leaves that issue missed for
recall; also report abstention counts.

### 4. Root-cause accuracy

Root-cause accuracy = cases with both the correct cause and correct causal
resource / all benchmark cases with a reviewed, determinate root cause.

Score the complete system response against the reviewed cause and resource.
A missing diagnosis or missed detection counts as incorrect in this denominator.
Any diagnostic score restricted to successfully detected cases must be labeled
as a secondary, conditional score.

Cases whose cause is genuinely uncertain are reported separately. Review whether
the system acknowledges insufficient evidence rather than inventing a diagnosis.
Do not use the API's own causal output as independent ground truth.

### 5. Recommendation quality

Acceptable-action rate = cases whose complete proposed action set is acceptable
/ all benchmark cases with reviewed action expectations.

Define acceptable actions, required actions, and explicitly harmful actions for
each case. A case passes when required actions are covered, all proposed actions
are acceptable, and none is harmful. Allow equivalent actions through a
documented review rubric rather than requiring exact wording.

Explicit "no action" or "investigate further" can be correct for a healthy or
ambiguous case. A missing response is not automatically an acceptable no-op.
A case requiring action fails if the system proposes nothing.

List every harmful recommendation with its evidence, regardless of the overall
acceptable-action rate. Examples include draining healthy nodes or terminating
useful work based on unsupported attribution. For free-text outputs, preserve
human review decisions; an automated judge's opinion is not ground truth.

## Benchmark requirements

Create reviewed cases containing:

- Case ID, dataset/version reference, and evaluation window.
- Scope: the jobs/resources and issue types reviewed.
- Input evidence available to the system.
- Expected issues, or an explicit reviewed healthy label.
- Expected root cause and causal resource, or an explicit unknown label.
- Acceptable, required, and harmful actions.
- Evidence supporting the labels and their review status.

Include idle allocations, legitimate bursty workloads, cancelled jobs that did
useful work, shared storage incidents, node-local faults, and ambiguous cases.
These are coverage requirements, not claims that those cases have been labeled.

Synthetic cases check known behavior and deliberately damaged inputs. Reviewed
real cases measure performance on the dataset. Report those results separately.
Never copy system predictions into expected answers. Keep tuning cases separate
from held-out evaluation cases and record benchmark versions.

Do not fabricate labels to make live evaluation runnable. Where labels or data
are missing, fail clearly or report the specific metric as unavailable.
Do not commit benchmark evidence derived from the gated MIT data.

## Execution modes

Preserve the commands in AGENTS.md and support Windows and Linux:

| Command | Direct invocation | Intended responsibility |
|---|---|---|
| make eval | python -m evaluation eval | Offline deterministic checks of analysis and evaluator behavior using synthetic fixtures |
| make eval-data | python -m evaluation eval-data | Real telemetry quality report and existing claims reproducibility checks |
| make eval-live | python -m evaluation eval-live | Run the actual system on reviewed benchmark cases and score detection, diagnosis, and actions |

Live evaluation must invoke the actual analysis flow being evaluated. Fetching
cached findings from an API measures only that component's outputs; label the
scope accurately and do not call it full AI-system evaluation. Inspect the API,
dashboard, and agent interfaces to choose the appropriate adapter.

Require prepared data, reviewed labels, and any endpoint/model credentials needed
by that adapter. Never silently substitute mocks for a real-data or live run.

Exit codes: 0 = completed with no configured acceptance failures;
1 = evaluation failure, invalid input, or failed acceptance criterion;
2 = missing prerequisites. A completed measurement without acceptance thresholds
must be labeled "measured; acceptance not configured", not "performance passed".

## Reports and acceptance

Produce a human-readable report and structured JSON under out/ (generated and
not committed). Every run should record:

- Dataset, benchmark, code, and model/configuration versions as applicable.
- Evaluation scope and time window.
- Metric values, raw numerators/denominators, and sample sizes.
- Results by issue type and relevant workload/resource group.
- Failed cases, supporting evidence references, exclusions, and unknown outcomes.
- Whether thresholds were configured and whether each was met.

The five evaluation questions are agreed. Numeric acceptance thresholds remain
provisional and must be explicit configuration, with a rationale tied to the
benchmark and consequences of errors. Do not hard-code earlier conversational
targets as validated standards. Report uncertainty for benchmark rates and avoid
claiming reliability from a tiny sample or from zero observed harmful actions.

## Implementation sequence

1. Inspect data schemas and system interfaces; document metric denominators and
   issue-matching rules.
2. Implement data profiling and the data-quality report.
3. Define and validate the reviewed benchmark format.
4. Implement the system adapter and detection, diagnosis, and action scoring.
5. Add meaningful synthetic checks for scoring edge cases: missed issues, false
   alerts, duplicates, healthy cases, abstentions, unknown labels, and empty
   denominators.
6. Produce the reports and run available checks. Run make validate and make eval
   before committing, as required by AGENTS.md. If prerequisites prevent a run,
   report that explicitly.

Keep the first version focused on these metrics. Savings-estimate accuracy,
evidence-support scoring, latency, cost, and F1 can be added later when needed.
