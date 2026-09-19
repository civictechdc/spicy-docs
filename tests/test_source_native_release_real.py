"""Bounded pinned real-input gate for the Federal Register source profile."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from rulespec_artifacts import LocalMemberSource, Producer

from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
)
from spicy_docs.source_native.profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.sources.federal_register.native import (
    _RENDITION_FIELDS,
    DOCUMENT_FIELDS,
    iter_federal_register_pages,
)
from spicy_docs.sources.federal_register.profile import FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

_SCOPE = {"publishedFrom": "2026-04-13", "publishedThrough": "2026-04-13"}
_IMPLEMENTATION_ID = "pkg:pypi/spicy-regs@0.1.7?checksum=sha256:" + "a" * 64
# Policy 1.3 (commit f3b9137, 2026-09-12) added full_text_xml_url to
# DOCUMENT_FIELDS and the body-xml rendition, landing after the 2026-09-11
# pin above was captured; this opt-in live test was not refreshed with it.
# The 2026-09-19 gate run found the resulting digest mismatch (spicy-docs
# gap E4). Re-fetching this day live on 2026-09-19 confirms it is not
# publisher drift: the record count, first/last sourceRecordId and the
# topics-missing count below are unchanged from the prior pin, and all 93
# records now carry a non-null full_text_xml_url with a matching non-null
# body-xml rendition -- exactly the 93 extra renditions (279 -> 372) and the
# one added field policy 1.3 introduced. Refresh this pin whenever
# DOCUMENT_FIELDS or _RENDITION_FIELDS change; investigate any other
# difference before updating this expectation.
_SOURCE_STATE_DIGEST = "sha256:59321d448bf52c5052a51036dff0a2fd81fde8466204b802029fd158b9104993"
# Non-network canary for the pin above. (FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION,
# DOCUMENT_FIELDS, _RENDITION_FIELDS) are exactly the inputs a live fetch's shape
# depends on, and the September drift (see the comment above _SOURCE_STATE_DIGEST)
# was one of them changing while the live pin, which only an opt-in integration
# run re-derives, sat still. When this digest test fails, one of those three
# inputs changed: refresh _SOURCE_STATE_DIGEST -- and the record/rendition counts
# asserted in the live test below -- by re-running the live test, in the SAME
# change that updates this recorded value.
_ACQUISITION_INPUTS_DIGEST = "sha256:f7530eea93698bef13948b22b7dd4b6b8d0dd5121b175e1b211faf33d9c99c94"


def _acquisition_inputs_digest() -> str:
    payload = {
        "policyVersion": FEDERAL_REGISTER_ACQUISITION_POLICY_VERSION,
        "documentFields": sorted(DOCUMENT_FIELDS),
        "renditionFields": [list(entry) for entry in _RENDITION_FIELDS],
    }
    return "sha256:" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def test_federal_register_acquisition_inputs_are_the_pinned_value() -> None:
    """Costs no network; see the module-level comment above ``_ACQUISITION_INPUTS_DIGEST``."""
    assert _acquisition_inputs_digest() == _ACQUISITION_INPUTS_DIGEST


def _completed_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


@pytest.mark.integration
def test_pinned_federal_register_day_publishes_and_replays_exactly(tmp_path: Path) -> None:
    producer = Producer(
        product="spicy-docs",
        implementation_id=_IMPLEMENTATION_ID,
        verifier_id="urn:spicy-regs:source-native-release-verifier",
        verifier_version="2.0",
        verifier_implementation_id=_IMPLEMENTATION_ID,
    )
    with httpx.Client(
        headers={"User-Agent": "spicy-regs-source-native/1.0 (https://github.com/civictechdc/spicy-regs)"},
        timeout=60.0,
        follow_redirects=True,
    ) as client:

        def fetch(url: str) -> bytes:
            response = client.get(url)
            response.raise_for_status()
            return response.content

        published = SourceNativeReleasePublisher(
            FEDERAL_REGISTER_PROFILE,
            blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
            clock=_completed_at,
        ).publish(
            iter_federal_register_pages(fetch, query_scope=_SCOPE),
            build=SourceNativeReleaseBuild(
                query_scope=_SCOPE,
                producer=producer,
                started_at="2026-08-25T00:00:00Z",
            ),
            destination=tmp_path / "release",
        )

    reader = SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        profile=FEDERAL_REGISTER_PROFILE,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({_IMPLEMENTATION_ID}),
    )
    records = list(reader.iter_records())
    renditions = list(reader.iter_renditions())

    assert reader.source_state_digest == _SOURCE_STATE_DIGEST
    assert len(records) == 93
    assert len(renditions) == 372
    # _SCOPE is one closed day, so every record's publication_date is 2026-04-13.
    assert records[0]["sourceRecordId"] == "2026-07034@2026-04-13"
    assert records[-1]["sourceRecordId"] == "2026-07143@2026-04-13"
    assert sum(not record["record"].get("topics") for record in records) == 84
    # len(renditions) == 372 alone holds even if every locator were null: it is
    # 93 records times 4 rendition kinds regardless of what the locators say.
    # The claim this pin actually makes -- every one of the 93 records carries
    # a non-null full_text_xml_url with a matching non-null body-xml rendition
    # -- needs its own count.
    body_xml_with_locator = sum(
        1 for rendition in renditions if rendition["renditionId"] == "body-xml" and rendition["locator"] is not None
    )
    assert body_xml_with_locator == 93
