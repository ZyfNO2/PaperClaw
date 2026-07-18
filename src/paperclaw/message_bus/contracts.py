"""Stable Agent Message Bus contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_TOPIC = re.compile(r"^[A-Za-z0-9_.:/-]{1,200}$")
_SENSITIVE_FIELD_NAMES = frozenset(
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

JSONScalar = str | int | float | bool | None
FrozenJSON = JSONScalar | tuple["FrozenJSON", ...] | Mapping[str, "FrozenJSON"]


class MessageBusError(RuntimeError):
    code = "message_bus_error"


class MessageBusConflictError(MessageBusError):
    code = "message_idempotency_conflict"


class MessageBusCapacityError(MessageBusError):
    code = "message_bus_capacity_exhausted"


class MessageBusAckError(MessageBusError):
    code = "message_bus_invalid_ack"


@dataclass(frozen=True)
class MessageDraft:
    topic: str
    sender_id: str
    idempotency_key: str
    payload: Mapping[str, Any]
    recipient_id: str | None = None
    headers: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _topic(self.topic)
        _identifier(self.sender_id, "sender_id")
        _identifier(self.idempotency_key, "idempotency_key")
        if self.recipient_id is not None:
            _identifier(self.recipient_id, "recipient_id")
        payload = normalize_json_object(self.payload, "payload")
        headers = normalize_json_object(self.headers, "headers")
        _reject_sensitive_fields(payload, "payload")
        _reject_sensitive_fields(headers, "headers")
        object.__setattr__(self, "payload", freeze_json_object(payload))
        object.__setattr__(self, "headers", freeze_json_object(headers))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "idempotency_key": self.idempotency_key,
            "payload": thaw_json(self.payload),
            "headers": thaw_json(self.headers),
        }


@dataclass(frozen=True)
class MessageEnvelope:
    message_id: str
    topic: str
    sequence: int
    sender_id: str
    idempotency_key: str
    payload: Mapping[str, Any]
    created_at: float
    recipient_id: str | None = None
    headers: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _identifier(self.message_id, "message_id")
        _topic(self.topic)
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
        ):
            raise ValueError("sequence must be a positive integer")
        _identifier(self.sender_id, "sender_id")
        _identifier(self.idempotency_key, "idempotency_key")
        if self.recipient_id is not None:
            _identifier(self.recipient_id, "recipient_id")
        if isinstance(self.created_at, bool) or not isinstance(
            self.created_at, (int, float)
        ):
            raise ValueError("created_at must be numeric")
        payload = normalize_json_object(self.payload, "payload")
        headers = normalize_json_object(self.headers, "headers")
        _reject_sensitive_fields(payload, "payload")
        _reject_sensitive_fields(headers, "headers")
        object.__setattr__(self, "payload", freeze_json_object(payload))
        object.__setattr__(self, "headers", freeze_json_object(headers))

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "topic": self.topic,
            "sequence": self.sequence,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "idempotency_key": self.idempotency_key,
            "payload": thaw_json(self.payload),
            "headers": thaw_json(self.headers),
            "created_at": float(self.created_at),
        }


@dataclass(frozen=True)
class PublishResult:
    message: MessageEnvelope
    created: bool


@dataclass(frozen=True)
class ConsumerCursor:
    consumer_id: str
    topic: str
    ack_sequence: int
    updated_at: float | None = None

    def __post_init__(self) -> None:
        _identifier(self.consumer_id, "consumer_id")
        _topic(self.topic)
        if (
            isinstance(self.ack_sequence, bool)
            or not isinstance(self.ack_sequence, int)
            or self.ack_sequence < 0
        ):
            raise ValueError("ack_sequence must be a non-negative integer")


@dataclass(frozen=True)
class MessageBusEvent:
    event_id: int
    event_type: str
    topic: str
    sequence: int | None
    created_at: float
    message_id: str | None = None
    consumer_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        metadata = normalize_json_object(self.metadata, "metadata")
        object.__setattr__(self, "metadata", freeze_json_object(metadata))


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        thaw_json(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_draft_bytes(draft: MessageDraft) -> bytes:
    return canonical_json_bytes(draft.canonical_dict())


def normalize_json_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    try:
        decoded = json.loads(
            json.dumps(dict(value), ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{name} must serialize to an object")
    if any(not isinstance(key, str) for key in decoded):
        raise ValueError(f"{name} keys must be strings")
    return decoded


def freeze_json_object(value: Mapping[str, Any]) -> Mapping[str, FrozenJSON]:
    return MappingProxyType(
        {str(key): freeze_json(child) for key, child in value.items()}
    )


def freeze_json(value: Any) -> FrozenJSON:
    if isinstance(value, Mapping):
        return freeze_json_object(value)
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json(child) for child in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"unsupported normalized JSON value: {type(value).__name__}")


def thaw_json(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(child) for child in value]
    return value


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise ValueError(f"{name} must match {_ID.pattern}")
    return value


def _topic(value: str) -> str:
    if not isinstance(value, str) or _TOPIC.fullmatch(value) is None:
        raise ValueError(f"topic must match {_TOPIC.pattern}")
    return value


def _reject_sensitive_fields(value: object, path: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower().replace("-", "_")
            child_path = f"{path}.{raw_key}"
            if key in _SENSITIVE_FIELD_NAMES:
                raise ValueError(
                    f"message contains credential-shaped field: {child_path}"
                )
            _reject_sensitive_fields(child, child_path)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{path}[{index}]")


__all__ = [
    "ConsumerCursor",
    "MessageBusAckError",
    "MessageBusCapacityError",
    "MessageBusConflictError",
    "MessageBusError",
    "MessageBusEvent",
    "MessageDraft",
    "MessageEnvelope",
    "PublishResult",
    "canonical_draft_bytes",
    "canonical_json_bytes",
    "freeze_json",
    "freeze_json_object",
    "normalize_json_object",
    "thaw_json",
]
