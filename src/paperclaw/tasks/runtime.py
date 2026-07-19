"""Async worker-pool supervisor over the durable task store."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import threading
import time
from typing import Protocol

from .contracts import TaskExecutionResult, TaskRecord, TaskStatus
from .distributed_store import DurableTaskStore, TaskLease


class TaskExecutor(Protocol):
    def __call__(
        self,
        task: TaskRecord,
        should_cancel: Callable[[], bool],
    ) -> TaskExecutionResult: ...


@dataclass(frozen=True)
class _ClaimContext:
    task: TaskRecord
    lease_generation: int | None


class BackgroundTaskSupervisor:
    """Run durable tasks in a bounded asyncio pool on a dedicated loop thread.

    The durable store is the source of truth. Production composition uses the
    fenced store contract; a legacy non-fenced store remains accepted for direct
    compatibility tests while the migration line is stacked.
    """

    def __init__(
        self,
        store: DurableTaskStore,
        executor: TaskExecutor,
        *,
        worker_id: str = "task-worker",
        max_concurrency: int = 4,
        provider_concurrency: int = 2,
        lease_seconds: float = 30.0,
        heartbeat_seconds: float = 5.0,
        poll_seconds: float = 0.1,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if provider_concurrency < 1:
            raise ValueError("provider_concurrency must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and below lease_seconds")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.store = store
        self._executor = executor
        self.worker_id = worker_id
        self.max_concurrency = max_concurrency
        self.provider_concurrency = provider_concurrency
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self._clock = clock
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._started = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._started.clear()
        self._thread = threading.Thread(
            target=self._thread_main,
            name=f"paperclaw-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()
        self._started.wait(timeout=5.0)

    def notify(self) -> None:
        self._wake.set()
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(lambda: None)

    def stop(self, *, wait: bool = True, timeout: float = 10.0) -> None:
        self._stop.set()
        self.notify()
        thread = self._thread
        if wait and thread is not None and thread.is_alive():
            thread.join(timeout=timeout)

    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def wait_for_terminal(
        self,
        task_id: str,
        *,
        timeout: float = 30.0,
        poll_seconds: float = 0.05,
    ) -> TaskRecord:
        deadline = self._clock() + timeout
        while True:
            task = self.store.get_task(task_id)
            if task.terminal:
                return task
            if self._clock() >= deadline:
                raise TimeoutError(f"task did not become terminal: {task_id}")
            time.sleep(poll_seconds)

    def _thread_main(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._started.set()
        await asyncio.to_thread(self.store.recover_expired_leases)
        active: set[asyncio.Task[None]] = set()
        provider_semaphore = asyncio.Semaphore(self.provider_concurrency)
        try:
            while not self._stop.is_set():
                active = {task for task in active if not task.done()}
                await asyncio.to_thread(self.store.refresh_dependencies)
                while len(active) < self.max_concurrency and not self._stop.is_set():
                    claimed = await asyncio.to_thread(self._claim_next)
                    if claimed is None:
                        break
                    runner = asyncio.create_task(
                        self._execute_claimed(claimed, provider_semaphore),
                        name=f"background-task:{claimed.task.task_id}",
                    )
                    active.add(runner)
                if active:
                    done, _pending = await asyncio.wait(
                        active,
                        timeout=self.poll_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for completed in done:
                        try:
                            completed.result()
                        except Exception:
                            # Execution boundaries persist their own failure state.
                            pass
                else:
                    await asyncio.sleep(self.poll_seconds)
                if self._wake.is_set():
                    self._wake.clear()
            for task in self.store.list_tasks(
                statuses=[TaskStatus.RUNNING, TaskStatus.CLAIMED]
            ):
                if task.lease_owner == self.worker_id:
                    await asyncio.to_thread(
                        self.store.request_cancel,
                        task.task_id,
                        reason="supervisor_stopping",
                    )
            if active:
                await asyncio.wait(active, timeout=min(2.0, self.heartbeat_seconds))
        finally:
            self._loop = None

    def _claim_next(self) -> _ClaimContext | None:
        fenced_claim = getattr(self.store, "claim_next_lease", None)
        if callable(fenced_claim):
            lease: TaskLease | None = fenced_claim(
                self.worker_id,
                lease_seconds=self.lease_seconds,
            )
            if lease is None:
                return None
            return _ClaimContext(lease.task, lease.generation)
        legacy_claim = getattr(self.store, "claim_next", None)
        if not callable(legacy_claim):
            raise RuntimeError("durable task store does not implement a claim operation")
        task = legacy_claim(self.worker_id, lease_seconds=self.lease_seconds)
        return _ClaimContext(task, None) if task is not None else None

    async def _execute_claimed(
        self,
        claimed: _ClaimContext,
        provider_semaphore: asyncio.Semaphore,
    ) -> None:
        try:
            running = await asyncio.to_thread(self._start_claimed, claimed)
        except Exception:
            return

        heartbeat_stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(running, claimed.lease_generation, heartbeat_stop),
            name=f"task-heartbeat:{running.task_id}",
        )

        def should_cancel() -> bool:
            if self._stop.is_set():
                return True
            try:
                return self.store.get_task(running.task_id).cancel_requested
            except Exception:
                return True

        try:
            async with provider_semaphore:
                result = await asyncio.wait_for(
                    asyncio.to_thread(self._executor, running, should_cancel),
                    timeout=running.timeout_seconds,
                )
            current = await asyncio.to_thread(self.store.get_task, running.task_id)
            if current.cancel_requested and result.status is TaskStatus.SUCCEEDED:
                result = TaskExecutionResult(
                    TaskStatus.CANCELLED,
                    output=result.output,
                    stop_reason=current.stop_reason or "cancel_requested",
                    side_effect_state=result.side_effect_state,
                    model_calls=result.model_calls,
                    tool_calls=result.tool_calls,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            await asyncio.to_thread(
                self._complete,
                running,
                claimed.lease_generation,
                result,
            )
        except TimeoutError:
            current = await asyncio.to_thread(self.store.get_task, running.task_id)
            terminal = (
                TaskStatus.UNKNOWN_OUTCOME
                if current.side_effect_state in {"committed", "unknown"}
                else TaskStatus.TIMED_OUT
            )
            await asyncio.to_thread(
                self._complete,
                running,
                claimed.lease_generation,
                TaskExecutionResult(
                    terminal,
                    error={"code": "task_timeout"},
                    stop_reason="task_timeout",
                    side_effect_state=current.side_effect_state,
                ),
            )
        except Exception as exc:
            current = await asyncio.to_thread(self.store.get_task, running.task_id)
            if (
                current.attempt < current.max_attempts
                and current.side_effect_state in {"none", "safe"}
                and not current.cancel_requested
            ):
                try:
                    await asyncio.to_thread(
                        self._requeue,
                        running,
                        claimed.lease_generation,
                        f"retryable:{type(exc).__name__}",
                    )
                except Exception:
                    pass
            else:
                terminal = (
                    TaskStatus.UNKNOWN_OUTCOME
                    if current.side_effect_state in {"committed", "unknown"}
                    else TaskStatus.FAILED
                )
                try:
                    await asyncio.to_thread(
                        self._complete,
                        running,
                        claimed.lease_generation,
                        TaskExecutionResult(
                            terminal,
                            error={
                                "code": "task_execution_failed",
                                "error_type": type(exc).__name__,
                                "message": str(exc)[:500],
                            },
                            stop_reason="task_execution_failed",
                            side_effect_state=current.side_effect_state,
                        ),
                    )
                except Exception:
                    pass
        finally:
            heartbeat_stop.set()
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):
                pass

    def _start_claimed(self, claimed: _ClaimContext) -> TaskRecord:
        if claimed.lease_generation is not None:
            method = getattr(self.store, "start_task_fenced")
            return method(
                claimed.task.task_id,
                self.worker_id,
                expected_version=claimed.task.version,
                lease_generation=claimed.lease_generation,
            )
        method = getattr(self.store, "start_task")
        return method(
            claimed.task.task_id,
            self.worker_id,
            expected_version=claimed.task.version,
        )

    def _complete(
        self,
        running: TaskRecord,
        generation: int | None,
        result: TaskExecutionResult,
    ) -> TaskRecord:
        if generation is not None:
            method = getattr(self.store, "complete_task_fenced")
            return method(
                running.task_id,
                self.worker_id,
                expected_version=running.version,
                lease_generation=generation,
                result=result,
            )
        method = getattr(self.store, "complete_task")
        return method(
            running.task_id,
            self.worker_id,
            expected_version=running.version,
            result=result,
        )

    def _requeue(
        self,
        running: TaskRecord,
        generation: int | None,
        reason: str,
    ) -> TaskRecord:
        if generation is not None:
            method = getattr(self.store, "requeue_task_fenced")
            return method(
                running.task_id,
                self.worker_id,
                expected_version=running.version,
                lease_generation=generation,
                reason=reason,
            )
        method = getattr(self.store, "requeue_task")
        return method(
            running.task_id,
            self.worker_id,
            expected_version=running.version,
            reason=reason,
        )

    async def _heartbeat_loop(
        self,
        task: TaskRecord,
        generation: int | None,
        stopped: asyncio.Event,
    ) -> None:
        while not stopped.is_set() and not self._stop.is_set():
            await asyncio.sleep(self.heartbeat_seconds)
            if stopped.is_set() or self._stop.is_set():
                break
            try:
                if generation is not None:
                    method = getattr(self.store, "heartbeat_fenced")
                    await asyncio.to_thread(
                        method,
                        task.task_id,
                        self.worker_id,
                        expected_version=task.version,
                        lease_generation=generation,
                        lease_seconds=self.lease_seconds,
                    )
                else:
                    method = getattr(self.store, "heartbeat")
                    await asyncio.to_thread(
                        method,
                        task.task_id,
                        self.worker_id,
                        expected_version=task.version,
                        lease_seconds=self.lease_seconds,
                    )
            except Exception:
                break


__all__ = ["BackgroundTaskSupervisor", "TaskExecutor"]
