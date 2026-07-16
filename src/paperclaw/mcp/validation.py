"""Fail-closed invocation-time validation for normalized MCP Tool schemas."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any, Mapping

from paperclaw.mcp.contracts import MCPError, MCPToolDescriptor, bounded_text


def validate_tool_arguments(
    descriptor: MCPToolDescriptor,
    arguments: Mapping[str, Any],
) -> None:
    """Validate one invocation against the frozen descriptor schema.

    The protocol foundation already rejects unsupported schema composition at
    discovery time. This validator covers the accepted subset immediately
    before every remote call and never delegates validation to the Server.
    """

    if not isinstance(arguments, Mapping):
        raise _argument_error(descriptor, "$ must be an object")
    schema = descriptor.input_schema_dict()
    _validate_node(dict(arguments), schema, path="$", descriptor=descriptor)


def _validate_node(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
    descriptor: MCPToolDescriptor,
) -> None:
    if not isinstance(schema, Mapping):
        raise _schema_error(descriptor, f"schema node is not an object at {path}")

    raw_type = schema.get("type")
    if raw_type is not None and not _matches_type(value, raw_type):
        raise _argument_error(
            descriptor,
            f"{path} has type {_type_name(value)}; expected {_render_type(raw_type)}",
        )

    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list):
            raise _schema_error(descriptor, f"enum is not an array at {path}")
        if not any(_json_equal(value, candidate) for candidate in enum):
            raise _argument_error(descriptor, f"{path} is not one of the allowed values")

    if "const" in schema and not _json_equal(value, schema["const"]):
        raise _argument_error(descriptor, f"{path} does not match the required constant")

    if isinstance(value, Mapping):
        _validate_object(dict(value), schema, path=path, descriptor=descriptor)
    elif isinstance(value, list):
        _validate_array(value, schema, path=path, descriptor=descriptor)
    elif isinstance(value, str):
        _validate_string(value, schema, path=path, descriptor=descriptor)
    elif _is_number(value):
        _validate_number(value, schema, path=path, descriptor=descriptor)


def _validate_object(
    value: dict[str, Any],
    schema: Mapping[str, Any],
    *,
    path: str,
    descriptor: MCPToolDescriptor,
) -> None:
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
        raise _schema_error(descriptor, f"required is invalid at {path}")
    for name in required:
        if name not in value:
            raise _argument_error(descriptor, f"missing required property: {path}.{name}")

    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        raise _schema_error(descriptor, f"properties is invalid at {path}")
    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, bool):
        raise _schema_error(descriptor, f"additionalProperties is invalid at {path}")

    for name, child in value.items():
        if not isinstance(name, str):
            raise _argument_error(descriptor, f"{path} contains a non-string property name")
        child_schema = properties.get(name)
        if child_schema is None:
            if not additional:
                raise _argument_error(descriptor, f"unexpected property: {path}.{name}")
            continue
        if not isinstance(child_schema, Mapping):
            raise _schema_error(descriptor, f"property schema is invalid at {path}.{name}")
        _validate_node(child, child_schema, path=f"{path}.{name}", descriptor=descriptor)

    _validate_size_keyword(
        len(value), schema, "minProperties", minimum=True, path=path, descriptor=descriptor
    )
    _validate_size_keyword(
        len(value), schema, "maxProperties", minimum=False, path=path, descriptor=descriptor
    )


def _validate_array(
    value: list[Any],
    schema: Mapping[str, Any],
    *,
    path: str,
    descriptor: MCPToolDescriptor,
) -> None:
    _validate_size_keyword(
        len(value), schema, "minItems", minimum=True, path=path, descriptor=descriptor
    )
    _validate_size_keyword(
        len(value), schema, "maxItems", minimum=False, path=path, descriptor=descriptor
    )
    unique = schema.get("uniqueItems", False)
    if not isinstance(unique, bool):
        raise _schema_error(descriptor, f"uniqueItems is invalid at {path}")
    if unique:
        for index, item in enumerate(value):
            if any(_json_equal(item, prior) for prior in value[:index]):
                raise _argument_error(descriptor, f"{path} contains duplicate items")

    items = schema.get("items")
    if items is not None:
        if not isinstance(items, Mapping):
            raise _schema_error(descriptor, f"items is invalid at {path}")
        for index, item in enumerate(value):
            _validate_node(item, items, path=f"{path}[{index}]", descriptor=descriptor)


def _validate_string(
    value: str,
    schema: Mapping[str, Any],
    *,
    path: str,
    descriptor: MCPToolDescriptor,
) -> None:
    _validate_size_keyword(
        len(value), schema, "minLength", minimum=True, path=path, descriptor=descriptor
    )
    _validate_size_keyword(
        len(value), schema, "maxLength", minimum=False, path=path, descriptor=descriptor
    )
    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            raise _schema_error(descriptor, f"pattern is invalid at {path}")
        try:
            matched = re.search(pattern, value) is not None
        except re.error as exc:
            raise _schema_error(descriptor, f"pattern cannot be compiled at {path}") from exc
        if not matched:
            raise _argument_error(descriptor, f"{path} does not match the required pattern")


def _validate_number(
    value: int | float,
    schema: Mapping[str, Any],
    *,
    path: str,
    descriptor: MCPToolDescriptor,
) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise _argument_error(descriptor, f"{path} must be finite")
    for keyword, comparator, message in (
        ("minimum", lambda actual, bound: actual >= bound, "below minimum"),
        ("maximum", lambda actual, bound: actual <= bound, "above maximum"),
        ("exclusiveMinimum", lambda actual, bound: actual > bound, "not above exclusiveMinimum"),
        ("exclusiveMaximum", lambda actual, bound: actual < bound, "not below exclusiveMaximum"),
    ):
        if keyword not in schema:
            continue
        bound = schema[keyword]
        if not _is_number(bound):
            raise _schema_error(descriptor, f"{keyword} is invalid at {path}")
        if not comparator(value, bound):
            raise _argument_error(descriptor, f"{path} is {message}")

    if "multipleOf" in schema:
        multiple = schema["multipleOf"]
        if not _is_number(multiple) or multiple <= 0:
            raise _schema_error(descriptor, f"multipleOf is invalid at {path}")
        try:
            actual_decimal = Decimal(str(value))
            multiple_decimal = Decimal(str(multiple))
            is_multiple = actual_decimal % multiple_decimal == 0
        except (InvalidOperation, ValueError) as exc:
            raise _schema_error(descriptor, f"multipleOf cannot be evaluated at {path}") from exc
        if not is_multiple:
            raise _argument_error(descriptor, f"{path} is not a multiple of {multiple}")


def _validate_size_keyword(
    actual: int,
    schema: Mapping[str, Any],
    keyword: str,
    *,
    minimum: bool,
    path: str,
    descriptor: MCPToolDescriptor,
) -> None:
    if keyword not in schema:
        return
    bound = schema[keyword]
    if isinstance(bound, bool) or not isinstance(bound, int) or bound < 0:
        raise _schema_error(descriptor, f"{keyword} is invalid at {path}")
    if (minimum and actual < bound) or (not minimum and actual > bound):
        relation = "at least" if minimum else "at most"
        raise _argument_error(descriptor, f"{path} must contain {relation} {bound} items")


def _matches_type(value: Any, raw_type: Any) -> bool:
    if isinstance(raw_type, str):
        return _matches_single_type(value, raw_type)
    if isinstance(raw_type, list) and raw_type:
        return all(isinstance(item, str) for item in raw_type) and any(
            _matches_single_type(value, item) for item in raw_type
        )
    return False


def _matches_single_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return _is_number(value)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, Mapping)
    return False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _json_equal(left: Any, right: Any) -> bool:
    if _is_number(left) and _is_number(right):
        return Decimal(str(left)) == Decimal(str(right))
    return type(left) is type(right) and left == right


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _render_type(raw_type: Any) -> str:
    if isinstance(raw_type, list):
        return " | ".join(str(item) for item in raw_type)
    return str(raw_type)


def _argument_error(descriptor: MCPToolDescriptor, message: str) -> MCPError:
    return MCPError(
        bounded_text(message, 300),
        code="INVALID_TOOL_ARGUMENTS",
        server_id=descriptor.server_id,
        phase="tools/call",
    )


def _schema_error(descriptor: MCPToolDescriptor, message: str) -> MCPError:
    return MCPError(
        bounded_text(message, 300),
        code="INVALID_TOOL_SCHEMA",
        server_id=descriptor.server_id,
        phase="tools/call",
    )
