"""File lease manager for exclusive write ownership.

A lease is scoped to one task and one agent. It is not a lock in the OS sense;
it is a runtime contract that the Coordinator and Worker both respect. Lease
expiry does not make overwriting safe: the expected_hash compare-and-swap on the
tool boundary handles external edits and TOCTOU.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading
from typing import Any

from paperclaw.multiagent.contracts import FileLease, LeaseDecision


@dataclass
class LeaseAcquireResult:
    """Outcome of attempting to acquire a write lease."""

    decision: LeaseDecision
    lease: FileLease | None = None
    existing: FileLease | None = None
    reason: str = ""


class LeaseManager:
    """In-memory registry of file write leases for the team run.

    Leases are acquired before a Worker is allowed to write. The manager enforces:
    - one writer per file at a time;
    - leases are scoped to a task and agent;
    - leases expire but expiry alone does not authorize a new write;
    - a lease is released when the task ends, fails, or is cancelled.
    """

    def __init__(self, workspace: Path, default_lease_seconds: int = 300) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.default_lease_seconds = default_lease_seconds
        self._leases: dict[str, FileLease] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        raw_path: str,
        owner_agent_id: str,
        task_id: str,
        duration_seconds: int | None = None,
    ) -> LeaseAcquireResult:
        """Try to acquire a write lease for a path.

        Returns CONFLICT if another task currently holds the lease. Returns
        ALREADY_OWNS if the same task already owns it. Paths outside the workspace
        are rejected.
        """

        with self._lock:
            resolved = self._resolve(raw_path)
            if resolved is None:
                return LeaseAcquireResult(
                    LeaseDecision.OUTSIDE_WORKSPACE,
                    reason=f"path escapes workspace: {raw_path}",
                )

            key = str(resolved)
            now = datetime.now(timezone.utc)
            existing = self._leases.get(key)

            if existing is not None:
                if existing.task_id == task_id:
                    return LeaseAcquireResult(
                        LeaseDecision.ALREADY_OWNS,
                        lease=existing,
                        reason="task already owns this lease",
                    )
                # Expired leases are reported as conflict; caller must decide whether
                # to force release. We never auto-claim an expired lease because the
                # file may have been modified externally.
                return LeaseAcquireResult(
                    LeaseDecision.CONFLICT,
                    existing=existing,
                    reason=f"file is leased by {existing.owner_agent_id} for task {existing.task_id}",
                )

            duration = duration_seconds or self.default_lease_seconds
            lease = FileLease(
                path=key,
                owner_agent_id=owner_agent_id,
                task_id=task_id,
                acquired_at=now,
                expires_at=now + timedelta(seconds=duration),
            )
            self._leases[key] = lease
            return LeaseAcquireResult(
                LeaseDecision.GRANTED,
                lease=lease,
                reason="lease granted",
            )

    def release(self, raw_path: str, task_id: str) -> bool:
        """Release a lease if it is owned by the given task."""

        with self._lock:
            resolved = self._resolve(raw_path)
            if resolved is None:
                return False
            key = str(resolved)
            existing = self._leases.get(key)
            if existing is None or existing.task_id != task_id:
                return False
            del self._leases[key]
            return True

    def release_all_for_task(self, task_id: str) -> list[str]:
        """Release every lease held by a task. Used on completion/failure/cancel."""

        with self._lock:
            released: list[str] = []
            for key, lease in list(self._leases.items()):
                if lease.task_id == task_id:
                    del self._leases[key]
                    released.append(key)
            return released

    def owner(self, raw_path: str) -> FileLease | None:
        """Return the current lease holder for a path, if any."""

        with self._lock:
            resolved = self._resolve(raw_path)
            if resolved is None:
                return None
            return self._leases.get(str(resolved))

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable copy of all active leases."""

        with self._lock:
            return {key: lease.to_dict() for key, lease in self._leases.items()}

    def _resolve(self, raw_path: str) -> Path | None:
        """Normalize a path and ensure it stays inside the workspace."""

        candidate = Path(raw_path)
        if candidate.is_absolute():
            resolved = candidate.resolve(strict=False)
        else:
            resolved = (self.workspace / candidate).resolve(strict=False)
        try:
            resolved.relative_to(self.workspace)
        except ValueError:
            return None
        return resolved
