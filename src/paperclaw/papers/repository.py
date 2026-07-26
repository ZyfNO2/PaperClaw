"""SQLite persistence adapter for immutable paper versions."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Iterator, Protocol

from .contracts import PaperMetadata, PaperRecord, PaperVersion


class PaperNotFoundError(KeyError):
    pass


class PaperConflictError(RuntimeError):
    def __init__(self, message: str, *, current_revision: int | None = None) -> None:
        super().__init__(message)
        self.current_revision = current_revision


class PaperRepository(Protocol):
    def get_paper(self, project_id: str, paper_id: str) -> PaperRecord: ...
    def list_papers(self, project_id: str, *, cursor: str | None = None, limit: int = 50) -> tuple[PaperRecord, ...]: ...
    def list_versions(self, project_id: str, paper_id: str) -> tuple[PaperVersion, ...]: ...


class SQLitePaperRepository:
    def __init__(self, database: str | Path) -> None:
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def get_by_hash(self, project_id: str, digest: str) -> tuple[PaperRecord, PaperVersion] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT paper_id, version_id FROM paper_versions WHERE project_id=? AND sha256=?",
                (project_id, digest),
            ).fetchone()
        return None if row is None else (
            self.get_paper(project_id, row["paper_id"]),
            self.get_version(project_id, row["paper_id"], row["version_id"]),
        )

    def insert(
        self, paper: PaperRecord, version: PaperVersion, *, existing: bool
    ) -> None:
        with self.transaction() as connection:
            duplicate = connection.execute(
                "SELECT version_id FROM paper_versions WHERE project_id=? AND sha256=?",
                (paper.project_id, version.sha256),
            ).fetchone()
            if duplicate:
                raise PaperConflictError("paper content was imported concurrently")
            if existing:
                row = connection.execute(
                    "SELECT current_version_number FROM papers WHERE project_id=? AND paper_id=?",
                    (paper.project_id, paper.paper_id),
                ).fetchone()
                if row is None:
                    raise PaperNotFoundError(paper.paper_id)
                if int(row[0]) + 1 != version.version_number:
                    raise PaperConflictError("paper version changed concurrently")
                connection.execute(
                    "UPDATE papers SET current_version_id=?, current_version_number=?, updated_at=? WHERE project_id=? AND paper_id=?",
                    (version.version_id, version.version_number, paper.updated_at, paper.project_id, paper.paper_id),
                )
            else:
                connection.execute(
                    "INSERT INTO papers VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        paper.project_id, paper.paper_id, paper.current_version_id,
                        paper.current_version_number, _metadata_json(paper.metadata),
                        paper.metadata_revision, paper.created_at, paper.updated_at, 1,
                    ),
                )
            connection.execute(
                "INSERT INTO paper_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    paper.project_id, version.version_id, version.paper_id,
                    version.version_number, version.format, version.original_filename,
                    version.byte_length, version.sha256, version.managed_locator,
                    version.source_path, version.created_at,
                ),
            )

    def get_paper(self, project_id: str, paper_id: str) -> PaperRecord:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM papers WHERE project_id=? AND paper_id=?",
                (project_id, paper_id),
            ).fetchone()
        if row is None:
            raise PaperNotFoundError(paper_id)
        return _paper(row)

    def list_papers(self, project_id: str, *, cursor: str | None = None, limit: int = 50) -> tuple[PaperRecord, ...]:
        if isinstance(limit, bool) or not 1 <= limit <= 200:
            raise ValueError("limit must be in [1, 200]")
        query = "SELECT * FROM papers WHERE project_id=?"
        params: list[object] = [project_id]
        if cursor:
            query += " AND paper_id>?"
            params.append(cursor)
        query += " ORDER BY paper_id LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            return tuple(_paper(row) for row in connection.execute(query, params))

    def list_versions(self, project_id: str, paper_id: str) -> tuple[PaperVersion, ...]:
        self.get_paper(project_id, paper_id)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM paper_versions WHERE project_id=? AND paper_id=? ORDER BY version_number",
                (project_id, paper_id),
            )
            return tuple(_version(row) for row in rows)

    def get_version(self, project_id: str, paper_id: str, version_id: str) -> PaperVersion:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM paper_versions WHERE project_id=? AND paper_id=? AND version_id=?",
                (project_id, paper_id, version_id),
            ).fetchone()
        if row is None:
            raise PaperNotFoundError(version_id)
        return _version(row)

    def update_metadata(self, project_id: str, paper_id: str, metadata: PaperMetadata, expected_revision: int) -> PaperRecord:
        now = _now()
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT metadata_revision FROM papers WHERE project_id=? AND paper_id=?",
                (project_id, paper_id),
            ).fetchone()
            if row is None:
                raise PaperNotFoundError(paper_id)
            current = int(row[0])
            if current != expected_revision:
                raise PaperConflictError("paper metadata changed concurrently", current_revision=current)
            connection.execute(
                "UPDATE papers SET metadata_json=?, metadata_revision=?, updated_at=? WHERE project_id=? AND paper_id=?",
                (_metadata_json(metadata), current + 1, now, project_id, paper_id),
            )
        return self.get_paper(project_id, paper_id)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.transaction() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS paper_schema_migrations(
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS papers(
                    project_id TEXT NOT NULL, paper_id TEXT NOT NULL,
                    current_version_id TEXT NOT NULL, current_version_number INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL, metadata_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    schema_version INTEGER NOT NULL,
                    PRIMARY KEY(project_id, paper_id)
                );
                CREATE TABLE IF NOT EXISTS paper_versions(
                    project_id TEXT NOT NULL, version_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL, version_number INTEGER NOT NULL,
                    format TEXT NOT NULL, original_filename TEXT NOT NULL,
                    byte_length INTEGER NOT NULL, sha256 TEXT NOT NULL,
                    managed_locator TEXT NOT NULL, source_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(project_id, paper_id, version_number),
                    UNIQUE(project_id, sha256),
                    FOREIGN KEY(project_id, paper_id) REFERENCES papers(project_id, paper_id)
                );
                INSERT OR IGNORE INTO paper_schema_migrations VALUES(1, CURRENT_TIMESTAMP);
                """
            )


def _metadata_json(value: PaperMetadata) -> str:
    return json.dumps(value.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _paper(row: sqlite3.Row) -> PaperRecord:
    return PaperRecord(
        row["paper_id"], row["project_id"], row["current_version_id"],
        int(row["current_version_number"]), PaperMetadata.from_dict(json.loads(row["metadata_json"])),
        int(row["metadata_revision"]), row["created_at"], row["updated_at"],
    )


def _version(row: sqlite3.Row) -> PaperVersion:
    return PaperVersion(
        row["version_id"], row["paper_id"], int(row["version_number"]), row["format"],
        row["original_filename"], int(row["byte_length"]), row["sha256"],
        row["managed_locator"], row["source_path"], row["created_at"],
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
