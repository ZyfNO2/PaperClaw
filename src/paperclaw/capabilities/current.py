"""Current capability catalog through v0.36."""

from dataclasses import replace

from .catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    default_capability_catalog as _baseline_catalog,
)


def default_capability_catalog() -> CapabilityCatalog:
    rows = {item.capability_id: item for item in _baseline_catalog().capabilities}
    rows["project.workspace"] = replace(
        rows["project.workspace"],
        maturity="foundation",
        surfaces=("library", "cli", "desktop"),
    )
    rows["product.capability_catalog"] = replace(
        rows["product.capability_catalog"],
        maturity="foundation",
        surfaces=("library", "cli", "desktop"),
    )
    rows["retrieval.hybrid_rrf"] = replace(
        rows["retrieval.hybrid_rrf"],
        maturity="foundation",
        surfaces=("library",),
        limitations=(
            "The bundled semantic backend uses deterministic feature hashing.",
            "No remote vector service is bundled.",
        ),
    )
    rows["multiagent.bus_choreography"] = replace(
        rows["multiagent.bus_choreography"],
        limitations=(
            "Delivery is at-least-once.",
            "SQLite and Redis Streams have different deployment boundaries.",
        ),
    )
    rows["evaluation.team_trace_closure"] = replace(
        rows["evaluation.team_trace_closure"],
        limitations=("The built-in Trace projection remains SQLite-backed.",),
    )

    additions = (
        CapabilityDescriptor(
            "multiagent.resilient_choreography",
            "v0.33",
            "shipped",
            ("library", "cli"),
            "Terminal Outbox recovery, durable cancellation and retry taxonomy.",
            (
                "evaluation.team_trace_closure",
                "multiagent.bus_choreography",
                "tasks.fenced_queue",
            ),
            ("External Tool side effects require Tool-level idempotency.",),
        ),
        CapabilityDescriptor(
            "multiagent.distributed_runtime",
            "v0.34",
            "shipped",
            ("library", "cli", "service"),
            "Redis Streams messaging and PostgreSQL choreography state.",
            (
                "multiagent.resilient_choreography",
                "multiagent.message_bus",
                "tasks.fenced_queue",
            ),
            (
                "PostgreSQL and Redis do not form one transaction.",
                "The Trace projection remains SQLite-backed.",
            ),
        ),
        CapabilityDescriptor(
            "retrieval.semantic_hybrid",
            "v0.35",
            "foundation",
            ("library",),
            "Persistent local vectors, weighted RRF and evidence-aware reranking.",
            ("retrieval.hybrid_rrf", "retrieval.local_bm25"),
            ("Local vectors use deterministic feature hashing.",),
        ),
        CapabilityDescriptor(
            "evaluation.research_quality",
            "v0.35",
            "shipped",
            ("library", "cli"),
            "Retrieval, citation, grounding, abstention and cost evaluation.",
            ("retrieval.semantic_hybrid", "evaluation.aggregate_dashboard"),
            ("Results depend on curated relevance and claim labels.",),
        ),
        CapabilityDescriptor(
            "project.extensions",
            "v0.36",
            "foundation",
            ("library", "cli"),
            "Project-scoped Skill and Connector registry with bounded activation.",
            ("mcp.tool_gateway", "project.workspace"),
            (
                "Connector runtimes must be registered by the application.",
                "Desktop management remains deferred.",
            ),
        ),
    )
    for item in additions:
        rows[item.capability_id] = item
    return CapabilityCatalog(tuple(rows.values()))


__all__ = ["default_capability_catalog"]
