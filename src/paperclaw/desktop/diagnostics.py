"""Local, sanitized diagnostic logging for desktop-only failures."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import traceback
from typing import Mapping

_MAX_TRACE_CHARS = 20_000
_CODE_PATTERN = re.compile(r"[^a-z0-9_.-]+")
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(api[_-]?key|authorization|bearer|credential|password|secret|token)"
    r"([\s\"':=]+)([^\s,;\]\}]+)"
)
_CREDENTIAL_PATTERN = re.compile(r"(?i)\b(?:sk|key|token)-[a-z0-9_-]{12,}\b")


def diagnostic_log_path(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    env = os.environ if environment is None else environment
    if os.name == "nt":
        local_app_data = env.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "PaperClaw" / "logs" / "desktop.log"
    state_home = env.get("XDG_STATE_HOME")
    if state_home:
        return Path(state_home) / "paperclaw" / "desktop.log"
    resolved_home = home or Path.home()
    return resolved_home / ".local" / "state" / "paperclaw" / "desktop.log"


def record_exception(
    code: str,
    exc: BaseException,
    *,
    secret: str = "",
    path: Path | None = None,
) -> Path | None:
    """Append a bounded traceback after removing credential-shaped values.

    Logging is best-effort and must never replace the public typed error path.
    """

    target = path or diagnostic_log_path()
    safe_code = _CODE_PATTERN.sub("_", str(code).strip().lower())[:64] or "runtime_error"
    rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    if secret:
        rendered = rendered.replace(secret, "<REDACTED>")
    rendered = _SECRET_ASSIGNMENT_PATTERN.sub(r"\1\2<REDACTED>", rendered)
    rendered = _CREDENTIAL_PATTERN.sub("<REDACTED>", rendered)
    rendered = rendered[:_MAX_TRACE_CHARS]
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"[{timestamp}] {safe_code}\n{rendered}\n"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(entry)
    except OSError:
        return None
    return target
