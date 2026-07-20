"""Current-stack capability catalog transformations through v0.36."""

from __future__ import annotations

from dataclasses import replace

from .catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    default_capability_catalog as _baseline_catalog,
)


def default_capability_catalog() -> CapabilityCatalog:
    """Return the audited capability catalog for the v0.36 development line."""

    replacements: dict[str, CapabilityDescriptor] = {}
    for item in _baseline_catalog().capabilities:
        if item.capability_id == "ui.desktop":
            item = replace(
                item,
                limitations=(
                    "Project extension registry management is CLI/library only; install and authorization UI remain deferred.",
                ),
            )
        elif item.capability_id == "retrieval.local_bm25":
            item = replace(
                item,
                limitations=(
                    "Lexical BM25 remains the authoritative local keyword backend.",
                    "Project lifecycle and stale-index policy are integrated in v0.28.",
                ),
            )
        elif item.capability_id == "retrieval.hybrid_rrf":
            item = replace(
                item,
                maturity="foundation",
                surfaces=("library",),
                limitations=(
                    "The bundled semantic backend uses deterministic feature hashing, not transformer embeddings.",
                    "No hosted vector database or embedding service is bundled.",
                ),
            )
        elif item.capability_id in {"product.capability_catalog", "project.workspace"}:
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
        elif item.capability_id == "multiagent.bus_choreography":
            item = replace(
                item,
                maturity="foundation",
                surfaces=("library", "cli"),
                limitations=(
                    "Delivery is at-least-once, not exactly-once.",
                    "SQLite and Redis Streams backends have different deployment boundaries.",
                ),
            )
        elif item.capability_id == "evaluation.team_trace_closure":
            item = replace(
                item,
                maturity="shipped",
                surfaces=("library", "cli"),
                limitations=("The built-in Trace projection remains SQLite-backed.",),
            )
        elif item.capability_id == "multiagent.resilient_choreography":
            item = replace(
                item,
                maturity="shipped",
                surfaces=("library", "cli"),
                limitations=(
                    "External Tool side effects still require Tool-level idempotency.",
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
            limitations=("No implicit watcher or hosted retrieval provider.",),
        ),
        CapabilityDescriptor(
            capability_id="retrieval.hybrid_rrf",
            introduced_version="v0.28",
            maturity="foundation",
            surfaces=("library",),
            summary=(
                "Deterministic citation-preserving weighted reciprocal-rank fusion over compatible retrievers."
            ),
            dependencies=("retrieval.local_bm25",),
            limitations=(
                "The bundled semantic backend uses deterministic feature hashing, not transformer embeddings.",
                "No hosted vector database or embedding service is bundled.",
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
                "No extension installation, Connector authorization or Artifact editing UI.",
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
                "SQLite and Redis Streams backends have different deployment boundaries.",
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
            limitations=("The built-in Trace projection remains SQLite-backed.",),
        ),
        CapabilityDescriptor(
            capability_id="multiagent.resilient_choreography",
            introduced_version="v0.33",
            maturity="shipped",
            surfaces=("library", "cli"),
            summary=(
                "Terminal Outbox recovery, durable cancellation, failure injection and retry taxonomy."
            ),
            dependencies=(
                "evaluation.team_trace_closure",
                "multiagent.bus_choreography",
                "tasks.fenced_queue",
            ),
            limitations=(
                "External Tool side effects still require Tool-level idempotency.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="multiagent.distributed_runtime",
            introduced_version="v0.34",
            maturity="shipped",
            surfaces=("library", "cli", "service"),
            summary=(
                "Redis Streams messaging and PostgreSQL choreography state for multi-process workers."
            ),
            dependencies=(
                "multiagent.resilient_choreography",
                "multiagent.message_bus",
                "tasks.fenced_queue",
            ),
            limitations=(
                "Redis Cluster cross-slot Lua deployment is not claimed.",
                "PostgreSQL and Redis do not form one distributed transaction.",
                "The Trace projection remains SQLite-backed.",
                "No Kafka or NATS adapter is claimed.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="retrieval.semantic_hybrid",
            introduced_version="v0.35",
            maturity="foundation",
            surfaces=("library",),
            summary=(
                "Persistent local semantic vectors, weighted RRF and evidence-aware citation-preserving reranking."
            ),
            dependencies=("retrieval.hybrid_rrf", "retrieval.local_bm25"),
            limitations=(
                "Semantic vectors use deterministic feature hashing rather than transformer embeddings.",
                "No external vector database or hosted embedding service is included.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="evaluation.research_quality",
            introduced_version="v0.35",
            maturity="shipped",
            surfaces=("library", "cli"),
            summary=(
                "Reproducible retrieval, citation, grounding, abstention, latency, token and cost evaluation."
            ),
            dependencies=(
                "retrieval.semantic_hybrid",
                "evaluation.aggregate_dashboard",
            ),
            limitations=(
                "Quality depends on curated relevance and explicit claim-support labels.",
                "Groundedness is not inferred by the answer-generating model.",
            ),
        ),
        CapabilityDescriptor(
            capability_id="project.extensions",
            introduced_version="v0.36",
            maturity="foundation",
            surfaces=("library", "cli"),
            summary=(
                "Project-scoped Skill and Connector descriptors with permission ceilings, controlled activation and audit."
            ),
            dependencies=("project.workspace", "tools.mcp_foundation"),
            limitations=(
                "Connector runtimes must be registered by the host application.",
                "No extension marketplace, installation UI or hosted authorization service is included.",
                "Project-provided executable modules are intentionally unsupported.",
            ),
        ),
    )
    missing = tuple(item for item in additions if item.capability_id not in replacements)
    return CapabilityCatalog(tuple(replacements.values()) + missing)


__all__ = ["default_capability_catalog"]
