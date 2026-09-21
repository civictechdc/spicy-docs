"""Check record additions and changes that release counts alone would hide.

Hand-built fixtures from tests/source_native_release_fixtures keep expected
records independent of the publisher being checked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.source_native_release_fixtures import records_release
from tools.analysis.compare_source_native_releases import compare

IDENTITY = ("document_number", "publication_date")
COMPARE = ("type", "title", "agencies", "abstract")


def _line(
    number: str,
    date: str,
    *,
    type_: str = "Notice",
    title: str = "A title",
    agencies: list[str] | None = None,
    abstract: str = "An abstract",
) -> dict[str, Any]:
    """Build one release line from the given record."""
    return {
        "sourceRecordId": f"{number}@{date}",
        "record": {
            "document_number": number,
            "publication_date": date,
            "type": type_,
            "title": title,
            "agencies": agencies if agencies is not None else ["AGENCY"],
            "abstract": abstract,
        },
    }


def _compare(tmp_path: Path, baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare baseline and candidate line sets under the given options."""
    base_root, blobs = records_release(tmp_path, "baseline", baseline)
    cand_root, _ = records_release(tmp_path, "candidate", candidate)
    return compare(base_root, cand_root, blobs, IDENTITY, COMPARE)


def test_pure_addition_reports_every_baseline_record_intact(tmp_path: Path) -> None:
    """The composite-identity shape: records return, nothing existing moves."""
    baseline = [_line("00-111", "2000-01-18"), _line("00-222", "2000-02-01")]
    candidate = [*baseline, _line("00-111", "2000-01-14", type_="Rule", title="A different rule")]

    result = _compare(tmp_path, baseline, candidate)

    assert result["recordCountDelta"] == 1
    assert result["addedRecordCount"] == 1
    assert result["baselineRecordsMatchedByteForByte"] == 2
    assert result["baselineRecordsChanged"] == 0
    assert result["baselineRecordsMissingFromCandidate"] == 0
    assert result["addedDifferingFromSurvivor"] == 1
    assert result["addedIdenticalToSurvivor"] == 0


def test_a_perturbed_baseline_record_is_reported_even_when_the_count_is_unchanged(tmp_path: Path) -> None:
    """The failure a count comparison cannot see.

    One record rewritten in place and one added leaves the delta at +1, exactly
    as a clean recovery would. Only the per-record digest separates them.
    """
    baseline = [_line("00-111", "2000-01-18", title="Original title"), _line("00-222", "2000-02-01")]
    candidate = [
        _line("00-111", "2000-01-18", title="REWRITTEN title"),
        _line("00-222", "2000-02-01"),
        _line("00-333", "2000-03-01"),
    ]

    result = _compare(tmp_path, baseline, candidate)

    assert result["recordCountDelta"] == 1
    assert result["baselineRecordsChanged"] == 1
    assert result["baselineRecordsChangedExamples"] == [["00-111", "2000-01-18"]]
    assert result["baselineRecordsMatchedByteForByte"] == 1


def test_a_dropped_baseline_record_is_reported_even_when_the_count_is_unchanged(tmp_path: Path) -> None:
    """One record silently lost and one gained also nets to zero."""
    baseline = [_line("00-111", "2000-01-18"), _line("00-222", "2000-02-01")]
    candidate = [_line("00-111", "2000-01-18"), _line("00-999", "2000-09-09")]

    result = _compare(tmp_path, baseline, candidate)

    assert result["recordCountDelta"] == 0
    assert result["baselineRecordsMissingFromCandidate"] == 1
    assert result["addedRecordCount"] == 1


def test_added_record_identical_to_its_survivor_is_split_from_a_differing_one(tmp_path: Path) -> None:
    """68 of the real 483 were identical re-observations; the split must survive."""
    baseline = [_line("00-111", "2000-01-18", title="Same"), _line("00-222", "2000-02-01", title="Other")]
    candidate = [
        *baseline,
        _line("00-111", "2000-01-14", title="Same"),
        _line("00-222", "2000-01-20", title="Genuinely different", type_="Rule"),
    ]

    result = _compare(tmp_path, baseline, candidate)

    assert result["addedIdenticalToSurvivor"] == 1
    assert result["addedDifferingFromSurvivor"] == 1
    assert result["differingFieldCounts"] == {"title": 1, "type": 1}


def test_title_prefix_variant_is_counted_but_still_a_differing_record(tmp_path: Path) -> None:
    """The republication heuristic narrows the residual; it does not reclassify."""
    baseline = [_line("00-111", "2000-01-18", title="A rule about widgets")]
    candidate = [*baseline, _line("00-111", "2000-01-14", title="A rule about widgets; Republication")]

    result = _compare(tmp_path, baseline, candidate)

    assert result["addedDifferingFromSurvivor"] == 1
    assert result["addedTitlePrefixVariants"] == 1
    assert result["addedDifferingResidual"] == 0


def test_a_genuinely_different_title_is_not_a_prefix_variant(tmp_path: Path) -> None:
    """A genuinely different title is not a prefix variant and stays in the residual."""
    baseline = [_line("00-111", "2000-01-18", title="Notice of Filing of Plat of an Island; Minnesota")]
    candidate = [*baseline, _line("00-111", "2000-01-14", title="Compliance Monitoring", type_="Rule")]

    result = _compare(tmp_path, baseline, candidate)

    assert result["addedTitlePrefixVariants"] == 0
    assert result["addedDifferingResidual"] == 1


def test_membership_only_when_no_compare_field_is_given(tmp_path: Path) -> None:
    """Without a compare field the result reports membership only, with no differing counts."""
    baseline = [_line("00-111", "2000-01-18")]
    candidate = [*baseline, _line("00-111", "2000-01-14")]
    base_root, blobs = records_release(tmp_path, "baseline", baseline)
    cand_root, _ = records_release(tmp_path, "candidate", candidate)

    result = compare(base_root, cand_root, blobs, IDENTITY, ())

    assert result["addedRecordCount"] == 1
    assert "addedDifferingFromSurvivor" not in result


def test_an_identity_that_does_not_identify_a_record_is_refused_not_averaged(tmp_path: Path) -> None:
    """Comparing on the wrong identity silently collapses records; refuse instead.

    Keyed on document_number alone, the two 00-111 filings become one entry and
    the tool would report a clean +0 while a real document went unexamined.
    """
    baseline = [_line("00-111", "2000-01-18"), _line("00-111", "2000-01-14")]
    base_root, blobs = records_release(tmp_path, "baseline", baseline)
    cand_root, _ = records_release(tmp_path, "candidate", baseline)

    with pytest.raises(SystemExit, match="identity fields do not identify a record"):
        compare(base_root, cand_root, blobs, ("document_number",), COMPARE)


def test_a_candidate_repeating_an_identity_is_refused(tmp_path: Path) -> None:
    """The candidate's own identity must be unique, or its record count is a lie."""
    baseline = [_line("00-111", "2000-01-18")]
    candidate = [_line("00-111", "2000-01-18"), _line("00-111", "2000-01-18", title="Second")]
    base_root, blobs = records_release(tmp_path, "baseline", baseline)
    cand_root, _ = records_release(tmp_path, "candidate", candidate)

    with pytest.raises(SystemExit, match="identity is not unique in the candidate"):
        compare(base_root, cand_root, blobs, IDENTITY, COMPARE)
