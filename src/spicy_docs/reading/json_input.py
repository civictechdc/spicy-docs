"""Parse source JSON without accepting ambiguous keys or unsupported numbers.

This reads captured input; Rulespec still owns canonical encoding and artifact
identity. Callers own their record shapes and the exception exposed to users.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

_WHITESPACE = re.compile(r"[ \t\r\n]*")
NumberPolicy = Literal["integer", "decimal", "finite-float"]


@dataclass(frozen=True, slots=True)
class JsonRecordSpan:
    """Half-open positions in decoded source characters and original UTF-8 bytes."""

    char_start: int
    char_end: int
    byte_start: int
    byte_end: int


@dataclass(frozen=True, slots=True)
class JsonRecordRead:
    value: object
    records: tuple[JsonRecordSpan, ...]


def read_json_records(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_policy: NumberPolicy,
    max_bytes: int,
    max_nodes: int = 100_000,
    max_depth: int = 64,
) -> JsonRecordRead:
    """Decode once and locate each top-level array member, or one non-array root.

    Empty arrays have no records. Spans omit surrounding JSON whitespace and
    delimiters; source escapes and number spelling remain in the original bytes.
    No result returns until the complete document and its bounds are checked.
    """
    _validate_input(raw, source, error_type, max_bytes, max_nodes, max_depth)
    parser = json.JSONDecoder(**_decoder_options(source, error_type, number_policy))
    try:
        text = raw.decode("utf-8")
        position = _skip_whitespace(text, 0)
        records: list[JsonRecordSpan] = []
        char_position = byte_position = 0

        def record(start: int, end: int) -> None:
            nonlocal char_position, byte_position
            byte_position += len(text[char_position:start].encode("utf-8"))
            byte_end = byte_position + len(text[start:end].encode("utf-8"))
            records.append(JsonRecordSpan(start, end, byte_position, byte_end))
            char_position, byte_position = end, byte_end

        if text[position : position + 1] == "[":
            value = []
            count = 1  # The top-level array itself is a JSON value at depth zero.
            position = _skip_whitespace(text, position + 1)
            if text[position : position + 1] != "]":
                while True:
                    if count >= max_nodes:
                        raise error_type(f"{source} exceeds max_nodes or max_depth")
                    item, end = parser.raw_decode(text, position)
                    count += _check_nodes(item, source, error_type, max_nodes - count, max_depth, initial_depth=1)
                    value.append(item)
                    record(position, end)
                    position = _skip_whitespace(text, end)
                    if text[position : position + 1] == "]":
                        break
                    if text[position : position + 1] != ",":
                        raise json.JSONDecodeError("Expecting ',' delimiter", text, position)
                    position = _skip_whitespace(text, position + 1)
            end = position + 1
        else:
            value, end = parser.raw_decode(text, position)
            _check_nodes(value, source, error_type, max_nodes, max_depth)
            record(position, end)
        end = _skip_whitespace(text, end)
        if end != len(text):
            raise json.JSONDecodeError("Extra data", text, end)
        return JsonRecordRead(value, tuple(records))
    except error_type:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise error_type(f"invalid {source} JSON: {error}") from error
    except (ValueError, InvalidOperation, RecursionError) as error:
        raise error_type(f"{source} exceeds JSON decoder limits") from error


def load_bounded_json(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_policy: NumberPolicy,
    max_bytes: int,
    max_nodes: int = 100_000,
    max_depth: int = 64,
) -> object:
    """Decode bounded UTF-8 input with an explicit number policy.

    Nodes count JSON values, including unknown fields. Limits cover the complete
    decoded document; the decoder may refuse excessive nesting earlier. Original
    bytes retain number spelling, including any rounding under finite-float policy.
    """
    _validate_input(raw, source, error_type, max_bytes, max_nodes, max_depth)
    loaders = {"integer": load_integer_json, "decimal": load_decimal_json, "finite-float": load_finite_json}
    if number_policy not in loaders:
        raise error_type(f"{source} has an unsupported number policy")
    try:
        value = loaders[number_policy](raw, source=source, error_type=error_type)
    except error_type:
        raise
    except (ValueError, InvalidOperation, RecursionError) as error:
        raise error_type(f"{source} exceeds JSON decoder limits") from error
    _check_nodes(value, source, error_type, max_nodes, max_depth)
    return value


def _skip_whitespace(text: str, position: int) -> int:
    match = _WHITESPACE.match(text, position)
    assert match is not None  # All callers supply a position within the source.
    return match.end()


def _validate_input(
    raw: bytes, source: str, error_type: type[ValueError], max_bytes: int, max_nodes: int, max_depth: int
) -> None:
    for name, value in (("max_bytes", max_bytes), ("max_nodes", max_nodes), ("max_depth", max_depth)):
        if type(value) is not int or value <= 0:
            raise error_type(f"{source} {name} must be a positive integer")
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise error_type(f"{source} must be non-empty bytes within max_bytes")


def _check_nodes(
    value: object,
    source: str,
    error_type: type[ValueError],
    max_nodes: int,
    max_depth: int,
    *,
    initial_depth: int = 0,
) -> int:
    pending = [(value, initial_depth)]
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
    return count


def load_finite_json(raw: bytes, *, source: str, error_type: type[ValueError] = ValueError) -> object:
    """Keep Python integers and finite binary floats; refuse duplicate keys, NaN and infinities."""
    return _load(raw, source=source, error_type=error_type, number_policy="finite-float")


def load_integer_json(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_label: str = "float",
) -> object:
    """Reject duplicate keys, any float and NaN, naming the number ``number_label`` in the refusal."""

    return _load(raw, source=source, error_type=error_type, number_policy="integer", number_label=number_label)


def load_decimal_json(raw: bytes, *, source: str, error_type: type[ValueError] = ValueError) -> object:
    """Retain decimal JSON values without binary-float rounding; forbid NaN."""

    return _load(raw, source=source, error_type=error_type, number_policy="decimal")


def _decoder_options(
    source: str, error_type: type[ValueError], number_policy: NumberPolicy, number_label: str = "float"
) -> dict[str, Any]:
    if number_policy not in ("integer", "decimal", "finite-float"):
        raise error_type(f"{source} has an unsupported number policy")

    def duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error_type(f"{source} JSON repeats field {key!r}")
            result[key] = value
        return result

    def invalid(value: str) -> None:
        label = number_label if number_policy == "integer" else "number"
        raise error_type(f"{source} JSON contains unsupported {label} {value!r}")

    def finite(value: str) -> float:
        result = float(value)
        if not math.isfinite(result):
            invalid(value)
        return result

    return {
        "object_pairs_hook": duplicate_keys,
        "parse_float": invalid if number_policy == "integer" else Decimal if number_policy == "decimal" else finite,
        "parse_constant": invalid,
    }


def _load(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_policy: NumberPolicy,
    number_label: str = "float",
) -> object:

    try:
        return json.loads(
            raw.decode("utf-8"),
            **_decoder_options(source, error_type, number_policy, number_label),
        )
    except error_type:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise error_type(f"invalid {source} JSON: {error}") from error
