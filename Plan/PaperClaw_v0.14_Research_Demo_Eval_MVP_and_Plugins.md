# PaperClaw v0.14 Research Demo & Eval — MVP + Plugin Plan

> Status: READY FOR IMPLEMENTATION  
> Dependencies: existing v0.08 Context Orchestration, v0.09 MCP, v0.09.1 Retrieval, v0.07 Trace/Eval, and optionally v0.12 Service API  
> Goal: turn existing capabilities into one reproducible, evidence-backed repository research workflow with measurable retrieval, citation, tool, latency, and task-quality results.

## 1. Target workflow

The canonical task is:

```text
Analyze a repository and report its architecture, active plans, implementation status,
tests/CI evidence, known limitations, and next development actions.
```

Reference data flow:

```text
Question
  -> local repository document retrieval
  -> optional GitHub MCP capability calls
  -> Context Orchestration selection
  -> Agent Runtime
  -> Verification Gate
  -> durable Trace
  -> deterministic Eval
  -> evidence-backed report
```

The output must distinguish:

- verified facts;
- inferences;
- proposals;
- unknowns.

Every important claim should point to a retrieval source, MCP result, file path, Trace event, or test artifact.

## 2. MVP scope

### 2.1 Dataset contract

Add a versioned JSONL dataset format:

```json
{
  "case_id": "repo-status-001",
  "question": "...",
  "workspace_fixture": "...",
  "expected_evidence": [
    {"source_id": "...", "required_terms": ["..."]}
  ],
  "required_claims": ["..."],
  "forbidden_claims": ["..."],
  "tags": ["architecture", "status"]
}
```

Dataset requirements:

- no copyrighted full-document duplication;
- deterministic local fixtures;
- train/dev/test split metadata;
- stable case IDs;
- schema validation;
- dataset version and digest.

### 2.2 Reproducible pipeline variants

Minimum variants:

```text
baseline_no_retrieval
bm25
bm25_context_policy
bm25_mcp_verify
```

All variants use:

- the same dataset;
- the same task text;
- fixed retrieval K;
- fixed limits;
- fixed seed where applicable;
- the same evaluation code;
- recorded configuration fingerprint.

The live-LLM variant is separate from deterministic FakeModel/offline evaluation.

### 2.3 Metrics

Retrieval metrics:

- Recall@K;
- MRR;
- evidence-source coverage;
- CJK retrieval subset score.

Answer metrics:

- required-claim coverage;
- forbidden-claim rate;
- citation correctness;
- citation completeness;
- unsupported-claim rate.

Operational metrics:

- model calls;
- tool calls;
- MCP calls;
- latency;
- selected-context size;
- terminal status.

No metric may be reported as measured unless the experiment was actually run.

### 2.4 Evaluation runner

CLI:

```text
paperclaw research-eval run --dataset ... --variant ... --output ...
paperclaw research-eval compare --input ... --output ...
```

The runner must:

- validate the dataset;
- execute or load recorded results;
- calculate deterministic metrics;
- write JSON and Markdown summaries;
- preserve per-case failures;
- include configuration and code/version metadata;
- never hide failed or skipped cases.

### 2.5 Evidence ledger

Each case produces a ledger containing:

- retrieved sources and ranks;
- selected Context candidates;
- MCP capabilities invoked;
- public tool results;
- final claims;
- attached citations;
- verification result;
- metric breakdown.

Raw secrets, hidden reasoning, and unbounded Provider responses are excluded.

### 2.6 Canonical demo

Provide one deterministic repository fixture and one real-repository configuration.

Offline demo:

- uses committed fixture documents;
- uses deterministic model/tool doubles;
- reproduces exact metrics.

Live demo:

- uses a disposable Provider credential;
- may call GitHub through the existing MCP path;
- is classified separately;
- records no credential.

## 3. MVP deliverables

Suggested modules:

```text
src/paperclaw/research_eval/
  __init__.py
  contracts.py
  dataset.py
  metrics.py
  runner.py
  compare.py
  cli.py
```

Tests:

```text
tests/unit/research_eval/
tests/integration/research_eval/
tests/fixtures/research_eval/
```

Artifacts:

```text
artifacts/v0_14/implementation_summary.md
artifacts/v0_14/test_report.md
artifacts/v0_14/known_limitations.md
artifacts/v0_14/canonical_results.json
artifacts/v0_14/canonical_report.md
docs/handoff/PaperClaw_v0.14_Research_Demo_Eval_HANDOFF.md
```

## 4. Plugin layer

### 4.1 Retrieval plugin

```python
class RetrievalVariant(Protocol):
    variant_id: str
    def retrieve(self, case: EvalCase, *, limit: int) -> Sequence[EvidenceHit]: ...
```

Potential plugins:

- vector retrieval;
- hybrid BM25 + vector;
- reranker;
- remote search provider;
- domain-specific index.

Every plugin must return normalized evidence hits with source IDs and ranks.

### 4.2 MCP capability plugin

```python
class CapabilityProvider(Protocol):
    provider_id: str
    def capabilities(self) -> Sequence[CapabilityDescriptor]: ...
    def invoke(self, capability_id: str, arguments: Mapping[str, object]) -> CapabilityResult: ...
```

Requirements:

- timeout and typed failure;
- sanitized bounded results;
- allowlisted capabilities;
- invocation count recorded;
- provider failure does not become fabricated evidence.

### 4.3 Metric plugin

```python
class EvalMetric(Protocol):
    metric_id: str
    def evaluate(self, case: EvalCase, result: CaseResult) -> MetricResult: ...
```

Metric plugins must be deterministic for identical inputs and report missing prerequisites explicitly.

### 4.4 Report plugin

Optional renderers:

- Markdown;
- JSON;
- CSV;
- HTML dashboard;
- CI summary.

Rendering cannot change metric values.

## 5. Experiment matrix

| Variant | Retrieval | Context policy | MCP | Verify | Required |
|---|---|---|---|---|---|
| A | none | no | no | optional | yes |
| B | BM25 | no | no | optional | yes |
| C | BM25 | yes | no | yes | yes |
| D | BM25 | yes | yes | yes | yes |
| E | plugin retrieval | yes | optional | yes | plugin phase |

Required comparisons:

- A vs B: retrieval contribution;
- B vs C: Context policy contribution;
- C vs D: MCP evidence contribution;
- failure cases where additional context harms performance;
- latency/tool-call cost for every gain.

## 6. Test matrix

| Area | Required evidence |
|---|---|
| Dataset schema | invalid/missing fields rejected |
| Digest | deterministic across runs |
| Recall@K/MRR | known toy rankings |
| Citation correctness | matching and mismatching source cases |
| Unsupported claims | explicit negative fixtures |
| Variant isolation | same dataset/config except declared change |
| Failure preservation | failed/skipped cases remain in report |
| Plugin isolation | plugin exception becomes typed case failure |
| CJK subset | Chinese query fixture |
| MCP failure | timeout/invalid result cannot become evidence |
| Reproducibility | canonical fixture gives exact JSON |
| Security | secret-like values absent from artifacts |

## 7. Delivery sequence

### Segment 0 — Freeze experiment contract

- inventory existing Retrieval, Context, MCP, Trace, Replay, and Eval APIs;
- define the smallest adapters rather than duplicating them;
- freeze dataset and result schemas;
- define exact metric formulas.

### Segment 1 — Dataset and metrics

- implement schema validation;
- implement Recall@K, MRR, claim, and citation metrics;
- add deterministic fixtures.

### Segment 2 — Runner and variants

- implement offline variants;
- record configuration fingerprints;
- preserve case-level evidence and failures.

### Segment 3 — Plugin protocols

- implement static retrieval, capability, metric, and renderer registries;
- add one deterministic custom metric or retrieval test plugin.

### Segment 4 — Canonical artifacts and live smoke

- generate canonical offline JSON/Markdown;
- run full tests and Ruff;
- perform one optional live Provider/MCP demo;
- produce Handoff with measured vs unverified boundaries.

## 8. Non-goals

The MVP does not include:

- training or fine-tuning a model;
- claiming general scientific benchmark validity;
- scraping unauthorized content;
- LLM-as-judge as the only metric;
- hidden manual edits to results;
- a production analytics warehouse;
- vector database dependency;
- automatic paper writing;
- fabricated citations or experiment outcomes.

## 9. Definition of Done

MVP is complete only when:

- dataset and result contracts are versioned and validated;
- four required variants can be run or deterministically replayed;
- Recall@K, MRR, claim coverage, citation correctness, unsupported-claim rate, latency, and call counts are reported;
- all failed and skipped cases remain visible;
- canonical offline artifacts are reproducible byte-for-byte or field-for-field;
- existing Retrieval/MCP/Context/Trace code is reused through adapters;
- full non-live regression and Ruff pass;
- live results are clearly separated from offline results.

Plugin phase is complete only when:

- retrieval, capability, metric, and renderer protocols are stable;
- registries are explicit/static;
- plugin failures are isolated;
- plugin identity/version appears in result metadata.
