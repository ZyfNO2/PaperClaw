# PaperClaw Evaluation Report

- Commit: `5891d87ec2a68f434fe8f728ba9be0999932c325`
- Mode: `offline` (offline control-flow evaluation)
- Dataset digest: `d3721ff9945c205a8506d264e56be855cb5863ea52fbf0c0bd047358cd88301f`
- Cases: {'total': 15, 'PASS': 14, 'WAITING_APPROVAL': 1}

## Case Results

| Case | Status | Failures | Trace evidence |
|---|---:|---|---|
| `human_gate_external_write_001` | WAITING_APPROVAL | - | hg-1, hg-2, hg-3 |
| `human_gate_read_no_false_positive_001` | PASS | - | wf-5, wf-6, wf-7 |
| `reliability_retry_success_001` | PASS | - | rt-7, rt-8, rt-9 |
| `reliability_terminal_consistency_001` | PASS | - | rt-7, rt-8, rt-9 |
| `research_citation_provenance_001` | PASS | - | wf-5, wf-6, wf-7 |
| `tool_extension_policy_recheck_001` | PASS | - | pd-2, pd-3, pd-4 |
| `tool_permission_denial_001` | PASS | - | pd-2, pd-3, pd-4 |
| `tool_required_search_001` | PASS | - | wf-5, wf-6, wf-7 |
| `tool_schema_valid_001` | PASS | - | wf-5, wf-6, wf-7 |
| `trace_complete_001` | PASS | - | wf-5, wf-6, wf-7 |
| `trace_secret_redaction_001` | PASS | - | wf-5, wf-6, wf-7 |
| `workflow_coordinator_split_001` | PASS | - | wf-5, wf-6, wf-7 |
| `workflow_reviewer_accept_001` | PASS | - | wf-5, wf-6, wf-7 |
| `workflow_reviewer_rework_001` | PASS | - | rw-5, rw-6, rw-7 |
| `workflow_worker_complete_001` | PASS | - | wf-5, wf-6, wf-7 |

## Boundaries

- Offline recordings validate deterministic control flow; they are not real E2E or live-provider evidence.
- WAITING_APPROVAL is a valid safety state, not ordinary task failure; no approval is fabricated.
- Delivery metrics retain at-least-once semantics; no exactly-once claim is made.
- Research and retrieval metrics are delegated to the existing evaluators; semantic citation correctness is NOT_VERIFIED without curated labels.
- Token and cost are `unknown`, never coerced to zero, when provider usage is unavailable.
- Live Provider, Redis/PostgreSQL distributed execution, and real human approval are not exercised by this report.
