"""The four user-visible widgets in the v0.06 TUI MVP."""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Input, RichLog, Static

from .state import RunSnapshot


class ChatLog(RichLog):
    """Conversation-only view; high-frequency runtime events stay elsewhere."""

    def add_user(self, text: str) -> None:
        self.write(f"[bold cyan]You[/]: {escape(text)}")

    def add_agent(self, text: str | None) -> None:
        self.write(f"[bold green]PaperClaw[/]: {escape(text or '(no output)')}")

    def add_system(self, text: str) -> None:
        self.write(f"[dim]System: {escape(text)}[/]")


class PromptInput(Input):
    """Task and slash-command input for one active run at a time."""

    def __init__(self, **kwargs) -> None:
        super().__init__(placeholder="Describe a task or type /help", **kwargs)


class RunStatus(Static):
    """Compact structured status for the current QueryEngine run."""

    def show_snapshot(self, snapshot: RunSnapshot) -> None:
        self.update(
            " | ".join(
                (
                    f"run={snapshot.run_id or '-'}",
                    f"status={snapshot.status}",
                    f"reason={snapshot.stop_reason or '-'}",
                    f"model={snapshot.model_calls}",
                    f"tool={snapshot.tool_calls}",
                    f"seq={snapshot.last_sequence}",
                )
            )
        )


class ToolTimeline(RichLog):
    """Whitelisted lifecycle timeline with no hidden chain-of-thought."""

    def add_event(self, text: str, *, known: bool) -> None:
        marker = "" if known else "[unknown] "
        self.write(escape(f"{marker}{text}"))
