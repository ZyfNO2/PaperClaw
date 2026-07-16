"""Full-screen Textual dashboard for one MultiAgent Coordinator run."""

from __future__ import annotations

from threading import RLock
from typing import Callable, Protocol

from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Static

from paperclaw.multiagent.contracts import AgentTask
from paperclaw.multiagent.coordinator import CoordinatorResult
from paperclaw.multiagent.team_view import TeamViewReducer, TeamViewSnapshot

from .team_widgets import TeamReview, TeamStatus, TeamTimeline, TeamWorkers

TeamEventHandler = Callable[[str, dict], None]


class CoordinatorLike(Protocol):
    def run(self, user_goal: str, tasks: list[AgentTask]) -> CoordinatorResult: ...


CoordinatorFactory = Callable[[TeamEventHandler], CoordinatorLike]


class TeamRuntimeEventMessage(Message):
    def __init__(self, event_type: str, envelope: dict) -> None:
        super().__init__()
        self.event_type = event_type
        self.envelope = dict(envelope)


class TeamFinishedMessage(Message):
    def __init__(
        self,
        result: CoordinatorResult | None,
        error_type: str | None = None,
    ) -> None:
        super().__init__()
        self.result = result
        self.error_type = error_type


class TeamApp(App[int]):
    """Thin client that renders only the stable team-view projection contract."""

    CSS_PATH = "team.tcss"
    TITLE = "PaperClaw MultiAgent Team"
    BINDINGS = [
        ("r", "start_team", "Run team"),
        ("q", "request_quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        coordinator_factory: CoordinatorFactory,
        goal: str,
        tasks: list[AgentTask],
        auto_start: bool = True,
    ) -> None:
        super().__init__()
        self._coordinator_factory = coordinator_factory
        self._goal = goal
        self._tasks = list(tasks)
        self._auto_start = auto_start
        self._reducer = TeamViewReducer()
        self._run_in_flight = False
        self._run_lock = RLock()

    @property
    def snapshot(self) -> TeamViewSnapshot:
        return self._reducer.snapshot

    def compose(self) -> ComposeResult:
        yield TeamStatus(id="team-status")
        with Horizontal(id="team-main"):
            with Vertical(id="team-left"):
                yield TeamWorkers(id="team-workers")
                yield TeamReview(id="team-review")
            with Vertical(id="team-right"):
                yield TeamTimeline(id="team-timeline", wrap=True, highlight=False)
        yield Static("R: run again after completion · Q: quit", id="team-help")

    def on_mount(self) -> None:
        self._render_snapshot(self._reducer.snapshot)
        self._apply_responsive_layout(self.size.width)
        if self._auto_start:
            self.call_after_refresh(self._start_team)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_responsive_layout(event.size.width)

    def _apply_responsive_layout(self, width: int) -> None:
        self.query_one("#team-main").set_class(width < 88, "narrow")

    def action_start_team(self) -> None:
        self._start_team()

    def _start_team(self) -> None:
        with self._run_lock:
            if self._run_in_flight:
                self.query_one(TeamTimeline).add_system(
                    "Team run is already active; duplicate start ignored."
                )
                return
            self._run_in_flight = True

        self._reducer.reset()
        timeline = self.query_one(TeamTimeline)
        timeline.reset()
        self._render_snapshot(self._reducer.snapshot)
        timeline.add_system("Team run submitted.")
        coordinator = self._coordinator_factory(self._on_team_event)

        def run_team() -> None:
            try:
                result = coordinator.run(self._goal, list(self._tasks))
            except Exception as exc:  # UI boundary: keep arbitrary exception text private
                self.post_message(
                    TeamFinishedMessage(
                        None,
                        error_type=type(exc).__name__,
                    )
                )
            else:
                self.post_message(TeamFinishedMessage(result))

        self.run_worker(
            run_team,
            name="multiagent-coordinator-run",
            group="active-team-run",
            thread=True,
            exclusive=True,
            exit_on_error=False,
        )

    def _on_team_event(self, event_type: str, envelope: dict) -> None:
        self.post_message(TeamRuntimeEventMessage(event_type, envelope))

    @on(TeamRuntimeEventMessage)
    def on_team_runtime_event(self, message: TeamRuntimeEventMessage) -> None:
        update = self._reducer.apply(message.event_type, message.envelope)
        if not update.accepted:
            return
        self._render_snapshot(update.snapshot)
        self.query_one(TeamTimeline).add_event(
            message.event_type,
            message.envelope,
            known=update.known_event,
        )

    @on(TeamFinishedMessage)
    def on_team_finished(self, message: TeamFinishedMessage) -> None:
        with self._run_lock:
            self._run_in_flight = False
        timeline = self.query_one(TeamTimeline)
        if message.error_type:
            timeline.add_system(
                "Team failed before a terminal result: "
                f"{message.error_type}. Exception detail was suppressed."
            )
            self._render_snapshot(self._reducer.snapshot)
            return
        if message.result is None:
            timeline.add_system("Team finished without a CoordinatorResult.")
            return
        snapshot = self._reducer.apply_result(message.result)
        self._render_snapshot(snapshot)
        timeline.add_system(
            f"Team finished: status={snapshot.status}, "
            f"stop_reason={snapshot.stop_reason or '-'} ."
        )

    def action_request_quit(self) -> None:
        with self._run_lock:
            active = self._run_in_flight
        if active:
            self.query_one(TeamTimeline).add_system(
                "Cannot quit while the Coordinator is active; no unsafe hard-cancel exists."
            )
            return
        self.exit(0 if self.snapshot.status == "completed" else 1)

    def _render_snapshot(self, snapshot: TeamViewSnapshot) -> None:
        self.query_one(TeamStatus).show_snapshot(snapshot)
        self.query_one(TeamWorkers).show_snapshot(snapshot)
        self.query_one(TeamReview).show_snapshot(snapshot)


__all__ = [
    "CoordinatorFactory",
    "CoordinatorLike",
    "TeamApp",
    "TeamFinishedMessage",
    "TeamRuntimeEventMessage",
]
