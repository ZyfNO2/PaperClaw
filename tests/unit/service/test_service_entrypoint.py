from __future__ import annotations

import pytest

from paperclaw.service.entrypoint import build_parser, main


def test_service_parser_exposes_operational_timing_controls() -> None:
    args = build_parser().parse_args(
        [
            "--lease-seconds",
            "12.5",
            "--heartbeat-seconds",
            "2.5",
            "--queue-timeout-seconds",
            "45",
            "--run-timeout-seconds",
            "90",
        ]
    )

    assert args.lease_seconds == 12.5
    assert args.heartbeat_seconds == 2.5
    assert args.queue_timeout_seconds == 45
    assert args.run_timeout_seconds == 90


def test_service_parser_rejects_non_positive_timing_values() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--lease-seconds", "0"])


def test_service_entrypoint_rejects_heartbeat_not_below_lease() -> None:
    with pytest.raises(
        SystemExit,
        match="--heartbeat-seconds must be less than --lease-seconds",
    ):
        main(["--lease-seconds", "1", "--heartbeat-seconds", "1"])
