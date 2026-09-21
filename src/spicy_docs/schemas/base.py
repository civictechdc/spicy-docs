"""Shared data shapes that flow between sources and transforms."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecordType:
    """One shape of data that flows through the pipeline: a name, schema, dedup key, extract function and optional S3
    path pattern.

    Instances are values, not classes; constructing one refuses a ``dedup_key`` absent from the schema and a schema that
    lacks ``modify_date``.
    """

    name: str
    schema: dict[str, Any]
    dedup_key: str
    extract: Callable[[dict], dict]
    path_pattern: str | None = None

    def __post_init__(self) -> None:
        if self.dedup_key not in self.schema:
            raise ValueError(f"RecordType {self.name!r}: dedup_key {self.dedup_key!r} not in schema")
        if "modify_date" not in self.schema:
            raise ValueError(f"RecordType {self.name!r}: schema must include 'modify_date'")
