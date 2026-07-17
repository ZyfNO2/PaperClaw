from __future__ import annotations

from pathlib import Path

import pytest

from paperclaw.policy import (
    AuthorizedTool,
    DefaultToolAuthorizationPolicy,
    ToolAuthorizationDecision,
    ToolRiskLevel,
)
from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = "fake"
        self.executed = False

    def validate(self, arguments):
        return None

    def execute(self, arguments, context):
        self.executed = True
        return ToolResult(True, "ok")


class BrokenPolicy:
    policy_id = "broken"

    def authorize(self, tool_name, arguments, workspace):
        raise RuntimeError("policy backend failed")


class InvalidPolicy:
    policy_id = "invalid"

    def authorize(self, tool_name, arguments, workspace):
        return True


def test_workspace_path_escape_is_denied(tmp_path):
    policy = DefaultToolAuthorizationPolicy()
    decision = policy.authorize(
        "file_read",
        {"path": "../outside.txt"},
        tmp_path,
    )
    assert decision.allowed is False
    assert decision.reason == "workspace_path_escape"


def test_private_network_and_metadata_urls_are_denied(tmp_path):
    policy = DefaultToolAuthorizationPolicy()
    for url in (
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1",
    ):
        decision = policy.authorize(
            "http_fetch",
            {"url": url},
            tmp_path,
        )
        assert decision.allowed is False
        assert decision.reason == "private_network_url"


def test_destructive_tool_requires_trusted_static_approval(tmp_path):
    denied = DefaultToolAuthorizationPolicy().authorize(
        "bash",
        {"command": "Get-ChildItem"},
        tmp_path,
    )
    allowed = DefaultToolAuthorizationPolicy(
        approved_tools={"bash"}
    ).authorize(
        "bash",
        {"command": "Get-ChildItem"},
        tmp_path,
    )
    assert denied == ToolAuthorizationDecision(
        False,
        ToolRiskLevel.DESTRUCTIVE,
        "approval_required",
        "default-tool-policy-v1",
    )
    assert allowed.allowed is True
    assert allowed.reason == "trusted_static_approval"


@pytest.mark.parametrize("policy", [BrokenPolicy(), InvalidPolicy()])
def test_policy_failure_or_invalid_result_fails_closed(tmp_path, policy):
    tool = FakeTool("file_read")
    authorized = AuthorizedTool(tool, workspace=tmp_path, policy=policy)
    with pytest.raises(ToolValidationError, match="denied by tool policy"):
        authorized.validate({"path": "safe.txt"})
    assert tool.executed is False


def test_authorized_tool_executes_only_after_policy_allows(tmp_path):
    path = tmp_path / "safe.txt"
    path.write_text("ok", encoding="utf-8")
    tool = FakeTool("file_read")
    authorized = AuthorizedTool(
        tool,
        workspace=tmp_path,
        policy=DefaultToolAuthorizationPolicy(),
    )
    authorized.validate({"path": "safe.txt"})
    result = authorized.execute(
        {"path": "safe.txt"},
        ToolContext(workspace=Path(tmp_path)),
    )
    assert result.ok is True
    assert tool.executed is True
