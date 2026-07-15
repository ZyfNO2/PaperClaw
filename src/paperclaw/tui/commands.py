"""Stable command boundary for the v0.06.1 safe session picker slice."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from paperclaw.context.session_picker import (
    SafeSessionPreview,
    SafeSessionSummary,
)


class SessionPickerLike(Protocol):
    def list_safe_sessions(self, *, limit: int = 20) -> tuple[SafeSessionSummary, ...]: ...

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
