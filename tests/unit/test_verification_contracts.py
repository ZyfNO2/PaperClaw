from datetime import datetime

from paperclaw.agent.verification import (
    DoneProposal,
    ReflectionDecision,
    TaskClaim,
    VerificationCheck,
    VerificationEvidence,
    VerificationPlan,
    VerificationResult,
)


def test_verification_contracts_are_serializable() -> None:
    plan = VerificationPlan(
        task_claims=[TaskClaim("claim-output", "script prints OK", True, True, "user")],
        checks=[VerificationCheck("check-command", ["claim-output"], "command", {"command": "python hello.py"}, True)],
        generated_from="unit-test",
        created_after_step=3,
    )
    evidence = VerificationEvidence(
        evidence_id="ev-1",
        check_id="check-command",
        status="passed",
        observed="stdout contains OK",
        source_tool="bash",
        source_step=3,
        exit_code=0,
        timestamp=datetime(2026, 7, 13, 12, 0, 0),
    )
    result = VerificationResult("passed", [evidence], ["claim-output"], [], [], True, "all required claims passed")
    reflection = ReflectionDecision("accept", ["ev-1"], [], None, "verification_passed", 0.95)
    proposal = DoneProposal("completed", "python hello.py => OK", [])

    assert plan.to_dict()["checks"][0]["check_type"] == "command"
    assert result.to_dict()["checks"][0]["timestamp"] == "2026-07-13T12:00:00"
    assert reflection.to_dict()["decision"] == "accept"
    assert proposal.to_dict()["claimed_verification"] == "python hello.py => OK"
