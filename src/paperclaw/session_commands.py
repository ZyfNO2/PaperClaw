"""Application boundary for safe session discovery and persistent TUI runs.

The Textual client consumes this module without importing Context/Repository or
SQLite implementation details. Storage policy remains in ``paperclaw.context``;
this layer exposes only stable commands and executor construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from paperclaw.context.repository import SQLiteRepository
from paperclaw.context.session import SessionService
from paperclaw.context.session_picker import (
    SafeSessionPicker,
    SafeSessionPreview,
    SafeSessionSummary,
)
from paperclaw.harness import ContextOrchestratedAgentRuntimeExecutor
from paperclaw.memory import build_memory_runtime
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


class SessionOperator:
    """Operator inspection/resume facade over the existing SessionService."""

    def __init__(self, repository: SQLiteRepository) -> None:
        self._repository = repository

    def inspect(self, session_id: str, *, max_events: int = 100) -> dict[str, Any]:
        if max_events < 1:
            raise ValueError("max_events must be positive")
        session = self._open(session_id)
        reconstruction = session.reconstruct()
        events = session.list_events()
        task_state_summaries = tuple(
            {
                "task_id": state.get("task_id"),
                "status": state.get("status"),
                "revision": state.get("revision"),
            }
            for state in reconstruction.task_states
        )
        reconstruction_payload = reconstruction.to_dict()
        reconstruction_payload["task_states"] = list(task_state_summaries)
        return {
            "session_id": reconstruction.session_id,
            "run_id": reconstruction.run_id,
            "reconstruction": reconstruction_payload,
            "events": [
                {
                    "event_id": event.event_id,
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "created_at": event.created_at,
                    "idempotency_key": event.idempotency_key,
                }
                for event in events[-max_events:]
            ],
        }

    def context(self, session_id: str) -> dict[str, Any]:
        session = self._open(session_id)
        snapshots = self._repository.list_snapshots(session.run_id)
        latest = snapshots[-1] if snapshots else None
        return {
            "session_id": session.conversation_id,
            "run_id": session.run_id,
            "latest": latest.to_dict() if latest is not None else None,
            "snapshot_count": len(snapshots),
        }

    def resume(
        self,
        session_id: str,
        *,
        permission_mode: str = "preserve",
    ) -> dict[str, Any]:
        return self._open(session_id).resume(permission_mode=permission_mode).to_dict()

    def _open(self, session_id: str) -> SessionService:
        normalized = session_id.strip()
        if not normalized:
            raise ValueError("session_id must not be empty")
        run = self._repository.get_run(normalized)
        if run is None:
            run = self._repository.latest_run_for_conversation(normalized)
        if run is None:
            raise ValueError(f"session does not exist: {normalized}")
        return SessionService.reopen(
            self._repository,
            conversation_id=str(run["conversation_id"]),
            run_id=str(run["run_id"]),
            agent_id="operator",
        )


class SessionCommandAPI:
    """UI-agnostic commands for listing, previewing, and reopening sessions.

    ``reopen`` is intentionally side-effect free. It revalidates that the
    conversation remains safely closed and returns the conversation_id. The
    caller creates a fresh QueryEngine; the first subsequent submission creates
    a new Run in that conversation.
    """

    def __init__(
        self,
        picker: SessionPickerLike,
        operator: SessionOperator | None = None,
    ) -> None:
        self._picker = picker
        self._operator = operator

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

    def inspect(self, session_id: str, *, max_events: int = 100) -> dict[str, Any]:
        if self._operator is None:
            raise RuntimeError("session operator is unavailable")
        return self._operator.inspect(session_id, max_events=max_events)

    def context(self, session_id: str) -> dict[str, Any]:
        if self._operator is None:
            raise RuntimeError("session operator is unavailable")
        return self._operator.context(session_id)

    def resume(
        self,
        session_id: str,
        *,
        permission_mode: str = "preserve",
    ) -> dict[str, Any]:
        if self._operator is None:
            raise RuntimeError("session operator is unavailable")
        return self._operator.resume(session_id, permission_mode=permission_mode)


class PersistentSessionRuntime:
    """Own the Repository used by one persistent TUI process.

    The object deliberately does not expose its Repository. Callers may obtain
    the read-only command API and ask this boundary to construct an executor
    bound to the same storage. ``close`` is idempotent through the Repository.
    """

    def __init__(self, database: str | Path) -> None:
        self._database = Path(database).expanduser().resolve()
        self._repository = SQLiteRepository(self._database, migrate=True)
        self.commands = SessionCommandAPI(
            SafeSessionPicker(self._database),
            SessionOperator(self._repository),
        )

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
    ) -> Any:
        components = build_memory_runtime(
            workspace,
            repository=self._repository,
        )
        return ContextOrchestratedAgentRuntimeExecutor(
            model,
            workspace,
            registry=components.tool_registry,
            enable_verification_gate=enable_verification_gate,
            repository=self._repository,
            legacy_event_handler=legacy_event_handler,
            context_policy=components.context_policy,
            context_source_registry=components.source_registry,
            memory_service=components.structured_memory_service,
            project_scope_id=(
                components.project_manifest.project_id
                if components.project_manifest is not None
                else None
            ),
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
    "SessionOperator",
    "SessionPickerLike",
    "open_persistent_session_runtime",
]
