"""Parse source JSON without accepting ambiguous keys or unsupported numbers.

This reads captured input; Rulespec still owns canonical encoding and artifact
identity. Callers own their record shapes and the exception exposed to users.
"""

from __future__ import annotations

import json
from typing import Any


def load_integer_json(
    raw: bytes,
    *,
    source: str,
    error_type: type[ValueError],
    number_label: str = "float",
) -> object:
    """Keep source diagnostics while rejecting duplicate keys, floats and NaN."""

    def duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise error_type(f"{source} JSON repeats field {key!r}")
            result[key] = value
        return result

    def unsupported_number(value: str) -> None:
        raise error_type(f"{source} JSON contains unsupported {number_label} {value!r}")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=duplicate_keys,
            parse_float=unsupported_number,
            parse_constant=unsupported_number,
        )
    except error_type:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise error_type(f"invalid {source} JSON: {error}") from error
