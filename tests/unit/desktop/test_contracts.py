from __future__ import annotations

import json

import pytest

from paperclaw.desktop.contracts import (
    DesktopPublicError,
    DesktopRunRequest,
    DesktopRunSnapshot,
    public_event_row,
)


def _valid_request(tmp_path, *, api_key: str = "unit-test-secret") -> dict:
    return {
        "task": "write a deterministic report",
        "workspace": str(tmp_path),
        "base_url": "https://example.invalid/v1/",
        "api_key": api_key,
        "model": "test-model",
        "provider": "test-provider",
        "enable_verification_gate": True,
        "max_steps": 12,
        "max_model_calls": 10,
        "max_tool_calls": 20,
    }


def test_run_request_validates_and_hides_api_key_from_repr(tmp_path) -> None:
    request = DesktopRunRequest.from_mapping(_valid_request(tmp_path))
    assert request.workspace == str(tmp_path.resolve())
    assert request.base_url == "https://example.invalid/v1"
    assert request.api_key == "unit-test-secret"
    assert "unit-test-secret" not in repr(request)


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("task", "  ", "validation_error"),
        ("api_key", "", "validation_error"),
        ("model", "", "validation_error"),
        ("base_url", "file:///tmp/provider", "provider_configuration_error"),
        ("base_url", "https://user:pass@example.invalid/v1", "provider_configuration_error"),
        ("max_steps", 0, "validation_error"),
        ("max_model_calls", True, "validation_error"),
        ("max_tool_calls", 1001, "validation_error"),
    ],
)
def test_run_request_rejects_invalid_fields(
    tmp_path,
    field: str,
    value,
    expected_code: str,
) -> None:
    payload = _valid_request(tmp_path)
    payload[field] = value
    with pytest.raises(DesktopPublicError) as raised:
        DesktopRunRequest.from_mapping(payload)
    assert raised.value.code == expected_code
    if payload["api_key"]:
        assert payload["api_key"] not in str(raised.value)


def test_run_request_rejects_missing_workspace_and_unknown_fields(tmp_path) -> None:
    payload = _valid_request(tmp_path)
    payload["workspace"] = str(tmp_path / "missing")
    with pytest.raises(DesktopPublicError) as raised:
        DesktopRunRequest.from_mapping(payload)
    assert raised.value.code == "workspace_not_found"

    payload = _valid_request(tmp_path)
    payload["unexpected"] = "value"
    with pytest.raises(DesktopPublicError, match="Unknown request fields"):
        DesktopRunRequest.from_mapping(payload)


def test_snapshot_serialization_redacts_secret_from_every_visible_field() -> None:
    secret = "top-secret-value"
    snapshot = DesktopRunSnapshot(
        run_id="run-1",
        status="failed",
        stop_reason=f"failed near {secret}",
        verification_summary=f"summary {secret}",
        final_result=f"result {secret}",
        error_code="runtime_error",
        error_message=f"message {secret}",
        terminal=True,
    )
    rendered = json.dumps(snapshot.to_public_dict(secret=secret), sort_keys=True)
    assert secret not in rendered
    assert "<REDACTED>" in rendered
    assert "api_key" not in rendered


def test_event_projection_ignores_unknown_payload_and_redacts_allowed_values() -> None:
    secret = "event-secret"
    unknown = public_event_row(
        "future.secret.event",
        {
            "run_id": "run-1",
            "sequence": 7,
            "reasoning": secret,
            "tool_output": secret,
        },
    ).to_public_dict(secret=secret)
    assert unknown["label"] == "future.secret.event"
    assert secret not in json.dumps(unknown)

    known = public_event_row(
        "tool.failed",
        {
            "run_id": "run-1",
            "sequence": 8,
            "tool": f"tool-{secret}",
            "call_index": 2,
            "error_code": "TOOL_FAILED",
            "output": secret,
        },
    ).to_public_dict(secret=secret)
    rendered = json.dumps(known)
    assert secret not in rendered
    assert "output" not in rendered


def test_public_error_is_typed_bounded_and_contains_no_extra_fields() -> None:
    error = DesktopPublicError("validation_error", "x" * 600)
    payload = error.to_public_dict()
    assert payload == {
        "ok": False,
        "error_code": "validation_error",
        "error_message": "x" * 500,
    }
