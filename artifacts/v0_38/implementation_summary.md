# v0.38 Implementation Summary

PaperClaw now owns a project-scoped academic paper domain with SQLite metadata,
content-addressed managed originals, immutable explicit versions and candidate /
confirmed metadata. `PaperService` is the shared seam for Python, REST, CLI and
Desktop callers. Import does not mutate retrieval indexes.

Commits:

- `5557bd2` — domain, repository, managed store and tests;
- `d323ad7` — REST and CLI adapters;
- `47483ca` — Desktop paper library.

No source code was copied from reference repositories.
