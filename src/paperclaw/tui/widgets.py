"""User-visible widgets for the PaperClaw Textual client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

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


@dataclass(frozen=True)
class VerificationView:
    """Sanitized aggregate facts rendered by the verification inspector."""

    status: str = "not_run"
    passed: int = 0
    failed: int = 0
    uncovered: int = 0
    verified_after_last_write: bool | None = None
    summary: str | None = None


class VerificationInspector(Static):
    """Render final deterministic verification facts, never raw tool output."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._snapshot = VerificationView()

    @property
    def snapshot(self) -> VerificationView:
        return self._snapshot

    def reset(self) -> None:
        self._snapshot = VerificationView()
        self._render_snapshot()

    def show_result(self, payload: Mapping[str, Any]) -> None:
        result = payload.get("result")
        result_map = result if isinstance(result, Mapping) else {}
        self._snapshot = VerificationView(
            status=_text(result_map.get("status")) or "unknown",
            passed=len(_string_list(result_map.get("passed_claim_ids"))),
            failed=len(_string_list(result_map.get("failed_claim_ids"))),
            uncovered=len(_string_list(result_map.get("uncovered_claim_ids"))),
            verified_after_last_write=result_map.get("verified_after_last_write")
            if isinstance(result_map.get("verified_after_last_write"), bool)
            else None,
            summary=_text(result_map.get("summary"), limit=500),
        )
        self._render_snapshot()

    def _render_snapshot(self) -> None:
        freshness = self._snapshot.verified_after_last_write
        freshness_text = "-" if freshness is None else ("yes" if freshness else "no")
        summary = self._snapshot.summary or "-"
        self.update(
            escape(
                "Verification\n"
                f"status={self._snapshot.status} | passed={self._snapshot.passed} | "
                f"failed={self._snapshot.failed} | uncovered={self._snapshot.uncovered}\n"
                f"after_last_write={freshness_text}\nsummary={summary}"
            )
        )


class ToolTimeline(RichLog):
    """Whitelisted lifecycle timeline with no hidden chain-of-thought."""

    def add_event(self, text: str, *, known: bool) -> None:
        marker = "" if known else "[unknown] "
        self.write(escape(f"{marker}{text}"))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _text(value: Any, *, limit: int = 200) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None
