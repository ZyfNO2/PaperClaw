"""HTTP adapter/client for the transport-neutral Worker Gateway."""

import hmac
import json
import re
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

_HTTP_EXECUTION_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")


def create_worker_gateway_app(
    service: WorkerGatewayService,
    *,
    bearer_token: str,
    max_request_bytes: int = 1_048_576,
    max_cancel_bytes: int = 16_384,
) -> Any:
    try:
        from fastapi import FastAPI, Header, HTTPException, Request
    except ImportError as exc:  # pragma: no cover - optional service dependency
        raise RuntimeError(
            'FastAPI service dependencies are missing; install "paperclaw[service]"'
        ) from exc

    token = _required_token(bearer_token)
    if max_request_bytes < 1 or max_cancel_bytes < 1:
        raise ValueError("HTTP gateway request bounds must be positive")
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
        if isinstance(exc, (ValueError, TypeError, json.JSONDecodeError)):
            return HTTPException(status_code=422, detail={"code": "invalid_request"})
        return HTTPException(status_code=500, detail={"code": "internal_error"})

    async def bounded_json(request: Request, limit: int) -> Mapping[str, Any]:
        raw = await request.body()
        if len(raw) > limit:
            raise GatewayPayloadTooLargeError("HTTP request body exceeds gateway limit")
        decoded = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(decoded, Mapping):
            raise ValueError("request body must be an object")
        return decoded

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
            body = await bounded_json(request, max_request_bytes)
            execution = ExecutionRequest.from_dict(body)
            _http_execution_id(execution.execution_id)
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
            normalized = _http_execution_id(execution_id)
            return service.get(normalized).to_dict()
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
            normalized = _http_execution_id(execution_id)
            body = await bounded_json(request, max_cancel_bytes)
            reason = (
                body.get("reason")
                if isinstance(body.get("reason"), str)
                else "remote_cancel_requested"
            )
            return service.cancel(normalized, reason=reason[:120]).to_dict()
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
        max_request_bytes: int = 1_048_576,
        max_response_bytes: int = 4_194_304,
    ) -> None:
        normalized = base_url.rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("base_url must use http or https")
        if timeout_seconds <= 0 or max_request_bytes < 1 or max_response_bytes < 1:
            raise ValueError("HTTP transport bounds must be positive")
        self._base_url = normalized
        self._token = _required_token(bearer_token)
        self._timeout_seconds = timeout_seconds
        self._max_request_bytes = max_request_bytes
        self._max_response_bytes = max_response_bytes

    def submit(self, request: ExecutionRequest) -> GatewayExecutionSnapshot:
        _http_execution_id(request.execution_id)
        payload = self._request("POST", "/v1/executions", request.to_dict())
        execution = payload.get("execution") if isinstance(payload, Mapping) else None
        if not isinstance(execution, Mapping):
            raise GatewayTransportError("gateway submit response is malformed")
        return GatewayExecutionSnapshot.from_dict(execution)

    def get(self, execution_id: str) -> GatewayExecutionSnapshot:
        normalized = _http_execution_id(execution_id)
        payload = self._request("GET", f"/v1/executions/{normalized}", None)
        if not isinstance(payload, Mapping):
            raise GatewayTransportError("gateway get response is malformed")
        return GatewayExecutionSnapshot.from_dict(payload)

    def cancel(self, execution_id: str, reason: str) -> GatewayExecutionSnapshot:
        normalized = _http_execution_id(execution_id)
        payload = self._request(
            "POST",
            f"/v1/executions/{normalized}/cancel",
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
            if len(body) > self._max_request_bytes:
                raise GatewayPayloadTooLargeError("gateway request exceeds client limit")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self._base_url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                headers_obj = getattr(response, "headers", None)
                if headers_obj is not None:
                    content_length = headers_obj.get("Content-Length")
                    if content_length is not None:
                        try:
                            if int(content_length) > self._max_response_bytes:
                                raise GatewayTransportError(
                                    "gateway response exceeds client limit"
                                )
                        except ValueError:
                            pass
                raw = response.read(self._max_response_bytes + 1)
                if len(raw) > self._max_response_bytes:
                    raise GatewayTransportError("gateway response exceeds client limit")
        except urllib.error.HTTPError as exc:
            _raise_http_error(exc)
            raise AssertionError("unreachable")
        except GatewayTransportError:
            raise
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


def _http_execution_id(value: str) -> str:
    if not isinstance(value, str) or _HTTP_EXECUTION_ID.fullmatch(value) is None:
        raise ValueError("HTTP execution_id must use only A-Z a-z 0-9 _ . : -")
    return value


def _required_token(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4_096:
        raise ValueError("bearer_token must be a bounded non-empty string")
    return value.strip()


__all__ = ["HttpWorkerGatewayTransport", "create_worker_gateway_app"]
