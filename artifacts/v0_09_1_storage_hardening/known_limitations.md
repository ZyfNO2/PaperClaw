# Known Limitations

- CI validates the stacked PR #24 tree; this hardening PR must be retargeted to PR #24 after validation.
- Windows-style URI tests verify stable exact identities, not case-insensitive path equivalence.
- Concurrency coverage is one writer and repeated readers, not a production multi-writer stress test.
- Abrupt process termination and filesystem-level power-loss simulation remain separate acceptance work.
