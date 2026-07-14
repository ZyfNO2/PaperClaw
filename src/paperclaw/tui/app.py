"""Full-screen Textual application for the v0.06 thin-client MVP."""

from __future__ import annotations

from threading import RLock
from typing import Callable, Protocol

from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input

from paperclaw.harness import RunLimits, RunResult

from .state import EventReducer
from .widgets import (
    ChatLog,
    PromptInput,
    RunStatus,
    ToolTimeline,
    VerificationInspector,
)

EventHandler = Callable[[str, dict], None]


class QueryEngineLike(Protocol):
    def submit(self, text: str, *, limits: RunLimits | None = None) -> RunResult: ...

    def request_stop(self, run_id: str, reason: str = "user_requested") -> bool: ...


EngineFactory = Callable[[EventHandler], QueryEngineLike]


class RuntimeEventMessage(Message):
    def __init__(self, event_type: str, payload: dict) -> None:
        super().__init__()
        self.event_type = event_type
        self.payload = dict(payload)


class RunFinishedMessage(Message):
    def __init__(self, result: RunResult | None, error: str | None = None) -> None:
        super().__init__()
        self.result = result
        self.error = error


class PaperClawApp(App[int]):
    """Single-run TUI that treats QueryEngine as its only runtime boundary."""

    CSS_PATH = "paperclaw.tcss"
    TITLE = "PaperClaw v0.06 TUI MVP"

    def __init__(
        self,
        *,
        engine_factory: EngineFactory,
        limits: RunLimits | None = None,
        initial_task: str | None = None,
    ) -> None:
        super().__init__()
        self._engine_factory = engine_factory
        self._limits = limits or RunLimits()
        self._initial_task = initial_task.strip() if initial_task else None
        self._reducer = EventReducer()
        self._engine = self._engine_factory(self._on_engine_event)
        self._run_in_flight = False
        self._active_run_id: str | None = None
        self._run_lock = RLock()
        self._quit_confirmation_pending = False
        self._exit_after_run = False

    def compose(self) -> ComposeResult:
        yield RunStatus(id="run-status")
        with Horizontal(id="main"):
            with Vertical(id="chat-pane"):
                yield ChatLog(id="chat-log", wrap=True, highlight=False, markup=True)
            with Vertical(id="timeline-pane"):
                yield VerificationInspector(id="verification-inspector")
                yield ToolTimeline(id="tool-timeline", wrap=True, highlight=False)
        yield PromptInput(id="prompt-input")

    def on_mount(self) -> None:
        self.query_one(RunStatus).show_snapshot(self._reducer.snapshot)
        self.query_one(VerificationInspector).reset()
        self._apply_responsive_layout(self.size.width)
        self.query_one(PromptInput).focus()
        if self._initial_task:
            self.call_after_refresh(self._submit_task, self._initial_task)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_layout(event.size.width)

    def _apply_responsive_layout(self, width: int) -> None:
        self.query_one("#main").set_class(width < 80, "narrow")

    @on(Input.Submitted, "#prompt-input")
    def on_prompt_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._handle_command(text)
        else:
            self._submit_task(text)

    def _handle_command(self, raw_command: str) -> None:
        command = raw_command.split(maxsplit=1)[0].lower()
        if command == "/help":
            self._chat.add_system(
                "/help show commands · /new reset conversation · "
                "/cancel request cooperative stop · /quit exit"
            )
        elif command == "/new":
            if self._run_in_flight:
                self._chat.add_system("Cannot start a new conversation while a run is active.")
                return
            self._reducer.reset()
            self._engine = self._engine_factory(self._on_engine_event)
            self._active_run_id = None
            self._quit_confirmation_pending = False
            self._chat.clear()
            self._timeline.clear()
            self._verification.reset()
            self._status.show_snapshot(self._reducer.snapshot)
            self._chat.add_system("Started a new conversation.")
        elif command == "/cancel":
            self._request_cancel()
        elif command == "/quit":
            self._request_quit()
        else:
            self._chat.add_system(f"Unknown command: {command}. Type /help.")

    def _submit_task(self, text: str) -> None:
        if self._run_in_flight:
            self._chat.add_system("A run is already active; wait or use /cancel.")
            return

        self._run_in_flight = True
        self._quit_confirmation_pending = False
        self._chat.add_user(text)
        self._chat.add_system("Run submitted. Cancellation is cooperative at safe boundaries.")
        engine = self._engine

        def run_query() -> None:
            try:
                result = engine.submit(text, limits=self._limits)
            except Exception as exc:  # UI boundary: surface sanitized failure, keep app alive
                self.post_message(
                    RunFinishedMessage(
                        None,
                        error=f"{type(exc).__name__}: {str(exc)[:500]}",
                    )
                )
            else:
                self.post_message(RunFinishedMessage(result))

        self.run_worker(
            run_query,
            name="query-engine-submit",
            group="active-run",
            thread=True,
            exclusive=True,
            exit_on_error=False,
        )

    def _on_engine_event(self, event_type: str, payload: dict) -> None:
        if event_type == "run.started":
            run_id = payload.get("run_id")
            if isinstance(run_id, str):
                with self._run_lock:
                    self._active_run_id = run_id
        self.post_message(RuntimeEventMessage(event_type, payload))

    @on(RuntimeEventMessage)
    def on_runtime_event(self, message: RuntimeEventMessage) -> None:
        reduced = self._reducer.apply(message.event_type, message.payload)
        if not reduced.accepted:
            return
        self._status.show_snapshot(reduced.snapshot)
        if reduced.timeline_text:
            self._timeline.add_event(reduced.timeline_text, known=reduced.known_event)
        if message.event_type == "verification.completed":
            self._verification.show_result(message.payload)

    @on(RunFinishedMessage)
    def on_run_finished(self, message: RunFinishedMessage) -> None:
        self._run_in_flight = False
        with self._run_lock:
            self._active_run_id = None
        self._prompt.focus()

        if message.error:
            self._chat.add_system(f"Run failed before a terminal result: {message.error}")
        elif message.result is not None:
            result = message.result
            snapshot = self._reducer.apply_result(
                run_id=result.run_id,
                status=result.status,
                stop_reason=result.stop_reason,
                model_calls=result.model_calls,
                tool_calls=result.tool_calls,
                last_sequence=result.last_event_sequence,
            )
            self._status.show_snapshot(snapshot)
            self._chat.add_agent(result.output)
            self._chat.add_system(
                f"Finished: status={result.status}, stop_reason={result.stop_reason}."
            )

        if self._exit_after_run:
            self.exit(0)

    def _request_cancel(self) -> None:
        with self._run_lock:
            run_id = self._active_run_id
        if not self._run_in_flight or run_id is None:
            self._chat.add_system("No active run to cancel.")
            return
        try:
            accepted = self._engine.request_stop(run_id, "user_requested")
        except Exception as exc:
            self._chat.add_system(
                f"Stop request failed: {type(exc).__name__}: {str(exc)[:200]}"
            )
            return
        if accepted:
            self._chat.add_system(
                "Stop requested. A synchronous model or shell call may continue until "
                "the next safe boundary."
            )
        else:
            self._chat.add_system("A stop request was already pending or the run has ended.")

    def _request_quit(self) -> None:
        if not self._run_in_flight:
            self.exit(0)
            return
        if not self._quit_confirmation_pending:
            self._quit_confirmation_pending = True
            self._chat.add_system(
                "A run is active. Enter /quit again to request cooperative stop and "
                "exit after the run reaches a terminal boundary."
            )
            return
        self._exit_after_run = True
        self._request_cancel()

    @property
    def _chat(self) -> ChatLog:
        return self.query_one(ChatLog)

    @property
    def _timeline(self) -> ToolTimeline:
        return self.query_one(ToolTimeline)

    @property
    def _verification(self) -> VerificationInspector:
        return self.query_one(VerificationInspector)

    @property
    def _status(self) -> RunStatus:
        return self.query_one(RunStatus)

    @property
    def _prompt(self) -> PromptInput:
        return self.query_one(PromptInput)
