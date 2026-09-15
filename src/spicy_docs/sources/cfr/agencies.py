"""Literal rows and locations from the eCFR administrative agency roster."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import InvalidOperation
from typing import Any

from spicy_docs.reading.json_input import load_decimal_json

from .models import DEFAULT_MAX_BYTES, CfrSourceError, _limit

ECFR_AGENCIES_URL = "https://www.ecfr.gov/api/admin/v1/agencies.json"
_TEXT_FIELDS = ("name", "short_name", "display_name", "sortable_name", "slug")


@dataclass(frozen=True, slots=True)
class EcfrAgencyIssue:
    source_path: str
    code: str


@dataclass(frozen=True, slots=True)
class EcfrAgencyReferenceObservation:
    raw: Any
    source_path: str


@dataclass(frozen=True, slots=True)
class EcfrAgencyObservation:
    raw: Any
    source_path: str
    parent_path: str | None
    child_paths: tuple[str, ...]
    references: tuple[EcfrAgencyReferenceObservation, ...]
    issues: tuple[EcfrAgencyIssue, ...]


@dataclass(frozen=True, slots=True)
class EcfrAgencyRoster:
    raw: Any
    records: tuple[EcfrAgencyObservation, ...]
    issues: tuple[EcfrAgencyIssue, ...]


def read_ecfr_agency_roster(
    payload: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_nodes: int = 100_000,
    max_depth: int = 64,
) -> EcfrAgencyRoster:
    """Keep source order, malformed rows and unknown fields without roster policy.

    Missing, null and empty fields remain distinct in ``raw``. Paths identify
    array positions, including duplicate slugs. Limits apply to the entire JSON
    document, including unknown fields. The caller retains the original bytes.
    """

    _limit(max_bytes)
    if not isinstance(payload, bytes) or not payload or len(payload) > max_bytes:
        raise CfrSourceError("eCFR agencies must be non-empty bytes within max_bytes")
    if type(max_nodes) is not int or max_nodes <= 0 or type(max_depth) is not int or max_depth <= 0:
        raise CfrSourceError("eCFR agencies max_nodes and max_depth must be positive integers")
    try:
        raw = load_decimal_json(payload, source="eCFR agencies", error_type=CfrSourceError)
    except CfrSourceError:
        raise
    except (ValueError, InvalidOperation) as error:
        raise CfrSourceError("eCFR agencies JSON contains an unsupported number") from error
    except RecursionError as error:
        raise CfrSourceError("eCFR agencies JSON exceeds the decoder nesting limit") from error
    pending = [(raw, 0)]
    count = 0
    while pending:
        value, depth = pending.pop()
        count += 1
        if count > max_nodes or depth > max_depth:
            raise CfrSourceError("eCFR agencies exceeds max_nodes or max_depth")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)

    if not isinstance(raw, dict):
        return EcfrAgencyRoster(raw, (), (EcfrAgencyIssue("$", "object_expected"),))
    if not isinstance(raw.get("agencies"), list):
        code = "array_expected" if "agencies" in raw else "missing_field"
        return EcfrAgencyRoster(raw, (), (EcfrAgencyIssue("$.agencies", code),))

    records: list[EcfrAgencyObservation] = []
    pending_rows = [(row, f"$.agencies[{i}]", None) for i, row in reversed(list(enumerate(raw["agencies"])))]
    while pending_rows:
        value, path, parent = pending_rows.pop()
        issues: list[EcfrAgencyIssue] = []
        references: list[EcfrAgencyReferenceObservation] = []
        children: list[tuple[Any, str, str]] = []
        if not isinstance(value, dict):
            issues.append(EcfrAgencyIssue(path, "object_expected"))
        else:
            for name in _TEXT_FIELDS:
                if name not in value:
                    issues.append(EcfrAgencyIssue(f"{path}.{name}", "missing_field"))
                elif not isinstance(value[name], str) and not (name == "short_name" and value[name] is None):
                    issues.append(EcfrAgencyIssue(f"{path}.{name}", "text_expected"))
            if "cfr_references" not in value:
                issues.append(EcfrAgencyIssue(f"{path}.cfr_references", "missing_field"))
            elif not isinstance(value["cfr_references"], list):
                issues.append(EcfrAgencyIssue(f"{path}.cfr_references", "array_expected"))
            else:
                for i, reference in enumerate(value["cfr_references"]):
                    reference_path = f"{path}.cfr_references[{i}]"
                    references.append(EcfrAgencyReferenceObservation(reference, reference_path))
                    if not isinstance(reference, dict):
                        issues.append(EcfrAgencyIssue(reference_path, "object_expected"))
            if "children" in value and not isinstance(value["children"], list):
                issues.append(EcfrAgencyIssue(f"{path}.children", "array_expected"))
            elif isinstance(value.get("children"), list):
                children = [(child, f"{path}.children[{i}]", path) for i, child in enumerate(value["children"])]
        records.append(
            EcfrAgencyObservation(
                value, path, parent, tuple(child[1] for child in children), tuple(references), tuple(issues)
            )
        )
        pending_rows.extend(reversed(children))
    return EcfrAgencyRoster(raw, tuple(records), ())
