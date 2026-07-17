## Scope

Regression hardening for the existing v0.09 stdio MCP protocol foundation.

### Included
- oversized no-newline response bound
- stderr flood isolation
- timeout/late-response terminal behavior
- close while blocked and request-thread cleanup
- pagination loop and duplicate Tool atomicity
- deep bounded JSON stability

### Excluded
No reconnect, Resources, Prompts, multi-Server routing, remote writes, or third-party interoperability claim.
