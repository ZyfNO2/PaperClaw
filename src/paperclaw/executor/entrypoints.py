"""Allowlisted subprocess entrypoints.

The child host resolves logical IDs through this registry. It never imports an
arbitrary module/function string supplied by a task payload.
"""

from __future__ import annotations

import os
from time import sleep
from typing import Any, Callable, Mapping

Entrypoint = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def resolve_entrypoint(entrypoint: str) -> Entrypoint:
    if entrypoint == "executor.echo.v1":
        return _echo
    if entrypoint == "executor.sleep.v1":
        return _sleep
    if entrypoint == "executor.crash.v1":
        return _crash
    if entrypoint == "executor.exit_no_result.v1":
        return _exit_no_result
    if entrypoint == "tasks.subagent.env.v1":
        from paperclaw.tasks.subprocess_worker import run_env_subagent_payload

        return run_env_subagent_payload
    raise KeyError(entrypoint)


def _echo(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"echo": dict(payload)}


def _sleep(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    value = payload.get("seconds", 0.1)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("seconds must be numeric")
    sleep(max(0.0, min(float(value), 60.0)))
    return {"slept_seconds": float(value)}


def _crash(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    del payload
    raise RuntimeError("diagnostic child crash")


def _exit_no_result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    code = payload.get("exit_code", 17)
    if isinstance(code, bool) or not isinstance(code, int):
        code = 17
    os._exit(max(1, min(code, 255)))


__all__ = ["Entrypoint", "resolve_entrypoint"]
