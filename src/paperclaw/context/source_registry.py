"""Deterministic public registration boundary for external ContextCandidate sources."""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal

from paperclaw.context.orchestration import (
    ContextCandidate,
    ContextCandidateSource,
    ContextRequest,
)

_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SourceKind = Literal["retrieval", "tool_selection", "memory", "custom"]


class ContextSourceRegistryError(RuntimeError):
    pass


class ContextSourceRegistryFrozen(ContextSourceRegistryError):
    pass


class ContextSourceCollectionError(ContextSourceRegistryError):
    def __init__(self, source_id: str, cause: BaseException) -> None:
        self.source_id = source_id
        self.cause_type = type(cause).__name__
        super().__init__(f"context source {source_id!r} failed with {self.cause_type}")


@dataclass(frozen=True)
class ContextSourceDescriptor:
    source_id: str
    kind: SourceKind
    priority: int = 0
    scopes: tuple[str, ...] = ("shared",)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not _SOURCE_ID.fullmatch(self.source_id):
            raise ValueError("source_id must be 1-128 characters from [A-Za-z0-9_.-]")
        if self.kind not in {"retrieval", "tool_selection", "memory", "custom"}:
            raise ValueError(f"unsupported ContextSource kind: {self.kind}")
        if not -10_000 <= self.priority <= 10_000:
            raise ValueError("priority must be in [-10000, 10000]")
        if not self.scopes or any(not scope.strip() for scope in self.scopes):
            raise ValueError("scopes must contain non-empty values")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("scopes must not contain duplicates")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scopes"] = list(self.scopes)
        return data


@dataclass(frozen=True)
class ContextSourceRegistrySnapshot:
    descriptors: tuple[ContextSourceDescriptor, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "descriptors": [descriptor.to_dict() for descriptor in self.descriptors],
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class _Registration:
    descriptor: ContextSourceDescriptor
    source: ContextCandidateSource


class ContextSourceRegistry(ContextCandidateSource):
    def __init__(self) -> None:
        self._registrations: dict[str, _Registration] = {}
        self._lock = threading.RLock()
        self._frozen = False

    def register(
        self,
        source_id: str,
        source: ContextCandidateSource,
        *,
        kind: SourceKind,
        priority: int = 0,
        scopes: Iterable[str] = ("shared",),
        enabled: bool = True,
    ) -> ContextSourceDescriptor:
        descriptor = ContextSourceDescriptor(
            source_id=source_id,
            kind=kind,
            priority=priority,
            scopes=tuple(scopes),
            enabled=enabled,
        )
        if not callable(getattr(source, "collect", None)):
            raise TypeError("source must implement collect(ContextRequest)")
        with self._lock:
            if self._frozen:
                raise ContextSourceRegistryFrozen(
                    "ContextSourceRegistry is frozen for runtime use"
                )
            if source_id in self._registrations:
                raise ValueError(f"ContextSource already registered: {source_id}")
            self._registrations[source_id] = _Registration(descriptor, source)
        return descriptor

    def freeze(self) -> ContextSourceRegistrySnapshot:
        with self._lock:
            self._frozen = True
            return self.snapshot()

    @property
    def is_frozen(self) -> bool:
        with self._lock:
            return self._frozen

    def snapshot(self) -> ContextSourceRegistrySnapshot:
        with self._lock:
            descriptors = tuple(
                registration.descriptor
                for registration in self._ordered_registrations(include_disabled=True)
            )
        payload = [descriptor.to_dict() for descriptor in descriptors]
        fingerprint = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return ContextSourceRegistrySnapshot(descriptors, fingerprint)

    def collect(self, request: ContextRequest) -> tuple[ContextCandidate, ...]:
        with self._lock:
            registrations = self._ordered_registrations(include_disabled=False)
        candidates: list[ContextCandidate] = []
        owners: dict[str, str] = {}
        for registration in registrations:
            source_id = registration.descriptor.source_id
            try:
                produced = tuple(registration.source.collect(request))
            except Exception as exc:
                raise ContextSourceCollectionError(source_id, exc) from exc
            for candidate in produced:
                if not isinstance(candidate, ContextCandidate):
                    raise ContextSourceCollectionError(
                        source_id,
                        TypeError("source returned a non-ContextCandidate value"),
                    )
                owner = owners.get(candidate.candidate_id)
                if owner is not None:
                    raise ContextSourceCollectionError(
                        source_id,
                        ValueError(f"candidate_id collision with source {owner!r}"),
                    )
                owners[candidate.candidate_id] = source_id
                candidates.append(candidate)
        return tuple(candidates)

    def _ordered_registrations(self, *, include_disabled: bool) -> tuple[_Registration, ...]:
        registrations = (
            registration
            for registration in self._registrations.values()
            if include_disabled or registration.descriptor.enabled
        )
        return tuple(
            sorted(
                registrations,
                key=lambda item: (-item.descriptor.priority, item.descriptor.source_id),
            )
        )


__all__ = [
    "ContextSourceCollectionError",
    "ContextSourceDescriptor",
    "ContextSourceRegistry",
    "ContextSourceRegistryError",
    "ContextSourceRegistryFrozen",
    "ContextSourceRegistrySnapshot",
    "SourceKind",
]
