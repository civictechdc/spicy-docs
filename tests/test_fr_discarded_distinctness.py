"""Check discarded-observation analysis with synthetic Federal Register releases.

Fixtures use real digest-addressed blobs and hand-written manifests/receipts.
The tool reads these directly, bypassing release admission, so fixtures provide
only the consumed fields: member role/blobRef, API results pages, and record JSONL.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from tests.source_fixtures import counted_subsets
from tests.source_native_release_fixtures import evidence_and_records_release
from tools.analysis.fr_discarded_distinctness import census


def _evidence_row(
    document_number: str,
    publication_date: str,
    *,
    type_: str,
    title: str,
    agencies: list[str],
    abstract: str,
) -> dict[str, Any]:
    """Build one evidence row for the given member."""
    return {
        "document_number": document_number,
        "publication_date": publication_date,
        "type": type_,
        "title": title,
        "agencies": agencies,
        "abstract": abstract,
    }


def _record_line(
    document_number: str,
    *,
    publication_date: str,
    type_: str,
    title: str,
    agencies: list[str],
    abstract: str,
) -> dict[str, Any]:
    """Build one published record JSON line."""
    return {
        "sourceRecordId": document_number,
        "record": {
            "publication_date": publication_date,
            "type": type_,
            "title": title,
            "agencies": agencies,
            "abstract": abstract,
        },
    }


def _write_release(
    tmp_path: Path,
    *,
    evidence_rows: list[dict[str, Any]],
    record_lines: list[dict[str, Any]],
    receipt: dict[str, int],
) -> tuple[Path, Path]:
    """Write a synthetic release directory over the given members."""
    return evidence_and_records_release(
        tmp_path, evidence_rows=evidence_rows, record_lines=record_lines, receipt=receipt
    )


def _fixture(tmp_path: Path) -> dict[str, Any]:
    """Cover distinct documents, re-observations, title prefixes, and singletons.

    - FR-2000-DISTINCT: older title differs; distinct-document candidate.
    - FR-2000-REOBS: all four compared fields agree; re-observation.
    - 00-12867: discarded title is the survivor's trimmed prefix; candidate and
      title-prefix hit ("General Counsel" versus "General Counsel; Republication").
    - FR-2000-SINGLE: excluded from the multi-date population.

    The receipt balances inputObservationCount - publishedRecordCount against the
    three discarded observations, so reconciliation.agrees must be True.
    """
    release_root, blob_store = _write_release(
        tmp_path / "happy",
        evidence_rows=[
            _evidence_row(
                "FR-2000-DISTINCT",
                "2000-01-14",
                type_="Rule",
                title="Old Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
            _evidence_row(
                "FR-2000-DISTINCT",
                "2000-01-18",
                type_="Rule",
                title="New Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
            _evidence_row(
                "FR-2000-REOBS",
                "2000-02-01",
                type_="Notice",
                title="Reobs Title",
                agencies=["DOT"],
                abstract="Same abstract",
            ),
            _evidence_row(
                "FR-2000-REOBS",
                "2000-02-05",
                type_="Notice",
                title="Reobs Title",
                agencies=["DOT"],
                abstract="Same abstract",
            ),
            _evidence_row(
                "00-12867",
                "2000-05-23",
                type_="Notice",
                title="Summary of Precedent Opinions of the General Counsel",
                agencies=["DOJ"],
                abstract="Abstract text",
            ),
            _evidence_row(
                "00-12867",
                "2000-05-30",
                type_="Notice",
                title="Summary of Precedent Opinions of the General Counsel; Republication",
                agencies=["DOJ"],
                abstract="Abstract text",
            ),
            _evidence_row(
                "FR-2000-SINGLE",
                "2000-03-01",
                type_="Rule",
                title="Single Observation",
                agencies=["HHS"],
                abstract="Only one date",
            ),
        ],
        record_lines=[
            _record_line(
                "FR-2000-DISTINCT",
                publication_date="2000-01-18",
                type_="Rule",
                title="New Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
            _record_line(
                "FR-2000-REOBS",
                publication_date="2000-02-05",
                type_="Notice",
                title="Reobs Title",
                agencies=["DOT"],
                abstract="Same abstract",
            ),
            _record_line(
                "00-12867",
                publication_date="2000-05-30",
                type_="Notice",
                title="Summary of Precedent Opinions of the General Counsel; Republication",
                agencies=["DOJ"],
                abstract="Abstract text",
            ),
            _record_line(
                "FR-2000-SINGLE",
                publication_date="2000-03-01",
                type_="Rule",
                title="Single Observation",
                agencies=["HHS"],
                abstract="Only one date",
            ),
        ],
        receipt={"inputObservationCount": 7, "publishedRecordCount": 4, "discardedObservationCount": 3},
    )
    return census(release_root, blob_store)


def _mismatched_reconciliation_fixture(tmp_path: Path) -> dict[str, Any]:
    """Same evidence/records as ``_fixture``'s DISTINCT pair, but a receipt whose
    discardedObservationCount cannot equal the enumeration: the scan finds exactly one discarded
    observation, and the receipt claims two."""
    release_root, blob_store = _write_release(
        tmp_path / "mismatched",
        evidence_rows=[
            _evidence_row(
                "FR-2000-DISTINCT",
                "2000-01-14",
                type_="Rule",
                title="Old Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
            _evidence_row(
                "FR-2000-DISTINCT",
                "2000-01-18",
                type_="Rule",
                title="New Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
        ],
        record_lines=[
            _record_line(
                "FR-2000-DISTINCT",
                publication_date="2000-01-18",
                type_="Rule",
                title="New Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
        ],
        # A correct receipt here would be inputObservationCount=2, publishedRecordCount=1,
        # discardedObservationCount=1. Claiming 2 disagrees with the scan's enumeration of 1.
        receipt={"inputObservationCount": 3, "publishedRecordCount": 1, "discardedObservationCount": 2},
    )
    return census(release_root, blob_store)


def test_discarded_observation_differing_on_title_is_a_distinct_document_candidate(tmp_path: Path) -> None:
    """A discarded observation differing on title is a distinct-document candidate with its differing field and
    titles recorded.
    """
    result = _fixture(tmp_path)

    examples = cast("list[dict[str, Any]]", result["examples"])
    distinct = {e["documentNumber"]: e for e in examples}
    assert "FR-2000-DISTINCT" in distinct
    assert distinct["FR-2000-DISTINCT"]["differingFields"] == ["title"]
    assert distinct["FR-2000-DISTINCT"]["discardedTitle"] == "Old Distinct Title"
    assert distinct["FR-2000-DISTINCT"]["survivorTitle"] == "New Distinct Title"
    # discardedThatAreDistinctDocuments: FR-2000-DISTINCT and 00-12867.
    assert result["discardedThatAreDistinctDocuments"] == 2


def test_discarded_observation_identical_on_all_four_fields_is_a_true_reobservation(tmp_path: Path) -> None:
    """An observation identical on all four compared fields is a true re-observation and is not an example."""
    result = _fixture(tmp_path)

    # FR-2000-REOBS is the only pair identical on type/title/agencies/abstract.
    assert result["discardedThatAreTrueReobservations"] == 1
    assert "FR-2000-REOBS" not in {e["documentNumber"] for e in result["examples"]}


def test_reconciliation_gate_disagrees_when_receipt_does_not_match_the_enumeration(tmp_path: Path) -> None:
    """The reconciliation gate agrees on a balanced receipt and disagrees when the receipt cannot equal the
    enumeration.
    """
    happy = _fixture(tmp_path)
    reconciliation = cast("dict[str, Any]", happy["reconciliation"])
    assert reconciliation["agrees"] is True
    assert reconciliation["receiptDiscardedObservationCount"] == reconciliation["scanDiscardedObservations"] == 3

    mismatched = _mismatched_reconciliation_fixture(tmp_path)
    bad_reconciliation = cast("dict[str, Any]", mismatched["reconciliation"])
    assert bad_reconciliation["agrees"] is False
    assert bad_reconciliation["receiptDiscardedObservationCount"] == 2
    assert bad_reconciliation["scanDiscardedObservations"] == 1
    assert "one of the two is wrong" in bad_reconciliation["ifThisDisagrees"]


def test_title_prefix_heuristic_catches_the_republication_variant(tmp_path: Path) -> None:
    """The title-prefix heuristic catches the republication variant and labels itself a heuristic."""
    result = _fixture(tmp_path)

    likely = cast("dict[str, Any]", result["likelyRepublications"])
    assert likely["status"].startswith("HEURISTIC, not an adjudication.")
    assert likely["count"] == 1
    example = likely["examples"][0]
    assert example["documentNumber"] == "00-12867"
    assert example["survivorTitle"].endswith("; Republication")
    assert example["discardedTitle"] == "Summary of Precedent Opinions of the General Counsel"


def test_single_date_number_never_enters_the_multi_date_population(tmp_path: Path) -> None:
    """A number observed on one date never enters the multi-date population."""
    result = _fixture(tmp_path)

    # FR-2000-SINGLE has one observation; DISTINCT, REOBS, and 00-12867 have two each.
    assert result["numbersObservedOnOneDate"] == 1
    assert result["numbersObservedOnMoreThanOneDate"] == 3
    assert result["distinctDocumentNumbersInEvidence"] == 4
    assert "FR-2000-SINGLE" not in {e["documentNumber"] for e in result["examples"]}


def test_every_subset_with_a_count_states_its_population(tmp_path: Path) -> None:
    """Every subset with a count states its population, including the flat top-level count/population pairs."""
    result = _fixture(tmp_path)

    subsets = counted_subsets(result)
    assert len(subsets) >= 1  # likelyRepublications is the one {"count", "population"} subset
    for subset in subsets:
        assert isinstance(subset.get("population"), str) and subset["population"].strip()

    # The report's other counts are flat top-level fields paired with a sibling "<name>Population"
    # (or the report's overall "population") string rather than a nested {"count", "population"}
    # object; check those pairings explicitly since the generic walk above cannot find them.
    assert isinstance(result["population"], str) and result["population"].strip()
    assert isinstance(result["distinctDocumentsPopulation"], str) and result["distinctDocumentsPopulation"].strip()
    assert isinstance(result["trueReobservationsPopulation"], str) and result["trueReobservationsPopulation"].strip()
    assert (
        isinstance(result["differingFieldCountsPopulation"], str) and result["differingFieldCountsPopulation"].strip()
    )
    adjudication_limit = cast("dict[str, Any]", result["adjudicationLimit"])
    assert (
        isinstance(adjudication_limit["capturedFieldsPopulation"], str)
        and adjudication_limit["capturedFieldsPopulation"].strip()
    )


def test_captured_fields_reflect_the_evidence_rows_actually_read(tmp_path: Path) -> None:
    """Captured fields reflect the evidence rows actually read, with correction_of absent because it was never
    requested.
    """
    result = _fixture(tmp_path)

    adjudication_limit = cast("dict[str, Any]", result["adjudicationLimit"])
    assert adjudication_limit["capturedFields"] == sorted(
        {"document_number", "publication_date", "type", "title", "agencies", "abstract"}
    )
    # correction_of was never requested by the acquisition policy captured here.
    assert adjudication_limit["correctionOfCaptured"] is False


def test_population_string_names_the_release_root_and_evidence_member_count(tmp_path: Path) -> None:
    """The population string names the release root and the actual evidence member count."""
    release_root, blob_store = _write_release(
        tmp_path,
        evidence_rows=[
            _evidence_row(
                "FR-2000-DISTINCT",
                "2000-01-14",
                type_="Rule",
                title="Old Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
            _evidence_row(
                "FR-2000-DISTINCT",
                "2000-01-18",
                type_="Rule",
                title="New Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
        ],
        record_lines=[
            _record_line(
                "FR-2000-DISTINCT",
                publication_date="2000-01-18",
                type_="Rule",
                title="New Distinct Title",
                agencies=["EPA"],
                abstract="Old abstract",
            ),
        ],
        receipt={"inputObservationCount": 2, "publishedRecordCount": 1, "discardedObservationCount": 1},
    )
    result = census(release_root, blob_store)

    # This release publishes its one evidence page as a single source-acquisition-evidence
    # member -- the population string must name that count, not a hardcoded one from the
    # original script's own corpus (which had 1,072 members).
    assert "the 1 source-acquisition-evidence members" in result["population"]
    assert str(release_root) in result["population"]
