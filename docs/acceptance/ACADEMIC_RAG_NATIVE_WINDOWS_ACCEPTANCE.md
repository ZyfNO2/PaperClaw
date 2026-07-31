# Academic RAG Native Windows acceptance

This is a manual operator check, not a Playwright result. Record one of PASS,
FAIL, BLOCKED, or NOT_RUN for every item. Do not use generated PDFs as real
scientific evidence.

## Environment

- System / Windows version: ____________________
- PaperAgent commit: ____________________
- PaperClaw commit: ____________________
- Python: ____________________  Browser: ____________________
- Operator: ____________________  Date/time: ____________________
- Log directory: ____________________

## Click-through

| Step | Status | Screenshot / log | Notes |
|---|---|---|---|
| Start PaperClaw | | | |
| Start PaperAgent production mode | | | |
| Create or select project | | | |
| Import server-local PDF path | | | |
| Observe parse/index progress | | | |
| Query and inspect accepted/rejected/conflicted Evidence | | | |
| Open Claim -> canonical page/object/bbox | | | |
| Read page/region PNG asset | | | |
| Open all eight Artifact types | | | |
| Approve / Reject / Revise and verify revision history | | | |
| Create/poll/cancel a durable run | | | |
| Trigger unavailable endpoint | | | |
| Trigger timeout / hash mismatch / stale locator | | | |
| Confirm production mode does not fall back to Demo | | | |

A missing manual click-through is BLOCKED_BY_NATIVE_WINDOWS_ACCEPTANCE; an
automated browser test cannot change that status.

