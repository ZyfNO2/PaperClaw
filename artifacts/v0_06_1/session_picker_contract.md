# v0.06.1 Safe Session Picker Contract

## Selection predicate

A conversation is selectable when:

```sql
latest_run.ended_at IS NOT NULL
AND NOT EXISTS (
  SELECT 1 FROM runs
  WHERE runs.conversation_id = conversation.conversation_id
    AND runs.ended_at IS NULL
)
```

The picker requires the `conversations`, `runs`, and `messages` tables. Missing tables, unreadable databases, missing files, and conversations that stop satisfying the predicate fail closed.

## Read boundary

`SafeSessionPicker` opens the target with SQLite URI `mode=ro` and `PRAGMA query_only = ON`. It does not migrate, create, repair, or write the database.

## Preview boundary

Preview returns:

- conversation metadata;
- latest ended Run metadata;
- message count;
- up to eight recent messages by default;
- normalized excerpts capped at 500 characters;
- only `user` and `assistant` roles as such; unknown roles render as `system`.

No session events, hidden reasoning, raw tool output, environment values, or arbitrary metadata are rendered.

## Reopen boundary

`SessionCommandAPI.reopen()` performs a fresh preview lookup and returns a `ReopenedConversation`. It has no write side effect.

The TUI then creates a fresh QueryEngine using the returned `conversation_id`. The next submit creates a new Run through the existing `AgentRuntimeExecutor -> SessionService -> SQLiteRepository` path. The ended Run is not reopened, appended to, or mutated.

## Compatibility

- `paperclaw tui` without `--database` preserves the v0.06 in-memory behavior.
- `--no-tui` preserves standard CLI fallback and does not open the database.
- Existing one-argument test engine factories remain supported for new conversations.
- Textual remains optional and lazy-loaded.

## Non-goals

- checkpoint resume;
- recovery reconciliation;
- reconnect to an active process;
- semantic replay of prior messages into the model prompt;
- MultiAgent session recovery.
