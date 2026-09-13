"""Only the selected profile's current acquisition policy is admissible."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from spicy_docs.source_native import SourceNativeReleaseError, verify_source_native_admission
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.sources.federal_register.native import federal_register_acquisition_policy
from tests.test_source_native_failure_shape import FIXTURE_PROFILE, _admit, _build_release


@pytest.mark.parametrize("declared_version", ["1.0", "1.1", "1.2", "1.3", "99.0"])
def test_only_current_federal_register_policy_version_is_accepted(tmp_path: Path, declared_version: str) -> None:
    # Use an independently sealed minimal source and the real policy identity;
    # this exercises the former Federal Register historical-allowlist branch.
    profile = replace(
        FIXTURE_PROFILE,
        acquisition_policy_id=FEDERAL_REGISTER_PROFILE.acquisition_policy_id,
        acquisition_policy_version=FEDERAL_REGISTER_PROFILE.acquisition_policy_version,
    )
    assert profile.acquisition_policy_version == "1.3"

    def declare_policy(spec: dict[str, Any]) -> None:
        spec["acquisitionPolicyId"] = profile.acquisition_policy_id
        spec["acquisitionPolicyVersion"] = declared_version

    release_root, blobs_root = _build_release(tmp_path, published_id="current-record", mutate_spec=declare_policy)
    if declared_version == "1.3":
        _admit(release_root, blobs_root, verify_source_native_admission, profile=profile)
    else:
        with pytest.raises(SourceNativeReleaseError, match="requires current fixture acquisition policy version"):
            _admit(release_root, blobs_root, verify_source_native_admission, profile=profile)


def test_federal_register_policy_declares_xml_field_and_locator_rules() -> None:
    policy = federal_register_acquisition_policy({"publishedFrom": "2026-08-25", "publishedThrough": "2026-08-25"})
    assert "full_text_xml_url" in policy["documentFields"]
    assert policy["renditionSelection"] == {
        "fields": [
            {"mediaType": "text/html", "renditionId": "body-html", "sourceField": "body_html_url"},
            {"mediaType": "application/xml", "renditionId": "body-xml", "sourceField": "full_text_xml_url"},
            {"mediaType": "text/html", "renditionId": "html", "sourceField": "html_url"},
            {"mediaType": "application/pdf", "renditionId": "pdf", "sourceField": "pdf_url"},
        ],
        "missingLocator": "emit-null",
    }
