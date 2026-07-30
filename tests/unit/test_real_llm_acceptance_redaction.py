from pathlib import Path

from scripts.run_v0_05_real_llm_acceptance import _redact_event_payload


def test_redaction_removes_provider_and_nested_secrets() -> None:
    payload = {
        "request_id": "provider-request-123",
        "authorization": "Bearer secret",
        "nested": {
            "api_key": "secret-key",
            "access_token": "secret-token",
        },
    }

    redacted = _redact_event_payload(payload)

    assert redacted == {
        "request_id": "<redacted>",
        "authorization": "<redacted>",
        "nested": {
            "api_key": "<redacted>",
            "access_token": "<redacted>",
        },
    }


def test_redaction_replaces_absolute_tool_paths() -> None:
    workspace = Path("C:/acceptance/workspace")
    redacted = _redact_event_payload(
        {
            "cwd": str(workspace),
            "path": str(workspace / "hello.py"),
            "relative": "hello.py",
        }
    )

    assert redacted["cwd"] == "<workspace>/workspace"
    assert redacted["path"] == "<workspace>/hello.py"
    assert redacted["relative"] == "hello.py"
