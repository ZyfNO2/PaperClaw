<<<<<<< HEAD
<<<<<<< HEAD
"""FastAPI/SSE adapter for RunApplicationService.
=======
"""FastAPI/SSE adapter for PaperClaw application services.
>>>>>>> 18cf7be
=======
"""FastAPI/SSE adapter for PaperClaw application services.
>>>>>>> 70e7334

Import this module only when the optional ``service`` dependencies are installed.
"""

import asyncio
import json
from typing import Any

from paperclaw.harness import RunLimits

<<<<<<< HEAD
<<<<<<< HEAD
from .application import RunApplicationService
from .contracts import ServiceError, ServiceRunRequest


def create_app(service: RunApplicationService) -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException
=======
=======
>>>>>>> 70e7334
from .contracts import ServiceError, ServiceRunRequest


def create_app(service: Any) -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
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
<<<<<<< HEAD
<<<<<<< HEAD
        limits: LimitsBody = Field(default_factory=LimitsBody)

    app = FastAPI(title="PaperClaw Service API", version="0.12.0")
=======
=======
>>>>>>> 70e7334
        disconnect_policy: str = Field(default="detach_on_disconnect")
        limits: LimitsBody = Field(default_factory=LimitsBody)

    app = FastAPI(title="PaperClaw Service API", version="0.15.0")
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
    app.state.paperclaw_service = service

    def public_error(exc: Exception) -> HTTPException:
        if isinstance(exc, ServiceError):
            return HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": str(exc)[:500]},
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
                disconnect_policy=body.disconnect_policy,
>>>>>>> 18cf7be
=======
                disconnect_policy=body.disconnect_policy,
>>>>>>> 70e7334
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
<<<<<<< HEAD
<<<<<<< HEAD
=======
        request: Request,
>>>>>>> 18cf7be
=======
        request: Request,
>>>>>>> 70e7334
        service_run_id: str,
        last_event_id: str | None = Header(
            default=None, alias="Last-Event-ID"
        ),
    ) -> StreamingResponse:
        try:
            after = int(last_event_id or "0")
<<<<<<< HEAD
<<<<<<< HEAD
            service.get_run(service_run_id)
=======
=======
>>>>>>> 70e7334
            if after < 0:
                raise ValueError("Last-Event-ID must not be negative")
            service.get_run(service_run_id)
            disconnect_policy = (
                service.get_disconnect_policy(service_run_id)
                if hasattr(service, "get_disconnect_policy")
                else "detach_on_disconnect"
            )
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
        except Exception as exc:
            raise public_error(exc) from exc

        async def generate():
            cursor = after
            while True:
<<<<<<< HEAD
<<<<<<< HEAD
=======
=======
>>>>>>> 70e7334
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
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334
                events, terminal = await asyncio.to_thread(
                    service.wait_for_events,
                    service_run_id,
                    after_sequence=cursor,
<<<<<<< HEAD
<<<<<<< HEAD
                    timeout=5.0,
=======
                    timeout=1.0,
>>>>>>> 18cf7be
=======
                    timeout=1.0,
>>>>>>> 70e7334
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

<<<<<<< HEAD
<<<<<<< HEAD
        return StreamingResponse(generate(), media_type="text/event-stream")
=======
=======
>>>>>>> 70e7334
        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
<<<<<<< HEAD
>>>>>>> 18cf7be
=======
>>>>>>> 70e7334

    return app
