# v0.09 MCP Capability Selection — Known Limitations

- lexical keyword matching only; no embeddings, LLM selector, semantic expansion or reranker;
- scope and selection eligibility are static metadata/policy inputs;
- selection eligibility does not guarantee invocation authorization and cannot replace Runtime Permission recheck;
- capability index is frozen for one Runtime construction; no list-changed refresh or reconnect;
- all registered MCP Tool names remain visible to the Agent Runtime, while detailed remote descriptions are exposed only for selected capabilities;
- no multi-server health score, load balancing or automatic conflict arbitration;
- no Human approval UI;
- no MCP Resources or Prompts;
- no remote write retry/idempotency policy;
- Server description remains untrusted data and may be excluded by Context budget;
- fixture metrics are small deterministic regression gates, not production benchmarks;
- E2E uses the repository fake stdio server, not a third-party production MCP server.
