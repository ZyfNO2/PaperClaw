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
