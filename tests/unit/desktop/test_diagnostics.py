from __future__ import annotations

import json
from pathlib import Path

from paperclaw.desktop import app
from paperclaw.desktop.diagnostics import diagnostic_log_path, record_exception


def test_diagnostic_log_path_has_stable_state_location(tmp_path) -> None:
    path = diagnostic_log_path(
        environment={"XDG_STATE_HOME": str(tmp_path / "state")},
        home=tmp_path / "home",
    )
    assert path.name == "desktop.log"
    assert "paperclaw" in {part.lower() for part in path.parts}


def test_record_exception_redacts_explicit_and_credential_shaped_values(tmp_path) -> None:
    secret = "sk-unit-test-secret-123456"
    target = tmp_path / "desktop.log"
    try:
        raise RuntimeError(f"api_key={secret} authorization Bearer token-secret-123456")
    except RuntimeError as exc:
        assert record_exception(
            "desktop_host_error",
            exc,
            secret=secret,
            path=target,
        ) == target

    rendered = target.read_text(encoding="utf-8")
    assert secret not in rendered
    assert "token-secret-123456" not in rendered
    assert "<REDACTED>" in rendered
    assert "desktop_host_error" in rendered
    assert "Traceback" in rendered


def test_app_main_returns_typed_error_and_records_unexpected_host_failure(
    monkeypatch,
    capsys,
) -> None:
    captured = []

    def fail_desktop(*, debug=False):
        raise RuntimeError("host failed")

    def capture(code, exc):
        captured.append((code, type(exc).__name__))
        return Path("desktop.log")

    monkeypatch.setattr(app, "run_desktop", fail_desktop)
    monkeypatch.setattr(app, "record_exception", capture)
    assert app.main([]) == 1
    output = json.loads(capsys.readouterr().err)
    assert output["error_code"] == "runtime_error"
    assert "host failed" not in output["error_message"]
    assert captured == [("desktop_host_error", "RuntimeError")]
