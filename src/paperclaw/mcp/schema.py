"""Conservative MCP Tool schema normalization for Phase A."""

from __future__ import annotations

from typing import Any, Mapping

from paperclaw.mcp.contracts import (
    DEFAULT_SCHEMA_URI,
    MCPError,
    MCPToolDescriptor,
    bounded_text,
    freeze_json,
    normalize_json_value,
    sha256_json,
    thaw_json,
    validate_tool_name,
)

SUPPORTED_SCHEMA_URIS = frozenset(
    {
        DEFAULT_SCHEMA_URI,
        f"{DEFAULT_SCHEMA_URI}#",
        "http://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema#",
    }
)
SUPPORTED_SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "type",
        "title",
        "description",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "const",
        "default",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
    }
)
SUPPORTED_JSON_TYPES = frozenset(
    {"object", "array", "string", "number", "integer", "boolean", "null"}
)


def normalize_tool_descriptor(raw: Any, *, server_id: str) -> MCPToolDescriptor:
    """Normalize one MCP Tool object or reject it without a partial descriptor."""

    if not isinstance(raw, Mapping):
        raise _schema_error("MCP tool descriptor must be an object", server_id)
    name = raw.get("name")
    try:
        validate_tool_name(name)
    except ValueError as exc:
        raise _schema_error(str(exc), server_id) from exc
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise _schema_error("MCP tool description must be a string", server_id)
    title = raw.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise _schema_error("MCP tool title must be a non-empty string", server_id)

    input_schema, dialect = normalize_json_schema(
        raw.get("inputSchema"),
        top_level_object=True,
        server_id=server_id,
        tool_name=name,
        field_name="inputSchema",
    )
    output_schema: Mapping[str, Any] | None = None
    output_hash: str | None = None
    if raw.get("outputSchema") is not None:
        output_schema, _ = normalize_json_schema(
            raw["outputSchema"],
            top_level_object=True,
            server_id=server_id,
            tool_name=name,
            field_name="outputSchema",
        )
        output_hash = sha256_json(thaw_json(output_schema))

    return MCPToolDescriptor(
        server_id=server_id,
        name=name,
        title=None if title is None else bounded_text(title, 500),
        description=bounded_text(description, 20_000),
        input_schema=input_schema,
        input_schema_hash=sha256_json(thaw_json(input_schema)),
        output_schema=output_schema,
        output_schema_hash=output_hash,
        schema_dialect=dialect,
    )


def normalize_json_schema(
    raw_schema: Any,
    *,
    top_level_object: bool,
    server_id: str,
    tool_name: str,
    field_name: str,
) -> tuple[Mapping[str, Any], str]:
    """Normalize the explicitly supported JSON Schema subset."""

    if not isinstance(raw_schema, Mapping):
        raise _schema_error(
            f"{tool_name}.{field_name} must be a JSON Schema object", server_id
        )
    schema = dict(raw_schema)
    dialect = schema.get("$schema", DEFAULT_SCHEMA_URI)
    if not isinstance(dialect, str) or dialect not in SUPPORTED_SCHEMA_URIS:
        raise _schema_error(
            f"unsupported JSON Schema dialect in {tool_name}.{field_name}",
            server_id,
            unsupported=True,
        )
    try:
        normalized = _normalize_schema_node(
            schema,
            path=f"{tool_name}.{field_name}",
            server_id=server_id,
        )
    except ValueError as exc:
        raise _schema_error(str(exc), server_id) from exc
    if top_level_object and normalized.get("type") != "object":
        raise _schema_error(
            f"{tool_name}.{field_name} top-level type must be object",
            server_id,
            unsupported=True,
        )
    normalized["$schema"] = dialect.rstrip("#")
    ordered = _sort_json(normalized)
    return freeze_json(ordered), dialect.rstrip("#")


def _normalize_schema_node(
    raw: Mapping[str, Any],
    *,
    path: str,
    server_id: str,
) -> dict[str, Any]:
    unsupported = sorted(set(raw) - SUPPORTED_SCHEMA_KEYWORDS)
    if unsupported:
        raise _schema_error(
            f"unsupported JSON Schema keyword at {path}: {unsupported[0]}",
            server_id,
            unsupported=True,
        )
    normalized: dict[str, Any] = {}
    raw_type = raw.get("type")
    if isinstance(raw_type, list):
        if (
            not raw_type
            or len(set(raw_type)) != len(raw_type)
            or any(
                not isinstance(item, str) or item not in SUPPORTED_JSON_TYPES
                for item in raw_type
            )
        ):
            raise _schema_error(f"invalid JSON Schema type union at {path}", server_id)
        normalized["type"] = sorted(raw_type)
    elif isinstance(raw_type, str):
        if raw_type not in SUPPORTED_JSON_TYPES:
            raise _schema_error(
                f"unsupported JSON Schema type at {path}: {raw_type}",
                server_id,
                unsupported=True,
            )
        normalized["type"] = raw_type
    elif raw_type is not None:
        raise _schema_error(
            f"JSON Schema type must be a string or string array at {path}", server_id
        )

    for key, value in raw.items():
        if key in {"type", "$schema"}:
            continue
        if key == "properties":
            normalized[key] = _normalize_properties(
                value, path=path, server_id=server_id
            )
        elif key == "items":
            if not isinstance(value, Mapping):
                raise _schema_error(
                    f"items must be one schema object at {path}",
                    server_id,
                    unsupported=True,
                )
            normalized[key] = _normalize_schema_node(
                value, path=f"{path}.items", server_id=server_id
            )
        elif key == "additionalProperties":
            if not isinstance(value, bool):
                raise _schema_error(
                    f"schema-valued additionalProperties is unsupported at {path}",
                    server_id,
                    unsupported=True,
                )
            normalized[key] = value
        elif key == "required":
            normalized[key] = _normalize_required(
                value, raw=raw, path=path, server_id=server_id
            )
        else:
            normalized[key] = normalize_json_value(value, path=f"{path}.{key}")
    return normalized


def _normalize_properties(value: Any, *, path: str, server_id: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _schema_error(f"properties must be an object at {path}", server_id)
    properties: dict[str, Any] = {}
    for name, schema in value.items():
        if not isinstance(name, str) or not name:
            raise _schema_error(
                f"property names must be non-empty strings at {path}", server_id
            )
        if not isinstance(schema, Mapping):
            raise _schema_error(
                f"property schema must be an object at {path}.{name}", server_id
            )
        properties[name] = _normalize_schema_node(
            schema,
            path=f"{path}.properties.{name}",
            server_id=server_id,
        )
    return properties


def _normalize_required(
    value: Any,
    *,
    raw: Mapping[str, Any],
    path: str,
    server_id: str,
) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise _schema_error(
            f"required must contain unique non-empty strings at {path}", server_id
        )
    properties = raw.get("properties", {})
    if isinstance(properties, Mapping):
        missing = sorted(set(value) - set(properties))
        if missing:
            raise _schema_error(
                f"required property is not declared at {path}: {missing[0]}", server_id
            )
    return sorted(value)


def _schema_error(
    message: str,
    server_id: str,
    *,
    unsupported: bool = False,
) -> MCPError:
    return MCPError(
        message,
        code="UNSUPPORTED_TOOL_SCHEMA" if unsupported else "INVALID_TOOL_SCHEMA",
        server_id=server_id,
        phase="tools/list",
    )


def _sort_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _sort_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_sort_json(item) for item in value]
    return value
