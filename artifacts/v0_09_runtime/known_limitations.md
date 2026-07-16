# v0.09 MCP Runtime Integration — Known Limitations

- Runtime integration currently assumes one synchronous single-flight session per connection.
- Cancellation is cooperative at the PaperClaw boundary and closes the complete MCP connection; it does not preserve the session for later calls.
- Timeout also closes the connection to prevent late-response contamination; reconnect is not implemented.
- Only the conservative JSON Schema subset accepted by Protocol Foundation can be validated.
- JSON Schema `format` is retained as annotation and is not semantically enforced in this slice.
- Permission UI/HITL is not implemented; callers provide a policy object explicitly.
- The provided allowlist policy is intentionally small and does not infer safety from Tool names/descriptions.
- Capability selection, automatic routing and multi-Server conflict resolution remain out of scope.
- MCP Resources, Prompts and non-text result content remain unsupported.
- No remote write retry or idempotency semantics are provided.
- Tests use deterministic fakes and a local stdio subprocess; third-party MCP interoperability is not claimed.
- Merge remains blocked until prerequisite v0.08 and MCP Protocol Foundation PRs are accepted into the target branch.
