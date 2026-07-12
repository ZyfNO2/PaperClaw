from datetime import datetime, timezone

import pytest

from paperclaw.agent.parser import ActionParseError, parse_action, parse_reflection_decision, validate_reflection_decision
from paperclaw.agent.state import ToolCall
from paperclaw.agent.verification import DoneProposal, VerificationEvidence, VerificationResult
from paperclaw.tools.file_read import FileReadTool
from paperclaw.tools.registry import ToolRegistry


def test_parser_accepts_tool_done_and_fenced_repair() -> None:
    call = parse_action('{"action":"file_read","arguments":{"path":"a"},"reason":"read"}', ("file_read",))
    done = parse_action('```json\n{"action":"done","arguments":{"result":"ok"}}\n```', ("file_read",))
    assert isinstance(call, ToolCall) and isinstance(done, DoneProposal)


def test_parser_normalizes_done_optional_fields() -> None:
    done = parse_action('{"action":"done","arguments":{"result":"ok","verification":null,"remaining_issues":"none"}}', ("file_read",))
    assert isinstance(done, DoneProposal)
    assert done.claimed_verification == ""
    assert done.remaining_issues == ["none"]


@pytest.mark.parametrize("raw", ["not json", "[]", '{"action":"unknown","arguments":{}}', '{"action":"file_read","arguments":[]}'])
def test_parser_rejects_invalid_output(raw: str) -> None:
    with pytest.raises(ActionParseError):
        parse_action(raw, ("file_read",))


def test_parse_reflection_decision_rejects_invalid_confidence() -> None:
    with pytest.raises(ActionParseError):
        parse_reflection_decision('{"decision":"repair","evidence_ids":[],"failed_claim_ids":[],"next_action":null,"reason_code":"x","confidence":2}')


def test_validate_reflection_decision_rejects_unknown_evidence() -> None:
    decision = parse_reflection_decision('{"decision":"repair","evidence_ids":["ev-999"],"failed_claim_ids":["claim-a"],"next_action":"retry","reason_code":"verification_failed","confidence":0.9}')
    result = VerificationResult(
        status="failed",
        checks=[VerificationEvidence("ev-1", "check-1", "failed", "bad", "bash", 1, 1, datetime.now(timezone.utc))],
        passed_claim_ids=[],
        failed_claim_ids=["claim-a"],
        uncovered_claim_ids=[],
        verified_after_last_write=True,
        summary="failed",
    )
    with pytest.raises(ActionParseError):
        validate_reflection_decision(decision, result)


def test_validate_reflection_decision_rejects_dropped_failed_claims() -> None:
    decision = parse_reflection_decision('{"decision":"repair","evidence_ids":["ev-1"],"failed_claim_ids":[],"next_action":"retry","reason_code":"verification_failed","confidence":0.9}')
    result = VerificationResult(
        status="failed",
        checks=[VerificationEvidence("ev-1", "check-1", "failed", "bad", "bash", 1, 1, datetime.now(timezone.utc))],
        passed_claim_ids=[],
        failed_claim_ids=["claim-a"],
        uncovered_claim_ids=[],
        verified_after_last_write=True,
        summary="failed",
    )
    with pytest.raises(ActionParseError):
        validate_reflection_decision(decision, result)


def test_registry_rejects_duplicate() -> None:
    with pytest.raises(ValueError):
        ToolRegistry([FileReadTool(), FileReadTool()])
