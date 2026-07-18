"""Runtime composition helpers for default Context and long-memory integration."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from paperclaw.agent.flow import default_registry
from paperclaw.context.orchestration import ContextPolicy
from paperclaw.context.source_registry import ContextSourceRegistry
from paperclaw.tools.registry import ToolRegistry

from .source import FrozenFoundationalContextSource, ProjectInstructionLoader
from .store import FileMemoryStore, MemoryPolicy, MemorySnapshot
from .tool import MemoryTool


@dataclass(frozen=True)
class MemoryRuntimeSettings:
    context_enabled: bool = True
    memory_enabled: bool = True
    user_profile_enabled: bool = True
    memory_tool_enabled: bool = True
    memory_root: Path = Path.home() / ".paperclaw" / "memories"
    memory_char_limit: int = 2_200
    user_char_limit: int = 1_375
    max_input_tokens: int = 16_000
    output_reserve_tokens: int = 2_000
    max_single_candidate_tokens: int = 4_000
    recent_message_limit: int = 12
    recent_tool_result_limit: int = 8

    @classmethod
    def from_env(cls) -> "MemoryRuntimeSettings":
        return cls(
            context_enabled=_env_bool("PAPERCLAW_CONTEXT_ENABLED", True),
            memory_enabled=_env_bool("PAPERCLAW_MEMORY_ENABLED", True),
            user_profile_enabled=_env_bool("PAPERCLAW_USER_PROFILE_ENABLED", True),
            memory_tool_enabled=_env_bool("PAPERCLAW_MEMORY_TOOL_ENABLED", True),
            memory_root=Path(
                os.getenv(
                    "PAPERCLAW_MEMORY_DIR",
                    str(Path.home() / ".paperclaw" / "memories"),
                )
            ).expanduser(),
            memory_char_limit=_env_int("PAPERCLAW_MEMORY_CHAR_LIMIT", 2_200),
            user_char_limit=_env_int("PAPERCLAW_USER_CHAR_LIMIT", 1_375),
            max_input_tokens=_env_int("PAPERCLAW_CONTEXT_MAX_INPUT_TOKENS", 16_000),
            output_reserve_tokens=_env_int(
                "PAPERCLAW_CONTEXT_OUTPUT_RESERVE_TOKENS", 2_000
            ),
            max_single_candidate_tokens=_env_int(
                "PAPERCLAW_CONTEXT_MAX_CANDIDATE_TOKENS", 4_000
            ),
            recent_message_limit=_env_int(
                "PAPERCLAW_CONTEXT_RECENT_MESSAGE_LIMIT", 12
            ),
            recent_tool_result_limit=_env_int(
                "PAPERCLAW_CONTEXT_RECENT_TOOL_LIMIT", 8
            ),
        )

    def context_policy(self) -> ContextPolicy:
        return ContextPolicy(
            max_input_tokens=self.max_input_tokens,
            output_reserve_tokens=self.output_reserve_tokens,
            max_single_candidate_tokens=self.max_single_candidate_tokens,
            recent_message_limit=self.recent_message_limit,
            recent_tool_result_limit=self.recent_tool_result_limit,
            prompt_version="paperclaw.prompt.v0.17.0",
            policy_version="paperclaw.context.v0.17.0",
        )


@dataclass(frozen=True)
class MemoryRuntimeComponents:
    store: FileMemoryStore
    snapshot: MemorySnapshot
    tool_registry: ToolRegistry
    source_registry: ContextSourceRegistry
    context_policy: ContextPolicy
    settings: MemoryRuntimeSettings


def build_memory_runtime(
    workspace: str | Path,
    *,
    settings: MemoryRuntimeSettings | None = None,
    store: FileMemoryStore | None = None,
) -> MemoryRuntimeComponents:
    resolved_settings = settings or MemoryRuntimeSettings.from_env()
    resolved_store = store or FileMemoryStore(
        resolved_settings.memory_root,
        policy=MemoryPolicy(
            memory_char_limit=resolved_settings.memory_char_limit,
            user_char_limit=resolved_settings.user_char_limit,
        ),
    )
    snapshot = resolved_store.snapshot()
    if not resolved_settings.memory_enabled:
        snapshot = MemorySnapshot(
            memory_entries=(),
            user_entries=(),
            memory_used_chars=0,
            user_used_chars=0,
            memory_limit_chars=resolved_settings.memory_char_limit,
            user_limit_chars=resolved_settings.user_char_limit,
            fingerprint=snapshot.fingerprint,
        )
    elif not resolved_settings.user_profile_enabled:
        snapshot = MemorySnapshot(
            memory_entries=snapshot.memory_entries,
            user_entries=(),
            memory_used_chars=snapshot.memory_used_chars,
            user_used_chars=0,
            memory_limit_chars=snapshot.memory_limit_chars,
            user_limit_chars=snapshot.user_limit_chars,
            fingerprint=snapshot.fingerprint,
        )

    tools = default_registry()
    if resolved_settings.memory_enabled and resolved_settings.memory_tool_enabled:
        tools.register(MemoryTool(resolved_store))

    project_snapshot = ProjectInstructionLoader(workspace).snapshot()
    sources = ContextSourceRegistry()
    sources.register(
        "foundational_context",
        FrozenFoundationalContextSource(
            memory_snapshot=snapshot,
            project_snapshot=project_snapshot,
        ),
        kind="memory",
        priority=1_000,
    )
    return MemoryRuntimeComponents(
        store=resolved_store,
        snapshot=snapshot,
        tool_registry=tools,
        source_registry=sources,
        context_policy=resolved_settings.context_policy(),
        settings=resolved_settings,
    )


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    parsed = int(value)
    if parsed < 0:
        raise ValueError(f"{name} must be non-negative")
    return parsed


__all__ = [
    "MemoryRuntimeComponents",
    "MemoryRuntimeSettings",
    "build_memory_runtime",
]
