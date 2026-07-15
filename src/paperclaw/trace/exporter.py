"""JSONL export/import for the stable TraceEvent v1 contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .contracts import TraceEvent, validate_trace
from .reader import TraceReader


@dataclass(frozen=True)
class TraceExportSummary:
    run_id: str
    output_path: str
    event_count: int
    first_sequence: int | None
    last_sequence: int | None
    sha256: str

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "run_id": self.run_id,
            "output_path": self.output_path,
            "event_count": self.event_count,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "sha256": self.sha256,
        }


def export_trace_jsonl(
    reader: TraceReader,
    run_id: str,
    output_path: str | Path,
    *,
    require_terminal: bool = False,
) -> TraceExportSummary:
    """Atomically export one run trace as deterministic UTF-8 JSONL.

    The output parent must already exist.  This follows the repository's
    existing CLI/database rule and avoids silently creating directories from
    user-controlled paths.
    """

    destination = Path(output_path)
    if not destination.parent.exists():
        raise FileNotFoundError(
            f"trace output parent does not exist: {destination.parent}"
        )
    if destination.exists() and destination.is_dir():
        raise IsADirectoryError(f"trace output is a directory: {destination}")

    events = reader.get_run_trace(run_id, require_terminal=require_terminal)
    lines = tuple(
        json.dumps(
            event.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        for event in events
    )
    content = "".join(f"{line}\n" for line in lines)
    encoded = content.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()

    temporary = destination.with_name(
        f".{destination.name}.tmp-{uuid4().hex[:12]}"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(encoded)
            handle.flush()
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    return TraceExportSummary(
        run_id=run_id,
        output_path=str(destination),
        event_count=len(events),
        first_sequence=events[0].sequence if events else None,
        last_sequence=events[-1].sequence if events else None,
        sha256=digest,
    )


def load_trace_jsonl(
    input_path: str | Path,
    *,
    require_terminal: bool = False,
) -> tuple[TraceEvent, ...]:
    """Load and validate TraceEvent v1 JSONL without executing any action."""

    source = Path(input_path)
    events: list[TraceEvent] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid trace JSON on line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(data, dict):
                raise ValueError(
                    f"trace line {line_number} must contain a JSON object"
                )
            try:
                event = TraceEvent(**data)
                event.validate()
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid trace event on line {line_number}: {exc}"
                ) from exc
            events.append(event)
    return validate_trace(events, require_terminal=require_terminal)
