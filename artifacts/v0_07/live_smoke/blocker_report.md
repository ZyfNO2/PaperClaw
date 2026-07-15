# v0.07 Mistral Live Smoke — Blocker Report

## Classification

`BLOCKED_BY_EXECUTION_ENVIRONMENT`

## Attempt

A real authenticated request was prepared against the HTTPS base URL contained in the supplied local secret file:

```text
GET <configured-base-url>/models
Authorization: Bearer <redacted>
```

The secret file precheck found exactly one HTTPS URL and one key-shaped value. No key bytes were printed, committed or copied into this artifact.

## Observed result

```text
exception: urllib.error.URLError
reason type: socket.gaierror
reason: [Errno -3] Temporary failure in name resolution
```

The failure occurred during DNS resolution before an HTTP connection was established.

## Conclusions

- Mistral service reachability from this execution environment: not available;
- HTTP status: none;
- authentication result: unknown;
- key validity: not verified;
- live model list: not retrieved;
- live chat completion: not executed;
- v0.07 offline trace implementation: unaffected and covered by CI.

## Reproduction in a network-enabled environment

```powershell
$env:PAPERCLAW_API_KEY = "<secret>"
$env:PAPERCLAW_BASE_URL = "https://api.mistral.ai/v1"
$env:PAPERCLAW_MODEL = "<model returned by /models>"
$env:PAPERCLAW_PROVIDER = "mistral"
python scripts/run_v0_07_mistral_trace_smoke.py
```

A valid pass must produce `LIVE ACCEPTANCE PASSED`, a terminal `run.completed`, provider/model/duration metadata, and no key bytes in SQLite, JSONL or summary artifacts.
