"""FastAPI/SSE adapter for PaperClaw application services.

Import this module only when the optional ``service`` dependencies are installed.
"""

import asyncio
import json
from typing import Any

from paperclaw.harness import RunLimits
from paperclaw.tasks.contracts import (
    TaskConflictError,
    TaskNotFoundError,
    TaskRuntimeError,
    TaskStatus,
)

from .contracts import ServiceError, ServiceRunRequest


def create_app(service: Any) -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
        from fastapi.responses import StreamingResponse
        from pydantic import BaseModel, Field
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            'FastAPI service dependencies are missing; install "paperclaw[service]"'
        ) from exc

    class LimitsBody(BaseModel):
        max_steps: int = Field(default=20, ge=1, le=10_000)
        max_model_calls: int = Field(default=10, ge=1, le=10_000)
        max_tool_calls: int = Field(default=20, ge=1, le=10_000)

    class RunBody(BaseModel):
        task: str = Field(min_length=1, max_length=100_000)
        workspace: str = Field(min_length=1, max_length=4_096)
        conversation_id: str | None = None
        client_id: str | None = None
        enable_verification_gate: bool = True
        disconnect_policy: str = Field(default="detach_on_disconnect")
        limits: LimitsBody = Field(default_factory=LimitsBody)

    class TaskBody(BaseModel):
        objective: str = Field(min_length=1, max_length=100_000)
        workspace: str = Field(min_length=1, max_length=4_096)
        task_id: str | None = Field(default=None, max_length=200)
        parent_run_id: str | None = Field(default=None, max_length=200)
        dependencies: list[str] = Field(default_factory=list, max_length=100)
        max_steps: int = Field(default=20, ge=1, le=10_000)
        timeout_seconds: float = Field(default=600.0, gt=0, le=86_400)
        max_attempts: int = Field(default=2, ge=1, le=20)
        title: str | None = Field(default=None, max_length=200)
        acceptance_criteria: list[str] = Field(default_factory=list, max_length=100)
        allowed_paths: list[str] = Field(default_factory=lambda: ["."], max_length=100)
        writable_paths: list[str] = Field(default_factory=list, max_length=100)
        allowed_tools: list[str] = Field(
            default_factory=lambda: ["file_read", "grep"],
            max_length=20,
        )

    app = FastAPI(title="PaperClaw Service API", version="0.19.0")
    app.state.paperclaw_service = service
    task_service = getattr(service, "task_service", None)
    if task_service is not None:
        app.state.paperclaw_task_service = task_service

    def public_error(exc: Exception) -> HTTPException:
        if isinstance(exc, ServiceError):
            return HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)[:500]},
            )
        if isinstance(exc, TaskNotFoundError):
            return HTTPException(
                status_code=404,
                detail={"code": "task_not_found", "message": str(exc)[:500]},
            )
        if isinstance(exc, TaskConflictError):
            return HTTPException(
                status_code=409,
                detail={"code": "task_conflict", "message": str(exc)[:500]},
            )
        if isinstance(exc, TaskRuntimeError):
            return HTTPException(
                status_code=409,
                detail={"code": "task_runtime_error", "message": str(exc)[:500]},
            )
        if isinstance(exc, (ValueError, TypeError)):
            return HTTPException(
                status_code=422,
                detail={"code": "invalid_request", "message": str(exc)[:500]},
            )
        return HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "internal service error"},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/runs", status_code=202)
    async def create_run(
        body: RunBody,
        idempotency_key: str | None = Header(
            default=None, alias="Idempotency-Key"
        ),
    ) -> dict[str, Any]:
        try:
            request = ServiceRunRequest(
                task=body.task,
                workspace=body.workspace,
                conversation_id=body.conversation_id,
                client_id=body.client_id,
                enable_verification_gate=body.enable_verification_gate,
                disconnect_policy=body.disconnect_policy,
                limits=RunLimits(
                    max_steps=body.limits.max_steps,
                    max_model_calls=body.limits.max_model_calls,
                    max_tool_calls=body.limits.max_tool_calls,
                ),
            )
            outcome = service.submit(
                request, idempotency_key=idempotency_key
            )
            return {
                "created": outcome.created,
                "run": outcome.run.to_dict(),
            }
        except Exception as exc:
            raise public_error(exc) from exc

    @app.get("/v1/runs/{service_run_id}")
    async def get_run(service_run_id: str) -> dict[str, Any]:
        try:
            return service.get_run(service_run_id).to_dict()
        except Exception as exc:
            raise public_error(exc) from exc

    @app.post("/v1/runs/{service_run_id}/cancel", status_code=202)
    async def cancel_run(
        service_run_id: str,
        reason: str = "user_requested",
    ) -> dict[str, Any]:
        try:
            return service.cancel(service_run_id, reason=reason).to_dict()
        except Exception as exc:
            raise public_error(exc) from exc

    @app.get("/v1/runs/{service_run_id}/events")
    async def stream_events(
        request: Request,
        service_run_id: str,
        last_event_id: str | None = Header(
            default=None, alias="Last-Event-ID"
        ),
    ) -> StreamingResponse:
        try:
            after = int(last_event_id or "0")
            if after < 0:
                raise ValueError("Last-Event-ID must not be negative")
            service.get_run(service_run_id)
            disconnect_policy = (
                service.get_disconnect_policy(service_run_id)
                if hasattr(service, "get_disconnect_policy")
                else "detach_on_disconnect"
            )
        except Exception as exc:
            raise public_error(exc) from exc

        async def generate():
            cursor = after
            while True:
                if await request.is_disconnected():
                    if disconnect_policy == "cancel_on_disconnect":
                        try:
                            await asyncio.to_thread(
                                service.cancel,
                                service_run_id,
                                reason="client_disconnected",
                            )
                        except Exception:
                            pass
                    break
                events, terminal = await asyncio.to_thread(
                    service.wait_for_events,
                    service_run_id,
                    after_sequence=cursor,
                    timeout=1.0,
                )
                if not events:
                    yield ": heartbeat\n\n"
                for event in events:
                    cursor = event.sequence
                    payload = json.dumps(
                        event.to_dict(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield (
                        f"id: {event.sequence}\n"
                        f"event: {event.event_type}\n"
                        f"data: {payload}\n\n"
                    )
                if terminal and not service.list_events(
                    service_run_id, after_sequence=cursor
                ):
                    break

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if task_service is not None:

        @app.post("/v1/tasks", status_code=202)
        async def create_task(
            body: TaskBody,
            idempotency_key: str | None = Header(
                default=None, alias="Idempotency-Key"
            ),
        ) -> dict[str, Any]:
            try:
                task, created = task_service.submit(
                    objective=body.objective,
                    workspace=body.workspace,
                    task_id=body.task_id,
                    parent_run_id=body.parent_run_id,
                    dependencies=body.dependencies,
                    max_steps=body.max_steps,
                    timeout_seconds=body.timeout_seconds,
                    max_attempts=body.max_attempts,
                    idempotency_key=idempotency_key,
                    metadata={
                        "title": body.title or body.objective[:80],
                        "acceptance_criteria": body.acceptance_criteria
                        or ["Return a structured task result."],
                        "allowed_paths": body.allowed_paths,
                        "writable_paths": body.writable_paths,
                        "allowed_tools": body.allowed_tools,
                    },
                )
                return {"created": created, "task": task.to_dict()}
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/tasks/{task_id}")
        async def get_task(task_id: str) -> dict[str, Any]:
            try:
                return task_service.get(task_id).to_dict()
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/runs/{parent_run_id}/tasks")
        async def list_run_tasks(parent_run_id: str) -> dict[str, Any]:
            try:
                tasks = task_service.list(parent_run_id=parent_run_id)
                return {
                    "parent_run_id": parent_run_id,
                    "tasks": [task.to_dict() for task in tasks],
                }
            except Exception as exc:
                raise public_error(exc) from exc

        @app.post("/v1/tasks/{task_id}/cancel", status_code=202)
        async def cancel_task(
            task_id: str,
            reason: str = "user_requested",
        ) -> dict[str, Any]:
            try:
                return task_service.cancel(task_id, reason=reason).to_dict()
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/tasks/{task_id}/output")
        async def task_output(task_id: str) -> dict[str, Any]:
            try:
                return task_service.output(task_id)
            except Exception as exc:
                raise public_error(exc) from exc

        @app.get("/v1/tasks/{task_id}/events")
        async def stream_task_events(
            request: Request,
            task_id: str,
            last_event_id: str | None = Header(
                default=None, alias="Last-Event-ID"
            ),
        ) -> StreamingResponse:
            try:
                after = int(last_event_id or "0")
                if after < 0:
                    raise ValueError("Last-Event-ID must not be negative")
                task_service.get(task_id)
            except Exception as exc:
                raise public_error(exc) from exc

            async def generate_tasks():
                cursor = after
                while True:
                    if await request.is_disconnected():
                        # Background tasks detach from SSE clients by default.
                        break
                    events = await asyncio.to_thread(
                        task_service.events,
                        task_id,
                        after_sequence=cursor,
                        limit=500,
                    )
                    if not events:
                        yield ": heartbeat\n\n"
                    for event in events:
                        cursor = event.sequence
                        payload = json.dumps(
                            event.to_dict(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        yield (
                            f"id: {event.sequence}\n"
                            f"event: {event.event_type}\n"
                            f"data: {payload}\n\n"
                        )
                    task = await asyncio.to_thread(task_service.get, task_id)
                    if task.terminal and not await asyncio.to_thread(
                        task_service.events,
                        task_id,
                        after_sequence=cursor,
                        limit=1,
                    ):
                        break
                    await asyncio.sleep(0.25)

            return StreamingResponse(
                generate_tasks(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

    return app
