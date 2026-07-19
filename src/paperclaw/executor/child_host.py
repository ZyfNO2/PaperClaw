"""Minimal JSON-file child host for isolated execution.

The parent launches this module with only request/result file paths. stdout and
stderr are intentionally not part of the protocol so child logs, prompts, and
provider output cannot accidentally become durable executor results.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from time import time
from typing import Any, Mapping

from .contracts import ExecutionRequest, ExecutionResult, ExecutorStatus
from .entrypoints import resolve_entrypoint


def run_request_file(request_path: Path, result_path: Path) -> int:
    started_at = time()
    try:
        raw = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            return 2
        request = ExecutionRequest.from_dict(raw)
    except Exception:
        return 2

    try:
        entrypoint = resolve_entrypoint(request.entrypoint)
    except KeyError:
        result = ExecutionResult(
            execution_id=request.execution_id,
            task_id=request.task_id,
            status=ExecutorStatus.FAILED,
            error_code="entrypoint_not_registered",
            error_type="LookupError",
            pid=os.getpid(),
            started_at=started_at,
            finished_at=time(),
        )
        _write_result(result_path, result)
        return 3

    try:
        output = entrypoint(request.payload)
        if not isinstance(output, Mapping):
            raise TypeError("entrypoint output must be a mapping")
        # Force JSON validation before declaring success.
        encoded = json.dumps(dict(output), ensure_ascii=False, allow_nan=False)
        normalized = json.loads(encoded)
        if not isinstance(normalized, dict):
            raise TypeError("entrypoint output must serialize to an object")
        result = ExecutionResult(
            execution_id=request.execution_id,
            task_id=request.task_id,
            status=ExecutorStatus.SUCCEEDED,
            output=normalized,
            pid=os.getpid(),
            started_at=started_at,
            finished_at=time(),
        )
        _write_result(result_path, result)
        return 0
    except Exception as exc:
        # Exception messages and traceback frames are deliberately excluded from
        # the IPC contract. They can contain prompts, file contents, or secrets.
        result = ExecutionResult(
            execution_id=request.execution_id,
            task_id=request.task_id,
            status=ExecutorStatus.CRASHED,
            error_code="child_exception",
            error_type=type(exc).__name__[:200],
            pid=os.getpid(),
            started_at=started_at,
            finished_at=time(),
        )
        try:
            _write_result(result_path, result)
        except Exception:
            return 5
        return 4


def _write_result(path: Path, result: ExecutionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        return 64
    return run_request_file(Path(args[0]), Path(args[1]))


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    raise SystemExit(main())
