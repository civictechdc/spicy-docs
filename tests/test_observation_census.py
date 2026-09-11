"""Fixture coverage for the ``tools/analysis/observation_census.py`` receipt helper."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from rulespec_artifacts import Producer

from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE
from spicy_docs.sources.federal_register.native import FederalRegisterPage, federal_register_documents_url
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tools.analysis.observation_census import LEGACY_NUMBER_PATTERN, MODERN_NUMBER_PATTERN, X_FORM_PATTERN, census

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


def _publish(
    tmp_path: Path, window: dict[str, str], *documents: dict[str, object]
) -> tuple[argparse.Namespace, dict[str, object]]:
    """Publish a two-traversal fixture release for ``documents`` and return its census args
    plus the publication receipt, mirroring the shape every acceptance-fixture publish needs."""
    response = _response(*documents)
    request_key = federal_register_documents_url(window)
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
        build=SourceNativeReleaseBuild(query_scope=window, producer=PRODUCER, started_at="2026-09-02T00:00:00Z"),
        destination=tmp_path / "release",
    )
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    args = _args(
        tmp_path,
        logical_id=published.artifact.pin.logical_id,
        artifact_digest=published.artifact.pin.artifact_digest,
    )
    return args, receipt


def test_census_reports_the_00_111_collision_and_its_winner(tmp_path: Path) -> None:
    """A fixture release carrying the real 00-111 collision -- a 2000-01-14 rule and
    a newer 2000-01-18 notice sharing one document_number -- reports two distinct
    records and zero discards under composite identity (SD-24): neither document
    evicts the other, so there is no multi-observation identity and nothing to
    collapse. The number/date findings below are unaffected -- they key on the
    classified record's own document_number, independent of sourceRecordId's
    shape -- so 00-111 still surfaces as one number reused across two dates, now
    as an informational fact about the source rather than a loss. 00-111 is
    legacy-form (it fails the modern \\d{4}-... pattern), so this release also proves
    the shape of every other collision field's EMPTY case: they are emitted, not omitted."""
    number = "00-111"
    args, receipt = _publish(
        tmp_path,
        WINDOW,
        _document(number, publication_date="2000-01-14", title="Compliance Monitoring"),
        _document(number, publication_date="2000-01-18", title="Notice of Filing of Plat of an Island; Minnesota"),
    )

    result = census(args)

    assert result["profile"] == "federal-register"
    assert result["totals"] == {
        "records": 2,
        "multiObservationIds": 0,
        "discardedObservations": receipt["discardedObservationCount"],
    }
    assert result["multiObservationRecords"] == []
    assert receipt["publishedRecordCount"] == 2
    assert receipt["discardedObservationCount"] == 0

    assert result["numberAndDateUniquelyIdentify"] is True
    assert result["sameNumberDifferentDateCount"] == 1
    assert result["sameNumberSameDateIdenticalDigestCount"] == 0
    assert result["sameNumberSameDateDifferingDigestCount"] == 0
    assert "counted over unnormalized document numbers, no prefix or case folding applied" in cast(
        "str", result["collisionCountingBasis"]
    )
    # 00-111 is legacy-form, so the modern-form and dual-form fields stay empty here.
    assert result["modernFormCollisions"] == []
    assert result["modernFormCollisionCount"] == 0
    assert result["legacyFormAlsoParsesAsModern"] is False
    assert result["legacyFormAlsoParsesAsModernCount"] == 0
    assert result["legacyFormAlsoParsesAsModernExamples"] == []
    letter_collisions = cast("dict[str, object]", result["letterPrefixStripCollisions"])
    assert letter_collisions["totalCount"] == 0
    assert letter_collisions["differingDateCount"] == 0
    assert letter_collisions["sameDateCount"] == 0
    assert letter_collisions["sameDateExamples"] == []
    assert result["xFormDateEncodingMismatches"] == []
    assert result["xFormDateEncodingMismatchCount"] == 0
    coverage = cast("dict[str, object]", result["coverage"])
    assert coverage["queryScope"] == WINDOW
    assert coverage["distinctNumberCount"] == 1
    assert "caveat" in coverage
    assert "eFamilySpilloverNote" in coverage


def test_modern_form_number_collision_is_counted_and_listed(tmp_path: Path) -> None:
    """A modern-form (YYYY-NNNNN) number reused across two dates is a real collision --
    unlike legacy-form 00-111 above -- so it must be counted and listed by name."""
    number = "2015-30555"
    window = {"publishedFrom": "2015-03-01", "publishedThrough": "2015-03-10"}
    args, _receipt = _publish(
        tmp_path,
        window,
        _document(number, publication_date="2015-03-01", title="First filing"),
        _document(number, publication_date="2015-03-10", title="Unrelated later filing"),
    )

    result = census(args)

    assert result["sameNumberDifferentDateCount"] == 1
    assert result["modernFormCollisionCount"] == 1
    [collision] = cast("list[dict[str, object]]", result["modernFormCollisions"])
    assert collision["recordId"] == number
    assert collision["dates"] == ["2015-03-01", "2015-03-10"]


def test_legacy_number_that_also_parses_as_modern_is_detected(tmp_path: Path) -> None:
    """A 4-digit-year, 4-digit-suffix number (2015-1234) fullmatches both the legacy
    and the modern pattern; the census must flag the ambiguity by name."""
    number = "2015-1234"
    window = {"publishedFrom": "2016-05-01", "publishedThrough": "2016-05-01"}
    args, _receipt = _publish(
        tmp_path, window, _document(number, publication_date="2016-05-01", title="Ambiguous-form filing")
    )

    result = census(args)

    assert result["legacyFormAlsoParsesAsModern"] is True
    assert result["legacyFormAlsoParsesAsModernCount"] == 1
    assert result["legacyFormAlsoParsesAsModernExamples"] == [number]
    assert result["legacyPattern"] == LEGACY_NUMBER_PATTERN.pattern
    assert result["modernPattern"] == MODERN_NUMBER_PATTERN.pattern


def test_x_form_date_encoding_mismatch_is_reported(tmp_path: Path) -> None:
    """X94-10503 self-encodes 1994-05-03 (YY-{seq}{MM}{DD}); a record filed under
    that number but a different publication_date is a self-encoding mismatch."""
    number = "X94-10503"
    window = {"publishedFrom": "1994-01-01", "publishedThrough": "1994-01-01"}
    args, _receipt = _publish(
        tmp_path, window, _document(number, publication_date="1994-01-01", title="Mismatched filing")
    )

    result = census(args)

    assert result["xFormDateEncodingMismatchCount"] == 1
    [mismatch] = cast("list[dict[str, object]]", result["xFormDateEncodingMismatches"])
    assert mismatch["recordId"] == number
    assert mismatch["encodedDate"] == "1994-05-03"
    assert mismatch["publicationDates"] == ["1994-01-01"]


def test_x_form_five_digit_tail_matching_date_is_not_reported(tmp_path: Path) -> None:
    """X94-10503's five-digit tail encodes 1994-05-03 (YY-{seq}{MM}{DD}); a record filed
    under that number with a matching publication_date is not a mismatch."""
    number = "X94-10503"
    window = {"publishedFrom": "1994-05-03", "publishedThrough": "1994-05-03"}
    args, _receipt = _publish(
        tmp_path, window, _document(number, publication_date="1994-05-03", title="Matching five-digit filing")
    )

    result = census(args)

    assert result["xFormDateEncodingMismatchCount"] == 0
    assert result["xFormDateEncodingMismatches"] == []


def test_x_form_six_digit_tail_matching_date_is_not_reported(tmp_path: Path) -> None:
    """The old X_FORM_PATTERN fixed the tail at exactly five digits, so it silently
    excluded every six- and seven-digit tail from this census -- 206 of them in the real
    corpus -- rather than reporting them matched or mismatched. X94-101207 is six digits
    (sequence "10", date the last four "1207"); its matching publication_date must be
    reported as a match now that the pattern's width covers it."""
    number = "X94-101207"
    window = {"publishedFrom": "1994-12-07", "publishedThrough": "1994-12-07"}
    args, _receipt = _publish(
        tmp_path, window, _document(number, publication_date="1994-12-07", title="Matching six-digit filing")
    )

    result = census(args)

    assert result["xFormDateEncodingMismatchCount"] == 0
    assert result["xFormDateEncodingMismatches"] == []


def test_x_form_seven_digit_tail_matching_date_is_not_reported(tmp_path: Path) -> None:
    """The widened pattern admits tails up to seven digits; X94-1121207 (sequence "112",
    date the last four "1207") must be recognized and matched too."""
    number = "X94-1121207"
    window = {"publishedFrom": "1994-12-07", "publishedThrough": "1994-12-07"}
    args, _receipt = _publish(
        tmp_path, window, _document(number, publication_date="1994-12-07", title="Matching seven-digit filing")
    )

    result = census(args)

    assert result["xFormDateEncodingMismatchCount"] == 0
    assert result["xFormDateEncodingMismatches"] == []


def test_x_form_six_digit_tail_mismatch_is_reported_right_anchored(tmp_path: Path) -> None:
    """X94-101207's tail must be read right-anchored (sequence "10", date "1207"), not
    left-anchored: left-anchored slicing of this same six-digit tail reads "01" and "20",
    which is exactly this record's (wrong) publication_date below -- so a left-anchored
    reader would call this a match even after the pattern is widened to admit six digits.
    Only the right-anchored fix reports the real mismatch. Also pins that the emitted
    xFormPattern field is the widened pattern actually used, not a stale copy."""
    number = "X94-101207"
    window = {"publishedFrom": "1994-01-20", "publishedThrough": "1994-01-20"}
    args, _receipt = _publish(
        tmp_path, window, _document(number, publication_date="1994-01-20", title="Mismatched six-digit filing")
    )

    result = census(args)

    assert result["xFormDateEncodingMismatchCount"] == 1
    [mismatch] = cast("list[dict[str, object]]", result["xFormDateEncodingMismatches"])
    assert mismatch["recordId"] == number
    assert mismatch["encodedDate"] == "1994-12-07"
    assert mismatch["publicationDates"] == ["1994-01-20"]
    assert result["xFormPattern"] == X_FORM_PATTERN.pattern
