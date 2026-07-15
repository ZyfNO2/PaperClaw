"""Read-only discovery and preview of safely closed conversations.

The picker deliberately reopens a conversation, not an ended Run. Selecting a
conversation only returns validated metadata and message previews; the next
QueryEngine submission creates a fresh Run under the same conversation_id.
Crash reconciliation, active-process reconnect, and arbitrary checkpoint resume
remain outside this slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from urllib.parse import quote


class SessionPickerError(RuntimeError):
    """Raised when the session catalog cannot be read safely."""


@dataclass(frozen=True)
class SafeSessionSummary:
    """One conversation whose Runs have all reached an orderly close."""

    conversation_id: str
    conversation_created_at: str
    latest_run_id: str
    latest_run_created_at: str
    latest_run_ended_at: str
    stop_reason: str | None
    message_count: int


@dataclass(frozen=True)
class SessionMessagePreview:
    """Sanitized user-visible message excerpt."""

    role: str
    content: str
    created_at: str


@dataclass(frozen=True)
class SafeSessionPreview:
    """Read-only preview returned before a conversation is selected."""

    summary: SafeSessionSummary
    messages: tuple[SessionMessagePreview, ...]


class SafeSessionPicker:
    """Read-only catalog for safe conversation reopen candidates.

    A conversation is eligible only when it has at least one Run, every Run has
    ``ended_at`` set, and the latest Run also has a terminal timestamp. The
    catalog never migrates or writes the database.
    """

    def __init__(self, database: str | Path, *, message_excerpt_limit: int = 500) -> None:
        if message_excerpt_limit < 1:
            raise ValueError("message_excerpt_limit must be positive")
        self._database = Path(database).expanduser().resolve()
        self._message_excerpt_limit = message_excerpt_limit

    @property
    def database(self) -> Path:
        return self._database

    def list_safe_sessions(self, *, limit: int = 20) -> tuple[SafeSessionSummary, ...]:
        """Return newest safe conversations first."""

        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        with self._connect() as connection:
            rows = connection.execute(
                _SAFE_SESSION_QUERY + " ORDER BY latest_run_ended_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(_summary_from_row(row) for row in rows)

    def preview_safe_session(
        self,
        conversation_id: str,
        *,
        message_limit: int = 8,
    ) -> SafeSessionPreview:
        """Revalidate one candidate and return its latest message excerpts."""

        normalized = conversation_id.strip()
        if not normalized:
            raise ValueError("conversation_id must not be empty")
        if message_limit < 1 or message_limit > 50:
            raise ValueError("message_limit must be between 1 and 50")

        with self._connect() as connection:
            row = connection.execute(
                _SAFE_SESSION_QUERY + " AND c.conversation_id = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                raise SessionPickerError(
                    "conversation is not safely closed or does not exist: "
                    f"{normalized}"
                )
            message_rows = connection.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? "
                "ORDER BY sequence DESC LIMIT ?",
                (normalized, message_limit),
            ).fetchall()

        messages = tuple(
            SessionMessagePreview(
                role=_safe_role(str(message["role"])),
                content=_excerpt(
                    str(message["content"]),
                    limit=self._message_excerpt_limit,
                ),
                created_at=str(message["created_at"]),
            )
            for message in reversed(message_rows)
        )
        return SafeSessionPreview(summary=_summary_from_row(row), messages=messages)

    def _connect(self) -> sqlite3.Connection:
        if not self._database.is_file():
            raise SessionPickerError(
                f"database path does not exist or is not a file: {self._database}"
            )
        try:
            uri_path = quote(self._database.as_posix(), safe="/:")
            connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            _validate_schema(connection)
            return connection
        except sqlite3.DatabaseError as exc:
            raise SessionPickerError(
                f"unable to read session database: {type(exc).__name__}: {str(exc)[:300]}"
            ) from exc


_SAFE_SESSION_QUERY = """
SELECT
    c.conversation_id AS conversation_id,
    c.created_at AS conversation_created_at,
    latest.run_id AS latest_run_id,
    latest.created_at AS latest_run_created_at,
    latest.ended_at AS latest_run_ended_at,
    latest.stop_reason AS stop_reason,
    (
        SELECT COUNT(*)
        FROM messages message_count
        WHERE message_count.conversation_id = c.conversation_id
    ) AS message_count
FROM conversations c
JOIN runs latest
  ON latest.run_id = (
      SELECT candidate.run_id
      FROM runs candidate
      WHERE candidate.conversation_id = c.conversation_id
      ORDER BY candidate.created_at DESC, candidate.run_id DESC
      LIMIT 1
  )
WHERE latest.ended_at IS NOT NULL
  AND NOT EXISTS (
      SELECT 1
      FROM runs active
      WHERE active.conversation_id = c.conversation_id
        AND active.ended_at IS NULL
  )
"""


def _validate_schema(connection: sqlite3.Connection) -> None:
    required = {"conversations", "runs", "messages"}
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    present = {str(row[0]) for row in rows}
    missing = sorted(required - present)
    if missing:
        raise SessionPickerError(
            "database is missing required session tables: " + ", ".join(missing)
        )


def _summary_from_row(row: sqlite3.Row) -> SafeSessionSummary:
    return SafeSessionSummary(
        conversation_id=str(row["conversation_id"]),
        conversation_created_at=str(row["conversation_created_at"]),
        latest_run_id=str(row["latest_run_id"]),
        latest_run_created_at=str(row["latest_run_created_at"]),
        latest_run_ended_at=str(row["latest_run_ended_at"]),
        stop_reason=str(row["stop_reason"]) if row["stop_reason"] is not None else None,
        message_count=int(row["message_count"]),
    )


def _safe_role(role: str) -> str:
    normalized = role.strip().lower()
    return normalized if normalized in {"user", "assistant"} else "system"


def _excerpt(content: str, *, limit: int) -> str:
    normalized = " ".join(content.replace("\x00", "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"
