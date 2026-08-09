# PaperClaw v0.39 Handoff

## Status

PARTIAL

Offline implementation and deterministic validation are complete for the
v0.39 scope. The full non-live suite still has two pre-existing Windows Bash
failures, repository-wide Ruff has pre-existing violations, exact-head CI was
not run because this branch was not pushed, and real LLM/Docker/manual OS
validation was not executed. v0.40 and v0.41 are intentionally out of scope.

## Repository

- Repository: ZyfNO2/PaperClaw
- Branch: codex/v0.39-durable-memory-context-resume
- Base SHA: 9095b286aa1b902fd280b320ac4dbc9130fd5b3d
- Planning reference: 939410466507336dc1783fee0c1dd96552aa72e9
- Planning reference parent: 5891d87ec2a68f434fe8f728ba9be0999932c325
- Final SHA: exact SHA is reported after the final commit; verify with git rev-parse HEAD
- Main was not merged or modified by this work.

The planning branch was inspected but not merged. It would remove newer,
verified v0.39 structured Memory work already present at the selected base.
The current branch extends that implementation in place.

## SPEC to implementation to test mapping

| Requirement | Implementation | Evidence | Status |
|---|---|---|---|
| Durable ordered SessionEvent | SessionEvent contract, SQLite repository, additive schema v5 | v0.39 contract tests and context contract tests | offline_validated |
| Idempotent append and concurrent ordering | run/idempotency unique index, BEGIN IMMEDIATE allocation, existing writer lock | cross-connection concurrent append test | offline_validated |
| Memory provenance | typed MemorySourceRef projected to bounded source_refs; legacy_file locator | provenance and legacy import tests | offline_validated |
| Conflict decision | keep_both, supersede, merge, reject_candidate records and immutable history | conflict decision test plus Memory regression | offline_validated |
| Deterministic Context Builder | existing ContextOrchestrator and PromptAssembler with explicit priority_order | orchestration tests and demo artifact equality | offline_validated |
| Token budget and omissions | existing quota/fit policy plus snapshot counters and fingerprint | context budget and snapshot tests | offline_validated |
| Atomic tool call/result retention | existing durable events paired into one tool-group candidate | atomic tool group test | offline_validated |
| ContextSnapshot | existing snapshot table extended with model, memory, artifact, event, compaction and policy locators | snapshot and v4-to-v5 migration tests | offline_validated |
| Crash/restart reconstruction | SessionService.reconstruct over runs, events, task state and snapshots | resume contract and session tests | offline_validated |
| Safe resume | terminal no-op, safe-boundary decision, preserve/tighten permission mode, no tool replay | safe, ambiguous, terminal and tighten assertions | offline_validated |
| Ambiguous side effect handling | unmatched structured tool start blocks with manual_review_required | ambiguous resume test and blocked trace event | offline_validated |
| Trace and operator inspection | existing event-to-trace projection; bounded manifest/event metadata CLI | trace and operator tests | offline_validated |
| Migration/backward compatibility | additive v5 migration and one-way idempotent legacy Memory importer | migration/import tests | offline_validated |
| Regression/CI evidence | focused tests and full non-live run; exact-head CI unavailable locally | results below | partial / AWAITING REAL TEST |

## Main architecture decisions

- Reused src/paperclaw/memory/store.py, the existing structured MemoryService
  and MemoryRepository adapter; no parallel Memory Store was created.
- Reused context/runtime_compaction.py, ContextOrchestrator, PromptAssembler,
  SessionService, existing event persistence, Artifact/Evidence references,
  task state persistence, idempotency and cancellation seams.
- ContextSnapshot is a bounded manifest, not a duplicated prompt archive.
- Context selection remains deterministic and policy-driven. Tool start/result
  pairs are selected as one candidate and orphaned structured results are not
  injected.
- Resume only reconstructs durable facts. It never automatically replays an
  external tool with an unknown outcome. The operator can preserve or request
  a tighter permission mode; no resume path expands permissions.
- Operator output excludes raw event payloads and prompt bodies by default.
- The existing canonical field conversation_id remains in SessionEvent;
  session_id is a compatibility alias on the contract/operator surface.
- No exactly-once execution claim is made.

## Storage, migration and compatibility

- SQLite schema moved additively from v4 to v5.
- v5 adds event turn/idempotency/payload references, a partial unique
  idempotency index, ContextSnapshot manifest columns, and the
  memory_conflict_decisions table.
- Existing v4 Context/Session/Memory tables are preserved.
- Existing file-backed MEMORY.md/USER.md behavior remains readable. The
  importer is one-way, bounded, idempotent and does not rewrite legacy files.
- Existing SessionService, ContextOrchestrator, PromptAssembler, Trace and
  operator-compatible APIs remain available. New arguments are optional.
- Package metadata remains 0.38.0; changing the distribution version was
  intentionally outside this implementation slice.

## Changed files

Primary runtime changes:

- src/paperclaw/context/contracts.py
- src/paperclaw/context/migrations.py
- src/paperclaw/context/repository.py
- src/paperclaw/context/session.py
- src/paperclaw/context/orchestration.py
- src/paperclaw/harness/context_runtime_executor.py
- src/paperclaw/memory/contracts.py
- src/paperclaw/memory/repository.py
- src/paperclaw/memory/service.py
- src/paperclaw/session_commands.py
- src/paperclaw/cli.py
- src/paperclaw/trace/reader.py

Compatibility/documentation/tests:

- src/paperclaw/context/__init__.py
- src/paperclaw/memory/__init__.py
- tests/unit/test_v039_durable_runtime_contracts.py
- tests/unit/test_context_contracts.py
- artifacts/v0_39/requirements_matrix.md
- artifacts/v0_39/implementation_summary.md
- artifacts/v0_39/test_report.md
- artifacts/v0_39/known_limitations.md
- README.md
- CHANGELOG.md
- artifacts/v0_08/mvp_demo_trace.json

## Verification boundary

Unit / contract:

- v0.39 durable contract tests: 9 passed.
- Final focused Memory/Context/Session/runtime run: 50 passed.
- Existing Memory/Context/Session/Resume regression: 144 passed.
- Demo artifact regression: 3 passed.

Fake/Mock model:

- ContextSnapshot-before-provider and deterministic runtime tests passed with
  the repository's FakeModel. This is not a real LLM or provider test.

Deterministic integration:

- v0.08 context demo artifact regenerated and equality tests passed.
- v0.39 migration, operator, legacy import and resume contract scenarios
  passed.

Real process test:

- Service process acceptance: 2 passed, including mock-provider SSE,
  idempotency and kill/restart reconciliation.

Full non-live regression:

- 1078 passed, 23 skipped, 12 deselected.
- 2 failed, both pre-existing Windows Bash tests:
  - tests/unit/test_bash_tool.py::test_bash_tool_respects_stop_token_mid_execution
  - tests/unit/test_grep_bash.py::test_bash_timeout_kills_child_process_tree
- The failures are in the existing PowerShell quoting/timeout behavior.
  Bash code was not changed for v0.39.

Lint/type/build:

- Ruff high-signal command required by current CI:
  ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
  passed.
- New v0.39 contract test has no Ruff findings.
- Full repository Ruff check was run and is not clean because the current
  repository has 873 pre-existing findings across unrelated files; this
  implementation did not perform a repository-wide formatting rewrite.
- No mypy, pyright or repository type-check command is configured in
  pyproject.toml or the active CI workflow: NOT CONFIGURED / NOT VERIFIED.
- Package build passed with python -m build --no-isolation and produced the
  existing 0.38.0 sdist/wheel.
- The isolated default build was not used as acceptance evidence because the
  environment's isolated dependency setup hit an encoding/network failure.

CI and live boundary:

- Exact-head GitHub CI: AWAITING REAL TEST; branch was not pushed.
- Real LLM/provider call: NOT VERIFIED.
- Real Docker sandbox: NOT VERIFIED.
- Manual native OS/TUI inspection: NOT VERIFIED.
- No secrets, provider credentials, benchmark scores, token/cost claims or
  Docker isolation claims were generated.

## Known limitations and remaining work

1. Fix or separately triage the two existing Windows Bash failures.
2. Run the repository's exact CI on the final pushed SHA.
3. Run real LLM, Docker and manual native-OS checks under the required
   environment if release acceptance requires them.
4. Decide separately whether to bump package metadata from 0.38.0.
5. Do not start v0.40 or v0.41 until v0.39 is accepted.

## Accurate next handoff steps

1. Verify the final branch and commit:
   git status --short --branch
   git rev-parse HEAD
2. Review artifacts/v0_39/requirements_matrix.md and this file.
3. Re-run the high-signal gate:
   python -m ruff check src/paperclaw tests --select E9,F63,F7,F82 --ignore F821
4. Re-run the v0.39 contracts:
   python -m pytest tests/unit/test_v039_durable_runtime_contracts.py -q
5. If release acceptance is required, push this branch and record the exact
   CI URL/result for the SHA; then separately run only the real tests that
   have the required provider, Docker and OS environment.
6. If the two Bash failures are fixed, rerun:
   python -m pytest -q -m "not real_llm and not distributed"
7. Only after those decisions should a maintainer update the v0.39 status
   from PARTIAL; no merge to main is implied by this handoff.
