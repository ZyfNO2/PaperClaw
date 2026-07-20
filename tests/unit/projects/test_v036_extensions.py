from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperclaw.projects.extension_cli import main as extension_main
from paperclaw.projects.extension_runtime import ProjectExtensionActivator
from paperclaw.projects.extensions import (
    ExtensionPermissions,
    ProjectExtensionDescriptor,
    ProjectExtensionRegistry,
)
from paperclaw.projects.manifest import ProjectManifestStore


class Runtime:
    def __init__(self, tools):
        self.tools = tools
        self.closed = False

    def discover_tools(self):
        return self.tools

    def close(self) -> None:
        self.closed = True


def workspace(tmp_path: Path) -> Path:
    ProjectManifestStore(tmp_path).initialize("Extension Test")
    return tmp_path


def test_skill_activation_is_bounded_and_syncs_manifest(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    skill = root / "skills" / "review.md"
    skill.parent.mkdir()
    skill.write_text("Review evidence before answering.\n", encoding="utf-8")
    registry = ProjectExtensionRegistry(root)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="skill.review",
            kind="skill",
            version="1.0.0",
            entrypoint="skills/review.md",
            enabled=True,
            permissions=ExtensionPermissions(
                tools=("file_read",),
                read_paths=("docs",),
            ),
        )
    )

    manifest = ProjectManifestStore(root).load()
    assert manifest.enabled_skills == ("skill.review",)
    activation = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(
            tools=("file_read", "grep"),
            read_paths=("docs", "src"),
        ),
    ).activate()
    active = activation.skills[0]
    assert active.path == "skills/review.md"
    assert active.permissions.tools == ("file_read",)
    assert active.permissions.read_paths == ("docs",)
    assert "Review evidence" in active.content


def test_connector_factory_is_allowlisted_and_tools_are_filtered(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    registry = ProjectExtensionRegistry(root)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.search",
            kind="connector",
            version="2.0.0",
            entrypoint="mcp:search",
            enabled=True,
            trust_source="verified",
            auth_ref="secret://project/search",
            permissions=ExtensionPermissions(
                tools=("search", "admin"),
                network_hosts=("search.example.com",),
            ),
        )
    )
    runtime = Runtime(
        [
            {
                "name": "search",
                "description": "Search evidence",
                "input_schema": {"type": "object"},
            },
            {"name": "admin", "input_schema": {}},
        ]
    )
    captured = []

    def factory(descriptor, permissions):
        captured.append((descriptor.auth_ref, permissions.tools))
        return runtime

    activator = ProjectExtensionActivator(
        registry,
        permission_ceiling=ExtensionPermissions(
            tools=("search",),
            network_hosts=("search.example.com",),
        ),
        connector_factories={"search": factory},
    )
    public = activator.activate().to_public_dict()
    assert captured == [("secret://project/search", ("search",))]
    assert [item["name"] for item in public["connectors"][0]["tools"]] == [
        "search"
    ]
    assert "auth_ref" not in json.dumps(public)
    assert "secret://project/search" in registry.path.read_text(encoding="utf-8")
    activator.close()
    assert runtime.closed


def test_unknown_factory_and_untrusted_skill_fail_closed(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    registry = ProjectExtensionRegistry(root)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.unknown",
            kind="connector",
            version="1.0.0",
            entrypoint="mcp:unknown",
            enabled=True,
            permissions=ExtensionPermissions(tools=("query",)),
        )
    )
    with pytest.raises(PermissionError, match="not registered"):
        ProjectExtensionActivator(
            registry,
            permission_ceiling=ExtensionPermissions(tools=("query",)),
        ).activate()

    registry.remove("connector.unknown")
    (root / "untrusted.md").write_text("data", encoding="utf-8")
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="skill.untrusted",
            kind="skill",
            version="1.0.0",
            entrypoint="untrusted.md",
            enabled=True,
            trust_source="untrusted",
        )
    )
    with pytest.raises(PermissionError, match="trust source"):
        ProjectExtensionActivator(
            registry,
            permission_ceiling=ExtensionPermissions(),
        ).activate()


def test_symlinks_private_discovery_and_size_limit_fail_closed(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    target = root / "target.md"
    target.write_text("content", encoding="utf-8")
    link = root / "skill.md"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    registry = ProjectExtensionRegistry(root)
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="skill.link",
            kind="skill",
            version="1.0.0",
            entrypoint="skill.md",
            enabled=True,
        )
    )
    with pytest.raises(ValueError, match="symbolic link"):
        ProjectExtensionActivator(
            registry, permission_ceiling=ExtensionPermissions()
        ).activate()

    registry.remove("skill.link")
    large = root / "large.md"
    large.write_text("abcd", encoding="utf-8")
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="skill.large",
            kind="skill",
            version="1.0.0",
            entrypoint="large.md",
            enabled=True,
        )
    )
    with pytest.raises(ValueError, match="byte limit"):
        ProjectExtensionActivator(
            registry,
            permission_ceiling=ExtensionPermissions(),
            max_skill_bytes=3,
        ).activate()

    registry.remove("skill.large")
    registry.register(
        ProjectExtensionDescriptor(
            extension_id="connector.private",
            kind="connector",
            version="1.0.0",
            entrypoint="mcp:private",
            enabled=True,
            permissions=ExtensionPermissions(tools=("query",)),
        )
    )
    runtime = Runtime(
        [
            {
                "name": "query",
                "input_schema": {"type": "object", "access_token": "blocked"},
            }
        ]
    )
    with pytest.raises(ValueError, match="private field"):
        ProjectExtensionActivator(
            registry,
            permission_ceiling=ExtensionPermissions(tools=("query",)),
            connector_factories={"private": lambda *_: runtime},
        ).activate()
    assert runtime.closed


def test_audit_symlink_and_private_metadata_are_rejected(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    control = root / ".paperclaw"
    control.mkdir(exist_ok=True)
    target = root / "outside.sqlite3"
    target.touch()
    audit = control / "extensions-audit.sqlite3"
    try:
        audit.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ValueError, match="audit database"):
        ProjectExtensionRegistry(root)

    audit.unlink()
    registry = ProjectExtensionRegistry(root)
    with pytest.raises(ValueError, match="private field"):
        registry.register(
            ProjectExtensionDescriptor(
                extension_id="connector.bad",
                kind="connector",
                version="1.0.0",
                entrypoint="mcp:bad",
                metadata={"access_token": "blocked"},
            )
        )


def test_cli_register_list_validate_and_audit(tmp_path: Path, capsys) -> None:
    root = workspace(tmp_path)
    (root / "skill.md").write_text("Bounded skill", encoding="utf-8")
    prefix = ["--workspace", str(root)]
    assert extension_main(
        prefix
        + [
            "register-skill",
            "--id",
            "skill.cli",
            "--version",
            "1.0.0",
            "--entrypoint",
            "skill.md",
            "--enabled",
            "--tool",
            "file_read",
        ]
    ) == 0
    capsys.readouterr()
    assert extension_main(prefix + ["list", "--enabled", "true"]) == 0
    assert json.loads(capsys.readouterr().out)["extensions"][0][
        "extension_id"
    ] == "skill.cli"
    assert extension_main(prefix + ["validate"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert extension_main(prefix + ["audit"]) == 0
    assert json.loads(capsys.readouterr().out)["events"][0]["action"] == "register"
