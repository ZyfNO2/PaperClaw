from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ModelTurn:
    """One model turn with transient observability metadata.

    ``content`` is the actionable provider output consumed by the runtime.
    ``reasoning`` remains observability-only and is not part of durable Trace
    payloads. ``metadata`` is restricted by adapters to non-secret normalized
    facts such as request ID, token counts, finish reason and retry counters.
    """

    content: str
    reasoning: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ChatModel(Protocol):
    """Minimal provider contract so runtime code stays independent from any SDK or gateway."""

    def complete(self, prompt: str) -> ModelTurn: ...
