import io
from pathlib import Path

from paperclaw.harness import RunLimits
from paperclaw.tui.runner import run_tui


class Stream(io.StringIO):
    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def test_no_tty_falls_back_when_task_is_available(tmp_path: Path) -> None:
    called = []
    stderr = Stream(tty=False)
    code = run_tui(
        workspace=tmp_path,
        limits=RunLimits(),
        enable_verification_gate=True,
        initial_task="task",
        no_tui=False,
        fallback=lambda: called.append(True) or 7,
        stdin=Stream(tty=False),
        stdout=Stream(tty=False),
        stderr=stderr,
    )
    assert code == 7
    assert called == [True]
    assert "Falling back" in stderr.getvalue()


def test_no_tty_without_task_returns_usage_error(tmp_path: Path) -> None:
    stderr = Stream(tty=False)
    code = run_tui(
        workspace=tmp_path,
        limits=RunLimits(),
        enable_verification_gate=True,
        initial_task=None,
        no_tui=False,
        fallback=None,
        stdin=Stream(tty=False),
        stdout=Stream(tty=False),
        stderr=stderr,
    )
    assert code == 2
    assert "paperclaw agent" in stderr.getvalue()


def test_explicit_fallback_does_not_create_requested_database(tmp_path: Path) -> None:
    database = tmp_path / "missing-parent" / "paperclaw.db"
    code = run_tui(
        workspace=tmp_path,
        limits=RunLimits(),
        enable_verification_gate=True,
        initial_task="task",
        no_tui=True,
        database=database,
        fallback=lambda: 0,
        stdin=Stream(tty=False),
        stdout=Stream(tty=False),
        stderr=Stream(tty=False),
    )
    assert code == 0
    assert database.exists() is False
    assert database.parent.exists() is False


def test_missing_textual_falls_back_even_with_tty(tmp_path: Path, monkeypatch) -> None:
    from paperclaw.tui import runner

    monkeypatch.setattr(runner, "textual_available", lambda: False)
    called = []
    stderr = Stream(tty=True)
    code = runner.run_tui(
        workspace=tmp_path,
        limits=RunLimits(),
        enable_verification_gate=True,
        initial_task="task",
        no_tui=False,
        fallback=lambda: called.append(True) or 0,
        stdin=Stream(tty=True),
        stdout=Stream(tty=True),
        stderr=stderr,
    )
    assert code == 0
    assert called == [True]
    assert "textual" in stderr.getvalue()
