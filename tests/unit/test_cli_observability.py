import threading
from pathlib import Path

from conftest import FakeModel, action, done
from paperclaw.agent.flow import AgentRuntime


def test_runtime_emits_tool_events(tmp_path: Path) -> None:
    events: list[tuple[str, dict]] = []
    model = FakeModel([action("file_write", {"path": "hello.py", "content": "print('ok')"}, reason="write file"), action("bash", {"command": "python hello.py"}, reason="run file"), done(result="ok", verification="python hello.py => ok")])
    state = AgentRuntime(model).run("test", tmp_path, event_handler=lambda event, payload: events.append((event, payload)))

    assert state["stop_reason"] == "done"
    event_names = [name for name, _ in events]
    assert "tool_call" in event_names
    assert "tool_result" in event_names
    assert "done" in event_names


def test_runtime_honours_cancel_event(tmp_path: Path) -> None:
    """Cooperative cancellation stops the loop at the next decision boundary."""

    cancel_event = threading.Event()
    # The model would otherwise run multiple steps.
    model = FakeModel([action("file_read", {"path": "x.txt"}, reason="read")] * 10)
    cancel_event.set()

    state = AgentRuntime(model).run("test", tmp_path, cancel_event=cancel_event)

    assert state["stop_reason"] == "cancelled"
