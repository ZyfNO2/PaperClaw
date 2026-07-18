"""First-class product Artifact contracts, distinct from RAG source artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_TYPE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_MEDIA_TYPE = re.compile(r"^[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+$")
_SENSITIVE = frozenset(
    {
        "api_key",
        "apikey",
        "token",
        "access_token",
        "refresh_token",
        "password",
        "secret",
        "authorization",
        "cookie",
        "client_secret",
        "private_key",
    }
)


class ArtifactError(RuntimeError):
    code = "artifact_error"


class ArtifactNotFoundError(ArtifactError):
    code = "artifact_not_found"


class ArtifactConflictError(ArtifactError):
    code = "artifact_idempotency_conflict"


class ArtifactCapacityError(ArtifactError):
    code = "artifact_capacity_exceeded"


class ArtifactIntegrityError(ArtifactError):
    code = "artifact_integrity_error"


@dataclass(frozen=True)
class ArtifactSourceLinks:
    project_id: str | None = None
    run_id: str | None = None
    task_id: str | None = None
    trace_id: str | None = None

    def __post_init__(self) -> None:
        for name in ("project_id", "run_id", "task_id", "trace_id"):
            value = getattr(self, name)
            if value is not None:
                _identifier(value, name)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
        }


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_id: str
    artifact_type: str
    title: str
    created_at: float
    updated_at: float
    latest_revision_number: int
    source: ArtifactSourceLinks = field(default_factory=ArtifactSourceLinks)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.artifact_id, "artifact_id")
        if _TYPE.fullmatch(self.artifact_type) is None:
            raise ValueError("invalid artifact_type")
        _bounded_text(self.title, "title", 500)
        if self.latest_revision_number < 1:
            raise ValueError("latest_revision_number must be positive")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "latest_revision_number": self.latest_revision_number,
            "source": self.source.to_dict(),
            "metadata": _thaw(self.metadata),
        }


@dataclass(frozen=True)
class ArtifactRevision:
    revision_id: str
    artifact_id: str
    revision_number: int
    content_hash: str
    byte_length: int
    media_type: str
    created_at: float
    message: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.revision_id, "revision_id")
        _identifier(self.artifact_id, "artifact_id")
        if self.revision_number < 1:
            raise ValueError("revision_number must be positive")
        if len(self.content_hash) != 64 or any(
            char not in "0123456789abcdef" for char in self.content_hash
        ):
            raise ValueError("content_hash must be lowercase SHA-256")
        if self.byte_length < 0:
            raise ValueError("byte_length must be non-negative")
        if _MEDIA_TYPE.fullmatch(self.media_type) is None:
            raise ValueError("invalid media_type")
        if self.message is not None:
            _bounded_text(self.message, "message", 2_000)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def to_dict(self) -> dict[str, object]:
        return {
            "revision_id": self.revision_id,
            "artifact_id": self.artifact_id,
            "revision_number": self.revision_number,
            "content_hash": self.content_hash,
            "byte_length": self.byte_length,
            "media_type": self.media_type,
            "created_at": self.created_at,
            "message": self.message,
            "metadata": _thaw(self.metadata),
        }


@dataclass(frozen=True)
class ArtifactBundle:
    artifact: ArtifactRecord
    revisions: tuple[ArtifactRevision, ...]

    def __post_init__(self) -> None:
        expected = tuple(range(1, len(self.revisions) + 1))
        if tuple(item.revision_number for item in self.revisions) != expected:
            raise ValueError("artifact revisions must be contiguous and ordered")
        if any(item.artifact_id != self.artifact.artifact_id for item in self.revisions):
            raise ValueError("revision artifact_id mismatch")
        if self.artifact.latest_revision_number != len(self.revisions):
            raise ValueError("latest revision does not match revision collection")

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact": self.artifact.to_dict(),
            "revisions": [item.to_dict() for item in self.revisions],
        }


def normalize_metadata(
    value: Mapping[str, Any],
    *,
    max_bytes: int = 65_536,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("artifact metadata must be an object")
    _validate_keys(value, "metadata")
    _reject_sensitive(value, "metadata")
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        decoded = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("artifact metadata must be JSON serializable") from exc
    if len(encoded) > max_bytes:
        raise ArtifactCapacityError("artifact metadata exceeds byte limit")
    return decoded


def _freeze_metadata(value: Mapping[str, Any]) -> Mapping[str, Any]:
    normalized = normalize_metadata(value)
    return MappingProxyType(
        {key: _freeze(child) for key, child in normalized.items()}
    )


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def _validate_keys(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            _validate_keys(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_keys(child, f"{path}[{index}]")


def _reject_sensitive(value: Any, path: str) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = key.strip().lower().replace("-", "_")
            if normalized in _SENSITIVE:
                raise ValueError(f"artifact metadata contains secret field: {path}.{key}")
            _reject_sensitive(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive(child, f"{path}[{index}]")


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"invalid {name}")
    return value


def _bounded_text(value: str, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{name} must be non-empty and at most {limit} characters")
    return value.strip()


__all__ = [
    "ArtifactBundle",
    "ArtifactCapacityError",
    "ArtifactConflictError",
    "ArtifactError",
    "ArtifactIntegrityError",
    "ArtifactNotFoundError",
    "ArtifactRecord",
    "ArtifactRevision",
    "ArtifactSourceLinks",
    "normalize_metadata",
]
