"""Deterministic MCP capability selection as a v0.08 ContextCandidate source."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Protocol

from paperclaw.context.orchestration import ContextCandidate, ContextRequest
from paperclaw.mcp.contracts import MCPToolDescriptor, bounded_text
from paperclaw.mcp.registration import mcp_registry_tool_name
from paperclaw.mcp.runtime import MCPRuntimeConnection

_TOKEN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class MCPCapabilityMetadata:
    """Prompt-independent searchable metadata for one registered MCP Tool."""

    qualified_name: str
    registry_tool_name: str
    server_id: str
    tool_name: str
    title: str | None
    description: str
    keywords: tuple[str, ...]
    input_fields: tuple[str, ...]
    scopes: tuple[str, ...]
    input_schema_hash: str

    def __post_init__(self) -> None:
        for name in (
            "qualified_name",
            "registry_tool_name",
            "server_id",
            "tool_name",
            "input_schema_hash",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if len(self.input_schema_hash) != 64:
            raise ValueError("input_schema_hash must be a SHA-256 digest")
        if not self.scopes or len(set(self.scopes)) != len(self.scopes):
            raise ValueError("scopes must be non-empty and unique")
        if len(set(self.keywords)) != len(self.keywords):
            raise ValueError("keywords must be unique")

    @classmethod
    def from_descriptor(
        cls,
        descriptor: MCPToolDescriptor,
        *,
        scopes: Iterable[str] = ("shared",),
        keywords: Iterable[str] = (),
    ) -> "MCPCapabilityMetadata":
        schema = descriptor.input_schema_dict()
        properties = schema.get("properties", {})
        input_fields = tuple(
            sorted(str(name) for name in properties if isinstance(name, str))
        )
        derived = _tokens(
            " ".join(
                (
                    descriptor.server_id,
                    descriptor.name,
                    descriptor.title or "",
                    descriptor.description,
                    " ".join(input_fields),
                    " ".join(keywords),
                )
            )
        )
        return cls(
            qualified_name=descriptor.qualified_name,
            registry_tool_name=mcp_registry_tool_name(descriptor),
            server_id=descriptor.server_id,
            tool_name=descriptor.name,
            title=descriptor.title,
            description=bounded_text(descriptor.description, 500),
            keywords=tuple(sorted(derived)),
            input_fields=input_fields,
            scopes=tuple(sorted(set(scopes))),
            input_schema_hash=descriptor.input_schema_hash,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["keywords"] = list(self.keywords)
        data["input_fields"] = list(self.input_fields)
        data["scopes"] = list(self.scopes)
        return data


@dataclass(frozen=True)
class MCPCapabilityIndexSnapshot:
    capabilities: tuple[MCPCapabilityMetadata, ...]
    fingerprint: str


class MCPCapabilityIndexFrozen(RuntimeError):
    pass


class MCPCapabilityIndex:
    """Deterministic in-memory metadata index over discovered MCP Tools."""

    def __init__(self) -> None:
        self._items: dict[str, MCPCapabilityMetadata] = {}
        self._lock = threading.RLock()
        self._frozen = False

    def add(self, metadata: MCPCapabilityMetadata) -> None:
        with self._lock:
            if self._frozen:
                raise MCPCapabilityIndexFrozen("MCP capability index is frozen")
            if metadata.qualified_name in self._items:
                raise ValueError(
                    f"duplicate MCP capability: {metadata.qualified_name}"
                )
            if any(
                item.registry_tool_name == metadata.registry_tool_name
                for item in self._items.values()
            ):
                raise ValueError(
                    f"duplicate MCP registry tool name: {metadata.registry_tool_name}"
                )
            self._items[metadata.qualified_name] = metadata

    def add_connection(
        self,
        connection: MCPRuntimeConnection,
        *,
        scopes_by_tool: Mapping[str, Iterable[str]] | None = None,
        keywords_by_tool: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        scopes_by_tool = scopes_by_tool or {}
        keywords_by_tool = keywords_by_tool or {}
        pending = tuple(
            MCPCapabilityMetadata.from_descriptor(
                descriptor,
                scopes=scopes_by_tool.get(
                    descriptor.qualified_name,
                    scopes_by_tool.get(descriptor.name, ("shared",)),
                ),
                keywords=keywords_by_tool.get(
                    descriptor.qualified_name,
                    keywords_by_tool.get(descriptor.name, ()),
                ),
            )
            for descriptor in connection.descriptors
        )
        with self._lock:
            if self._frozen:
                raise MCPCapabilityIndexFrozen("MCP capability index is frozen")
            existing_qualified = set(self._items)
            existing_registry = {
                item.registry_tool_name for item in self._items.values()
            }
            pending_qualified = [item.qualified_name for item in pending]
            pending_registry = [item.registry_tool_name for item in pending]
            if (
                existing_qualified.intersection(pending_qualified)
                or len(set(pending_qualified)) != len(pending_qualified)
                or existing_registry.intersection(pending_registry)
                or len(set(pending_registry)) != len(pending_registry)
            ):
                raise ValueError("MCP capability batch contains an identity collision")
            for item in pending:
                self._items[item.qualified_name] = item

    def freeze(self) -> MCPCapabilityIndexSnapshot:
        with self._lock:
            self._frozen = True
            return self.snapshot()

    def snapshot(self) -> MCPCapabilityIndexSnapshot:
        with self._lock:
            items = tuple(self._items[name] for name in sorted(self._items))
        payload = [item.to_dict() for item in items]
        fingerprint = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return MCPCapabilityIndexSnapshot(items, fingerprint)


@dataclass(frozen=True)
class MCPSelectionPermissionDecision:
    allowed: bool
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.allowed, bool):
            raise ValueError("allowed must be boolean")
        if not self.reason.strip():
            raise ValueError("reason must be non-empty")


class MCPSelectionPermissionPolicy(Protocol):
    """Selection-time eligibility only; invocation Permission remains authoritative."""

    def authorize(
        self,
        *,
        capability: MCPCapabilityMetadata,
        scopes: tuple[str, ...],
    ) -> MCPSelectionPermissionDecision: ...


@dataclass(frozen=True)
class DenyAllMCPSelectionPolicy:
    def authorize(
        self,
        *,
        capability: MCPCapabilityMetadata,
        scopes: tuple[str, ...],
    ) -> MCPSelectionPermissionDecision:
        del capability, scopes
        return MCPSelectionPermissionDecision(False, "not selection-eligible")


@dataclass(frozen=True)
class AllowListMCPSelectionPolicy:
    allowed_tools: frozenset[str]

    def authorize(
        self,
        *,
        capability: MCPCapabilityMetadata,
        scopes: tuple[str, ...],
    ) -> MCPSelectionPermissionDecision:
        del scopes
        allowed = capability.qualified_name in self.allowed_tools
        return MCPSelectionPermissionDecision(
            allowed,
            "selection allowlist match" if allowed else "not in selection allowlist",
        )


@dataclass(frozen=True)
class MCPCapabilitySelectionRequest:
    task: str
    scopes: tuple[str, ...] = ("shared",)
    top_k: int = 5

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ValueError("task must be non-empty")
        if not self.scopes:
            raise ValueError("scopes must be non-empty")
        if self.top_k <= 0 or self.top_k > 100:
            raise ValueError("top_k must be in [1, 100]")


@dataclass(frozen=True)
class MCPCapabilitySelection:
    capability: MCPCapabilityMetadata
    score: int
    matched_keywords: tuple[str, ...]
    permission_reason: str
    rank: int


class MCPCapabilitySelector:
    """Stable lexical/scope/permission Top-K selector over a frozen snapshot."""

    def __init__(
        self,
        snapshot: MCPCapabilityIndexSnapshot,
        *,
        permission_policy: MCPSelectionPermissionPolicy | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.permission_policy = permission_policy or DenyAllMCPSelectionPolicy()

    def select(
        self,
        request: MCPCapabilitySelectionRequest,
    ) -> tuple[MCPCapabilitySelection, ...]:
        task_tokens = _tokens(request.task)
        scored: list[tuple[int, tuple[str, ...], str, MCPCapabilityMetadata]] = []
        requested_scopes = set(request.scopes)
        for capability in self.snapshot.capabilities:
            available_scopes = set(capability.scopes)
            if "*" not in available_scopes and not requested_scopes.intersection(
                available_scopes
            ):
                continue
            try:
                decision = self.permission_policy.authorize(
                    capability=capability,
                    scopes=request.scopes,
                )
            except Exception:
                continue
            if not isinstance(decision, MCPSelectionPermissionDecision) or not decision.allowed:
                continue
            matched = tuple(sorted(task_tokens.intersection(capability.keywords)))
            if not matched:
                continue
            score = _score(capability, task_tokens, matched)
            scored.append((score, matched, decision.reason, capability))
        scored.sort(key=lambda item: (-item[0], item[3].qualified_name))
        return tuple(
            MCPCapabilitySelection(
                capability=capability,
                score=score,
                matched_keywords=matched,
                permission_reason=reason,
                rank=rank,
            )
            for rank, (score, matched, reason, capability) in enumerate(
                scored[: request.top_k],
                start=1,
            )
        )


class MCPCapabilityContextSource:
    """Convert selected MCP metadata to untrusted ContextCandidates."""

    def __init__(
        self,
        selector: MCPCapabilitySelector,
        *,
        top_k: int = 5,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        self.selector = selector
        self.top_k = top_k
        self.last_selection: tuple[MCPCapabilitySelection, ...] = ()

    def collect(self, request: ContextRequest) -> tuple[ContextCandidate, ...]:
        scopes = tuple(
            dict.fromkeys(
                (
                    "shared",
                    request.role,
                    *( (request.task_id,) if request.task_id else () ),
                )
            )
        )
        selection = self.selector.select(
            MCPCapabilitySelectionRequest(
                task=request.raw_prompt,
                scopes=scopes,
                top_k=self.top_k,
            )
        )
        self.last_selection = selection
        return tuple(_candidate(item) for item in selection)


def _candidate(selection: MCPCapabilitySelection) -> ContextCandidate:
    capability = selection.capability
    content = json.dumps(
        {
            "type": "mcp_capability",
            "registry_tool_name": capability.registry_tool_name,
            "remote_identity": capability.qualified_name,
            "title": capability.title,
            "description_untrusted": capability.description,
            "input_fields": list(capability.input_fields),
            "matched_keywords": list(selection.matched_keywords),
            "selection_score": selection.score,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ContextCandidate(
        candidate_id=f"mcp-capability:{capability.qualified_name}",
        source="mcp_capability_selection",
        source_ref=capability.qualified_name,
        layer="L4",
        kind="capability",
        scope=capability.scopes,
        priority=600 - selection.rank,
        trust="external_untrusted",
        freshness=0,
        estimated_tokens=max(1, (len(content) + 3) // 4),
        content=content,
        bucket="tool",
        metadata={
            "registry_tool_name": capability.registry_tool_name,
            "input_schema_hash": capability.input_schema_hash,
            "rank": selection.rank,
            "score": selection.score,
            "permission_granted": False,
            "invocation_permission_recheck_required": True,
        },
    )


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN.findall(value) if len(token) >= 2}


def _score(
    capability: MCPCapabilityMetadata,
    task_tokens: set[str],
    matched: tuple[str, ...],
) -> int:
    tool_tokens = _tokens(capability.tool_name)
    title_tokens = _tokens(capability.title or "")
    field_tokens = _tokens(" ".join(capability.input_fields))
    description_tokens = _tokens(capability.description)
    return (
        10 * len(task_tokens.intersection(tool_tokens))
        + 6 * len(task_tokens.intersection(title_tokens))
        + 3 * len(task_tokens.intersection(field_tokens))
        + len(task_tokens.intersection(description_tokens))
        + 2 * len(matched)
    )


__all__ = [
    "AllowListMCPSelectionPolicy",
    "DenyAllMCPSelectionPolicy",
    "MCPCapabilityContextSource",
    "MCPCapabilityIndex",
    "MCPCapabilityIndexFrozen",
    "MCPCapabilityIndexSnapshot",
    "MCPCapabilityMetadata",
    "MCPCapabilitySelection",
    "MCPCapabilitySelectionRequest",
    "MCPCapabilitySelector",
    "MCPSelectionPermissionDecision",
    "MCPSelectionPermissionPolicy",
]
