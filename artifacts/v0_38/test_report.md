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

The three Desktop skips are environment/optional-path skips already declared by the
suite. Native pywebview click-through remains pending and is not represented as live
validation.
