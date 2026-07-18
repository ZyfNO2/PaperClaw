"""Frozen foundational Context sources for project instructions and long memory."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Iterable

from paperclaw.context.orchestration import ContextCandidate, ContextRequest, estimate_tokens

from .store import MemoryEntry, MemorySnapshot

_IMPORT_PATTERN = re.compile(r"(?<![A-Za-z0-9_])@([A-Za-z0-9_./\\-]+)")
_DEFAULT_INSTRUCTION_FILES = ("PAPERCLAW.md", "CLAUDE.md", "AGENTS.md")
<<<<<<< HEAD
=======
_TRUNCATION_MARKER = "\n[paperclaw: project instructions truncated at configured limit]"
>>>>>>> 77ef8ea


@dataclass(frozen=True)
class ProjectInstructionSnapshot:
    content: str
    source_files: tuple[str, ...]
    fingerprint: str
<<<<<<< HEAD
=======
    truncated: bool = False
>>>>>>> 77ef8ea


class ProjectInstructionLoader:
    """Load workspace-scoped instruction files with bounded recursive imports.

    PaperClaw uses ``PAPERCLAW.md`` as its native project file and accepts
    ``CLAUDE.md``/``AGENTS.md`` for compatibility. Imports are limited to the
    workspace and a depth of five; absolute paths and path traversal are rejected.
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        filenames: Iterable[str] = _DEFAULT_INSTRUCTION_FILES,
        max_depth: int = 5,
        max_file_chars: int = 32_000,
        max_total_chars: int = 64_000,
    ) -> None:
        self.workspace = Path(workspace).resolve(strict=True)
        self.filenames = tuple(filenames)
        self.max_depth = max_depth
        self.max_file_chars = max_file_chars
        self.max_total_chars = max_total_chars
        if max_depth < 0 or max_file_chars < 1 or max_total_chars < 1:
            raise ValueError("instruction loader limits are invalid")

    def snapshot(self) -> ProjectInstructionSnapshot:
        loaded: dict[Path, str] = {}
        for filename in self.filenames:
            candidate = (self.workspace / filename).resolve(strict=False)
            if candidate.is_file():
                self._load(candidate, depth=0, loaded=loaded)
        blocks: list[str] = []
        used = 0
        source_files: list[str] = []
<<<<<<< HEAD
=======
        truncated = False
>>>>>>> 77ef8ea
        for path, content in loaded.items():
            relative = path.relative_to(self.workspace).as_posix()
            block = f"[project-instruction:{relative}]\n{content}"
            if used + len(block) > self.max_total_chars:
<<<<<<< HEAD
                remaining = self.max_total_chars - used
                if remaining > 0:
                    blocks.append(block[:remaining])
=======
                truncated = True
                remaining = self.max_total_chars - used
                marker_budget = len(_TRUNCATION_MARKER)
                if remaining > marker_budget:
                    blocks.append(block[: remaining - marker_budget] + _TRUNCATION_MARKER)
                    source_files.append(relative)
                elif remaining > 0:
                    blocks.append(_TRUNCATION_MARKER[-remaining:])
>>>>>>> 77ef8ea
                break
            blocks.append(block)
            source_files.append(relative)
            used += len(block)
        rendered = "\n\n".join(blocks)
        fingerprint = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        return ProjectInstructionSnapshot(
            content=rendered,
            source_files=tuple(source_files),
            fingerprint=fingerprint,
<<<<<<< HEAD
=======
            truncated=truncated,
>>>>>>> 77ef8ea
        )

    def _load(self, path: Path, *, depth: int, loaded: dict[Path, str]) -> None:
        if path in loaded or depth > self.max_depth:
            return
        try:
            path.relative_to(self.workspace)
        except ValueError:
            return
        if not path.is_file():
            return
        content = path.read_text(encoding="utf-8", errors="replace")[: self.max_file_chars]
        loaded[path] = content
        for import_path in self._imports(content):
            candidate = Path(import_path)
            if candidate.is_absolute():
                continue
            resolved = (path.parent / candidate).resolve(strict=False)
            try:
                resolved.relative_to(self.workspace)
            except ValueError:
                continue
            self._load(resolved, depth=depth + 1, loaded=loaded)

    @staticmethod
    def _imports(content: str) -> tuple[str, ...]:
        imports: list[str] = []
        in_fence = False
        for line in content.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            imports.extend(match.group(1) for match in _IMPORT_PATTERN.finditer(line))
        return tuple(dict.fromkeys(imports))


class FrozenFoundationalContextSource:
    """Expose immutable session-start project/user/memory snapshots to Context."""

    def __init__(
        self,
        *,
        memory_snapshot: MemorySnapshot,
        project_snapshot: ProjectInstructionSnapshot,
<<<<<<< HEAD
    ) -> None:
        self.memory_snapshot = memory_snapshot
        self.project_snapshot = project_snapshot
=======
        minimum_confidence: float = 0.60,
    ) -> None:
        if (
            isinstance(minimum_confidence, bool)
            or not isinstance(minimum_confidence, (int, float))
            or not 0 <= float(minimum_confidence) <= 1
        ):
            raise ValueError("minimum_confidence must be within [0, 1]")
        self.memory_snapshot = memory_snapshot
        self.project_snapshot = project_snapshot
        self.minimum_confidence = float(minimum_confidence)
>>>>>>> 77ef8ea

    def collect(self, request: ContextRequest) -> tuple[ContextCandidate, ...]:
        candidates: list[ContextCandidate] = []
        project = self.project_snapshot
        if project.content:
            candidates.append(
                ContextCandidate(
                    candidate_id=f"project-instructions:{project.fingerprint[:16]}",
                    source="project_instructions",
                    source_ref=",".join(project.source_files),
                    layer="L1",
                    kind="constraint",
                    scope=("shared",),
                    priority=950,
                    trust="trusted_local",
                    freshness=request.at_sequence,
                    estimated_tokens=estimate_tokens(project.content),
                    content=project.content,
                    bucket="protected",
                    pinned=True,
                    compressible=False,
<<<<<<< HEAD
=======
                    metadata={"truncated": project.truncated},
>>>>>>> 77ef8ea
                )
            )

        user_content = self._render_store(
            "USER PROFILE",
            self.memory_snapshot.user_entries,
<<<<<<< HEAD
            self.memory_snapshot.user_used_chars,
=======
>>>>>>> 77ef8ea
            self.memory_snapshot.user_limit_chars,
        )
        if user_content:
            candidates.append(
                ContextCandidate(
                    candidate_id=f"user-profile:{self.memory_snapshot.fingerprint[:16]}",
                    source="long_memory_user",
                    source_ref="USER.md",
                    layer="L1",
                    kind="constraint",
                    scope=("shared",),
                    priority=930,
                    trust="user",
                    freshness=request.at_sequence,
                    estimated_tokens=estimate_tokens(user_content),
                    content=user_content,
                    bucket="protected",
                    pinned=True,
                    compressible=False,
                )
            )

        memory_content = self._render_store(
            "MEMORY",
            self.memory_snapshot.memory_entries,
<<<<<<< HEAD
            self.memory_snapshot.memory_used_chars,
=======
>>>>>>> 77ef8ea
            self.memory_snapshot.memory_limit_chars,
        )
        if memory_content:
            candidates.append(
                ContextCandidate(
                    candidate_id=f"agent-memory:{self.memory_snapshot.fingerprint[:16]}",
                    source="long_memory_agent",
                    source_ref="MEMORY.md",
                    layer="L2",
                    kind="observation",
                    scope=("shared",),
                    priority=880,
                    trust="trusted_local",
                    freshness=request.at_sequence,
                    estimated_tokens=estimate_tokens(memory_content),
                    content=memory_content,
                    bucket="context",
                    pinned=True,
                    compressible=False,
                )
            )
        return tuple(candidates)

<<<<<<< HEAD
    @staticmethod
    def _render_store(
        title: str,
        entries: tuple[MemoryEntry, ...],
        used_chars: int,
        limit_chars: int,
    ) -> str:
        if not entries:
            return ""
        percentage = round((used_chars / limit_chars) * 100) if limit_chars else 0
        lines = [f"{title} [{percentage}% — {used_chars}/{limit_chars} chars]"]
        for entry in entries:
=======
    def _render_store(
        self,
        title: str,
        entries: tuple[MemoryEntry, ...],
        limit_chars: int,
    ) -> str:
        selected = tuple(
            entry
            for entry in entries
            if entry.confidence >= self.minimum_confidence and not entry.is_expired
        )
        if not selected:
            return ""
        used_chars = sum(len(entry.content) for entry in selected) + max(
            0, len(selected) - 1
        )
        percentage = round((used_chars / limit_chars) * 100) if limit_chars else 0
        lines = [
            f"{title} [{percentage}% — {used_chars}/{limit_chars} chars; "
            f"minimum_confidence={self.minimum_confidence:.2f}]"
        ]
        for entry in selected:
>>>>>>> 77ef8ea
            lines.append(
                "\n".join(
                    (
                        f"[{entry.entry_id}] category={entry.category} "
                        f"confidence={entry.confidence:.2f} updated={entry.updated_at}",
                        entry.content,
                    )
                )
            )
        return "\n§\n".join(lines)


__all__ = [
    "FrozenFoundationalContextSource",
    "ProjectInstructionLoader",
    "ProjectInstructionSnapshot",
]
