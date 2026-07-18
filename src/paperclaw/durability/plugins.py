"""Static recovery policy plugins for durable execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .core import DurableRun, RecoveryDecision, RecoveryPolicy


@dataclass(frozen=True)
class RecoveryPluginFailure:
    policy_id: str
    error_type: str
    message: str


class RecoveryPolicyRegistry:
    """Select one explicit policy and fail closed if it raises."""

    def __init__(
        self,
        policies: Sequence[RecoveryPolicy],
        *,
        active_policy_id: str,
    ) -> None:
        policies_tuple = tuple(policies)
        mapping = {policy.policy_id: policy for policy in policies_tuple}
        if len(mapping) != len(policies_tuple):
            raise ValueError("duplicate recovery policy_id")
        if active_policy_id not in mapping:
            raise ValueError("active recovery policy is not registered")
        self.policy_id = f"registry:{active_policy_id}"
        self._active = mapping[active_policy_id]
        self._failures: list[RecoveryPluginFailure] = []

    @property
    def failures(self) -> tuple[RecoveryPluginFailure, ...]:
        return tuple(self._failures)

    def classify(
        self,
        run: DurableRun,
        *,
        action_receipt_count: int,
    ) -> RecoveryDecision:
        try:
            return self._active.classify(
                run, action_receipt_count=action_receipt_count
            )
        except Exception as exc:
            self._failures.append(
                RecoveryPluginFailure(
                    policy_id=self._active.policy_id,
                    error_type=type(exc).__name__,
                    message=str(exc)[:500],
                )
            )
            return RecoveryDecision(
                "manual",
                f"plugin_policy_error:{type(exc).__name__}",
                self._active.policy_id,
            )
