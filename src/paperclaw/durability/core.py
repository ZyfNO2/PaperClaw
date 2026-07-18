"""SQLite reference implementation for durable PaperClaw service runs."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Iterator, Mapping, Protocol

TERMINAL_STATES = frozenset(
    {
        "completed",
        "failed",
        "blocked",
        "stopped",
        "budget_exhausted",
        "recovery_required",
    }
)
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "failed", "stopped", "recovery_required"}),
    "running": frozenset(
        {
            "queued",
            "cancelling",
            "completed",
            "failed",
            "blocked",
            "stopped",
            "budget_exhausted",
            "recovery_required",
        }
    ),
    "cancelling": frozenset({"stopped", "failed", "recovery_required"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "blocked": frozenset(),
    "stopped": frozenset(),
    "budget_exhausted": frozenset(),
    "recovery_required": frozenset(),
}


class DurabilityError(RuntimeError):
    pass


class RunAlreadyExistsError(DurabilityError):
    pass


class DurableRunNotFoundError(DurabilityError):
    pass


class IdempotencyRecordConflictError(DurabilityError):
    pass


class CompareAndSwapError(DurabilityError):
    pass


class InvalidTransitionError(DurabilityError):
    pass


class LeaseConflictError(DurabilityError):
    pass


class ActionInProgressError(DurabilityError):
    pass


@dataclass(frozen=True)
class DurableRun:
    run_id: str
    request_digest: str
    state: str
    version: int
    recovery_attempts: int
    created_at: float
    updated_at: float
    terminal_reason: str | None
    metadata: Mapping[str, Any]

    @property
    def terminal(self) -> bool:
        return self.state in TERMINAL_STATES


@dataclass(frozen=True)
class RunTransition:
    run_id: str
    from_state: str | None
    to_state: str
    version: int
    reason: str
    actor: str
    timestamp: float
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ActionReservation:
    action_key: str
    created: bool
    status: str
    outcome: Mapping[str, Any] | None


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    policy_id: str


@dataclass(frozen=True)
class ReconciliationItem:
    run_id: str
    previous_state: str
    next_state: str
    reason: str
    policy_id: str
    applied: bool


class RecoveryPolicy(Protocol):
    policy_id: str

    def classify(
        self,
        run: DurableRun,
        *,
        action_receipt_count: int,
    ) -> RecoveryDecision: ...


class DefaultRecoveryPolicy:
    policy_id = "default-v1"

    def classify(
        self,
        run: DurableRun,
        *,
        action_receipt_count: int,
    ) -> RecoveryDecision:
        if run.terminal:
            return RecoveryDecision("none", "already_terminal", self.policy_id)
        if run.state == "running":
            if action_receipt_count:
                return RecoveryDecision(
                    "manual",
                    "external_action_receipt_present",
                    self.policy_id,
                )
            if run.recovery_attempts == 0:
                return RecoveryDecision(
                    "requeue",
                    "no_external_action_and_first_recovery",
                    self.policy_id,
                )
            return RecoveryDecision(
                "manual",
                "automatic_recovery_budget_exhausted",
                self.policy_id,
            )
        if run.state == "cancelling":
            return RecoveryDecision(
                "manual",
                "cancellation_outcome_uncertain",
                self.policy_id,
            )
        return RecoveryDecision("none", "state_not_reconciled", self.policy_id)


class SQLiteDurableRunStore:
    """Reference durable store with optimistic transitions and worker leases."""

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = Path(path)
        if not self.path.parent.exists():
            raise ValueError("database parent directory must exist")
        self._clock = clock
        self._initialize()

    def create_run(
        self,
        run_id: str,
        request_digest: str,
        *,
        idempotency_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[DurableRun, bool]:
        _identifier(run_id, "run_id")
        digest = request_digest.strip()
        if not digest:
            raise ValueError("request_digest must not be empty")
        key = _optional_identifier(idempotency_key, "idempotency_key")
        now = self._clock()
        metadata_json = _json_dump(metadata or {})
        with self._transaction() as connection:
            if key is not None:
                existing = connection.execute(
                    "SELECT request_digest, run_id FROM durable_idempotency "
                    "WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None:
                    if existing["request_digest"] != digest:
                        raise IdempotencyRecordConflictError(
                            "idempotency key belongs to another request"
                        )
                    return self._get_run(connection, existing["run_id"]), False
            try:
                connection.execute(
                    """
                    INSERT INTO durable_runs (
                        run_id, request_digest, state, version,
                        recovery_attempts, created_at, updated_at,
                        terminal_reason, metadata_json
                    ) VALUES (?, ?, 'queued', 0, 0, ?, ?, NULL, ?)
                    """,
                    (run_id, digest, now, now, metadata_json),
                )
            except sqlite3.IntegrityError as exc:
                raise RunAlreadyExistsError(f"run already exists: {run_id}") from exc
            connection.execute(
                """
                INSERT INTO durable_run_transitions (
                    run_id, from_state, to_state, version,
                    reason, actor, timestamp, metadata_json
                ) VALUES (?, NULL, 'queued', 0, 'created', 'service', ?, '{}')
                """,
                (run_id, now),
            )
            if key is not None:
                connection.execute(
                    """
                    INSERT INTO durable_idempotency (
                        idempotency_key, request_digest, run_id, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (key, digest, run_id, now),
                )
            return self._get_run(connection, run_id), True

    def get_run(self, run_id: str) -> DurableRun:
        with self._connection() as connection:
            return self._get_run(connection, run_id)

    def transition(
        self,
        run_id: str,
        *,
        expected_state: str,
        expected_version: int,
        next_state: str,
        reason: str,
        actor: str,
        metadata: Mapping[str, Any] | None = None,
        increment_recovery_attempts: bool = False,
    ) -> DurableRun:
        if next_state not in ALLOWED_TRANSITIONS.get(expected_state, frozenset()):
            raise InvalidTransitionError(
                f"transition not allowed: {expected_state} -> {next_state}"
            )
        normalized_reason = _required_text(reason, "reason")
        normalized_actor = _required_text(actor, "actor")
        now = self._clock()
        terminal_reason = normalized_reason if next_state in TERMINAL_STATES else None
        with self._transaction() as connection:
            recovery_delta = 1 if increment_recovery_attempts else 0
            cursor = connection.execute(
                """
                UPDATE durable_runs
                SET state = ?,
                    version = version + 1,
                    recovery_attempts = recovery_attempts + ?,
                    updated_at = ?,
                    terminal_reason = ?
                WHERE run_id = ? AND state = ? AND version = ?
                """,
                (
                    next_state,
                    recovery_delta,
                    now,
                    terminal_reason,
                    run_id,
                    expected_state,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise CompareAndSwapError(
                    f"state/version mismatch for run {run_id}"
                )
            new_version = expected_version + 1
            connection.execute(
                """
                INSERT INTO durable_run_transitions (
                    run_id, from_state, to_state, version,
                    reason, actor, timestamp, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    expected_state,
                    next_state,
                    new_version,
                    normalized_reason,
                    normalized_actor,
                    now,
                    _json_dump(metadata or {}),
                ),
            )
            if next_state in TERMINAL_STATES or next_state == "queued":
                connection.execute(
                    "DELETE FROM durable_worker_leases WHERE run_id = ?",
                    (run_id,),
                )
            return self._get_run(connection, run_id)

    def claim_next(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 30.0,
    ) -> DurableRun | None:
        worker = _required_text(worker_id, "worker_id")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._clock()
        with self._transaction() as connection:
            row = connection.execute(
                """
                SELECT * FROM durable_runs
                WHERE state = 'queued'
                ORDER BY created_at, run_id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            version = int(row["version"])
            cursor = connection.execute(
                """
                UPDATE durable_runs
                SET state = 'running', version = version + 1, updated_at = ?
                WHERE run_id = ? AND state = 'queued' AND version = ?
                """,
                (now, row["run_id"], version),
            )
            if cursor.rowcount != 1:
                raise CompareAndSwapError("queued run changed during claim")
            new_version = version + 1
            connection.execute(
                """
                INSERT INTO durable_worker_leases (
                    run_id, worker_id, expires_at, run_version
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    worker_id = excluded.worker_id,
                    expires_at = excluded.expires_at,
                    run_version = excluded.run_version
                """,
                (row["run_id"], worker, now + lease_seconds, new_version),
            )
            connection.execute(
                """
                INSERT INTO durable_run_transitions (
                    run_id, from_state, to_state, version,
                    reason, actor, timestamp, metadata_json
                ) VALUES (?, 'queued', 'running', ?, 'worker_claimed', ?, ?, '{}')
                """,
                (row["run_id"], new_version, worker, now),
            )
            return self._get_run(connection, row["run_id"])

    def renew_lease(
        self,
        run_id: str,
        worker_id: str,
        *,
        expected_run_version: int,
        lease_seconds: float = 30.0,
    ) -> float:
        worker = _required_text(worker_id, "worker_id")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = self._clock()
        expires_at = now + lease_seconds
        with self._transaction() as connection:
            run = self._get_run(connection, run_id)
            if run.version != expected_run_version or run.state not in {
                "running",
                "cancelling",
            }:
                raise LeaseConflictError("run is not owned at expected version")
            cursor = connection.execute(
                """
                UPDATE durable_worker_leases
                SET expires_at = ?, run_version = ?
                WHERE run_id = ? AND worker_id = ?
                """,
                (expires_at, expected_run_version, run_id, worker),
            )
            if cursor.rowcount != 1:
                raise LeaseConflictError("worker does not own lease")
        return expires_at

    def release_lease(self, run_id: str, worker_id: str) -> bool:
        worker = _required_text(worker_id, "worker_id")
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM durable_worker_leases "
                "WHERE run_id = ? AND worker_id = ?",
                (run_id, worker),
            )
            return cursor.rowcount == 1

    def list_recovery_candidates(self) -> tuple[DurableRun, ...]:
        now = self._clock()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT r.*
                FROM durable_runs AS r
                LEFT JOIN durable_worker_leases AS l ON l.run_id = r.run_id
                WHERE r.state IN ('running', 'cancelling')
                  AND (l.run_id IS NULL OR l.expires_at <= ?)
                ORDER BY r.updated_at, r.run_id
                """,
                (now,),
            ).fetchall()
            return tuple(_row_to_run(row) for row in rows)

    def reserve_action(
        self,
        run_id: str,
        logical_step_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ActionReservation:
        self.get_run(run_id)
        action_key = make_action_key(
            run_id, logical_step_id, tool_name, arguments
        )
        now = self._clock()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO durable_action_receipts (
                        action_key, run_id, logical_step_id, tool_name,
                        arguments_digest, status, outcome_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, ?)
                    """,
                    (
                        action_key,
                        run_id,
                        _required_text(logical_step_id, "logical_step_id"),
                        _required_text(tool_name, "tool_name"),
                        _arguments_digest(arguments),
                        now,
                        now,
                    ),
                )
                return ActionReservation(action_key, True, "pending", None)
            except sqlite3.IntegrityError:
                row = connection.execute(
                    "SELECT status, outcome_json FROM durable_action_receipts "
                    "WHERE action_key = ?",
                    (action_key,),
                ).fetchone()
                if row is None:
                    raise
                outcome = (
                    json.loads(row["outcome_json"])
                    if row["outcome_json"] is not None
                    else None
                )
                return ActionReservation(
                    action_key,
                    False,
                    row["status"],
                    outcome,
                )

    def complete_action(
        self,
        action_key: str,
        outcome: Mapping[str, Any],
    ) -> ActionReservation:
        now = self._clock()
        encoded = _json_dump(outcome)
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT status, outcome_json FROM durable_action_receipts "
                "WHERE action_key = ?",
                (action_key,),
            ).fetchone()
            if row is None:
                raise DurabilityError(f"unknown action receipt: {action_key}")
            if row["status"] == "completed":
                return ActionReservation(
                    action_key,
                    False,
                    "completed",
                    json.loads(row["outcome_json"]),
                )
            if row["status"] != "pending":
                raise DurabilityError("action receipt is not pending")
            connection.execute(
                """
                UPDATE durable_action_receipts
                SET status = 'completed', outcome_json = ?, updated_at = ?
                WHERE action_key = ? AND status = 'pending'
                """,
                (encoded, now, action_key),
            )
            return ActionReservation(
                action_key, False, "completed", json.loads(encoded)
            )

    def fail_action(
        self,
        action_key: str,
        *,
        error_type: str,
        message: str,
    ) -> ActionReservation:
        now = self._clock()
        outcome = {
            "error_type": _required_text(error_type, "error_type")[:120],
            "message": _required_text(message, "message")[:500],
        }
        encoded = _json_dump(outcome)
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE durable_action_receipts
                SET status = 'failed', outcome_json = ?, updated_at = ?
                WHERE action_key = ? AND status = 'pending'
                """,
                (encoded, now, action_key),
            )
            if cursor.rowcount != 1:
                raise DurabilityError("action receipt is not pending")
        return ActionReservation(action_key, False, "failed", outcome)

    def action_receipt_count(self, run_id: str) -> int:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM durable_action_receipts "
                "WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            return int(row["count"])

    def transitions(self, run_id: str) -> tuple[RunTransition, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM durable_run_transitions
                WHERE run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
            return tuple(
                RunTransition(
                    run_id=row["run_id"],
                    from_state=row["from_state"],
                    to_state=row["to_state"],
                    version=int(row["version"]),
                    reason=row["reason"],
                    actor=row["actor"],
                    timestamp=float(row["timestamp"]),
                    metadata=json.loads(row["metadata_json"]),
                )
                for row in rows
            )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS durable_schema (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    version INTEGER NOT NULL
                );
                INSERT INTO durable_schema(singleton, version)
                VALUES (1, 1)
                ON CONFLICT(singleton) DO NOTHING;

                CREATE TABLE IF NOT EXISTS durable_runs (
                    run_id TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    recovery_attempts INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    terminal_reason TEXT,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS durable_run_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES durable_runs(run_id),
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS durable_worker_leases (
                    run_id TEXT PRIMARY KEY REFERENCES durable_runs(run_id),
                    worker_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    run_version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS durable_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    run_id TEXT NOT NULL REFERENCES durable_runs(run_id),
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS durable_action_receipts (
                    action_key TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES durable_runs(run_id),
                    logical_step_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    outcome_json TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS durable_runs_state_idx
                ON durable_runs(state, updated_at);
                CREATE INDEX IF NOT EXISTS durable_transitions_run_idx
                ON durable_run_transitions(run_id, id);
                CREATE INDEX IF NOT EXISTS durable_actions_run_idx
                ON durable_action_receipts(run_id);
                """
            )
            row = connection.execute(
                "SELECT version FROM durable_schema WHERE singleton = 1"
            ).fetchone()
            if row is None or int(row["version"]) != self.SCHEMA_VERSION:
                raise DurabilityError("unsupported durable schema version")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except Exception:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _get_run(connection: sqlite3.Connection, run_id: str) -> DurableRun:
        row = connection.execute(
            "SELECT * FROM durable_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise DurableRunNotFoundError(f"unknown durable run: {run_id}")
        return _row_to_run(row)


class RecoveryCoordinator:
    def __init__(
        self,
        store: SQLiteDurableRunStore,
        *,
        policy: RecoveryPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or DefaultRecoveryPolicy()

    def reconcile(self) -> tuple[ReconciliationItem, ...]:
        results: list[ReconciliationItem] = []
        for run in self._store.list_recovery_candidates():
            action_count = self._store.action_receipt_count(run.run_id)
            try:
                decision = self._policy.classify(
                    run, action_receipt_count=action_count
                )
            except Exception as exc:
                decision = RecoveryDecision(
                    "manual",
                    f"policy_error:{type(exc).__name__}",
                    getattr(self._policy, "policy_id", "unknown"),
                )
            if decision.action == "none":
                results.append(
                    ReconciliationItem(
                        run.run_id,
                        run.state,
                        run.state,
                        decision.reason,
                        decision.policy_id,
                        False,
                    )
                )
                continue
            next_state = (
                "queued" if decision.action == "requeue" else "recovery_required"
            )
            try:
                self._store.transition(
                    run.run_id,
                    expected_state=run.state,
                    expected_version=run.version,
                    next_state=next_state,
                    reason=decision.reason,
                    actor=f"recovery:{decision.policy_id}",
                    metadata={"policy_id": decision.policy_id},
                    increment_recovery_attempts=decision.action == "requeue",
                )
            except CompareAndSwapError:
                results.append(
                    ReconciliationItem(
                        run.run_id,
                        run.state,
                        run.state,
                        "concurrent_reconciliation",
                        decision.policy_id,
                        False,
                    )
                )
            else:
                results.append(
                    ReconciliationItem(
                        run.run_id,
                        run.state,
                        next_state,
                        decision.reason,
                        decision.policy_id,
                        True,
                    )
                )
        return tuple(results)


class IdempotentActionExecutor:
    """Execute a deterministic side-effect callback at most once per action key."""

    def __init__(self, store: SQLiteDurableRunStore) -> None:
        self._store = store

    def execute(
        self,
        run_id: str,
        logical_step_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        action: Callable[[], Mapping[str, Any]],
    ) -> Mapping[str, Any]:
        reservation = self._store.reserve_action(
            run_id, logical_step_id, tool_name, arguments
        )
        if not reservation.created:
            if reservation.status == "completed" and reservation.outcome is not None:
                return reservation.outcome
            raise ActionInProgressError(
                f"action already reserved with status={reservation.status}"
            )
        try:
            outcome = action()
        except Exception as exc:
            self._store.fail_action(
                reservation.action_key,
                error_type=type(exc).__name__,
                message=str(exc),
            )
            raise
        return self._store.complete_action(
            reservation.action_key, outcome
        ).outcome or {}


def make_action_key(
    run_id: str,
    logical_step_id: str,
    tool_name: str,
    arguments: Mapping[str, Any],
) -> str:
    payload = {
        "run_id": _required_text(run_id, "run_id"),
        "logical_step_id": _required_text(logical_step_id, "logical_step_id"),
        "tool_name": _required_text(tool_name, "tool_name"),
        "arguments_digest": _arguments_digest(arguments),
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "act-" + hashlib.sha256(encoded).hexdigest()


def _row_to_run(row: sqlite3.Row) -> DurableRun:
    return DurableRun(
        run_id=row["run_id"],
        request_digest=row["request_digest"],
        state=row["state"],
        version=int(row["version"]),
        recovery_attempts=int(row["recovery_attempts"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        terminal_reason=row["terminal_reason"],
        metadata=json.loads(row["metadata_json"]),
    )


def _arguments_digest(arguments: Mapping[str, Any]) -> str:
    encoded = _json_dump(arguments).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_dump(value: Mapping[str, Any]) -> str:
    sanitized = _sanitize_metadata(value)
    return json.dumps(
        sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sanitize_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:4_000]
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:100]:
            key = str(raw_key)[:100]
            normalized = key.lower().replace("-", "_")
            if any(
                marker in normalized
                for marker in (
                    "api_key",
                    "authorization",
                    "password",
                    "secret",
                    "credential",
                )
            ):
                continue
            output[key] = _sanitize_metadata(raw_value, depth=depth + 1)
        return output
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _sanitize_metadata(item, depth=depth + 1)
            for item in list(value)[:100]
        ]
    return str(value)[:4_000]


def _identifier(value: str, name: str) -> str:
    normalized = _required_text(value, name)
    if len(normalized) > 200 or any(char.isspace() for char in normalized):
        raise ValueError(f"{name} must be a compact identifier")
    return normalized


def _optional_identifier(value: str | None, name: str) -> str | None:
    return None if value is None else _identifier(value, name)


def _required_text(value: str, name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized
