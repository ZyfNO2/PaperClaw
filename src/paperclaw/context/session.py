"""SessionService and EventSink for the v0.04 Context Runtime.

This module bridges the Runtime (Coordinator / Worker / Agent Loop / future
InstrumentedFlowRunner) and the SQLite Repository. It exposes:

- ``EventSink``: a Protocol that Runtime components implement to receive
  structured events. The Runtime calls ``emit`` without knowing whether the
  sink persists, prints, or drops the event.
- ``NullEventSink``: parity-mode sink. ``emit`` is a no-op so the Runtime
  behaves identically to the original PocketFlow Flow without persistence.
- ``SqliteEventSink``: persists events via ``SQLiteRepository`` using the
  concurrency-safe ``append_event_with_auto_sequence`` path.
- ``SessionService``: Runtime-facing manager. Owns conversation_id, run_id,
  agent_id, and exposes ``emit`` / ``update_task_state`` /
  ``record_side_effect`` / ``close``. Supports both fresh ``open`` and
  ``reopen`` for crash-safe resume.

Design constraints (SOP §5.3 / §10):

- Mutating tool calls (Bash, file write/edit, external API) MUST call
  ``record_side_effect`` BEFORE and AFTER the operation so the idempotency
  ledger can detect replays. The Runtime decides whether to proceed.
- Long operations (model call, Bash, file I/O) must NOT hold the SQLite
  write transaction; ``SqliteEventSink.emit`` opens a short transaction per
  event under the Repository writer lock.
- The sink is the only sanctioned path for Runtime to write events. Direct
  Repository access from nodes is discouraged.
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from paperclaw.context.contracts import SessionEvent, utc_now_iso
from paperclaw.context.repository import Repository, SQLiteRepository


# ---------------------------------------------------------------------------
# EventSink protocol and reference implementations
# ---------------------------------------------------------------------------


class EventSink(Protocol):
    """Where Runtime events go.

    The Protocol decouples nodes (Coordinator / Worker / future
    InstrumentedFlowRunner) from the persistence layer. A Runtime that wants
    parity with original PocketFlow behavior uses ``NullEventSink``; a Runtime
    that wants persistence uses ``SqliteEventSink``.

    ``emit`` MUST be safe to call from any thread. Implementations are
    responsible for their own locking.
    """

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_id: str = "",
        task_id: str | None = None,
    ) -> int:
        """Record one event and return its sequence number.

        Returns 0 when the sink does not allocate sequences (e.g.
        ``NullEventSink``). Callers MUST NOT treat 0 as an error; it means
        "this sink does not persist ordering".
        """
        ...


class NullEventSink:
    """No-op sink for parity mode.

    Preserves the original PocketFlow Flow behavior: no events, no
    sequences, no persistence. Used when the Runtime wants to disable
    observability without changing call sites.
    """

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_id: str = "",
        task_id: str | None = None,
    ) -> int:
        return 0


class SqliteEventSink:
    """Persist events to SQLite via the Repository.

    Uses ``Repository.append_event_with_auto_sequence`` so concurrent emitters
    cannot race on the same sequence number. Each emit is one short write
    transaction; long operations (model calls, Bash, file I/O) MUST NOT be
    performed inside ``emit``.

    The sink is bound to a single (conversation_id, run_id) pair. Multi-run
    sessions should create one sink per run via ``SessionService.event_sink``.
    """

    def __init__(
        self,
        repo: Repository,
        *,
        conversation_id: str,
        run_id: str,
        agent_id: str = "runtime",
    ):
        self._repo = repo
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._default_agent_id = agent_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        agent_id: str = "",
        task_id: str | None = None,
    ) -> int:
        """Append one event and return the assigned sequence.

        ``payload`` is augmented with ``schema_version`` (default 1) and
        ``task_id`` if provided. The original payload dict is NOT mutated;
        a shallow copy is persisted so callers can re-use the dict.

        Returns the sequence number. If a duplicate ``event_id`` was already
        committed (idempotent success), returns the original sequence.
        """
        # Build the persisted payload without mutating caller's dict.
        persisted = dict(payload)
        persisted.setdefault("schema_version", 1)
        if task_id is not None:
            persisted.setdefault("task_id", task_id)
        if agent_id:
            persisted.setdefault("agent_id", agent_id)
        elif self._default_agent_id:
            persisted.setdefault("agent_id", self._default_agent_id)

        # event_id is deterministic-ish: type + uuid suffix. The Repository
        # uses event_id for idempotency, so a replay of the same logical
        # operation MUST reuse the same event_id. Callers that need
        # idempotency should pass their own event_id via payload['event_id']
        # — this sink will honor it.
        event_id = persisted.pop("event_id", None) or f"evt-{uuid4().hex[:12]}"

        appended, sequence = self._repo.append_event_with_auto_sequence(
            event_id=event_id,
            conversation_id=self._conversation_id,
            run_id=self._run_id,
            event_type=event_type,
            payload=persisted,
        )
        return sequence


# ---------------------------------------------------------------------------
# SessionService
# ---------------------------------------------------------------------------


class SessionService:
    """Runtime-facing session manager.

    Owns conversation_id, run_id, and the default agent_id. Exposes:

    - ``emit`` / ``event_sink``: structured event emission.
    - ``update_task_state`` / ``get_task_state``: TaskState revision control.
    - ``record_side_effect``: idempotency ledger for mutating operations.
    - ``last_committed_sequence``: read-side for resume decisions.
    - ``close``: ends the Run with a stop_reason.

    Usage::

        # Fresh session
        svc = SessionService.open(repo, conversation_id="conv-1")
        svc.emit("flow.started", {"plan": "..."})
        ...
        svc.close(stop_reason="done")

        # Reopen (after process exit)
        svc = SessionService.reopen(repo, conversation_id="conv-1", run_id="run-xyz")
        last = svc.last_committed_sequence()

    The service does NOT own the Repository. Callers are responsible for
    closing the Repository when the process exits.
    """

    def __init__(
        self,
        repo: Repository,
        *,
        conversation_id: str,
        run_id: str,
        agent_id: str = "runtime",
        sink: EventSink | None = None,
    ):
        self._repo = repo
        self._conversation_id = conversation_id
        self._run_id = run_id
        self._agent_id = agent_id
        # Sink defaults to a SqliteEventSink bound to this run. Callers can
        # pass NullEventSink to disable persistence for parity mode.
        self._sink: EventSink = sink or SqliteEventSink(
            repo,
            conversation_id=conversation_id,
            run_id=run_id,
            agent_id=agent_id,
        )
        # Closed flag makes close() idempotent. A second close() is a no-op
        # so the audit log never gets two flow.stopped events for the same
        # run and the Repository's runs.ended_at is not overwritten.
        self._closed = False

    # ------------------------------------------------------------------
    # Constructors
    # ------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        repo: Repository,
        *,
        conversation_id: str,
        agent_id: str = "runtime",
        metadata: dict[str, Any] | None = None,
        sink: EventSink | None = None,
    ) -> "SessionService":
        """Start a fresh conversation + run.

        ``conversation_id`` is caller-chosen (e.g. "session-2026-07-14-1").
        ``run_id`` is generated as ``run-<uuid_hex>`` and persisted via
        ``repo.start_run`` so the runs table is the authoritative record.
        """
        repo.create_conversation(conversation_id)
        run_id = f"run-{uuid4().hex[:12]}"
        repo.start_run(
            run_id=run_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            role=agent_id,
            metadata=metadata,
        )
        svc = cls(
            repo,
            conversation_id=conversation_id,
            run_id=run_id,
            agent_id=agent_id,
            sink=sink,
        )
        return svc

    @classmethod
    def reopen(
        cls,
        repo: Repository,
        *,
        conversation_id: str,
        run_id: str,
        agent_id: str = "runtime",
        sink: EventSink | None = None,
    ) -> "SessionService":
        """Reopen an existing run by ID.

        Does NOT advance sequence or emit any event. The Runtime is expected
        to inspect ``last_committed_sequence`` and the latest Checkpoint
        before deciding whether to resume or raise ``recovery_required``.
        """
        return cls(
            repo,
            conversation_id=conversation_id,
            run_id=run_id,
            agent_id=agent_id,
            sink=sink,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def conversation_id(self) -> str:
        return self._conversation_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def sink(self) -> EventSink:
        """The bound EventSink. Pass this to Runtime components."""
        return self._sink

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        agent_id: str = "",
        task_id: str | None = None,
    ) -> int:
        """Emit one Runtime event via the bound sink.

        Returns the assigned sequence number (0 for NullEventSink).
        Raises ``RuntimeError`` if the session has been closed. This guard
        prevents the audit log from gaining events after ``flow.stopped``.
        """
        if self._closed:
            raise RuntimeError(
                f"session {self._run_id} is closed; cannot emit {event_type}"
            )
        return self._sink.emit(
            event_type,
            payload or {},
            agent_id=agent_id or self._agent_id,
            task_id=task_id,
        )

    def event_sink(self, *, agent_id: str | None = None) -> EventSink:
        """Return a sink bound to this session.

        For MultiAgent runs, pass ``agent_id`` to label events from a
        specific Worker. The sink still writes to the same run_id; only the
        default ``agent_id`` field differs.
        """
        if agent_id is None or agent_id == self._agent_id:
            return self._sink
        # Bound sink for a different agent (e.g. a Worker). Shares the run.
        return SqliteEventSink(
            self._repo,
            conversation_id=self._conversation_id,
            run_id=self._run_id,
            agent_id=agent_id,
        )

    # ------------------------------------------------------------------
    # Task state
    # ------------------------------------------------------------------

    def update_task_state(
        self,
        task_id: str,
        status: str,
        payload: dict[str, Any],
        *,
        bump_revision: bool = True,
    ) -> int:
        """Upsert a TaskState row and return the new revision."""
        return self._repo.upsert_task_state(
            task_id,
            self._run_id,
            status,
            payload,
            bump_revision=bump_revision,
        )

    def get_task_state(self, task_id: str) -> dict[str, Any] | None:
        return self._repo.get_task_state(task_id)

    def list_task_states(self) -> list[dict[str, Any]]:
        return self._repo.list_task_states(self._run_id)

    # ------------------------------------------------------------------
    # Idempotency for side-effecting operations
    # ------------------------------------------------------------------

    def record_side_effect(
        self,
        operation_id: str,
        event_type: str,
        payload_hash: str,
    ) -> bool:
        """Record a side-effecting operation idempotently.

        Returns True if this is the first time the operation_id was seen
        (caller should proceed with the side effect). Returns False if the
        operation was already recorded (caller MUST skip the side effect to
        avoid duplicate writes).

        Use this for Bash, file_write, file_edit, and external API calls.
        ``operation_id`` should be deterministic from the operation arguments
        (e.g. ``"bash:<hash_of_command_cwd>"``) so a replay produces the
        same id and is detected.
        """
        return self._repo.record_idempotent_operation(
            operation_id=operation_id,
            event_type=event_type,
            payload_hash=payload_hash,
            run_id=self._run_id,
        )

    # ------------------------------------------------------------------
    # Read-side for resume decisions
    # ------------------------------------------------------------------

    def last_committed_sequence(self) -> int:
        return self._repo.last_committed_sequence(self._run_id)

    def list_events(self, since_sequence: int = 0) -> list[SessionEvent]:
        return self._repo.list_events(self._run_id, since_sequence=since_sequence)

    def latest_checkpoint(self):
        return self._repo.latest_checkpoint(self._run_id)

    # ------------------------------------------------------------------
    # Messages (raw conversation log)
    # ------------------------------------------------------------------

    def append_message(
        self,
        role: str,
        content: str,
        *,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Append one raw message to the conversation log.

        Uses ``append_message_with_auto_sequence`` so concurrent callers
        (e.g. MultiAgent Workers in the same conversation) cannot race on
        the sequence number. Messages have their own monotonic sequence
        within a conversation, distinct from the SessionEvent sequence.
        """
        mid = message_id or f"msg-{uuid4().hex[:12]}"
        self._repo.append_message_with_auto_sequence(
            message_id=mid,
            conversation_id=self._conversation_id,
            run_id=self._run_id,
            role=role,
            content=content,
            metadata=metadata,
        )
        return mid

    def list_messages(self) -> list[dict[str, Any]]:
        return self._repo.list_messages(self._conversation_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self, stop_reason: str | None = None) -> None:
        """End the run with a stop_reason.

        Idempotent: a second call is a no-op. The first call records
        ``runs.ended_at`` and emits one ``flow.stopped`` event so the audit
        log has exactly one terminal event per run.

        Ordering rationale (crash-safe): ``end_run`` is recorded BEFORE the
        ``flow.stopped`` event. If the process dies between the two writes,
        the run is marked ended but no terminal event exists — resume logic
        that inspects ``last_committed_sequence`` will treat this as
        "already stopped" rather than silently continuing. The reverse order
        (emit then end_run) would be more dangerous: a crash after emit
        would leave a ``flow.stopped`` event with ``runs.ended_at IS NULL``,
        and resume might think the run is still active.
        """
        if self._closed:
            return
        self._closed = True
        self._repo.end_run(self._run_id, stop_reason=stop_reason)
        # Emit the terminal event AFTER end_run so runs.ended_at is already
        # persisted. If emit fails, the run is still marked ended; we swallow
        # the sink error so close() itself never raises.
        try:
            self._sink.emit(
                "flow.stopped",
                {"schema_version": 1, "stop_reason": stop_reason},
                agent_id=self._agent_id,
            )
        except Exception:
            # Closing must not fail because of a sink error. The run is
            # already ended in the Repository.
            pass


# ---------------------------------------------------------------------------
# Convenience: open a SessionService from a db path
# ---------------------------------------------------------------------------


def open_session(
    db_path: str,
    *,
    conversation_id: str | None = None,
    agent_id: str = "runtime",
    backup_dir: str | None = None,
) -> tuple[SQLiteRepository, SessionService]:
    """Open a Repository + SessionService pair.

    Returns ``(repo, session)``. Caller is responsible for closing both
    when done. Convenience helper for CLI entrypoints and demos.
    """
    from pathlib import Path

    repo = SQLiteRepository(
        db_path,
        backup_dir=Path(backup_dir) if backup_dir else None,
        migrate=True,
    )
    conv = conversation_id or f"conv-{uuid4().hex[:8]}"
    session = SessionService.open(repo, conversation_id=conv, agent_id=agent_id)
    return repo, session


def reopen_session(
    db_path: str,
    *,
    conversation_id: str,
    run_id: str,
    agent_id: str = "runtime",
    backup_dir: str | None = None,
) -> tuple[SQLiteRepository, SessionService]:
    """Reopen an existing session for resume."""
    from pathlib import Path

    repo = SQLiteRepository(
        db_path,
        backup_dir=Path(backup_dir) if backup_dir else None,
        migrate=True,
    )
    session = SessionService.reopen(
        repo,
        conversation_id=conversation_id,
        run_id=run_id,
        agent_id=agent_id,
    )
    return repo, session
