"""Fail-isolated observer plugins for the PaperClaw service layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from .contracts import PublicRunEvent, PublicRunView


class ServicePlugin(Protocol):
    plugin_id: str

    def on_run_created(self, run: PublicRunView) -> None: ...

    def on_event(self, event: PublicRunEvent) -> None: ...

    def on_run_terminal(self, run: PublicRunView) -> None: ...


@dataclass(frozen=True)
class PluginFailure:
    plugin_id: str
    hook: str
    error_type: str
    message: str


class ServicePluginRegistry:
    """Static plugin registry. Plugin failures never alter run state."""

    def __init__(self, plugins: Sequence[ServicePlugin] = ()) -> None:
        ids = [plugin.plugin_id for plugin in plugins]
        if any(not plugin_id.strip() for plugin_id in ids):
            raise ValueError("plugin_id must not be empty")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate service plugin_id")
        self._plugins = tuple(plugins)
        self._failures: list[PluginFailure] = []

    @property
    def failures(self) -> tuple[PluginFailure, ...]:
        return tuple(self._failures)

    def run_created(self, run: PublicRunView) -> None:
        self._dispatch("on_run_created", run)

    def event(self, event: PublicRunEvent) -> None:
        self._dispatch("on_event", event)

    def run_terminal(self, run: PublicRunView) -> None:
        self._dispatch("on_run_terminal", run)

    def _dispatch(self, hook: str, value: object) -> None:
        for plugin in self._plugins:
            try:
                getattr(plugin, hook)(value)
            except Exception as exc:
                self._failures.append(
                    PluginFailure(
                        plugin_id=plugin.plugin_id,
                        hook=hook,
                        error_type=type(exc).__name__,
                        message=str(exc)[:500],
                    )
                )
