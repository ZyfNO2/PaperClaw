# PaperClaw Desktop / Browser Integration Handoff

Status: `implemented` work in progress. This file records inspected contracts and
must not be read as live or release validation.

## Baseline

- repository: `ZyfNO2/PaperClaw`
- base branch: `origin/main`
- base commit: `5891d87ec2a68f434fe8f728ba9be0999932c325`
- integration branch: `codex/desktop-browser-integration`

## Dual-surface API matrix

Both surfaces call the explicit methods on `PaperClawBackend.api`. Desktop dispatches
to `window.pywebview.api`; Browser dispatches to the token-protected loopback
`POST /api/<method>`. Browser arity is enforced before `DesktopAPI` dispatch.

| Operation | Arguments | Python implementation | Success / side effect | Public error | Coverage before this branch |
|---|---|---|---|---|---|
| defaults/state | none | `DesktopAPI.get_defaults/get_state` | non-secret config / authoritative snapshot | typed `DesktopPublicError` projection | Desktop unit + injected-bridge Playwright |
| start/cancel | request / none | `DesktopAPI` → `DesktopController` | one active run; stopping request | validation, provider, workspace, active/not-active | controller and Desktop API unit |
| events | limit, client ID | `DesktopAPI.poll_events` | independent cursor over bounded mirror history | validation | basic two-client fan-out unit |
| workspace/paper picker | none | `DesktopAPI` + native workspace extension | native path or cancelled result | native-window/runtime/path errors | Desktop unit only |
| theme | theme | `DesktopAPI.set_theme` | persisted preference | validation/runtime | Desktop unit + injected Playwright |
| provider actions | explicit provider/model values | provider extension | manual provider state; secret retained in Python | safe provider/public errors | extension unit + injected Playwright |
| project/capabilities | workspace/filter | product extension/service | read/refresh project projections | safe product/public errors | extension unit |
| artifacts | workspace/id/filter/export fields | product extension/service | list/read/export | safe product/public errors | extension unit |
| papers | workspace/source/id/metadata | product extension/service | import/list/read/version/confirm | safe paper/public errors | extension unit; Browser consumption missing |

Missing evidence at baseline: real loopback Browser UI flow, full API signature/arity
audit, overflow/reset/cursor eviction/concurrent polling, Browser Papers consumption,
terminal recovery, cancellation ordering, and real PyWebView graphical acceptance.

## Evidence boundary

Loopback HTTP and deterministic-controller Playwright are local process and browser
integration evidence. They are not production, provider, real-LLM, or real graphical
PyWebView validation.
