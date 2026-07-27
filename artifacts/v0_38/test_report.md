# v0.38 Test Report

Date: 2026-07-27

| Gate | Result |
|---|---|
| Paper/REST/CLI/capability focused suite | 21 passed |
| Desktop suite | 91 passed, 3 skipped |
| JavaScript syntax (`node --check`) | passed |
| Ruff correctness (`E9,F63,F7,F82`) | passed |
| Package build | sdist and wheel built for 0.38.0 |
| Local PDF corpus smoke | 5/5 imported, repeat deduplicated |
| Full non-live regression | 1019 passed, 23 skipped, 12 deselected |
| Post-review hardening suite | 13 passed |

The three Desktop skips are environment/optional-path skips already declared by the
suite. Native pywebview click-through remains pending and is not represented as live
validation.

Post-review regression cases cover truncated PDF rejection, concurrent same-hash
idempotency with replay, corrupt existing blob rejection, and REST ancestor-root
confinement.
