"""CheckpointWriter Protocol and SQLite-backed implementation.

Addendum P0-C §5.1 introduces a stable ``CheckpointWriter`` boundary so the
``InstrumentedFlowRunner`` does not need to know whether Checkpoints land in
SQLite, an in-memory fake, or a remote store. The Protocol decouples the
runner from the persistence layer the same way ``EventSink`` decouples event
emission from ``SessionService``.

Design constraints (Addendum §5.2 commit order):

- The runner emits ``node.completed`` BEFORE calling
  ``CheckpointWriter.commit_checkpoint``. The writer is the LAST step of the
  safe step boundary — business state must already be persisted by the time
  the writer is invoked. The writer itself MUST NOT trigger business
  persistence; it only records the recovery marker.
- The writer MUST be safe to call from the runner's orchestration thread.
  ``SqliteCheckpointWriter`` delegates to ``Repository.insert_checkpoint``,
  which serializes writes with a single-writer lock (SOP §5.4).
- A writer that cannot persist (disk full, locked DB) SHOULD raise so the
  runner can surface the failure rather than silently dropping the recovery
  marker. P0-B's stub swallowed writer errors; P0-C tightens this to "raise
  and let the caller decide" because a missing Checkpoint breaks resume
  guarantees (Addendum §5.3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from paperclaw.context.contracts import Checkpoint

if TYPE_CHECKING:
    # Avoid an import cycle at runtime: Repository imports from contracts,
    # and contracts does not import runtime. The Protocol only needs the
    # Repository for type annotations.
    from paperclaw.context.repository import Repository


@runtime_checkable
class CheckpointWriter(Protocol):
    """Boundary for committing Checkpoints at safe step boundaries.

    The Protocol is ``runtime_checkable`` so tests can substitute fakes
    (e.g. an in-memory list-recording writer) without inheriting from a
    concrete class. The two methods mirror the Repository's checkpoint
    surface so ``SqliteCheckpointWriter`` is a thin adapter.

    Why not just pass the Repository directly to the runner? Two reasons:

    1. The Repository exposes many unrelated methods (event append, task
       state, context items, idempotency). The runner only needs
       ``insert_checkpoint`` and ``latest_checkpoint``. A narrow Protocol
       keeps the runner's dependency surface auditable.
    2. Future writers (in-memory test fakes, remote checkpoint stores) can
       implement just these two methods without re-implementing the whole
       Repository Protocol.
    """

    def commit_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist ``checkpoint`` as the latest safe step boundary for its
        ``run_id``.

        MUST be idempotent for the same ``checkpoint_id`` — a retry of the
        same step boundary MUST NOT create a duplicate row. The SQLite
        implementation relies on the ``checkpoint_id`` PRIMARY KEY for
        idempotency; callers that retry should reuse the same id.

        Raises:
            Exception: if the checkpoint cannot be persisted (disk full,
                locked DB, schema mismatch). The caller (runner) is
                responsible for surfacing this; P0-C does NOT swallow
                writer errors because a missing Checkpoint breaks the
                resume guarantee.
        """
        ...

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """Return the most recent Checkpoint for ``run_id``, or ``None`` if
        no Checkpoint has been committed.

        "Most recent" is defined by the writer's storage order. For SQLite
        this is ``ORDER BY last_committed_sequence DESC`` — the checkpoint
        with the highest committed event sequence is the latest safe
        boundary. Callers use this to build a ``FlowResumePoint`` for
        resumption.
        """
        ...


class SqliteCheckpointWriter:
    """``CheckpointWriter`` backed by ``SQLiteRepository``.

    A thin adapter: ``commit_checkpoint`` delegates to
    ``Repository.insert_checkpoint``; ``latest_checkpoint`` delegates to
    ``Repository.latest_checkpoint``. The writer holds no state of its own
    so it is safe to construct one per run or share one across runs (the
    Repository serializes writes internally).

    Why a class and not just functions? The Protocol expects an object with
    methods; a class gives tests a concrete type to ``isinstance`` against
    and gives future writers a clear pattern to follow (compose a
    ``Repository`` or equivalent, expose the two Protocol methods).
    """

    def __init__(self, repo: "Repository") -> None:
        # Defensive: store the reference, do not copy or wrap. The Repository
        # owns the SQLite connection and the writer lock; the writer is a
        # stateless pass-through.
        self._repo = repo

    def commit_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Persist ``checkpoint`` via the Repository.

        The Repository's ``insert_checkpoint`` opens a short write
        transaction under the writer lock. Long operations (model calls,
        Bash, file I/O) MUST NOT be performed inside this method — the
        caller is responsible for ensuring business state was persisted
        BEFORE constructing the Checkpoint (Addendum §5.2 commit order).
        """
        self._repo.insert_checkpoint(checkpoint)

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """Return the latest Checkpoint for ``run_id`` or ``None``."""
        return self._repo.latest_checkpoint(run_id)


class InMemoryCheckpointWriter:
    """Test-only writer that records Checkpoints in a list.

    Useful for unit tests that need to assert which Checkpoints were
    committed without spinning up SQLite. NOT for production use: the
    in-memory list is not persisted across processes and has no
    concurrency guarantees beyond Python's GIL.

    ``latest_checkpoint`` returns the Checkpoint with the highest
    ``last_committed_sequence`` for the given ``run_id``, mirroring the
    SQLite ``ORDER BY last_committed_sequence DESC`` semantics.
    """

    def __init__(self) -> None:
        self.committed: list[Checkpoint] = []

    def commit_checkpoint(self, checkpoint: Checkpoint) -> None:
        self.committed.append(checkpoint)

    def latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        candidates = [c for c in self.committed if c.run_id == run_id]
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.last_committed_sequence)
