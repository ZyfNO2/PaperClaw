# v0.09 Phase A Known Limitations

- local stdio transport only;
- one active request at a time;
- one Server per session;
- no reconnect, cache refresh, routing, health score, or conflict resolution;
- conservative JSON Schema subset rejects references and composition keywords;
- no argument validation against normalized schema;
- no ToolRegistry, Permission, approval, Run Budget, Trace, or Agent Runtime wiring;
- no Prompt injection or capability selection;
- no MCP Resources or Prompts;
- no image, audio, resource-link, or embedded-resource result support;
- no remote write operations or idempotency policy;
- no real third-party MCP Server interoperability verification.
