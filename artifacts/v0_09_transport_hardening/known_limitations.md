# Known Limitations

- All tests use a deterministic local Python stdio Server.
- Physical Windows Terminal process behavior and third-party MCP Servers remain separate acceptance activities.
- The slice validates the existing synchronous single-flight transport; it does not add reconnect or multiplexing.
- Deep JSON coverage is bounded and does not claim protection against every parser implementation limit.
