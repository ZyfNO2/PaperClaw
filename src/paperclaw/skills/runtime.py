"""Skill discovery, trust classification and bounded instruction loading."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


class SkillTrust(StrEnum):
    LOCAL_TRUSTED = "local_trusted"
    WORKSPACE_REVIEWED = "workspace_reviewed"
    REMOTE_UNTRUSTED = "remote_untrusted"


_READ_ONLY_TOOLS = frozenset(
    {
        "file_read",
        "grep",
        "lsp_diagnostics",
        "lsp_definition",
        "lsp_references",
        "lsp_symbols",
        "lsp_hover",
    }
)


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    version: str
    trust: SkillTrust
    source: str
    allowed_tools: tuple[str, ...]
    parameters: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "trust": self.trust.value,
            "source": self.source,
            "allowed_tools": list(self.allowed_tools),
            "parameters": list(self.parameters),
        }


@dataclass(frozen=True)
class SkillDefinition:
    metadata: SkillMetadata
    instructions: str

    def to_dict(self, *, include_instructions: bool = False) -> dict[str, Any]:
        result = self.metadata.to_dict()
        if include_instructions:
            result["instructions"] = self.instructions
        return result


class SkillRuntimeError(RuntimeError):
    pass


class SkillNotFoundError(SkillRuntimeError):
    pass


class SkillRegistry:
    """Discover local SKILL.md files and explicitly registered remote Skills."""

    def __init__(
        self,
        *,
        workspace: str | Path,
        user_root: str | Path | None = None,
        max_instruction_chars: int = 60_000,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        self.user_root = (
            Path(user_root).expanduser().resolve()
            if user_root is not None
            else Path.home() / ".paperclaw" / "skills"
        )
        self.max_instruction_chars = max_instruction_chars
        self._definitions: dict[str, SkillDefinition] = {}
        self._remote: dict[str, SkillDefinition] = {}

    def discover(self) -> tuple[SkillMetadata, ...]:
        discovered: dict[str, SkillDefinition] = {}
        roots = [
            (self.user_root, SkillTrust.LOCAL_TRUSTED),
            (self.workspace / ".paperclaw" / "skills", SkillTrust.WORKSPACE_REVIEWED),
        ]
        for root, trust in roots:
            if not root.is_dir():
                continue
            resolved_root = root.resolve()
            for path in sorted(root.glob("*/SKILL.md")):
                try:
                    resolved = path.resolve(strict=True)
                except OSError:
                    continue
                if not _is_within(resolved_root, resolved):
                    continue
                definition = self._parse_file(resolved, trust)
                if definition.metadata.name in discovered:
                    continue
                discovered[definition.metadata.name] = definition
        # Explicit remote registrations never override local/reviewed Skills.
        for name, definition in self._remote.items():
            discovered.setdefault(name, definition)
        self._definitions = discovered
        return tuple(
            definition.metadata
            for _, definition in sorted(discovered.items())
        )

    def register_remote(
        self,
        *,
        name: str,
        description: str,
        version: str,
        instructions: str,
        allowed_tools: Sequence[str] = (),
        parameters: Sequence[str] = (),
        source: str = "mcp",
    ) -> SkillMetadata:
        normalized_tools = tuple(
            tool for tool in _strings(allowed_tools, "allowed_tools") if tool in _READ_ONLY_TOOLS
        )
        metadata = SkillMetadata(
            name=_name(name),
            description=_text(description, "description", 2_000),
            version=_text(version, "version", 100),
            trust=SkillTrust.REMOTE_UNTRUSTED,
            source=_text(source, "source", 1_000),
            allowed_tools=normalized_tools,
            parameters=_strings(parameters, "parameters"),
        )
        definition = SkillDefinition(
            metadata,
            _text(instructions, "instructions", self.max_instruction_chars),
        )
        self._remote[metadata.name] = definition
        self._definitions.pop(metadata.name, None)
        return metadata

    def list(self) -> tuple[SkillMetadata, ...]:
        return self.discover()

    def get(self, name: str) -> SkillDefinition:
        normalized = _name(name)
        self.discover()
        try:
            return self._definitions[normalized]
        except KeyError as exc:
            raise SkillNotFoundError(f"unknown skill: {normalized}") from exc

    def render(
        self,
        name: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> SkillDefinition:
        definition = self.get(name)
        supplied = dict(parameters or {})
        unknown = sorted(set(supplied) - set(definition.metadata.parameters))
        if unknown:
            raise ValueError(f"unknown skill parameters: {', '.join(unknown)}")
        missing = [
            parameter
            for parameter in definition.metadata.parameters
            if parameter not in supplied
        ]
        if missing:
            raise ValueError(f"missing skill parameters: {', '.join(missing)}")
        instructions = definition.instructions
        for parameter in definition.metadata.parameters:
            value = supplied[parameter]
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"skill parameter {parameter} must be scalar")
            instructions = instructions.replace(
                "{{" + parameter + "}}",
                str(value),
            )
        return SkillDefinition(definition.metadata, instructions)

    def _parse_file(self, path: Path, trust: SkillTrust) -> SkillDefinition:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillRuntimeError(f"skill could not be read: {path}") from exc
        metadata_values, body = _frontmatter(text)
        name = _name(metadata_values.get("name") or path.parent.name)
        description = _text(
            metadata_values.get("description") or f"Skill {name}",
            "description",
            2_000,
        )
        version = _text(metadata_values.get("version") or "1", "version", 100)
        requested_tools = _csv(metadata_values.get("allowed_tools", ""))
        allowed_tools = tuple(requested_tools)
        if trust is SkillTrust.WORKSPACE_REVIEWED:
            # Workspace Skills may request local tools, but recursive control tools
            # are never inherited from prose metadata.
            allowed_tools = tuple(
                tool
                for tool in allowed_tools
                if tool
                not in {
                    "delegate_tasks",
                    "task_create",
                    "enter_plan_mode",
                    "approve_plan",
                    "skill_load",
                }
            )
        parameters = tuple(_csv(metadata_values.get("parameters", "")))
        metadata = SkillMetadata(
            name=name,
            description=description,
            version=version,
            trust=trust,
            source=str(path),
            allowed_tools=allowed_tools,
            parameters=parameters,
        )
        return SkillDefinition(
            metadata,
            _text(body, "instructions", self.max_instruction_chars),
        )


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        raise SkillRuntimeError("SKILL.md frontmatter is not terminated")
    header = text[4:end]
    metadata: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise SkillRuntimeError("SKILL.md frontmatter must use key: value")
        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key not in {
            "name",
            "description",
            "version",
            "allowed_tools",
            "parameters",
        }:
            continue
        metadata[normalized_key] = value.strip()
    return metadata, text[end + 5 :].strip()


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _name(value: str) -> str:
    normalized = _text(value, "name", 100).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", normalized):
        raise ValueError("skill name must use lowercase letters, digits, ., _ or -")
    return normalized


def _text(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > limit:
        raise ValueError(f"{name} exceeds {limit} characters")
    return normalized


def _strings(values: Sequence[str], name: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a sequence")
    return tuple(_text(value, name, 200) for value in values)


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = [
    "SkillDefinition",
    "SkillMetadata",
    "SkillNotFoundError",
    "SkillRegistry",
    "SkillRuntimeError",
    "SkillTrust",
]
