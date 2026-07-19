"""Current-stack capability catalog transformations beyond the v0.27 baseline."""

from __future__ import annotations

from dataclasses import replace

from .catalog import (
    CapabilityCatalog,
    CapabilityDescriptor,
    default_capability_catalog as _v027_catalog,
)


def default_capability_catalog() -> CapabilityCatalog:
    """Return the audited capability catalog for the v0.30 stacked line."""
    replacements: dict[str, CapabilityDescriptor] = {}
    for item in _v027_catalog().capabilities:
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
    )
    return CapabilityCatalog(tuple(replacements.values()) + additions)


__all__ = ["default_capability_catalog"]
