from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.skills import SkillListTool, SkillRegistry, SkillTool, SkillTrust
from paperclaw.tools.base import ToolContext


def write_skill(root: Path, name: str, body: str) -> None:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(body, encoding="utf-8")


def test_workspace_skill_discovery_and_parameter_rendering(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_skill(
        workspace / ".paperclaw" / "skills",
        "review",
        """---
name: review
description: Review a module
version: 2
allowed_tools: file_read, grep, delegate_tasks
parameters: target
---
Review {{target}} and return findings.
""",
    )
    registry = SkillRegistry(workspace=workspace, user_root=tmp_path / "user-skills")

    metadata = registry.list()
    assert len(metadata) == 1
    assert metadata[0].trust is SkillTrust.WORKSPACE_REVIEWED
    assert metadata[0].allowed_tools == ("file_read", "grep")

    rendered = registry.render("review", {"target": "src/paperclaw"})
    assert "src/paperclaw" in rendered.instructions
    assert "{{target}}" not in rendered.instructions


def test_user_skill_precedes_workspace_duplicate(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_root = tmp_path / "user-skills"
    write_skill(
        user_root,
        "same",
        "---\nname: same\ndescription: trusted\n---\nTrusted instructions.",
    )
    write_skill(
        workspace / ".paperclaw" / "skills",
        "same",
        "---\nname: same\ndescription: workspace\n---\nWorkspace instructions.",
    )
    registry = SkillRegistry(workspace=workspace, user_root=user_root)

    definition = registry.get("same")
    assert definition.metadata.trust is SkillTrust.LOCAL_TRUSTED
    assert definition.instructions == "Trusted instructions."


def test_remote_skill_is_read_only_and_cannot_override_local(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    user_root = tmp_path / "user-skills"
    write_skill(
        user_root,
        "safe",
        "---\nname: safe\ndescription: local\n---\nLocal.",
    )
    registry = SkillRegistry(workspace=workspace, user_root=user_root)
    remote = registry.register_remote(
        name="remote-review",
        description="remote",
        version="1",
        instructions="Remote read-only review.",
        allowed_tools=["file_read", "bash", "task_create"],
    )
    registry.register_remote(
        name="safe",
        description="attempted override",
        version="9",
        instructions="Remote override.",
        allowed_tools=["file_read"],
    )

    assert remote.trust is SkillTrust.REMOTE_UNTRUSTED
    assert remote.allowed_tools == ("file_read",)
    assert registry.get("safe").metadata.trust is SkillTrust.LOCAL_TRUSTED


def test_skill_tools_return_instruction_artifact_without_permission_effect(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_skill(
        workspace / ".paperclaw" / "skills",
        "summarize",
        "---\nname: summarize\ndescription: Summarize\n---\nRead and summarize.",
    )
    registry = SkillRegistry(workspace=workspace, user_root=tmp_path / "user")
    context = ToolContext(workspace)

    listed = json.loads(SkillListTool(registry).execute({}, context).output)
    assert listed["skills"][0]["name"] == "summarize"
    loaded = json.loads(
        SkillTool(registry).execute({"name": "summarize"}, context).output
    )
    assert loaded["permission_effect"] == "none"
    assert loaded["recursive_execution"] is False
    assert loaded["skill"]["instructions"] == "Read and summarize."


def test_skill_rejects_unknown_or_missing_parameters(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    write_skill(
        workspace / ".paperclaw" / "skills",
        "parameterized",
        "---\nname: parameterized\ndescription: p\nparameters: target\n---\n{{target}}",
    )
    registry = SkillRegistry(workspace=workspace, user_root=tmp_path / "user")
    with pytest.raises(ValueError, match="missing skill parameters"):
        registry.render("parameterized", {})
    with pytest.raises(ValueError, match="unknown skill parameters"):
        registry.render("parameterized", {"target": "x", "other": "y"})
