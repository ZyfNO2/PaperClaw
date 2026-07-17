from __future__ import annotations

import importlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from paperclaw.context.orchestration import (
    ContextAssemblyBudgetExhausted,
    ContextCandidate,
    ContextOrchestrator,
    ContextPolicy,
    ContextRequest,
)
from paperclaw.mcp import MCPServerConfig

ROOT = Path(__file__).parents[2]


def _candidate(
    candidate_id: str,
    content: str,
    *,
    priority: int = 100,
    freshness: int = 1,
    trust: str = "trusted_local",
    bucket: str = "context",
    kind: str = "fact",
    conflict_group: str | None = None,
    pinned: bool = False,
) -> ContextCandidate:
    return ContextCandidate(
        candidate_id=candidate_id,
        source="hardening_fixture",
        source_ref=candidate_id,
        layer="L2",
        kind=kind,
        scope=("shared",),
        priority=priority,
        trust=trust,
        freshness=freshness,
        estimated_tokens=max(1, len(content) // 4),
        content=content,
        bucket=bucket,
        conflict_group=conflict_group,
        pinned=pinned,
    )


def _request(*candidates: ContextCandidate) -> ContextRequest:
    return ContextRequest(
        run_id="run-hardening",
        conversation_id="conversation-hardening",
        step_id="step-1",
        raw_prompt="Complete the deterministic task.",
        workspace="",
        additional_candidates=tuple(candidates),
    )


def _policy(*, max_input: int = 2_000, reserve: int = 200) -> ContextPolicy:
    return ContextPolicy(
        max_input_tokens=max_input,
        output_reserve_tokens=reserve,
        max_single_candidate_tokens=max(1, max_input),
        source_quotas=(("context", 0.8), ("retrieval", 0.2)),
    )


def test_context_mcp_and_retrieval_packages_import_together() -> None:
    modules = [
        importlib.import_module("paperclaw.context"),
        importlib.import_module("paperclaw.mcp"),
        importlib.import_module("paperclaw.retrieval"),
    ]
    assert [module.__name__ for module in modules] == [
        "paperclaw.context",
        "paperclaw.mcp",
        "paperclaw.retrieval",
    ]


def test_candidate_permutation_does_not_change_selection_or_fingerprint() -> None:
    candidates = (
        _candidate("fact-a", "alpha", priority=100),
        _candidate("fact-b", "beta", priority=200),
        _candidate(
            "old-format",
            "use yaml",
            freshness=1,
            conflict_group="format",
        ),
        _candidate(
            "new-format",
            "use json",
            freshness=2,
            conflict_group="format",
        ),
    )
    orchestrator = ContextOrchestrator(policy=_policy())
    baseline = orchestrator.assemble(_request(*candidates))
    baseline_selected = tuple(item.candidate_id for item in baseline.trace.selected)
    baseline_conflicts = tuple(
        (item.conflict_group, item.winner_id, item.loser_ids)
        for item in baseline.trace.conflicts
    )

    for permutation in itertools.permutations(candidates):
        assembly = orchestrator.assemble(_request(*permutation))
        assert assembly.prompt == baseline.prompt
        assert assembly.fingerprint == baseline.fingerprint
        assert tuple(item.candidate_id for item in assembly.trace.selected) == baseline_selected
        assert tuple(
            (item.conflict_group, item.winner_id, item.loser_ids)
            for item in assembly.trace.conflicts
        ) == baseline_conflicts


@pytest.mark.parametrize("max_input,reserve", [(80, 20), (120, 30), (256, 64), (800, 100)])
def test_rendered_prompt_never_exceeds_available_budget(
    max_input: int, reserve: int
) -> None:
    candidates = tuple(
        _candidate(f"candidate-{index}", f"value-{index}-" + "x" * 80)
        for index in range(20)
    )
    policy = _policy(max_input=max_input, reserve=reserve)
    assembly = ContextOrchestrator(policy=policy).assemble(_request(*candidates))

    assert assembly.estimated_tokens <= policy.available_input_tokens
    assert assembly.trace.allocation.rendered_prompt_tokens <= policy.available_input_tokens


def test_protected_overflow_remains_fail_closed_at_arbitrary_boundary() -> None:
    protected = _candidate(
        "protected",
        "must-retain-" + "x" * 400,
        kind="constraint",
        pinned=True,
    )
    policy = _policy(max_input=100, reserve=25)
    with pytest.raises(ContextAssemblyBudgetExhausted) as raised:
        ContextOrchestrator(policy=policy).assemble(_request(protected))
    assert raised.value.available_tokens == 75
    assert raised.value.required_tokens > raised.value.available_tokens


def test_cross_process_hash_seed_does_not_change_contract_fingerprints() -> None:
    script = r'''
import json
from paperclaw.context.orchestration import ContextCandidate, ContextOrchestrator, ContextPolicy, ContextRequest
from paperclaw.mcp import normalize_tool_descriptor
from paperclaw.retrieval import stable_id
candidate = ContextCandidate(candidate_id="b", source="fixture", source_ref="b", layer="L2", kind="fact", scope=("shared",), priority=1, trust="trusted_local", freshness=1, estimated_tokens=1, content="beta", bucket="context")
other = ContextCandidate(candidate_id="a", source="fixture", source_ref="a", layer="L2", kind="fact", scope=("shared",), priority=1, trust="trusted_local", freshness=1, estimated_tokens=1, content="alpha", bucket="context")
request = ContextRequest(run_id="r", conversation_id="c", step_id="s", raw_prompt="task", workspace="", additional_candidates=(candidate, other))
policy = ContextPolicy(max_input_tokens=500, output_reserve_tokens=50, source_quotas=(("context", 1.0),))
assembly = ContextOrchestrator(policy=policy).assemble(request)
tool = normalize_tool_descriptor({"name": "echo", "inputSchema": {"required": ["text"], "properties": {"text": {"type": "string"}}, "type": "object"}}, server_id="srv")
print(json.dumps([assembly.fingerprint, tool.input_schema_hash, stable_id("doc", "file:///tmp/a", "markdown")]))
'''
    outputs: list[str] = []
    for seed in ("1", "2", "123456"):
        environment = os.environ.copy()
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + environment.get(
            "PYTHONPATH", ""
        )
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        outputs.append(completed.stdout.strip())
    assert len(set(outputs)) == 1


def test_ten_thousand_candidates_are_bounded_and_trace_is_content_free() -> None:
    secret = "secret-sentinel-must-not-enter-trace"
    candidates = tuple(
        _candidate(
            f"candidate-{index:05d}",
            f"value-{index:05d}-{secret if index == 9999 else 'public'}",
            priority=index % 17,
        )
        for index in range(10_000)
    )
    policy = _policy(max_input=4_000, reserve=500)
    started = time.monotonic()
    assembly = ContextOrchestrator(policy=policy).assemble(_request(*candidates))
    elapsed = time.monotonic() - started

    payload = assembly.trace.to_event_payload(limit=50)
    serialized = json.dumps(payload, sort_keys=True)
    assert elapsed < 10.0
    assert payload["trace_truncated"] is True
    assert payload["selected_count"] + payload["excluded_count"] >= 10_000
    assert len(payload["selected"]) <= 50
    assert len(payload["excluded"]) <= 50
    assert secret not in serialized


def test_secret_values_do_not_enter_config_fingerprint_or_context_trace() -> None:
    secret = "private-token-value"
    config = MCPServerConfig(
        server_id="combined-hardening",
        command=(sys.executable, "-c", "pass"),
        environment=(("TOKEN", secret),),
    )
    external = _candidate(
        "external-secret",
        secret,
        trust="external_untrusted",
        bucket="retrieval",
    )
    assembly = ContextOrchestrator(policy=_policy()).assemble(_request(external))

    assert secret not in config.fingerprint
    assert secret not in json.dumps(assembly.trace.to_event_payload(), sort_keys=True)
    assert secret in assembly.prompt
