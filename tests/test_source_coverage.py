"""Coverage facts stay bound to requested selectors and admitted source policies."""

from __future__ import annotations

from pathlib import Path

import pytest

from examples.offline_release import PRODUCT_ID, run_example
from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher
from spicy_docs.source_native_profiles import (
    GAO_PRODUCT_PAGE_PROFILE,
    REGULATIONS_GOV_COMMENT_PROFILE,
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.sources.regulations_gov.acquisition import (
    iter_regulations_gov_comment_pages,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import PRODUCER, _completed_at, _reader
from tests.test_regulations_gov_comments_source_native import _Reader


def test_gao_outcome_explains_exact_id_coverage_through_publish_and_verify(tmp_path: Path) -> None:
    result = run_example(tmp_path)
    published, verified = result["publication"], result["verification"]
    assert isinstance(published, dict)
    assert isinstance(verified, dict)
    outcome = published["collectionOutcome"]

    assert outcome == verified["collectionOutcome"]
    assert outcome["requestedScope"] == {"productIds": [PRODUCT_ID]}
    assert outcome["sourceStateScope"] == "complete-snapshot"
    assert outcome["traversalAcceptance"] == "source-enumeration"
    assert outcome["acquisitionPolicyVersion"] == "1.1"
    assert outcome["acquisitionPolicy"] == GAO_PRODUCT_PAGE_PROFILE.acquisition_policy(outcome["requestedScope"])
    assert outcome["acquisitionPolicy"]["strategy"] == "complete-explicit-product-id-enumeration"
    assert outcome["acquisitionPolicy"]["coverageLimits"] == [
        "Only the explicitly requested product IDs are covered; other product IDs are unrequested.",
        "Each requested page is captured separately; no single publisher-wide version is established.",
    ]


@pytest.mark.parametrize(
    ("profile", "acquire", "date_prefix"),
    [
        (REGULATIONS_GOV_DOCUMENT_PROFILE, iter_regulations_gov_document_pages, "published"),
        (REGULATIONS_GOV_DOCKET_PROFILE, iter_regulations_gov_docket_pages, "modified"),
        (REGULATIONS_GOV_COMMENT_PROFILE, iter_regulations_gov_comment_pages, "posted"),
    ],
)
def test_mirrulations_empty_enumeration_preserves_exact_scope_and_listing_limits(
    tmp_path: Path, profile, acquire, date_prefix: str
) -> None:
    scope = {"agencies": ["EPA"], f"{date_prefix}From": "2026-08-25", f"{date_prefix}Through": "2026-08-25"}
    requested = []

    def read(agency):
        requested.append(agency)
        return _Reader([])

    published = SourceNativeReleasePublisher(
        profile,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        acquire(read, query_scope=scope),
        build=SourceNativeReleaseBuild(query_scope=scope, producer=PRODUCER, started_at="2026-08-25T00:00:00Z"),
        destination=tmp_path / "release",
    )
    outcome = _reader(published.root, published.artifact.pin, profile=profile).collection_outcome

    assert requested == ["EPA"]  # Other agencies were never asked, not found empty.
    assert outcome["requestedScope"] == scope
    assert outcome["recordOutcome"] == "empty"
    assert outcome["sourceStateScope"] == "complete-snapshot"
    assert outcome["traversalAcceptance"] == "source-enumeration"
    assert outcome["acquisitionPolicyVersion"] == "1.2"
    assert outcome["acquisitionPolicy"] == profile.acquisition_policy(scope)
    assert outcome["acquisitionPolicyDigest"] == published.artifact.root["spec"]["acquisitionPolicyDigest"]
    assert outcome["acquisitionPolicy"]["dateSelection"] == "after-full-agency-object-acquisition"
    assert outcome["acquisitionPolicy"]["coverageLimits"] == [
        "Membership follows one live listing of the requested agencies and collection, with dates applied afterward.",
        "The built-in transport fetches each listed object with its ETag as an IfMatch precondition.",
        "Individual object pins do not establish one frozen version of the whole listing or publisher.",
    ]
