"""Application boundary for safe session discovery and persistent TUI runs.

The Textual client consumes this module without importing Context/Repository or
SQLite implementation details. Storage policy remains in ``paperclaw.context``;
this layer exposes only stable commands and executor construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session_picker import (
    SafeSessionPicker,
    SafeSessionPreview,
    SafeSessionSummary,
)
from paperclaw.harness import AgentRuntimeExecutor
from paperclaw.models.base import ChatModel


class SessionPickerLike(Protocol):
    def list_safe_sessions(
        self,
        *,
        limit: int = 20,
    ) -> tuple[SafeSessionSummary, ...]: ...

    def preview_safe_session(
        self,
        conversation_id: str,
        *,
        message_limit: int = 8,
    ) -> SafeSessionPreview: ...


@dataclass(frozen=True)
class ReopenedConversation:
    """Validated selection used to construct a fresh conversation-scoped engine."""

    conversation_id: str
    preview: SafeSessionPreview


class SessionCommandAPI:
    """UI-agnostic commands for listing, previewing, and reopening sessions.

    ``reopen`` is intentionally side-effect free. It revalidates that the
    conversation remains safely closed and returns the conversation_id. The
    caller creates a fresh QueryEngine; the first subsequent submission creates
    a new Run in that conversation.
    """

    def __init__(self, picker: SessionPickerLike) -> None:
        self._picker = picker

    def list(self, *, limit: int = 20) -> tuple[SafeSessionSummary, ...]:
        return self._picker.list_safe_sessions(limit=limit)

    def preview(
        self,
        conversation_id: str,
        *,
        message_limit: int = 8,
    ) -> SafeSessionPreview:
        return self._picker.preview_safe_session(
            conversation_id,
            message_limit=message_limit,
        )

    def reopen(
        self,
        conversation_id: str,
        *,
        message_limit: int = 8,
    ) -> ReopenedConversation:
        preview = self.preview(conversation_id, message_limit=message_limit)
        return ReopenedConversation(
            conversation_id=preview.summary.conversation_id,
            preview=preview,
        )


class PersistentSessionRuntime:
    """Own the Repository used by one persistent TUI process.

    The object deliberately does not expose its Repository. Callers may obtain
    the read-only command API and ask this boundary to construct an executor
    bound to the same storage. ``close`` is idempotent through the Repository.
    """

    def __init__(self, database: str | Path) -> None:
        self._database = Path(database).expanduser().resolve()
        self._repository = SQLiteRepository(self._database, migrate=True)
        self.commands = SessionCommandAPI(SafeSessionPicker(self._database))

    @property
    def database(self) -> Path:
        return self._database

    def create_executor(
        self,
        model: ChatModel,
        workspace: Path,
        *,
        enable_verification_gate: bool,
        legacy_event_handler,
    ) -> AgentRuntimeExecutor:
        return AgentRuntimeExecutor(
            model,
            workspace,
            enable_verification_gate=enable_verification_gate,
            repository=self._repository,
            legacy_event_handler=legacy_event_handler,
        )

    def close(self) -> None:
        self._repository.close()


def open_persistent_session_runtime(
    database: str | Path,
) -> PersistentSessionRuntime:
    """Open the explicit persistence boundary used by the optional TUI."""

    return PersistentSessionRuntime(database)


__all__ = [
    "PersistentSessionRuntime",
    "ReopenedConversation",
    "SafeSessionPreview",
    "SafeSessionSummary",
    "SessionCommandAPI",
    "SessionPickerLike",
    "open_persistent_session_runtime",
]
