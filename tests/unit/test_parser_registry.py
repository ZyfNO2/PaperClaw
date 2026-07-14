import pytest

from paperclaw.agent.parser import ActionParseError, parse_action
from paperclaw.agent.state import DoneAction, ToolCall
from paperclaw.tools.file_read import FileReadTool
from paperclaw.tools.registry import ToolRegistry


def test_parser_accepts_tool_done_and_fenced_repair() -> None:
    call = parse_action('{"action":"file_read","arguments":{"path":"a"},"reason":"read"}', ("file_read",))
    done = parse_action('```json\n{"action":"done","arguments":{"result":"ok"}}\n```', ("file_read",))
    assert isinstance(call, ToolCall) and isinstance(done, DoneAction)


def test_parser_normalizes_done_optional_fields() -> None:
    done = parse_action('{"action":"done","arguments":{"result":"ok","verification":null,"remaining_issues":"none"}}', ("file_read",))
    assert isinstance(done, DoneAction)
    assert done.verification == ""
    assert done.remaining_issues == ["none"]


@pytest.mark.parametrize("raw", ["not json", "[]", '{"action":"unknown","arguments":{}}', '{"action":"file_read","arguments":[]}'])
def test_parser_rejects_invalid_output(raw: str) -> None:
    with pytest.raises(ActionParseError):
        parse_action(raw, ("file_read",))


def test_registry_rejects_duplicate() -> None:
    with pytest.raises(ValueError):
        ToolRegistry([FileReadTool(), FileReadTool()])
