"""Current capability catalog through v0.38."""

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
    rows["project.extensions"] = replace(
        rows.get(
            "project.extensions",
            CapabilityDescriptor(
                "project.extensions",
                "v0.36",
                "foundation",
                ("library", "cli"),
                "Project-scoped Skill and Connector registry with bounded activation.",
                ("mcp.tool_gateway", "project.workspace"),
                (),
            ),
        ),
        maturity="shipped",
        surfaces=("library", "cli"),
        summary=(
            "Project-scoped extension registry, bounded activation and "
            "host-controlled Connector Tool execution."
        ),
        limitations=(
            "Connector runtimes and secret resolution remain host supplied.",
            "Desktop installation and hosted credential setup are not included.",
            "Project-owned executable modules remain prohibited.",
        ),
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
            "academic.paper_versioning",
            "v0.38",
            "shipped",
            ("library", "cli", "service", "desktop"),
            "Managed PDF, Markdown and TXT import with immutable versions and confirmed metadata.",
            ("project.workspace",),
            (
                "Structured page and object parsing is not included.",
                "Metadata is local candidate data until explicitly confirmed.",
            ),
        ),
        CapabilityDescriptor(
            "academic.structured_objects",
            "v0.40",
            "shipped",
            ("library", "cli", "service", "desktop"),
            "Version-bound pages, sections, paragraphs and replayable academic objects.",
            ("academic.paper_versioning",),
            ("OCR and a full PDF editor are not included.",),
        ),
        CapabilityDescriptor(
            "academic.multichannel_retrieval",
            "v0.42",
            "foundation",
            ("library", "cli", "service", "desktop"),
            "Atomic text and ColQwen2 visual generations with explainable channel scores.",
            ("academic.structured_objects", "retrieval.local_bm25"),
            ("GPU live validation is environment-dependent.",),
        ),
        CapabilityDescriptor(
            "academic.evidence_workspace",
            "v0.43",
            "shipped",
            ("library", "cli", "service", "desktop"),
            "Sufficiency-aware Evidence Bundles, replay, research artifacts and scoped memory.",
            ("academic.multichannel_retrieval",),
            ("Native Desktop acceptance is a manual release gate.",),
        ),
    )
    for item in additions:
        rows[item.capability_id] = item
    return CapabilityCatalog(tuple(rows.values()))


__all__ = ["default_capability_catalog"]
