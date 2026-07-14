from dataclasses import dataclass
from typing import Protocol


@dataclass
class ModelTurn:
    content: str
    reasoning: str = ""


class ChatModel(Protocol):
    def complete(self, prompt: str) -> ModelTurn: ...
