"""HTTP adapter/client for the transport-neutral Worker Gateway."""

from __future__ import annotations

import hmac
import json
from typing import Any, Mapping
import urllib.error
import urllib.request

from .contracts import ExecutionRequest
from .gateway import (
    GatewayConflictError,
    GatewayError,
    GatewayExecutionSnapshot,
    GatewayNotFoundError,
    GatewayPayloadTooLargeError,
    GatewayPolicyError,
    GatewayTransportError,
    WorkerGatewayService,
)


def create_worker_gateway_app(
    service: WorkerGatewayService,
    *,
    bearer_token: str,
) -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
    except ImportError as exc:  # pragma: no cover - optional service dependency
        raise RuntimeError(
            'FastAPI service dependencies are missing; install "paperclaw[service]"'
        ) from exc

    token = _required_token(bearer_token)
    app = FastAPI(title="PaperClaw Worker Gateway", version="0.24.0")
    app.state.paperclaw_worker_gateway = service

    def authorize(value: str | None) -> None:
        prefix = "Bearer "
        if not isinstance(value, str) or not value.startswith(prefix):
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})
        supplied = value[len(prefix) :]
        if not hmac.compare_digest(supplied.encode("utf-8"), token.encode("utf-8")):
            raise HTTPException(status_code=401, detail={"code": "unauthorized"})

    def public_error(exc: Exception) -> HTTPException:
        if isinstance(exc, GatewayNotFoundError):
            return HTTPException(status_code=404, detail={"code": exc.code})
        if isinstance(exc, GatewayConflictError):
            return HTTPException(status_code=409, detail={"code": exc.code})
        if isinstance(exc, GatewayPayloadTooLargeError):
            return HTTPException(status_code=413, detail={"code": exc.code})
        if isinstance(exc, GatewayPolicyError):
            return HTTPException(status_code=403, detail={"code": exc.code})
        if isinstance(exc, (ValueError, TypeError)):
            return HTTPException(status_code=422, detail={"code": "invalid_request"})
        return HTTPException(status_code=500, detail={"code": "internal_error"})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/executions", status_code=202)
    async def submit_execution(
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        authorize(authorization)
        try:
            body = await request.json()
            if not isinstance(body, Mapping):
                raise ValueError("request body must be an object")
            execution = ExecutionRequest.from_dict(body)
            snapshot, created = service.submit(execution)
            return {"created": created, "execution": snapshot.to_dict()}
        except HTTPException:
            raise
        except Exception as exc:
            raise public_error(exc) from exc

    @app.get("/v1/executions/{execution_id}")
    async def get_execution(
        execution_id: str,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        authorize(authorization)
        try:
            return service.get(execution_id).to_dict()
        except Exception as exc:
            raise public_error(exc) from exc

    @app.post("/v1/executions/{execution_id}/cancel", status_code=202)
    async def cancel_execution(
        execution_id: str,
        request: Request,
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> dict[str, Any]:
        authorize(authorization)
        try:
            try:
                body = await request.json()
            except Exception:
                body = {}
            reason = (
                body.get("reason")
                if isinstance(body, Mapping) and isinstance(body.get("reason"), str)
                else "remote_cancel_requested"
            )
            return service.cancel(execution_id, reason=reason[:120]).to_dict()
        except HTTPException:
            raise
        except Exception as exc:
            raise public_error(exc) from exc

    return app


class HttpWorkerGatewayTransport:
    """stdlib HTTP transport used by `RemoteWorkerExecutor`."""

    def __init__(
        self,
        base_url: str,
        *,
        bearer_token: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = normalized
        self._token = _required_token(bearer_token)
        self._timeout_seconds = timeout_seconds

    def submit(self, request: ExecutionRequest) -> GatewayExecutionSnapshot:
        payload = self._request("POST", "/v1/executions", request.to_dict())
        execution = payload.get("execution") if isinstance(payload, Mapping) else None
        if not isinstance(execution, Mapping):
            raise GatewayTransportError("gateway submit response is malformed")
        return GatewayExecutionSnapshot.from_dict(execution)

    def get(self, execution_id: str) -> GatewayExecutionSnapshot:
        payload = self._request("GET", f"/v1/executions/{execution_id}", None)
        if not isinstance(payload, Mapping):
            raise GatewayTransportError("gateway get response is malformed")
        return GatewayExecutionSnapshot.from_dict(payload)

    def cancel(self, execution_id: str, reason: str) -> GatewayExecutionSnapshot:
        payload = self._request(
            "POST",
            f"/v1/executions/{execution_id}/cancel",
            {"reason": reason[:120]},
        )
        if not isinstance(payload, Mapping):
            raise GatewayTransportError("gateway cancel response is malformed")
        return GatewayExecutionSnapshot.from_dict(payload)

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        body = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "PaperClaw-Worker-Gateway/0.24",
        }
        if payload is not None:
            body = json.dumps(
                dict(payload), ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            _raise_http_error(exc)
            raise AssertionError("unreachable")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise GatewayTransportError(
                "worker gateway transport unavailable", uncertain=True
            ) from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayTransportError("gateway returned invalid JSON") from exc
        if not isinstance(decoded, Mapping):
            raise GatewayTransportError("gateway response must be an object")
        return decoded


def _raise_http_error(exc: urllib.error.HTTPError) -> None:
    status = exc.code
    if status == 404:
        raise GatewayNotFoundError("execution not found") from exc
    if status == 409:
        raise GatewayConflictError("execution conflict") from exc
    if status == 413:
        raise GatewayPayloadTooLargeError("gateway payload too large") from exc
    if status in {401, 403}:
        raise GatewayPolicyError("gateway authorization denied") from exc
    if 400 <= status < 500:
        raise GatewayError(f"gateway rejected request with HTTP {status}") from exc
    raise GatewayTransportError(
        f"gateway returned HTTP {status}", uncertain=status >= 500
    ) from exc


def _required_token(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4_096:
        raise ValueError("bearer_token must be a bounded non-empty string")
    return value.strip()


__all__ = ["HttpWorkerGatewayTransport", "create_worker_gateway_app"]
