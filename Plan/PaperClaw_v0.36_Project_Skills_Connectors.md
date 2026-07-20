# PaperClaw v0.36 Project-scoped Skills / Connectors

This document records the next stacked increment. Implementation lives on a dedicated v0.36 branch created from the final v0.35 exact head.

## Invariants

- project manifests store only extension metadata and `secret://` references;
- project files cannot dynamically import Python modules or factories;
- connector runtimes must be supplied by a host-controlled allowlist;
- effective permissions are the intersection of project declarations and runtime ceilings;
- Skill files must remain regular UTF-8 files inside the project workspace;
- activation snapshots, audit events and public discovery never contain resolved secret values;
- MCP tools are filtered by effective permissions before exposure;
- all registry writes are atomic and auditable.
