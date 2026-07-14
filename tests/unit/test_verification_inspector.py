from paperclaw.tui.widgets import VerificationInspector


def test_verification_inspector_renders_only_aggregate_facts() -> None:
    inspector = VerificationInspector()
    inspector.show_result(
        {
            "result": {
                "status": "failed",
                "passed_claim_ids": ["claim-1"],
                "failed_claim_ids": ["claim-2"],
                "uncovered_claim_ids": ["claim-3"],
                "verified_after_last_write": False,
                "summary": "one required check failed",
                "checks": [{"observed": "secret command output"}],
            }
        }
    )

    assert inspector.snapshot.status == "failed"
    assert inspector.snapshot.passed == 1
    assert inspector.snapshot.failed == 1
    assert inspector.snapshot.uncovered == 1
    assert inspector.snapshot.verified_after_last_write is False
    assert inspector.snapshot.summary == "one required check failed"
