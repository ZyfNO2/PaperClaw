"""Machine-readable PaperClaw capability truth source."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Iterable

_CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_VERSION = re.compile(r"^v\d+\.\d+(?:\.\d+)?$")
_MATURITIES = frozenset({"shipped", "foundation", "experimental", "planned"})
_SURFACES = frozenset({"library", "cli", "tui", "desktop", "service"})


@dataclass(frozen=True, order=True)
class CapabilityDescriptor:
    capability_id: str
    introduced_version: str
    maturity: str
    surfaces: tuple[str, ...]
    summary: str
    dependencies: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _CAPABILITY_ID.fullmatch(self.capability_id) is None:
            raise ValueError("invalid capability_id")
        if _VERSION.fullmatch(self.introduced_version) is None:
            raise ValueError("invalid introduced_version")
        if self.maturity not in _MATURITIES:
            raise ValueError("invalid capability maturity")
        normalized_surfaces = tuple(sorted(dict.fromkeys(self.surfaces)))
        if not normalized_surfaces or any(
            surface not in _SURFACES for surface in normalized_surfaces
        ):
            raise ValueError("invalid capability surfaces")
        if not isinstance(self.summary, str) or not self.summary.strip():
            raise ValueError("capability summary must not be empty")
        normalized_dependencies = tuple(sorted(dict.fromkeys(self.dependencies)))
        normalized_limitations = tuple(
            item.strip() for item in self.limitations if item.strip()
        )
        object.__setattr__(self, "surfaces", normalized_surfaces)
        object.__setattr__(self, "dependencies", normalized_dependencies)
        object.__setattr__(self, "limitations", normalized_limitations)

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "introduced_version": self.introduced_version,
            "maturity": self.maturity,
            "surfaces": list(self.surfaces),
            "summary": self.summary,
            "dependencies": list(self.dependencies),
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True)
class CapabilityCatalog:
    capabilities: tuple[CapabilityDescriptor, ...]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported capability catalog schema")
        ordered = tuple(sorted(self.capabilities, key=lambda item: item.capability_id))
        ids = [item.capability_id for item in ordered]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate capability_id")
        known = set(ids)
        for item in ordered:
            unknown = set(item.dependencies) - known
            if unknown:
                raise ValueError(
                    f"unknown dependencies for {item.capability_id}: {sorted(unknown)}"
                )
        object.__setattr__(self, "capabilities", ordered)

    def select(
        self,
        *,
        maturity: str | None = None,
        surface: str | None = None,
    ) -> tuple[CapabilityDescriptor, ...]:
        if maturity is not None and maturity not in _MATURITIES:
            raise ValueError("invalid capability maturity filter")
        if surface is not None and surface not in _SURFACES:
            raise ValueError("invalid capability surface filter")
        return tuple(
            item
            for item in self.capabilities
            if (maturity is None or item.maturity == maturity)
            and (surface is None or surface in item.surfaces)
        )

    def to_dict(
        self,
        *,
        maturity: str | None = None,
        surface: str | None = None,
    ) -> dict[str, object]:
        selected = self.select(maturity=maturity, surface=surface)
        return {
            "schema_version": self.schema_version,
            "count": len(selected),
            "filters": {"maturity": maturity, "surface": surface},
            "capabilities": [item.to_dict() for item in selected],
        }

    def to_json(
        self,
        *,
        maturity: str | None = None,
        surface: str | None = None,
    ) -> str:
        return json.dumps(
            self.to_dict(maturity=maturity, surface=surface),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )

    def render_text(
        self,
        *,
        maturity: str | None = None,
        surface: str | None = None,
    ) -> str:
        selected = self.select(maturity=maturity, surface=surface)
        lines = [
            "PaperClaw Capability Catalog v1",
            f"count={len(selected)} maturity={maturity or '*'} surface={surface or '*'}",
        ]
        for item in selected:
            lines.append(
                f"- {item.capability_id} [{item.maturity}] "
                f"{item.introduced_version} ({','.join(item.surfaces)}): {item.summary}"
            )
            lines.extend(f"  limit: {value}" for value in item.limitations)
        return "\n".join(lines)


def _items(value: Iterable[str] | str) -> tuple[str, ...]:
    """Normalize metadata without accidentally iterating one string by character."""
    if isinstance(value, str):
        return (value,)
    return tuple(value)


def _cap(
    capability_id: str,
    version: str,
    maturity: str,
    surfaces: Iterable[str] | str,
    summary: str,
    *,
    dependencies: Iterable[str] | str = (),
    limitations: Iterable[str] | str = (),
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        introduced_version=version,
        maturity=maturity,
        surfaces=_items(surfaces),
        summary=summary,
        dependencies=_items(dependencies),
        limitations=_items(limitations),
    )


def default_capability_catalog() -> CapabilityCatalog:
    """Return the audited capability catalog for the v0.27 stack."""
    capabilities = (
        _cap(
            "agent.react_runtime", "v0.01", "shipped", ("library", "cli"),
            "Bounded ReAct coding-agent runtime with allowlisted tools.",
        ),
        _cap(
            "verification.evidence_gate", "v0.02", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "Deterministic evidence verification and bounded reflection.",
            dependencies="agent.react_runtime",
        ),
        _cap(
            "multiagent.coordinator", "v0.03", "shipped",
            ("library", "cli", "tui"),
            "Coordinator/Worker/Reviewer orchestration with DAG and permissions.",
            dependencies="agent.react_runtime",
            limitations="Durable message-bus choreography is not wired yet.",
        ),
        _cap(
            "context.session_store", "v0.04", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "SQLite-backed session, checkpoint and safe resume contracts.",
        ),
        _cap(
            "harness.query_engine", "v0.05", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "Stable bounded run entrypoint and event contract.",
            dependencies="agent.react_runtime",
        ),
        _cap(
            "ui.tui", "v0.06", "shipped", "tui",
            "Textual thin client with cancellation and safe session selection.",
            dependencies="harness.query_engine",
        ),
        _cap(
            "trace.durable", "v0.07", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "Versioned redacted durable trace, inspection, replay and evaluation.",
            dependencies="context.session_store",
        ),
        _cap(
            "context.orchestration", "v0.08", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "Trust-aware deterministic prompt assembly with bounded context.",
        ),
        _cap(
            "mcp.tool_gateway", "v0.09", "foundation",
            ("library", "cli", "service"),
            "MCP discovery, schema adaptation, permission recheck and calls.",
            limitations="No unified project connector-management surface.",
        ),
        _cap(
            "retrieval.local_bm25", "v0.09.1", "foundation",
            ("library", "cli"),
            "Incremental local BM25 retrieval with grounded citation anchors.",
            dependencies="context.orchestration",
            limitations=(
                "Lexical retrieval only; semantic recall and reranking are deferred.",
                "Project lifecycle integration is introduced in v0.27.",
            ),
        ),
        _cap(
            "model.policy", "v0.10", "shipped",
            ("library", "cli", "desktop", "service"),
            "Provider/model selection, reliability and bounded fallback policy.",
        ),
        _cap(
            "ui.desktop", "v0.11", "experimental", "desktop",
            "Thin pywebview desktop shell with in-memory provider secrets.",
            dependencies=("harness.query_engine", "model.policy"),
            limitations="Capability/project/skill management UI is deferred.",
        ),
        _cap(
            "memory.long_term", "v0.17", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "Bounded user profile, long memory and project instruction context.",
            dependencies="context.orchestration",
        ),
        _cap(
            "tasks.durable_runtime", "v0.19", "foundation",
            ("library", "cli", "service"),
            "Durable background task lifecycle, leases, heartbeat and recovery.",
        ),
        _cap(
            "agent.plan_mode", "v0.20", "shipped",
            ("library", "cli", "tui", "desktop", "service"),
            "Plan mode, user questions and static Skills loading.",
        ),
        _cap(
            "lsp.read_only", "v0.21", "foundation", ("library", "cli"),
            "Read-only diagnostics, definition, references, symbols and hover.",
        ),
        _cap(
            "verification.semantic_acceptance", "v0.22", "foundation",
            ("library", "cli", "service"),
            "Separated deterministic verification and semantic acceptance judging.",
            dependencies="verification.evidence_gate",
        ),
        _cap(
            "executor.subprocess", "v0.23", "foundation",
            ("library", "cli", "service"),
            "Allowlisted subprocess execution with process-tree termination.",
            limitations="Parallel Coordinator remains in-process.",
        ),
        _cap(
            "worker.remote_gateway", "v0.24", "foundation",
            ("library", "service"),
            "Authenticated idempotent remote execution transport.",
            dependencies="executor.subprocess",
            limitations="Idempotency is gateway-process lifetime only.",
        ),
        _cap(
            "tasks.fenced_queue", "v0.25", "foundation",
            ("library", "cli", "service"),
            "Generation-fenced durable ownership and multi-process contention safety.",
            dependencies="tasks.durable_runtime",
            limitations="SQLite evidence is same-filesystem, not multi-host.",
        ),
        _cap(
            "multiagent.message_bus", "v0.26", "foundation", "library",
            "Durable ordered Agent message envelopes with cursors and backpressure.",
            limitations="Not wired into Coordinator runtime choreography.",
        ),
        _cap(
            "product.capability_catalog", "v0.27", "experimental",
            ("library", "cli"),
            "Machine-readable capability maturity, surfaces and limitations.",
        ),
        _cap(
            "project.workspace", "v0.27", "experimental", ("library", "cli"),
            "Safe project manifest, instructions and local knowledge indexing.",
            dependencies=(
                "context.orchestration",
                "memory.long_term",
                "retrieval.local_bm25",
            ),
        ),
        _cap(
            "artifact.revisions", "v0.27", "planned",
            ("library", "desktop", "service"),
            "First-class versioned outputs linked to run/task/trace evidence.",
            limitations="Planned for a later release; no implementation yet.",
        ),
        _cap(
            "evaluation.aggregate_dashboard", "v0.27", "planned",
            ("library", "desktop", "service"),
            "Aggregate success, tool accuracy, latency and cost evaluation.",
            dependencies="trace.durable",
            limitations="Current evaluation is primarily per trace.",
        ),
    )
    return CapabilityCatalog(capabilities)


__all__ = [
    "CapabilityCatalog",
    "CapabilityDescriptor",
    "default_capability_catalog",
]
