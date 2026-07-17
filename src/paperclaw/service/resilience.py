"""Typed production-protection policies for the service layer."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeoutPolicy:
    queue_timeout_seconds: float = 300.0
    provider_timeout_seconds: float = 120.0
    tool_timeout_seconds: float = 60.0
    run_timeout_seconds: float = 600.0
    graceful_shutdown_seconds: float = 15.0

    def __post_init__(self) -> None:
        for name, value in (
            ("queue_timeout_seconds", self.queue_timeout_seconds),
            ("provider_timeout_seconds", self.provider_timeout_seconds),
            ("tool_timeout_seconds", self.tool_timeout_seconds),
            ("run_timeout_seconds", self.run_timeout_seconds),
            ("graceful_shutdown_seconds", self.graceful_shutdown_seconds),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be numeric")
            if value <= 0:
                raise ValueError(f"{name} must be positive")


class LayerTimeoutError(TimeoutError):
    def __init__(self, layer: str, seconds: float) -> None:
        normalized = layer.strip()
        if not normalized:
            raise ValueError("layer must not be empty")
        self.layer = normalized
        self.seconds = float(seconds)
        self.code = f"{normalized}_timeout"
        super().__init__(f"{normalized} timed out after {seconds:g}s")
