"""Persistent Plan Mode state, artifacts, approval and user questions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Mapping, Sequence
from uuid import uuid4


class PlanPhase(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    REJECTED = "rejected"


@dataclass(frozen=True)
class PlanArtifact:
    plan_id: str
    scope_id: str
    title: str
    summary: str
    steps: tuple[str, ...]
    risks: tuple[str, ...]
    verification: tuple[str, ...]
    status: PlanPhase
    version: int
    created_at: float
    updated_at: float
    approved_at: float | None = None
    rejected_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "scope_id": self.scope_id,
            "title": self.title,
            "summary": self.summary,
            "steps": list(self.steps),
            "risks": list(self.risks),
            "verification": list(self.verification),
            "status": self.status.value,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "approved_at": self.approved_at,
            "rejected_at": self.rejected_at,
        }


@dataclass(frozen=True)
class UserQuestion:
    question_id: str
    scope_id: str
    prompt: str
    options: tuple[str, ...]
    allow_free_text: bool
    status: str
    answer: str | None
    created_at: float
    answered_at: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "scope_id": self.scope_id,
            "prompt": self.prompt,
            "options": list(self.options),
            "allow_free_text": self.allow_free_text,
            "status": self.status,
            "answer": self.answer,
            "created_at": self.created_at,
            "answered_at": self.answered_at,
        }


class PlanRuntimeError(RuntimeError):
    pass


class PlanTransitionError(PlanRuntimeError):
    pass


class PlanNotFoundError(PlanRuntimeError):
    pass


class SQLitePlanStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def enter(self, scope_id: str) -> PlanPhase:
        scope = _text(scope_id, "scope_id", 200)
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT phase FROM plan_scopes WHERE scope_id = ?", (scope,)
            ).fetchone()
            if row is not None and row["phase"] in {
                PlanPhase.PLANNING.value,
                PlanPhase.AWAITING_APPROVAL.value,
            }:
                connection.rollback()
                raise PlanTransitionError("scope already has an active plan")
            connection.execute(
                """
                INSERT INTO plan_scopes(scope_id, phase, active_plan_id, updated_at)
                VALUES (?, 'planning', NULL, ?)
                ON CONFLICT(scope_id) DO UPDATE SET
                    phase='planning', active_plan_id=NULL, updated_at=excluded.updated_at
                """,
                (scope, now),
            )
            connection.commit()
        return PlanPhase.PLANNING

    def create_artifact(
        self,
        scope_id: str,
        *,
        title: str,
        summary: str,
        steps: Sequence[str],
        risks: Sequence[str],
        verification: Sequence[str],
    ) -> PlanArtifact:
        scope = _text(scope_id, "scope_id", 200)
        normalized_steps = _strings(steps, "steps", required=True)
        normalized_risks = _strings(risks, "risks")
        normalized_verification = _strings(
            verification, "verification", required=True
        )
        now = time.time()
        plan_id = f"plan-{uuid4().hex[:16]}"
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            scope_row = connection.execute(
                "SELECT phase FROM plan_scopes WHERE scope_id = ?", (scope,)
            ).fetchone()
            if scope_row is None or scope_row["phase"] != PlanPhase.PLANNING.value:
                connection.rollback()
                raise PlanTransitionError("scope is not in planning phase")
            connection.execute(
                """
                INSERT INTO plan_artifacts(
                    plan_id, scope_id, title, summary, steps_json, risks_json,
                    verification_json, status, version, created_at, updated_at,
                    approved_at, rejected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'awaiting_approval', 0, ?, ?, NULL, NULL)
                """,
                (
                    plan_id,
                    scope,
                    _text(title, "title", 300),
                    _text(summary, "summary", 20_000),
                    _dump(normalized_steps),
                    _dump(normalized_risks),
                    _dump(normalized_verification),
                    now,
                    now,
                ),
            )
            connection.execute(
                "UPDATE plan_scopes SET phase='awaiting_approval', "
                "active_plan_id=?, updated_at=? WHERE scope_id=?",
                (plan_id, now, scope),
            )
            connection.commit()
        return self.get_plan(plan_id)

    def decide(self, scope_id: str, plan_id: str, *, approve: bool) -> PlanArtifact:
        scope = _text(scope_id, "scope_id", 200)
        plan = _text(plan_id, "plan_id", 200)
        now = time.time()
        next_phase = PlanPhase.EXECUTING if approve else PlanPhase.REJECTED
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM plan_artifacts WHERE plan_id=? AND scope_id=?",
                (plan, scope),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise PlanNotFoundError(f"unknown plan: {plan}")
            if row["status"] != PlanPhase.AWAITING_APPROVAL.value:
                connection.rollback()
                raise PlanTransitionError("plan is not awaiting approval")
            connection.execute(
                """
                UPDATE plan_artifacts
                SET status=?, version=version+1, updated_at=?,
                    approved_at=CASE WHEN ? THEN ? ELSE approved_at END,
                    rejected_at=CASE WHEN ? THEN rejected_at ELSE ? END
                WHERE plan_id=?
                """,
                (
                    next_phase.value,
                    now,
                    int(approve),
                    now,
                    int(approve),
                    now,
                    plan,
                ),
            )
            connection.execute(
                "UPDATE plan_scopes SET phase=?, active_plan_id=?, updated_at=? "
                "WHERE scope_id=?",
                (
                    next_phase.value,
                    plan if approve else None,
                    now,
                    scope,
                ),
            )
            connection.commit()
        return self.get_plan(plan)

    def phase(self, scope_id: str) -> PlanPhase:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT phase FROM plan_scopes WHERE scope_id=?",
                (_text(scope_id, "scope_id", 200),),
            ).fetchone()
        return PlanPhase(row["phase"]) if row is not None else PlanPhase.IDLE

    def active_plan(self, scope_id: str) -> PlanArtifact | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT active_plan_id FROM plan_scopes WHERE scope_id=?",
                (_text(scope_id, "scope_id", 200),),
            ).fetchone()
        if row is None or row["active_plan_id"] is None:
            return None
        return self.get_plan(row["active_plan_id"])

    def get_plan(self, plan_id: str) -> PlanArtifact:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM plan_artifacts WHERE plan_id=?",
                (_text(plan_id, "plan_id", 200),),
            ).fetchone()
        if row is None:
            raise PlanNotFoundError(f"unknown plan: {plan_id}")
        return _plan(row)

    def ask(
        self,
        scope_id: str,
        *,
        prompt: str,
        options: Sequence[str] = (),
        allow_free_text: bool = True,
    ) -> UserQuestion:
        scope = _text(scope_id, "scope_id", 200)
        question_id = f"question-{uuid4().hex[:16]}"
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO plan_questions(
                    question_id, scope_id, prompt, options_json, allow_free_text,
                    status, answer, created_at, answered_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?, NULL)
                """,
                (
                    question_id,
                    scope,
                    _text(prompt, "prompt", 10_000),
                    _dump(_strings(options, "options")),
                    int(bool(allow_free_text)),
                    now,
                ),
            )
        return self.get_question(question_id)

    def answer(self, question_id: str, answer: str) -> UserQuestion:
        question = self.get_question(question_id)
        if question.status != "pending":
            raise PlanTransitionError("question is not pending")
        normalized = _text(answer, "answer", 20_000)
        if question.options and not question.allow_free_text and normalized not in question.options:
            raise ValueError("answer must be one of the allowed options")
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                "UPDATE plan_questions SET status='answered', answer=?, answered_at=? "
                "WHERE question_id=? AND status='pending'",
                (normalized, now, question.question_id),
            )
        return self.get_question(question.question_id)

    def get_question(self, question_id: str) -> UserQuestion:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM plan_questions WHERE question_id=?",
                (_text(question_id, "question_id", 200),),
            ).fetchone()
        if row is None:
            raise PlanNotFoundError(f"unknown question: {question_id}")
        return UserQuestion(
            question_id=row["question_id"],
            scope_id=row["scope_id"],
            prompt=row["prompt"],
            options=tuple(json.loads(row["options_json"])),
            allow_free_text=bool(row["allow_free_text"]),
            status=row["status"],
            answer=row["answer"],
            created_at=float(row["created_at"]),
            answered_at=(
                float(row["answered_at"]) if row["answered_at"] is not None else None
            ),
        )

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS plan_schema(
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    version INTEGER NOT NULL
                );
                INSERT INTO plan_schema(singleton, version) VALUES(1, 1)
                ON CONFLICT(singleton) DO NOTHING;

                CREATE TABLE IF NOT EXISTS plan_scopes(
                    scope_id TEXT PRIMARY KEY,
                    phase TEXT NOT NULL,
                    active_plan_id TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plan_artifacts(
                    plan_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    risks_json TEXT NOT NULL,
                    verification_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    approved_at REAL,
                    rejected_at REAL
                );
                CREATE INDEX IF NOT EXISTS plan_artifacts_scope_idx
                ON plan_artifacts(scope_id, created_at);
                CREATE TABLE IF NOT EXISTS plan_questions(
                    question_id TEXT PRIMARY KEY,
                    scope_id TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    allow_free_text INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    answer TEXT,
                    created_at REAL NOT NULL,
                    answered_at REAL
                );
                CREATE INDEX IF NOT EXISTS plan_questions_scope_idx
                ON plan_questions(scope_id, created_at);
                """
            )
            row = connection.execute(
                "SELECT version FROM plan_schema WHERE singleton=1"
            ).fetchone()
            if row is None or int(row["version"]) != self.SCHEMA_VERSION:
                raise PlanRuntimeError("unsupported plan schema version")

    def _connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection


def _plan(row: sqlite3.Row) -> PlanArtifact:
    return PlanArtifact(
        plan_id=row["plan_id"],
        scope_id=row["scope_id"],
        title=row["title"],
        summary=row["summary"],
        steps=tuple(json.loads(row["steps_json"])),
        risks=tuple(json.loads(row["risks_json"])),
        verification=tuple(json.loads(row["verification_json"])),
        status=PlanPhase(row["status"]),
        version=int(row["version"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        approved_at=(
            float(row["approved_at"]) if row["approved_at"] is not None else None
        ),
        rejected_at=(
            float(row["rejected_at"]) if row["rejected_at"] is not None else None
        ),
    )


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return normalized


def _strings(values: Sequence[str], name: str, *, required: bool = False) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a sequence of strings")
    normalized = tuple(_text(value, name, 10_000) for value in values)
    if required and not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "PlanArtifact",
    "PlanNotFoundError",
    "PlanPhase",
    "PlanRuntimeError",
    "PlanTransitionError",
    "SQLitePlanStore",
    "UserQuestion",
]
