# PaperClaw v0.06 acceptance correction

> Branch: `fix/v0.06-acceptance-cancel-race`
> Status: code fix committed; CI and remaining physical acceptance pending

This correction records that PR #2 was merged before all physical-terminal and real/sanitized database gates were closed. Merge state is not equivalent to v0.06 acceptance GO.

The repair branch narrows cooperative cancellation ownership to adapter calls already in flight and adds deterministic coverage for the previously missing Tool `execute()` exception race. Provider, Tool validation and Tool execution adapter failures may translate to cooperative stop only when the stop token was accepted while that call was in flight. Unrelated runtime, session and persistence failures remain `runtime_failed`.

Remaining gates:

- narrow Windows Terminal resize screenshot;
- post-fix physical TUI `/cancel` capture;
- Doctor quick/full results against a safe real or sanitized database copy;
- final evidence review before changing v0.06 to GO.
