"""Adopt exact Parquet members through an injected PyIceberg table."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from spicy_docs.public_tables.format import (
    PublicTableError,
)
from spicy_docs.public_tables.reader import (
    PublicTableReader,
)


@runtime_checkable
class IcebergTable(Protocol):
    """The two standard PyIceberg table operations used by the sink."""

    def current_snapshot(self) -> object | None: ...

    def add_files(
        self,
        file_paths: list[str],
        *,
        check_duplicate_files: bool = True,
    ) -> None: ...


class IcebergPublicTableSink:
    """Adopt exact Parquet members as the first snapshot of an injected table."""

    def __init__(self, table: IcebergTable) -> None:
        self._table = table

    def publish(
        self,
        public_table: PublicTableReader,
    ) -> object:
        if self._table.current_snapshot() is not None:
            raise PublicTableError("Iceberg target must be a new empty table for this immutable generation")
        locations = list(public_table.iceberg_member_locations)
        if len(locations) != len(set(locations)) or any(not value for value in locations):
            raise PublicTableError("Iceberg member locations are empty or repeated")
        self._table.add_files(locations, check_duplicate_files=True)
        snapshot = self._table.current_snapshot()
        if snapshot is None:
            raise PublicTableError("Iceberg did not commit a snapshot")
        return snapshot
