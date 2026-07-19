# Academic Tailoring Gold Benchmark v1

This benchmark evaluates whether PaperClaw/PaperAgent can turn incomplete, realistic research requests into evidence-backed academic tailoring plans.

## Purpose

The dataset is not a list of ideal final paper titles. Each case is a multi-stage gold trace describing how a competent research agent should:

1. parse a sparse user input;
2. separate explicit facts, inferences, proposals, and unknowns;
3. search for baseline, gap, parallel-method, comparison, and risk evidence;
4. filter irrelevant papers by title/keywords, abstract semantics, and core-paper full text;
5. ask at most one or two high-value clarification questions;
6. freeze a reproducible baseline;
7. state a falsifiable hypothesis;
8. build module cards and semantic integration contracts;
9. recommend the smallest testable stitch;
10. define fair comparisons, ablations, resource metrics, and stop conditions;
11. return `GO`, `REVISE`, `REVISE_TO_PILOT`, or `NO_GO`.

The gold data deliberately avoids making one exact paper title the only acceptable answer. Equivalent primary-source papers are allowed when they satisfy the same role, mechanism, reproducibility, and constraint evidence.

## Files

- `cases-01.jsonl` through `cases-04.jsonl`: 20 compact gold records, five cases per shard.
- `trace-profile.json`: shared ten-stage gold trace and global hard failures.
- `validate_cases.py`: dependency-free structural validator.
- `tests/unit/research_eval/test_academic_tailoring_gold_dataset.py`: repository regression test.

## Coverage

The 20 cases cover:

- computer vision, medical AI, industrial inspection, remote sensing;
- human motion and HCI;
- NLP, RAG, hallucination control;
- graph learning, recommendation, time-series anomaly detection;
- agricultural AI;
- ambiguous task formulation, missing deployment constraints, missing material identity;
- no supplied paper, one supplied paper, and two supplied papers.

User-supplied material counts are intentionally bounded:

- 15 cases: no supplied paper;
- 3 cases: one supplied paper;
- 2 cases: two supplied papers.

No case contains more than two supplied papers.

## Record contract

Each JSONL row contains:

- `case_id`
- `user_input` and zero-to-two `supplied_materials`
- normalized `intent` and unresolved `unknowns`
- one or two `clarification_questions`
- `baseline_expectation` and `parallel_expectations`
- falsifiable `hypothesis`
- `tailoring_advice`
- `experiment_plan`
- `stop_conditions`
- expected `decision`
- case-specific `special_assertions`
- `tags` and the shared `trace_profile` identifier

## Evaluation strategy

A candidate run should be converted into a normalized trace and scored at stage level.

### Hard failures

A case fails immediately when the agent:

- fabricates a paper, identifier, result, code link, or reproduced metric;
- treats a verified DOI as proof of relevance;
- forces a supplied paper into an incompatible role;
- claims novelty from module composition alone;
- leaks future/test information or uses an unfair split;
- hides stronger baselines or negative results;
- returns a success decision without a reproducible baseline and testable hypothesis.

### Stage assertions

Recommended stage scoring:

| Stage | Weight |
|---|---:|
| Input parsing and unknown tracking | 10 |
| Exploratory retrieval and relevance filtering | 15 |
| Clarification quality | 10 |
| Baseline selection and freeze | 15 |
| Gap and falsifiable hypothesis | 15 |
| Module provenance and compatibility | 15 |
| Minimal stitch | 10 |
| Experiment/ablation plan | 5 |
| Decision and recovery path | 5 |

A stage should not pass merely because the final prose mentions the expected keyword. The trace must show the corresponding decision and evidence binding.

## Suggested runner behavior

1. Feed only `user_input` and the declared `supplied_materials` to the system under test.
2. Allow the agent to perform retrieval and ask clarification questions.
3. Simulate user replies from the gold intent only after the agent asks a relevant question.
4. Capture the full trace, including queries, retrieved candidates, rejected candidates, evidence bindings, baseline decision, module contracts, and final plan.
5. Compare the normalized trace with `trace-profile.json` and each case's role, hypothesis, tailoring, experiment, stop-condition, and assertion fields.
6. Treat equivalent methods as acceptable only when the mechanism and role match.

## Important interpretation rule

The benchmark describes correct research behavior, not guaranteed empirical outcomes. Any predicted improvement remains a hypothesis until experiments are run. A correct agent may return `REVISE` or `NO_GO`; forcing every case to produce a positive combined method is a benchmark failure.
