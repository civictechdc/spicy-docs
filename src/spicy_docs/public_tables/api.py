"""Public-table entry points collected for callers that need the full table API.

Public-table operations require the optional PyArrow dependency. Source-native
commands import this API only when a table operation is requested.
"""

# Public constants also support explicit imports outside historical __all__.
# ruff: noqa: F401
from spicy_docs.public_tables.format import (
    DEFAULT_MAX_BATCH_BYTES,
    DEFAULT_MAX_ROWS_PER_BATCH,
    DEFAULT_MAX_ROWS_PER_MEMBER,
    FORMAT_VERSION,
    INPUT_ROLE,
    KIND,
    MANIFEST_KEY,
    MEMBER_ROLE,
    PARQUET_COMPRESSION,
    PARQUET_FORMAT_VERSION,
    PARQUET_MEDIA_TYPE,
    VERIFIER_ID,
    VERIFIER_VERSION,
    PublicTableBuild,
    PublicTableError,
    PublishedPublicTable,
    SourceNativeTableInput,
)
from spicy_docs.public_tables.iceberg import (
    IcebergPublicTableSink,
    IcebergTable,
)
from spicy_docs.public_tables.publish import (
    PublicTablePublisher,
)
from spicy_docs.public_tables.reader import (
    PublicTableArtifactLocation,
    PublicTableReader,
)
from spicy_docs.public_tables.verify import (
    verify_public_table_admission,
    verify_public_table_release,
)

__all__ = [
    "FORMAT_VERSION",
    "KIND",
    "VERIFIER_ID",
    "VERIFIER_VERSION",
    "IcebergPublicTableSink",
    "IcebergTable",
    "PublicTableArtifactLocation",
    "PublicTableBuild",
    "PublicTableError",
    "PublicTablePublisher",
    "PublicTableReader",
    "PublishedPublicTable",
    "SourceNativeTableInput",
    "verify_public_table_admission",
    "verify_public_table_release",
]
