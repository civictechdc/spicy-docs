"""Releases: selection behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.federal_register_source_native import (
    federal_register_source_record_id,
)
from spicy_docs.source_native import (
    SourceNativeReleaseError,
)
from tests.releases.fixtures import (
    _collapsing_profile,
    _document,
    _publish,
    _reader,
    _signing_date_version,
    _stable_pages,
)
from tests.source_fixtures import payload_rows


def test_three_observations_of_one_identity_keep_the_newest_and_count_the_discards(
    tmp_path: Path,
) -> None:
    """Selection is a grouped maximum, not a pairwise search: three observations
    of one identity collapse to the newest and count the other two as discarded,
    whatever order the source enumerated them in.

    SD-24: "one identity" for the Federal Register profile is now
    (document_number, publication_date) (composite identity), so all three
    observations share one publication_date here, and signing_date -- a field
    composite identity does not touch -- stands in for the version an
    upstream re-observation would actually vary.
    """
    number = "2026-00001"
    pages = _stable_pages(
        _document(number, signing_date="2026-08-24", title="middle observation"),
        _document(number, signing_date="2026-08-23", title="oldest observation"),
        _document(number, signing_date="2026-08-25", title="newest observation"),
    )
    profile = _collapsing_profile(refuse_equal_observation_versions=True, observation_version=_signing_date_version)

    published = _publish(tmp_path, pages, profile=profile)
    reader = _reader(published.root, published.artifact.pin, profile=profile)

    assert [row["record"]["title"] for row in reader.iter_records()] == ["newest observation"]
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == receipt["inputObservationCount"] - 1
    assert receipt["discardedObservationCount"] == 2
    # Every discarded observation stays in the acquisition evidence.
    accepted = [row for row in payload_rows(published.root, "acquisition-pages") if row["accepted"]]
    discovered = [record for row in accepted for record in row["discoveredRecords"]]
    assert [record["sourceRecordId"] for record in discovered] == [f"{number}@2026-08-25"] * 3
    assert len({record["recordDigest"] for record in discovered}) == 3


def test_a_repeated_version_among_three_observations_refuses_the_tie(tmp_path: Path) -> None:
    """A refused tie is not weakened by a third, newer-looking observation: the
    repeated (identity, normalized instant) pair still fails the publication."""
    number = "2026-00001"
    pages = _stable_pages(
        _document(number, publication_date="2026-08-24", title="tied observation"),
        _document(number, publication_date="2026-08-24", title="other tied observation"),
        _document(number, publication_date="2026-08-25", title="newest observation"),
    )

    with pytest.raises(SourceNativeReleaseError, match="source-version tie"):
        _publish(tmp_path, pages, profile=_collapsing_profile(refuse_equal_observation_versions=True))


def test_reused_document_number_with_different_dates_are_two_distinct_records(
    tmp_path: Path,
) -> None:
    """SD-24 / composite identity: the source reuses document_number across
    unrelated documents -- 00-111 resolves (via the API's own
    /documents/00-111.json) to a 2000-01-18 notice, while the full-history
    crawl also discovers an older 2000-01-14 rule filed under the same
    number -- and identity is now (document_number, publication_date), so
    neither document evicts the other: both are distinct records and both
    survive. This is the specimen the composite-identity decision names."""
    number = "00-111"
    window = {"publishedFrom": "2000-01-14", "publishedThrough": "2000-01-18"}
    pages = _stable_pages(
        _document(
            number,
            publication_date="2000-01-14",
            title="Compliance Monitoring and Enforcement Priorities",
        ),
        _document(
            number,
            publication_date="2000-01-18",
            title="Notice of Filing of Plat of an Island; Minnesota",
        ),
        window=window,
    )

    published = _publish(tmp_path, pages, query_scope=window)
    reader = _reader(published.root, published.artifact.pin)

    records = list(reader.iter_records())
    assert [row["sourceRecordId"] for row in records] == [
        "00-111@2000-01-14",
        "00-111@2000-01-18",
    ]
    assert [row["record"]["title"] for row in records] == [
        "Compliance Monitoring and Enforcement Priorities",
        "Notice of Filing of Plat of an Island; Minnesota",
    ]
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 2
    assert receipt["discardedObservationCount"] == 0
    # Both observations stay in acquisition evidence; neither is discarded now.
    accepted = [row for row in payload_rows(published.root, "acquisition-pages") if row["accepted"]]
    discovered = [record for row in accepted for record in row["discoveredRecords"]]
    assert [record["sourceRecordId"] for record in discovered] == [
        "00-111@2000-01-14",
        "00-111@2000-01-18",
    ]
    assert len({record["recordDigest"] for record in discovered}) == 2


def test_federal_register_source_record_id_is_canonical_and_reversible() -> None:
    """The composite identity's spelling is a public contract (SD-24): the same
    two source-issued fields always produce the same string (canonical), and
    the string can always be split back into exactly those two fields
    (reversible) -- a lossless pairing, not a hash or a digest."""
    record = {"document_number": "00-111", "publication_date": "2000-01-14", "title": "irrelevant"}

    identity = federal_register_source_record_id(record)

    assert identity == "00-111@2000-01-14"
    # Canonical: recomputing from the same two fields is byte-identical.
    assert federal_register_source_record_id(dict(record)) == identity
    # Reversible: document_number can never contain '@' (classify_document
    # enforces _ASCII_ID) and publication_date is canonical ISO text, so the
    # composite has exactly one '@' and splitting on it recovers both fields.
    assert identity.count("@") == 1
    number, published = identity.split("@")
    assert number == record["document_number"]
    assert published == record["publication_date"]


def test_reused_document_number_with_identical_digests_collapses_without_tying(
    tmp_path: Path,
) -> None:
    """A source refetch of the exact same object under one document_number is
    not a tie: two byte-identical objects at one publication_date collapse to
    one published record, and the repeat still counts as a discarded
    observation (raw bytes need not match, only the canonical record digest)."""
    number = "00-222"
    pages = _stable_pages(_document(number), _document(number))

    published = _publish(tmp_path, pages)
    reader = _reader(published.root, published.artifact.pin)

    assert len(list(reader.iter_records())) == 1
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == 1


def test_reused_document_number_with_differing_digests_at_one_date_refuses_the_tie(
    tmp_path: Path,
) -> None:
    """Two different objects sharing one document_number and one
    publication_date are a genuine ambiguity, not a refetch or a window
    overlap: the shipped profile refuses instead of inventing a winner."""
    number = "00-333"
    window = {"publishedFrom": "2000-01-14", "publishedThrough": "2000-01-14"}
    pages = _stable_pages(
        _document(number, publication_date="2000-01-14", title="First filing"),
        _document(number, publication_date="2000-01-14", title="Second filing"),
        window=window,
    )

    with pytest.raises(SourceNativeReleaseError, match="source-version tie"):
        _publish(tmp_path, pages, query_scope=window)
