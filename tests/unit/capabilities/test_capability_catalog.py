from __future__ import annotations

import json

from paperclaw.capabilities import default_capability_catalog


def test_default_catalog_is_deterministic_and_dependency_complete() -> None:
    first = default_capability_catalog()
    second = default_capability_catalog()

    assert first.to_dict() == second.to_dict()
    ids = [item.capability_id for item in first.capabilities]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert "project.workspace" in ids
    assert "project.knowledge_runtime" in ids
    assert "artifact.revisions" in ids
    assert "desktop.product_management" in ids
    assert "multiagent.bus_choreography" in ids
    assert "evaluation.aggregate_dashboard" in ids
    assert "evaluation.team_trace_closure" in ids
    assert "multiagent.resilient_choreography" in ids


def test_catalog_distinguishes_delivered_foundations_from_planned_work() -> None:
    catalog = default_capability_catalog()

    shipped = {item.capability_id for item in catalog.select(maturity="shipped")}
    foundation = {
        item.capability_id for item in catalog.select(maturity="foundation")
    }
    experimental = {
        item.capability_id for item in catalog.select(maturity="experimental")
    }
    planned = {item.capability_id for item in catalog.select(maturity="planned")}

    assert "agent.react_runtime" in shipped
    assert "evaluation.team_trace_closure" in shipped
    assert "multiagent.resilient_choreography" in shipped
    assert "worker.remote_gateway" in foundation
    assert "multiagent.message_bus" in foundation
    assert "multiagent.bus_choreography" in foundation
    assert "evaluation.aggregate_dashboard" in foundation
    assert "project.knowledge_runtime" in foundation
    assert "artifact.revisions" in foundation
    assert "desktop.product_management" in experimental
    assert "evaluation.aggregate_dashboard" not in planned
    assert "artifact.revisions" not in planned
    assert shipped.isdisjoint(foundation)


def test_surface_filter_and_json_contract() -> None:
    catalog = default_capability_catalog()
    desktop = catalog.select(surface="desktop")

    assert desktop
    assert all("desktop" in item.surfaces for item in desktop)
    payload = json.loads(catalog.to_json(surface="desktop"))
    assert payload["schema_version"] == 1
    assert payload["count"] == len(desktop)
    assert payload["filters"] == {"maturity": None, "surface": "desktop"}
    assert any(
        item["capability_id"] == "desktop.product_management"
        for item in payload["capabilities"]
    )


def test_text_render_exposes_limitations_without_secrets() -> None:
    rendered = default_capability_catalog().render_text(
        maturity="foundation", surface="service"
    )

    assert "worker.remote_gateway" in rendered
    assert "gateway-process lifetime" in rendered
    assert "api_key" not in rendered
