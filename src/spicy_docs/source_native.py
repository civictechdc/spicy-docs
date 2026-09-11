"""Supported source-native API; implementations live in :mod:`spicy_docs.releases`.

Historical identifiers and public import paths remain stable while the release
operations have separate implementation homes.
"""

# Public constants also support explicit imports outside historical __all__.
# ruff: noqa: F401
from rulespec_artifacts import schema_bundle_digest

from spicy_docs.releases.admission import (
    verify_source_native_admission,
)
from spicy_docs.releases.format import (
    ALWAYS_REQUIRED_ROLES,
    CURRENT_PRODUCER_PRODUCT,
    FAILURE_CLASS_DETERMINISTIC,
    FAILURE_CLASS_TRANSIENT,
    FORMAT,
    FORMAT_VERSION,
    KIND,
    KNOWN_ACQUISITION_POLICY_VERSIONS,
    KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS,
    MANIFEST_KEY,
    MAX_EVIDENCE_BYTES,
    MAX_ROW_BYTES,
    PARTITION_ALGORITHM,
    PARTITION_BUCKET_COUNT,
    PARTITION_KINDS,
    PARTITION_LEDGER,
    PARTITION_PAGES,
    PARTITION_RECORDS,
    PARTITION_RENDITIONS,
    PARTITION_ROLES,
    REASON_RECORD_UNCLASSIFIABLE,
    RECEIPT_KEY,
    RELEASE_SCHEMA_ID,
    RELEASE_SCHEMA_KEY,
    REQUIRED_ROLES,
    ROLE_EVIDENCE,
    ROLE_LEDGER,
    ROLE_RECEIPT,
    ROLE_RECORDS,
    ROLE_RELEASE_SCHEMA,
    ROLE_RENDITIONS,
    ROLE_SCHEMA,
    ROLE_SCOPES,
    SCOPES_KEY,
    SPEC_FIELDS,
    SUPPORTED_PRODUCER_PRODUCTS,
    VERIFIER_ID,
    VERIFIER_VERSION,
    PublishedSourceNativeRelease,
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    installed_release_schema_bundle,
    release_schema_bundle,
)
from spicy_docs.releases.publish import (
    SourceNativeReleasePublisher,
)
from spicy_docs.releases.reader import (
    SourceNativeReleaseReader,
)
from spicy_docs.releases.verify import (
    verify_source_native_release,
)

__all__ = [
    "KIND",
    "PublishedSourceNativeRelease",
    "SourceNativeReleaseBuild",
    "SourceNativeReleaseError",
    "SourceNativeReleasePublisher",
    "SourceNativeReleaseReader",
    "installed_release_schema_bundle",
    "release_schema_bundle",
    "verify_source_native_admission",
    "verify_source_native_release",
]
