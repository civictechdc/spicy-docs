# Frozen SpicyDocs f1c42c7 source loader; test-only diagnostic/value reference.
"""Parse source JSON without accepting ambiguous keys or unsupported numbers.

This reads captured input; Rulespec still owns canonical encoding and artifact
identity. Callers own their record shapes and the exception exposed to users.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Literal


def load_bounded_json(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_policy: Literal["integer", "decimal", "finite-float"],
    max_bytes: int,
    max_nodes: int = 100_000,
    max_depth: int = 64,
) -> object:
    """Decode bounded UTF-8 input with an explicit number policy.

    Nodes count JSON values, including unknown fields. Limits cover the complete
    decoded document; the decoder may refuse excessive nesting earlier. Original
    bytes retain number spelling, including any rounding under finite-float policy.
    """
    for name, value in (("max_bytes", max_bytes), ("max_nodes", max_nodes), ("max_depth", max_depth)):
        if type(value) is not int or value <= 0:
            raise error_type(f"{source} {name} must be a positive integer")
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise error_type(f"{source} must be non-empty bytes within max_bytes")
    loaders = {"integer": load_integer_json, "decimal": load_decimal_json, "finite-float": load_finite_json}
    if number_policy not in loaders:
        raise error_type(f"{source} has an unsupported number policy")
    try:
        value = loaders[number_policy](raw, source=source, error_type=error_type)
    except error_type:
        raise
    except (ValueError, InvalidOperation, RecursionError) as error:
        raise error_type(f"{source} exceeds JSON decoder limits") from error
    pending = [(value, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if count > max_nodes or depth > max_depth:
            raise error_type(f"{source} exceeds max_nodes or max_depth")
        children = item.values() if isinstance(item, dict) else item if isinstance(item, list) else ()
        if count + len(pending) + len(children) > max_nodes or (children and depth >= max_depth):
            raise error_type(f"{source} exceeds max_nodes or max_depth")
        pending.extend((child, depth + 1) for child in children)
    return value


def load_finite_json(raw: bytes, *, source: str, error_type: type[ValueError] = ValueError) -> object:
    """Keep Python integers and finite binary floats; refuse ambiguous JSON."""

    def invalid(value: str) -> None:
        raise error_type(f"{source} JSON contains unsupported number {value!r}")

    def finite(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            invalid(value)
        return result

    return _load(raw, source=source, error_type=error_type, parse_float=finite, parse_constant=invalid)


def load_integer_json(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_label: str = "float",
) -> object:
    """Keep source diagnostics while rejecting duplicate keys, floats and NaN."""

    def unsupported_number(value: str) -> None:
        raise error_type(f"{source} JSON contains unsupported {number_label} {value!r}")

    return _load(
        raw, source=source, error_type=error_type, parse_float=unsupported_number, parse_constant=unsupported_number
    )


def load_decimal_json(raw: bytes, *, source: str, error_type: type[ValueError] = ValueError) -> object:
    """Retain decimal JSON values without binary-float rounding; forbid NaN."""

    def invalid(value: str) -> None:
        raise error_type(f"{source} JSON contains unsupported number {value!r}")

    return _load(raw, source=source, error_type=error_type, parse_float=Decimal, parse_constant=invalid)


def _load(
    raw: bytes, *, source: str, error_type: type[ValueError], parse_float: Callable, parse_constant: Callable
) -> object:
    def duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error_type(f"{source} JSON repeats field {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=duplicate_keys,
            parse_float=parse_float,
            parse_constant=parse_constant,
        )
    except error_type:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise error_type(f"invalid {source} JSON: {error}") from error
