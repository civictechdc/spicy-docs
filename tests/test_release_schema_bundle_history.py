"""Current admission refuses independently sealed historical schema bundles.

The test-only 1.1 bundle is copied exactly from the installed 1.0 directory at
commit 83e2032. Its independently recorded digest is pinned below; production
packages ship only the 2.0 schema family.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rulespec_artifacts import schema_bundle_digest

from spicy_docs.source_native import (
    FORMAT_VERSION,
    RELEASE_SCHEMA_ID,
    RELEASE_SCHEMA_KEY,
    VERIFIER_VERSION,
    SourceNativeReleaseError,
    installed_release_schema_bundle,
    release_schema_bundle,
    verify_source_native_admission,
)
from tests.test_source_native_failure_shape import _admit, _build_release


def test_current_schema_family_has_explicit_version_two_identity() -> None:
    assert FORMAT_VERSION == VERIFIER_VERSION == "2.0"
    assert RELEASE_SCHEMA_ID == "urn:spicy-regs:schema:source-native-release:2.0"
    assert RELEASE_SCHEMA_KEY == "schemas/source-native-release-2.0.json"
    assert installed_release_schema_bundle() == release_schema_bundle()
    receipt = installed_release_schema_bundle()["publication-receipt.schema.json"]
    assert set(receipt["required"]) == set(receipt["properties"])
    assert "byteMeasurements" not in receipt["properties"]


def test_correctly_sealed_historical_schema_bundle_is_refused(tmp_path: Path) -> None:
    bundle = json.loads((Path(__file__).parent / "fixtures/source_native_release_1_1.schemas.json").read_bytes())
    assert schema_bundle_digest(bundle) == "sha256:4c32416532f34a8bb7fbb4009c6324881495b9a6038c61931f8cf05694e1e164"
    release_root, blobs_root = _build_release(tmp_path, published_id="current-record", release_schemas=bundle)

    with pytest.raises(SourceNativeReleaseError, match="schema bundle differs from the current installed bundle"):
        _admit(release_root, blobs_root, verify_source_native_admission)


def test_current_schema_bundle_is_admissible(tmp_path: Path) -> None:
    release_root, blobs_root = _build_release(tmp_path, published_id="current-record")
    _admit(release_root, blobs_root, verify_source_native_admission)
