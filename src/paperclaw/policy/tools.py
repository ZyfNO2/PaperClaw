"""Deterministic authorization boundary for model-proposed tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import ipaddress
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlparse

from paperclaw.tools.base import ToolContext, ToolResult, ToolValidationError
from paperclaw.tools.registry import ToolRegistry


class ToolRiskLevel(StrEnum):
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ToolAuthorizationDecision:
    allowed: bool
    risk: ToolRiskLevel
    reason: str
    policy_id: str


class ToolAuthorizationPolicy(Protocol):
    policy_id: str

    def authorize(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        workspace: Path,
    ) -> ToolAuthorizationDecision: ...


class DefaultToolAuthorizationPolicy:
    """Conservative reference policy used by the HTTP service.

    Read-only and workspace-scoped write tools are allowed after argument
    validation. Shell/external/destructive tools require an explicit static
    approval supplied by trusted application configuration, never by model text.
    """

    policy_id = "default-tool-policy-v1"

    def __init__(
        self,
        *,
        approved_tools: frozenset[str] | set[str] | tuple[str, ...] = (),
    ) -> None:
        self._approved_tools = frozenset(approved_tools)

    def authorize(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        workspace: Path,
    ) -> ToolAuthorizationDecision:
        normalized_name = tool_name.strip()
        if not normalized_name:
            return self._deny(ToolRiskLevel.DESTRUCTIVE, "missing_tool_name")
        try:
            resolved_workspace = workspace.resolve(strict=True)
        except Exception:
            return self._deny(ToolRiskLevel.DESTRUCTIVE, "invalid_workspace")

        path_error = _validate_paths(arguments, resolved_workspace)
        if path_error is not None:
            return self._deny(self._risk(normalized_name), path_error)
        network_error = _validate_urls(arguments)
        if network_error is not None:
            return self._deny(self._risk(normalized_name), network_error)

        risk = self._risk(normalized_name)
        if risk in {ToolRiskLevel.READ_ONLY, ToolRiskLevel.WORKSPACE_WRITE}:
            return ToolAuthorizationDecision(
                True, risk, "allowed_by_default_policy", self.policy_id
            )
        if normalized_name in self._approved_tools:
            return ToolAuthorizationDecision(
                True, risk, "trusted_static_approval", self.policy_id
            )
        return self._deny(risk, "approval_required")

    def _risk(self, tool_name: str) -> ToolRiskLevel:
        if tool_name in {"file_read", "grep"}:
            return ToolRiskLevel.READ_ONLY
        if tool_name in {"file_write", "file_edit"}:
            return ToolRiskLevel.WORKSPACE_WRITE
        if tool_name in {"bash", "shell", "sql_write"}:
            return ToolRiskLevel.DESTRUCTIVE
        if any(marker in tool_name for marker in ("send", "publish", "upload", "delete")):
            return ToolRiskLevel.EXTERNAL_WRITE
        return ToolRiskLevel.DESTRUCTIVE

    def _deny(self, risk: ToolRiskLevel, reason: str) -> ToolAuthorizationDecision:
        return ToolAuthorizationDecision(False, risk, reason, self.policy_id)


class AuthorizedTool:
    """Tool adapter that makes policy approval a prerequisite for execution."""

    def __init__(
        self,
        tool: Any,
        *,
        workspace: Path,
        policy: ToolAuthorizationPolicy,
    ) -> None:
        self._tool = tool
        self._workspace = workspace.resolve(strict=True)
        self._policy = policy
        self.name = tool.name
        self.description = tool.description

    def validate(self, arguments: dict[str, Any]) -> None:
        decision = self._decision(arguments)
        if not decision.allowed:
            raise ToolValidationError(
                "denied by tool policy "
                f"{decision.policy_id}: risk={decision.risk.value} "
                f"reason={decision.reason}"
            )
        self._tool.validate(arguments)

    def execute(
        self,
        arguments: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        decision = self._decision(arguments)
        if not decision.allowed:
            raise ToolValidationError(
                "denied by tool policy "
                f"{decision.policy_id}: risk={decision.risk.value} "
                f"reason={decision.reason}"
            )
        return self._tool.execute(arguments, context)

    def _decision(self, arguments: Mapping[str, Any]) -> ToolAuthorizationDecision:
        try:
            decision = self._policy.authorize(
                self.name,
                arguments,
                self._workspace,
            )
        except Exception as exc:
            return ToolAuthorizationDecision(
                False,
                ToolRiskLevel.DESTRUCTIVE,
                f"policy_error:{type(exc).__name__}",
                getattr(self._policy, "policy_id", "unknown-policy"),
            )
        if not isinstance(decision, ToolAuthorizationDecision):
            return ToolAuthorizationDecision(
                False,
                ToolRiskLevel.DESTRUCTIVE,
                "invalid_policy_result",
                getattr(self._policy, "policy_id", "unknown-policy"),
            )
        return decision


def authorize_registry(
    registry: ToolRegistry,
    *,
    workspace: Path | str,
    policy: ToolAuthorizationPolicy,
) -> ToolRegistry:
    resolved_workspace = Path(workspace).resolve(strict=True)
    return ToolRegistry(
        AuthorizedTool(
            registry.get(name),
            workspace=resolved_workspace,
            policy=policy,
        )
        for name in registry.names
    )


def _validate_paths(arguments: Mapping[str, Any], workspace: Path) -> str | None:
    for key, value in _walk(arguments):
        normalized_key = key.casefold().replace("-", "_")
        if not any(marker in normalized_key for marker in ("path", "file", "directory")):
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = workspace / candidate
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(workspace)
        except Exception:
            return "workspace_path_escape"
    return None


def _validate_urls(arguments: Mapping[str, Any]) -> str | None:
    for key, value in _walk(arguments):
        normalized_key = key.casefold().replace("-", "_")
        if "url" not in normalized_key and "uri" not in normalized_key:
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            return "unsupported_url_scheme"
        host = (parsed.hostname or "").casefold()
        if not host:
            return "missing_url_host"
        if parsed.username or parsed.password:
            return "url_credentials_not_allowed"
        if (
            host in {
                "localhost",
                "localhost.localdomain",
                "metadata.google.internal",
                "metadata.azure.internal",
                "instance-data",
            }
            or host.endswith(".localhost")
        ):
            return "private_network_url"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if host.isdigit() or (
                labels
                and all(
                    label.isdigit() or label.startswith("0x")
                    for label in labels
                )
            ):
                return "private_network_url"
            continue
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            return "private_network_url"
    return None


def _walk(value: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    found: list[tuple[str, Any]] = []

    def visit(item: Any, prefix: str = "") -> None:
        if isinstance(item, Mapping):
            for raw_key, child in list(item.items())[:200]:
                key = str(raw_key)
                found.append((key, child))
                visit(child, key)
        elif isinstance(item, (list, tuple)):
            for child in list(item)[:200]:
                visit(child, prefix)

    visit(value)
    return tuple(found)
