"""Read-only SQLite health checks for PaperClaw databases.

This module is a maintenance boundary, not a runtime persistence path. It opens
an existing database in read-only/query-only mode, never runs migrations, and
returns a structured report suitable for CLI diagnostics and release checks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3
from urllib.parse import quote


@dataclass(frozen=True)
class DatabaseHealthReport:
    """Structured outcome of one non-mutating database inspection."""

    path: str
    check: str
    ok: bool
    messages: tuple[str, ...]
    schema_version: int | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["messages"] = list(self.messages)
        return data


def inspect_sqlite_database(
    database: str | Path,
    *,
    full: bool = False,
) -> DatabaseHealthReport:
    """Inspect an existing database without creating, migrating, or writing it.

    ``quick_check`` is the default because it is appropriate for routine startup
    and support diagnostics. ``full=True`` selects SQLite's more expensive
    ``integrity_check``. Foreign-key violations are reported separately because
    neither pragma treats them as part of the B-tree integrity result.
    """

    resolved = Path(database).expanduser().resolve()
    check = "integrity_check" if full else "quick_check"
    if not resolved.is_file():
        return DatabaseHealthReport(
            path=str(resolved),
            check=check,
            ok=False,
            messages=(),
            error_code="DATABASE_NOT_FOUND",
            error_message="database path does not exist or is not a file",
        )

    connection: sqlite3.Connection | None = None
    try:
        uri_path = quote(resolved.as_posix(), safe="/:")
        connection = sqlite3.connect(f"file:{uri_path}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(f"PRAGMA {check}").fetchall()
        messages = [str(row[0]) for row in rows if row]

        for table, rowid, parent, foreign_key_index in connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall():
            messages.append(
                "foreign_key_violation:"
                f"table={table},rowid={rowid},parent={parent},fk={foreign_key_index}"
            )

        schema_version = _read_schema_version(connection)
        ok = bool(messages) and all(message.lower() == "ok" for message in messages)
        return DatabaseHealthReport(
            path=str(resolved),
            check=check,
            ok=ok,
            messages=tuple(messages),
            schema_version=schema_version,
        )
    except sqlite3.DatabaseError as exc:
        return DatabaseHealthReport(
            path=str(resolved),
            check=check,
            ok=False,
            messages=(),
            error_code="SQLITE_DATABASE_ERROR",
            error_message=f"{type(exc).__name__}: {str(exc)[:500]}",
        )
    finally:
        if connection is not None:
            connection.close()


def _read_schema_version(connection: sqlite3.Connection) -> int | None:
    try:
        row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    except sqlite3.DatabaseError:
        return None
    if row is None or row[0] is None:
        return None
    return int(row[0])
