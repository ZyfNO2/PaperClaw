from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

import pytest

from paperclaw.models.base import ModelTurn


class FakeModel:
    def __init__(self, actions: list[dict | str]) -> None:
        self.actions = iter(actions)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        value = next(self.actions)
        content = value if isinstance(value, str) else json.dumps(value)
        return ModelTurn(content=content)


def action(name: str, arguments: dict, reason: str = "test") -> dict:
    return {"action": name, "arguments": arguments, "reason": reason}


def done(result: str = "complete", verification: str = "verified by command") -> dict:
    return action("done", {"result": result, "verification": verification, "remaining_issues": []})


def reflect(decision: str, *, reason_code: str = "test_decision", confidence: float = 0.9, next_action: str | None = None, evidence_ids: list[str] | None = None, failed_claim_ids: list[str] | None = None) -> dict:
    return {
        "decision": decision,
        "evidence_ids": evidence_ids or [],
        "failed_claim_ids": failed_claim_ids or [],
        "next_action": next_action,
        "reason_code": reason_code,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# v0.04 demo trace normalization
# ---------------------------------------------------------------------------
#
# The v0.04 MVP demo (tests/integration/test_v0_04_mvp_demo.py) writes a
# reviewable JSON artifact into the repo so reviewers can inspect the
# five-stage flow without re-running pytest. Runtime-generated identifiers
# (snapshot_id, summary-<digest>, started_at, the pytest temp path) would
# dirty the worktree after every run, so this fixture normalizes those
# volatile fields to stable placeholders after the test passes.
#
# The fixture lives in tests/conftest.py (NOT tests/integration/conftest.py)
# on purpose: an integration-dir conftest would shadow this module on
# ``from conftest import ...`` resolution and break test_cli_observability
# / test_minimal_react_loop, which import FakeModel / action / done /
# reflect from here. Keeping everything in the parent conftest preserves
# both the helpers and the normalize behavior without shadowing.

_TRACE_PATH = (
    Path(__file__).resolve().parents[1]
    / "artifacts"
    / "v0_04"
    / "mvp_demo_trace.json"
)


def _normalize_trace(trace: dict[str, Any]) -> dict[str, Any]:
    """Replace volatile evidence fields with stable review placeholders."""
    stages = trace.get("stages", [])
    by_name = {
        stage.get("stage"): stage
        for stage in stages
        if isinstance(stage, dict)
    }

    setup = by_name.get("1_setup")
    if setup is not None:
        setup["db_path"] = "<pytest-temp>/demo.db"

    compaction = by_name.get("2_compaction")
    if compaction is not None:
        compaction["snapshot_id"] = "<snapshot_id>"
        compaction["source_item_ids"] = [
            "<compaction_summary_id>"
            if isinstance(item_id, str) and item_id.startswith("summary-")
            else item_id
            for item_id in compaction.get("source_item_ids", [])
        ]

    unsafe_resume = by_name.get("5_unsafe_resume")
    if unsafe_resume is not None:
        for operation in unsafe_resume.get("pending_operations", []):
            if isinstance(operation, dict) and "started_at" in operation:
                operation["started_at"] = "<runtime_timestamp>"

    return trace


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo) -> Any:
    """Attach the per-phase report onto the item so teardown-stage fixtures
    can tell whether the test itself passed.

    Without this hook, an autouse teardown fixture cannot distinguish a
    passing test from a failing one. That matters here because the
    v0.04 demo fixture must NOT raise ``pytest.fail`` when the original
    test already failed — masking the real exception with a cleanup
    error makes the failure mode harder to diagnose.
    """
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def normalize_v0_04_demo_trace(request: pytest.FixtureRequest) -> Iterator[None]:
    """Normalize the tracked v0.04 demo artifact after its test runs.

    Only normalizes when the test passed. If the test failed, the raw
    exception is the signal reviewers need — running normalize or
    raising ``pytest.fail`` here would mask the original failure with a
    second, less informative error.

    The fixture is autouse across the whole test tree but opts out by
    node name for anything other than the v0.04 demo, so other tests pay
    only the cost of one early-return.
    """
    yield

    # Don't touch the trace if the test itself failed — the original
    # exception must stay visible.
    rep_call = getattr(request.node, "rep_call", None)
    if rep_call is None or rep_call.failed:
        return

    # Only the v0.04 demo writes this trace; other tests opt out by name.
    if request.node.name != "test_v0_04_mvp_demo":
        return

    if not _TRACE_PATH.exists():
        # Test passed but the trace wasn't written — that's a real bug
        # worth surfacing as a separate, clearly-labeled failure.
        pytest.fail(
            f"test passed but did not write expected trace at {_TRACE_PATH}"
        )

    with _TRACE_PATH.open("r", encoding="utf-8") as trace_file:
        trace = json.load(trace_file)

    normalized = _normalize_trace(trace)
    with _TRACE_PATH.open("w", encoding="utf-8", newline="\n") as trace_file:
        json.dump(normalized, trace_file, indent=2, ensure_ascii=False)
        trace_file.write("\n")
