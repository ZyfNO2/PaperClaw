# Known Limitations

- The hardening suite uses deterministic local contracts and does not execute a live Provider.
- The 10k-candidate threshold is a regression bound on GitHub Actions, not a production capacity SLA.
- MultiAgent shared/private Context policy remains outside this slice.
- Raw Context is expected in the Provider Prompt but must remain absent from durable Trace metadata.
