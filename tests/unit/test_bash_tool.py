import threading
import time
from pathlib import Path

import pytest

from paperclaw.tools.bash import BashTool
from paperclaw.tools.base import ToolContext


class _TestStopToken:
    """Minimal StopToken implementation for cooperative-cancel tests."""

    def __init__(self) -> None:
        self._cancelled = False
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def reason(self) -> str | None:
        return self._reason

    def cancel(self, reason: str = "test") -> None:
        self._reason = reason
        self._cancelled = True


def test_bash_tool_respects_stop_token_mid_execution(tmp_path: Path) -> None:
    """A cancelled stop token terminates a long-running bash command early."""
    tool = BashTool()
    token = _TestStopToken()
    context = ToolContext(workspace=tmp_path, stop_token=token)

    def cancel_after_delay() -> None:
        time.sleep(0.5)
        token.cancel("user_requested")

    canceller = threading.Thread(target=cancel_after_delay, daemon=True)
    canceller.start()

    start = time.monotonic()
    with pytest.raises(RuntimeError, match="bash execution cancelled"):
        tool.execute(
            {"command": "python -c \"import time; time.sleep(5)\""},
            context,
        )
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"command was not cancelled promptly: {elapsed:.2f}s"
