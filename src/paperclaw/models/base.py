from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelTurn:
    """One model turn separated into actionable content and optional observability-only reasoning."""

    content: str
    reasoning: str = ""


class ChatModel(Protocol):
    """Minimal provider contract so runtime code stays independent from any SDK or gateway."""

    def complete(self, prompt: str) -> ModelTurn: ...
