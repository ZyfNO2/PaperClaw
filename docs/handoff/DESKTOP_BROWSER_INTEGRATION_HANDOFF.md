# PaperClaw Desktop / Browser Integration Handoff

Status: `offline_validated`. This is local unit, integration, loopback-browser, and
package-build evidence. It is not live-provider, release, or real graphical PyWebView
acceptance evidence.

## Repository and commits

- repository: `ZyfNO2/PaperClaw`
- base branch/commit: `origin/main` at
  `5891d87ec2a68f434fe8f728ba9be0999932c325`
- integration branch/commit: `codex/desktop-browser-integration` at
  `b6b2b23202850d95e726be85d94672b46b961009`
- debugging branch/implementation commit: `codex/frontend-debugging-and-ux` at
  `ec12480f55a09ad456c34285e36f22c236019502`
- the final documentation-only commit is reported with the pushed branch head.

## Contract and transport

Both surfaces consume the single explicit `PaperClawBackend.api` contract. Desktop
dispatches to `window.pywebview.api`; Browser dispatches to token-protected loopback
`POST /api/<method>`. There is no arbitrary method bridge. Browser dispatch validates
method allowlisting, positional arity, JSON content type, token, and response schema.

| Capability | Desktop | Browser | Result |
|---|---|---|---|
| defaults/state | PyWebView bridge | loopback HTTP | authoritative, secret-free snapshot |
| start/cancel | PyWebView bridge | loopback HTTP | single active run, cancel guard |
| event polling | per-client cursor | per-client cursor | bounded history, generation + sequence |
| theme | persisted API | persisted API | shared projection |
| provider/model | explicit methods | explicit methods | safe public errors; secrets remain Python-side |
| project/capabilities | extension methods | extension methods | shared read/refresh behavior |
| artifacts | extension methods | extension methods | list/read/export parity |
| papers | extension methods | extension methods | Browser path is now wired and tested |
| native filesystem picker | native window | unavailable by browser design | Browser returns visible `native_window_required` |

The Browser native-picker limitation is intentional: no upload/path-acquisition API
exists, so the UI must not claim a successful local selection.

## Runtime state, races, and errors

- Initialization is promise-guarded and finite-retry; provider defaults are loaded
  once and distributed through `paperclaw:defaults`.
- Polling uses non-overlapping `setTimeout`: 250 ms active, 1500 ms idle, 4000 ms
  hidden, and exponential transport-failure backoff capped at 8000 ms.
- Request generations reject stale start/cancel/poll results. Event generation and
  monotonic sequence prevent replay across runs; bounded collections cap timeline at
  300, rendered-event identities at 600, and mission messages at 300.
- `get_state` is authoritative for control locking and recovery. Duplicate cancel is
  suppressed; cancel failure rolls back through a fresh state projection.
- Public backend errors survive reconnect until the operation is retried. Transport,
  invalid-JSON, missing-schema, token, timeout, and network failures are normalized
  without leaking secrets or stack traces.
- `?debug=1` exposes only mode, run ID, connection/poll/generation/sequence counters,
  dropped count, safe error code, active requests, interval, and visibility. It is
  absent in normal mode and contains no token or provider secret.
- Loopback responses carry CSP; disconnected clients no longer emit unhandled
  `BrokenPipe`/connection-reset server tracebacks.

## Version and presentation

`src/paperclaw/__init__.py` is the version source (`0.38.0`); package metadata reads it
dynamically, and Desktop defaults/projected UI and provider/model User-Agent consume
the same value. The UI no longer presents a stale hard-coded version. Responsive
checks cover desktop, laptop, tablet portrait, and narrow mobile viewports. Loading,
empty, failure, retry, disabled/busy controls, focus behavior, and native-only errors
are visible rather than silently failing.

## Defects fixed

- Browser Papers previously called only the PyWebView bridge and was nonfunctional.
- `poll_events` Browser arity disagreed with the Python defaulted signature.
- A rejected duplicate start cleared fan-out history before acceptance.
- Provider initialization duplicated defaults calls.
- Reconnect could erase an unrelated actionable backend error.
- Polling could overlap, replay stale responses, grow DOM/state without bounds, and
  continue at an aggressive rate while idle or hidden.
- Package/UI/User-Agent versions diverged.
- Browser disconnects could print server-side socket tracebacks.

## Verification evidence

Executed from the repository root:

| Command / scope | Result |
|---|---|
| Desktop contract, baseline, version, and adapter pytest selection | `106 passed, 3 skipped` |
| Playwright Chromium against a real local `BrowserHost` | `21 passed` in 22.51 s |
| Full non-live regression: `pytest -q -m "not real_llm and not distributed"` | `1030 passed, 35 skipped, 12 deselected` in 81.01 s |
| `python -m build` | built `paperclaw-0.38.0.tar.gz` and `paperclaw-0.38.0-py3-none-any.whl` |
| Ruff high-signal checks | passed |
| Node syntax checks for changed JavaScript | passed |

The real-`BrowserHost` tests cover normal completion, independent two-tab polling,
cancel, safe public-error retry, disconnect/invalid-JSON recovery and backoff, hidden
polling cadence, single initialization, version projection, dropped-event diagnostics,
native-only picker truthfulness, five viewport sizes, and an empty console-error /
page-error capture on the normal flow.

## Explicitly unverified / remaining

- Real graphical PyWebView window acceptance: **NOT VERIFIED**. The automated evidence
  exercises the shared frontend and real loopback HTTP host, not a user-observed native
  window.
- Real LLM/provider run: **NOT VERIFIED**; excluded by the required non-live marker.
- Distributed deployment: **NOT VERIFIED**; excluded by marker.
- HumanGate / waiting-for-approval UI: **NOT IMPLEMENTED / NOT VERIFIED** because the
  inspected Desktop runtime does not expose that state in its current public contract.
- Browser local filesystem selection remains unavailable until a secure upload or
  browser-native acquisition contract is designed.

Recommended next step: perform a manual PyWebView smoke test on a graphical Windows
session, then separately validate a credentialed provider run under the repository's
live-test policy. Do not reinterpret this handoff as release approval.
