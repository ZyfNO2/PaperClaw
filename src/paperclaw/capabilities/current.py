"""Current-stack capability catalog transformations through v0.32."""

from __future__ import annotations

from dataclasses import replace

from .catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    default_capability_catalog as _baseline_catalog,
)


def default_capability_catalog() -> CapabilityCatalog:
    """Return the audited capability catalog for the v0.32 development line.

    The baseline may already contain descriptors that older stacked transforms
    appended. Replace by capability id and append only genuinely missing rows.
    """

    replacements: dict[str, CapabilityDescriptor] = {}
    for item in _baseline_catalog().capabilities:
        if item.capability_id == "ui.desktop":
            item = replace(
                item,
                limitations=(
                    "Skills and Connector mutation/auth management remain deferred.",
                ),
            )
        elif item.capability_id == "retrieval.local_bm25":
            item = replace(
                item,
                limitations=(
                    "Lexical retrieval remains the built-in local backend.",
                    "Project lifecycle and stale-index policy are integrated in v0.28.",
                ),
            )
        elif item.capability_id == "product.capability_catalog":
            item = replace(
                item,
                maturity="foundation",
                surfaces=("library", "cli", "desktop"),
            )
        elif item.capability_id == "project.workspace":
            item = replace(
                item,
                maturity="foundation",
                surfaces=("library", "cli", "desktop"),
            )
        elif item.capability_id == "artifact.revisions":
            item = replace(
                item,
                introduced_version="v0.29",
                maturity="foundation",
                surfaces=("library", "cli", "desktop"),
                summary=(
                    "Append-only versioned product outputs with source linkage and safe export."
                ),
                limitations=(
                    "Local file/blob store only; sharing and blob garbage collection are deferred.",
                ),
            )
        replacements[item.capability_id] = item

    additions = (
        CapabilityDescriptor(
            capability_id="project.knowledge_runtime",
            introduced_version="v0.28",
            maturity="foundation",
            surfaces=("library", "cli", "desktop"),
            summary=(
                "Project index lifecycle, explicit stale policy and project-scoped memory."
            ),
            dependencies=(
                "memory.long_term",
                "project.workspace",
                "retrieval.local_bm25",
            ),
            limitations=(
                "No implicit watcher or hosted semantic retrieval provider.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="retrieval.hybrid_rrf",
            introduced_version="v0.28",
            maturity="foundation",
            surfaces=("library",),
            summary=(
                "Deterministic citation-preserving reciprocal-rank fusion over compatible retrievers."
            ),
            dependencies=("retrieval.local_bm25",),
            limitations=(
                "Semantic/vector retrievers are adapter-provided; no hosted backend is bundled.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="desktop.product_management",
            introduced_version="v0.30",
            maturity="experimental",
            surfaces=("desktop",),
            summary=(
                "Bounded desktop views and explicit actions for capabilities, projects and artifacts."
            ),
            dependencies=(
                "artifact.revisions",
                "product.capability_catalog",
                "project.knowledge_runtime",
            ),
            limitations=(
                "No Skill installation, Connector authentication or Artifact editing.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="multiagent.bus_choreography",
            introduced_version="v0.31",
            maturity="foundation",
            surfaces=("library", "cli"),
            summary=(
                "Message Bus requests drive Coordinator, Worker and Reviewer execution with retry and DLQ."
            ),
            dependencies=("multiagent.coordinator", "multiagent.message_bus"),
            limitations=(
                "Delivery is at-least-once, not exactly-once.",
                "Terminal state and event publication are not one atomic Outbox transaction.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="evaluation.aggregate_dashboard",
            introduced_version="v0.31",
            maturity="foundation",
            surfaces=("library", "cli"),
            summary=(
                "Aggregate success, tool failure, latency, retry, token and cost evaluation."
            ),
            dependencies=("trace.durable",),
            limitations=(
                "Pricing is operator supplied.",
                "No Desktop dashboard surface is claimed.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="evaluation.team_trace_closure",
            introduced_version="v0.32",
            maturity="shipped",
            surfaces=("library", "cli"),
            summary=(
                "Team Run, durable Trace and aggregate Eval share one stable run identity."
            ),
            dependencies=(
                "evaluation.aggregate_dashboard",
                "multiagent.bus_choreography",
                "trace.durable",
            ),
            limitations=(
                "Failure injection, cancellation and Outbox hardening are v0.33 scope.",
            ),
        ),
    )
    missing = tuple(
        item for item in additions if item.capability_id not in replacements
    )
    return CapabilityCatalog(tuple(replacements.values()) + missing)


__all__ = ["default_capability_catalog"]
