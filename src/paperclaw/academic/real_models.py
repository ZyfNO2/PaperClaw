"""Fail-closed checks for P0 real-model runs.

These checks do not make a Fake encoder real. They only validate that an
operator supplied the pinned model identity and that the requested runtime is
available before a result can be labelled as real evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from typing import Literal


class RealModelBlocked(RuntimeError):
    """Raised when a P0 real-model requirement is not satisfied."""


@dataclass(frozen=True)
class RealModelStatus:
    kind: Literal["minilm", "colqwen2"]
    model_name: str
    revision: str
    dependencies_available: bool
    cuda_available: bool | None
    status: Literal["READY", "BLOCKED"]
    reason: str


def check_real_model_environment(
    kind: Literal["minilm", "colqwen2"],
    *,
    model_name: str,
    revision: str,
) -> RealModelStatus:
    expected = {
        "minilm": "sentence-transformers/all-MiniLM-L6-v2",
        "colqwen2": "vidore/colqwen2-base",
    }[kind]
    if model_name != expected or not revision:
        return RealModelStatus(
            kind,
            model_name,
            revision,
            False,
            None,
            "BLOCKED",
            "model identity or fixed revision is missing",
        )
    dependencies = (
        importlib.util.find_spec("torch") is not None
        and importlib.util.find_spec("transformers") is not None
        and (kind == "minilm" or importlib.util.find_spec("colpali_engine") is not None)
    )
    cuda: bool | None = None
    if importlib.util.find_spec("torch") is not None:
        import torch

        cuda = bool(torch.cuda.is_available())
    if not dependencies:
        reason = "required model dependencies are unavailable"
    elif kind == "colqwen2" and cuda is not True:
        reason = "ColQwen2 P0 run requires a CUDA device"
    else:
        reason = "pinned real-model environment is available"
    return RealModelStatus(
        kind,
        model_name,
        revision,
        dependencies,
        cuda,
        "READY" if dependencies and (kind == "minilm" or cuda is True) else "BLOCKED",
        reason,
    )


def require_real_encoder(
    encoder: object | None,
    kind: Literal["minilm", "colqwen2"],
) -> object:
    """Reject absent, fake, unpinned, or CPU-placeholder encoders."""

    if encoder is None:
        raise RealModelBlocked(f"{kind} encoder is not configured")
    class_name = type(encoder).__name__.lower()
    if "fake" in class_name or "mock" in class_name:
        raise RealModelBlocked(f"{kind} encoder is Fake/Mock")
    expected = {
        "minilm": "sentence-transformers/all-MiniLM-L6-v2",
        "colqwen2": "vidore/colqwen2-base",
    }[kind]
    if getattr(encoder, "model_name", None) != expected:
        raise RealModelBlocked(f"{kind} encoder model identity is not pinned")
    if not getattr(encoder, "revision", None):
        raise RealModelBlocked(f"{kind} encoder revision is not pinned")
    if kind == "colqwen2" and getattr(encoder, "device", None) != "cuda":
        raise RealModelBlocked("ColQwen2 CPU fallback cannot be labelled as P0 real evidence")
    return encoder


__all__ = ["RealModelBlocked", "RealModelStatus", "check_real_model_environment", "require_real_encoder"]
