# Coding Agent Prompt — PaperClaw P0 Agent Runtime Hardening

Use this prompt when delegating implementation to a coding agent.

---

You are implementing the next P0 Agent Runtime hardening work in `ZyfNO2/PaperClaw`.

Read these documents first:

1. `Plan/PaperClaw_P0_Agent_Runtime_Hardening_Master_Plan.md`
2. the SPEC/SOP for the increment you are implementing:
   - v0.39: `Plan/PaperClaw_v0.39_Durable_Memory_Context_Resume_SPEC_SOP.md`
   - v0.40: `Plan/PaperClaw_v0.40_Sandbox_Execution_SPEC_SOP.md`
   - v0.41: `Plan/PaperClaw_v0.41_Agent_Runtime_Eval_Harness_SPEC_SOP.md`
3. current repository `README.md`, `CHANGELOG.md`, relevant prior `Plan/`, `artifacts/`, tests and CI workflows.

Do not assume the plan describes the current code exactly. Before modifying anything, inspect the real repository HEAD, default branch, current implementation, tests, CI, latest Handoff and any commits made after this planning document. If repository facts conflict with the plan, preserve the newer verified implementation and use the smallest compatible design; record the deviation in the final Handoff.

Core rule: this is an upgrade of existing PaperClaw architecture, not permission to create parallel systems. Reuse the existing memory store, context compaction, ToolRegistry/BashTool lifecycle, Trace/eval, task persistence, artifact/evidence, cancellation, retry/idempotency and extension permission seams wherever they satisfy the contract.

Implement ONE increment at a time. Do not combine v0.39, v0.40 and v0.41 into one giant patch unless explicitly instructed.

For the selected increment:

1. Resolve current `main` HEAD and create an isolated feature branch.
2. Map every SPEC requirement to existing code, planned code and a test.
3. Implement the smallest architecture that satisfies the SPEC without unrelated refactors.
4. Preserve public/legacy behavior by default unless the SPEC explicitly changes it.
5. Add focused unit/integration tests before claiming completion.
6. Run targeted tests, then full non-live regression, lint/type/build gates used by the current repository.
7. Inspect CI for the exact candidate commit and fix failures introduced by the change.
8. Do not describe Mock/Fake/deterministic tests as real E2E. Real LLM, Docker isolation, native OS UI or external-service verification must be reported separately.
9. Do not fabricate benchmark numbers, CI status, provider results, Docker behavior or manual acceptance.
10. Commit at logical milestones with traceable messages.
11. Finish with `artifacts/v0_XX/HANDOFF.md` containing repository/branch, exact final SHA, completed requirements, major files, architecture decisions, tests/CI, pending real tests, limitations, remaining work and exact next-step commands.
12. Do not merge to `main` unless explicitly requested.

Hard stop only when a required external dependency cannot be supplied by the environment (credential, Docker daemon, real OS interaction, paid provider, hardware, production service, permission conflict). Before stopping, complete every offline/testable part and provide exact operator steps and expected evidence for the blocked validation.

When reporting completion, use only these states:

- `COMPLETE`: implementation + required executable acceptance complete;
- `PARTIAL`: meaningful implementation complete but non-core work remains;
- `BLOCKED`: external requirement prevents further progress;
- `AWAITING REAL TEST`: offline implementation complete, specified real environment validation remains.

Start now by inspecting the repository; do not answer with only a plan or review.
