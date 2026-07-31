from __future__ import annotations

import pytest

from paperclaw.academic import RetrievalBudget, RetrievalRequest
from paperclaw.academic.corrective import plan_corrective_retrieval


def _request(**changes) -> RetrievalRequest:
    values = dict(
        text="accuracy of 10.1234/example",
        channels=("lexical", "dense", "visual"),
        paper_ids=("paper-1",),
        object_types=("paragraph",),
        version_ids=("v2",),
    )
    values.update(changes)
    return RetrievalRequest(**values)


@pytest.mark.parametrize(
    "reason",
    [
        "identity_conflict",
        "metric_conflict",
        "unit_conflict",
        "version_conflict",
        "channel_unavailable",
        "filter_exhausted",
        "no_candidates",
    ],
)
def test_corrective_plans_are_material_bounded_and_preserve_identity(reason) -> None:
    plan = plan_corrective_retrieval(
        _request(), reason=reason, identity_constraints=("10.1234/example",)
    )
    corrected = plan.request()
    assert plan.changed
    assert "10.1234/example" in corrected.text
    assert corrected.paper_ids == ("paper-1",)
    assert corrected.version_ids == ("v2",)
    assert corrected.budget.max_corrective_rounds == 0
    assert corrected.budget.max_candidates <= 100


def test_metric_correction_adds_table_scope_and_exact_channel() -> None:
    corrected = plan_corrective_retrieval(
        _request(),
        reason="metric_conflict",
        section_scope=("Results",),
    ).request()
    assert {"table", "table_cell"} <= set(corrected.object_types)
    assert "exact" in corrected.channels
    assert corrected.section_scope == ("Results",)
    assert RetrievalRequest.from_dict(corrected.to_dict()).section_scope == ("Results",)


def test_unavailable_visual_channel_is_removed() -> None:
    corrected = plan_corrective_retrieval(
        _request(channels=("visual",)), reason="channel_unavailable"
    ).request()
    assert corrected.channels == ("lexical",)


def test_budget_exhaustion_fails_before_planning() -> None:
    request = _request(budget=RetrievalBudget(max_corrective_rounds=0))
    with pytest.raises(ValueError, match="exhausted"):
        plan_corrective_retrieval(request, reason="no_candidates")
