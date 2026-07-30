"""Bounded, reason-aware corrective retrieval planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .contracts import RetrievalBudget, RetrievalRequest

CorrectiveReason = Literal[
    "no_candidates",
    "filter_exhausted",
    "identity_conflict",
    "metric_conflict",
    "unit_conflict",
    "version_conflict",
    "channel_unavailable",
]


@dataclass(frozen=True)
class CorrectivePlan:
    primary_reason: CorrectiveReason
    original_query: str
    rewritten_query: str
    original_channels: tuple[str, ...]
    corrected_channels: tuple[str, ...]
    original_filters: dict[str, tuple[str, ...]]
    corrected_filters: dict[str, tuple[str, ...]]
    original_budget: RetrievalBudget
    corrected_budget: RetrievalBudget
    identity_constraints: tuple[str, ...]
    object_type_scope: tuple[str, ...]
    section_scope: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return any(
            (
                self.original_query != self.rewritten_query,
                self.original_channels != self.corrected_channels,
                self.original_filters != self.corrected_filters,
                self.original_budget != self.corrected_budget,
            )
        )

    def request(self) -> RetrievalRequest:
        if not self.changed:
            raise ValueError("corrective plan must materially change the request")
        if any(value.casefold() not in self.rewritten_query.casefold() for value in self.identity_constraints):
            raise ValueError("corrective rewrite lost a canonical identity constraint")
        return RetrievalRequest(
            self.rewritten_query,
            self.corrected_channels,
            self.corrected_filters["paper_ids"],
            self.object_type_scope,
            self.corrected_budget,
            self.corrected_filters["version_ids"],
        )


def plan_corrective_retrieval(
    request: RetrievalRequest,
    *,
    reason: CorrectiveReason,
    identity_constraints: tuple[str, ...] = (),
    section_scope: tuple[str, ...] = (),
) -> CorrectivePlan:
    """Produce one deterministic correction without consuming another round."""

    if request.budget.max_corrective_rounds < 1:
        raise ValueError("corrective retrieval budget is exhausted")
    channels = list(request.channels)
    papers, versions = request.paper_ids, request.version_ids
    object_types = request.object_types
    rewrite_terms: list[str] = []

    if reason == "filter_exhausted":
        object_types = ()
        rewrite_terms.append("broader object scope")
    elif reason in {"identity_conflict", "version_conflict"}:
        channels = ["exact", "lexical"]
        rewrite_terms.append("canonical identity active version")
    elif reason in {"metric_conflict", "unit_conflict"}:
        channels = [channel for channel in ("exact", "lexical", "dense") if channel in channels or channel == "exact"]
        object_types = tuple(dict.fromkeys((*object_types, "table", "table_cell")))
        rewrite_terms.append("metric definition units dataset split")
    elif reason == "channel_unavailable":
        channels = [channel for channel in channels if channel != "visual"]
        if not channels:
            channels = ["lexical"]
        rewrite_terms.append("textual evidence")
    else:
        rewrite_terms.append("synonyms definitions")

    rewritten = request.text
    suffix = " ".join(rewrite_terms)
    if suffix.casefold() not in rewritten.casefold():
        rewritten = f"{rewritten} {suffix}".strip()
    for identity in identity_constraints:
        if identity.casefold() not in rewritten.casefold():
            rewritten = f"{rewritten} {identity}".strip()

    corrected_budget = RetrievalBudget(
        max_candidates=min(100, max(request.budget.max_candidates + 5, request.budget.max_candidates * 2)),
        max_chars=min(50_000, max(request.budget.max_chars + 2_000, request.budget.max_chars * 2)),
        max_primary_rounds=1,
        max_corrective_rounds=0,
        max_conflict_rounds=request.budget.max_conflict_rounds,
    )
    return CorrectivePlan(
        reason,
        request.text,
        rewritten,
        request.channels,
        tuple(dict.fromkeys(channels)),
        {"paper_ids": papers, "version_ids": versions},
        {"paper_ids": papers, "version_ids": versions},
        request.budget,
        corrected_budget,
        identity_constraints,
        object_types,
        section_scope,
    )
