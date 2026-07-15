# v0.06.1 Known Limitations

1. Reopen selects a conversation and creates a fresh Run on the next submit. It does not resume an ended Run.
2. Previous messages are restored to the TUI for human preview, but are not automatically injected into the model prompt. Semantic conversation continuation remains future work behind a bounded context contract.
3. Active Runs are excluded rather than reconciled. A stale Run with `ended_at IS NULL` must be handled by recovery tooling, not the picker.
4. The list is snapshot-based. `preview` and `reopen` revalidate safety, but a separate process may create a Run after selection and before the next submit. The repository remains authoritative and will persist the new Run normally; cross-process conversation leasing is not implemented.
5. Message previews are normalized and truncated, but they are not a general secret-classification system. Users should not treat the TUI transcript as a secure secret viewer.
6. The picker does not display checkpoint state, recovery diagnostics, session deletion, renaming, search, pagination, or retention controls.
7. Real Windows Terminal and Live Provider acceptance is pending. Headless Textual tests are not physical terminal evidence.
