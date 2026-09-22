"""Footer-only Parquet facts: column names and row count without a data scan.

A reader that needs a partition's row count or column names before deciding
whether to materialize it pays only the footer read here, never a row-group
scan. Use this wherever a count gates a read; do not re-derive counts from a
full scan afterwards.
"""

from __future__ import annotations

from io import BytesIO


def parquet_footer(content: bytes) -> tuple[tuple[str, ...], int]:
    """One pinned file's ``(column_names, row_count)`` from its footer alone.

    ``pyarrow`` is imported here, not at module scope, so importing this module
    needs no parquet dependency until a caller actually reads a footer.
    """
    from pyarrow.parquet import ParquetFile

    metadata = ParquetFile(BytesIO(content)).metadata
    return tuple(metadata.schema.names), metadata.num_rows
