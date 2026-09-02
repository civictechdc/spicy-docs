"""Fixture coverage for the ``tools/observation_census.py`` receipt helper."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from rulespec_artifacts import Producer

from spicy_docs.federal_register_source_native import FederalRegisterPage, federal_register_documents_url
from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
from tools.observation_census import census

IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="1.0",
    verifier_implementation_id=IMPLEMENTATION_ID,
)
WINDOW = {"publishedFrom": "2000-01-14", "publishedThrough": "2000-01-18"}


def _document(number: str, *, publication_date: str, title: str) -> dict[str, object]:
    return {
        "agencies": [],
        "body_html_url": None,
        "document_number": number,
        "html_url": f"https://www.federalregister.gov/d/{number}",
        "pdf_url": None,
        "publication_date": publication_date,
        "regulation_id_numbers": [],
        "title": title,
        "topics": [],
        "type": "Rule",
    }


def _response(*documents: dict[str, object]) -> bytes:
    return json.dumps(
        {"count": len(documents), "next_page_url": None, "results": list(documents), "total_pages": 1},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _args(tmp_path: Path, *, logical_id: str, artifact_digest: str) -> argparse.Namespace:
    return argparse.Namespace(
        release=tmp_path / "release",
        blob_store=tmp_path / "blobs",
        logical_id=logical_id,
        artifact_digest=artifact_digest,
        verifier_implementation_id=IMPLEMENTATION_ID,
        profile="federal-register",
    )


def _clock() -> datetime:
    return datetime(2026, 9, 2, 0, 0, 1, tzinfo=UTC)


def test_census_reports_the_00_111_collision_and_its_winner(tmp_path: Path) -> None:
    """A fixture release carrying the real 00-111 collision -- a 2000-01-14 rule and
    a newer 2000-01-18 notice sharing one document_number -- reports one
    multi-observation identity, both raw instants, the newer winner, and the
    discarded-observation count the receipt independently agrees on."""
    number = "00-111"
    response = _response(
        _document(number, publication_date="2000-01-14", title="Compliance Monitoring"),
        _document(number, publication_date="2000-01-18", title="Notice of Filing of Plat of an Island; Minnesota"),
    )
    request_key = federal_register_documents_url(WINDOW)
    pages = [
        FederalRegisterPage(
            traversal_index=traversal,
            page_index=0,
            request_key=request_key,
            source_cursor=None,
            response_bytes=response,
        )
        for traversal in range(2)
    ]
    published = SourceNativeReleasePublisher(
        FEDERAL_REGISTER_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_clock,
    ).publish(
        pages,
        build=SourceNativeReleaseBuild(query_scope=WINDOW, producer=PRODUCER, started_at="2026-09-02T00:00:00Z"),
        destination=tmp_path / "release",
    )
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    args = _args(
        tmp_path,
        logical_id=published.artifact.pin.logical_id,
        artifact_digest=published.artifact.pin.artifact_digest,
    )

    result = census(args)

    assert result["profile"] == "federal-register"
    assert result["totals"] == {
        "records": 1,
        "multiObservationIds": 1,
        "discardedObservations": receipt["discardedObservationCount"],
    }
    [entry] = cast("list[dict[str, object]]", result["multiObservationRecords"])
    assert entry["recordId"] == number
    assert entry["observationCount"] == 2
    assert sorted(cast("list[str]", entry["versions"])) == ["2000-01-14", "2000-01-18"]
    assert entry["winner"] == "2000-01-18"
    assert entry["distinctDigests"] == 2
    assert entry["post2000"] is True
