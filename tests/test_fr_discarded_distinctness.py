"""Fixture coverage for the ``tools/fr_discarded_distinctness.py`` receipt helper (SD-18).

Builds synthetic Federal Register source-native releases the way
``tests/test_cross_filing_census.py`` builds synthetic regulations.gov releases: a real
``LocalSourceNativeBlobStore`` holding digest-addressed blobs, plus a hand-written
``manifests/source-native.json`` and ``receipts/publication.json`` naming them. The tool under
test never goes through ``SourceNativeReleaseReader``/``admit_artifact`` -- it reads the manifest
and receipt directly, exactly as the promoted script did -- so the fixtures only need to satisfy
what the tool itself reads: a member's ``role`` and ``blobRef``, an evidence blob shaped as one
Federal Register API page (``{"results": [...]}``), and a records blob shaped as the release's
JSONL (one ``{"sourceRecordId": ..., "record": {...}}`` per line).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from spicy_docs.source_native import ROLE_EVIDENCE, ROLE_RECORDS
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
from tools.fr_discarded_distinctness import census


def _store(tmp_path: Path) -> LocalSourceNativeBlobStore:
    return LocalSourceNativeBlobStore(tmp_path / "blobs")


def _put_bytes(store: LocalSourceNativeBlobStore, data: bytes) -> str:
    blob_ref = "sha256:" + hashlib.sha256(data).hexdigest()
    store.put_blob(blob_ref, len(data), [data])
    return blob_ref


def _put_json(store: LocalSourceNativeBlobStore, obj: Any) -> str:
    return _put_bytes(store, json.dumps(obj).encode())


def _put_jsonl(store: LocalSourceNativeBlobStore, rows: list[dict[str, Any]]) -> str:
    return _put_bytes(store, ("\n".join(json.dumps(row) for row in rows) + "\n").encode())


def _evidence_row(
    document_number: str,
    publication_date: str,
    *,
    type_: str,
    title: str,
    agencies: list[str],
    abstract: str,
) -> dict[str, Any]:
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


def _member(role: str, blob_ref: str) -> dict[str, str]:
    return {"role": role, "blobRef": blob_ref}


def _write_release(
    tmp_path: Path,
    *,
    evidence_rows: list[dict[str, Any]],
    record_lines: list[dict[str, Any]],
    receipt: dict[str, int],
) -> tuple[Path, Path]:
    store = _store(tmp_path)
    evidence_blob = _put_json(store, {"results": evidence_rows})
    records_blob = _put_jsonl(store, record_lines)

    release_root = tmp_path / "release"
    manifests_dir = release_root / "manifests"
    manifests_dir.mkdir(parents=True)
    (manifests_dir / "source-native.json").write_text(
        json.dumps({"members": [_member(ROLE_EVIDENCE, evidence_blob), _member(ROLE_RECORDS, records_blob)]})
    )
    receipts_dir = release_root / "receipts"
    receipts_dir.mkdir(parents=True)
    (receipts_dir / "publication.json").write_text(json.dumps(receipt))

    return release_root, tmp_path / "blobs"


def _fixture(tmp_path: Path) -> dict[str, Any]:
    """One release covering every scenario this tool reports on.

    FR-2000-DISTINCT: two observations; the discarded (older) one differs from the survivor on
      title -- a distinct-document candidate.
    FR-2000-REOBS: two observations; the discarded one is identical to the survivor on all four
      compared fields -- a true re-observation.
    00-12867: the real historical example from the promoted script's own docstring. The discarded
      title is a trimmed prefix of the survivor's ("...General Counsel" vs "...General Counsel;
      Republication") -- differs (so it is also a distinct-document candidate) and trips the
      title-prefix heuristic.
    FR-2000-SINGLE: one observation only -- must never enter the multi-date population at all.
    The receipt is written to balance exactly (inputObservationCount - publishedRecordCount ==
    discardedObservationCount == the three discarded observations enumerated above), so
    reconciliation.agrees must be True.
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
    result = _fixture(tmp_path)

    # FR-2000-REOBS is the only pair identical on type/title/agencies/abstract.
    assert result["discardedThatAreTrueReobservations"] == 1
    assert "FR-2000-REOBS" not in {e["documentNumber"] for e in result["examples"]}


def test_reconciliation_gate_disagrees_when_receipt_does_not_match_the_enumeration(tmp_path: Path) -> None:
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
    result = _fixture(tmp_path)

    likely = cast("dict[str, Any]", result["likelyRepublications"])
    assert likely["status"].startswith("HEURISTIC, not an adjudication.")
    assert likely["count"] == 1
    example = likely["examples"][0]
    assert example["documentNumber"] == "00-12867"
    assert example["survivorTitle"].endswith("; Republication")
    assert example["discardedTitle"] == "Summary of Precedent Opinions of the General Counsel"


def test_single_date_number_never_enters_the_multi_date_population(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    # FR-2000-SINGLE has one observation; DISTINCT, REOBS, and 00-12867 have two each.
    assert result["numbersObservedOnOneDate"] == 1
    assert result["numbersObservedOnMoreThanOneDate"] == 3
    assert result["distinctDocumentNumbersInEvidence"] == 4
    assert "FR-2000-SINGLE" not in {e["documentNumber"] for e in result["examples"]}


def _walk_subsets_with_counts(node: object) -> list[dict[str, Any]]:
    """Every dict carrying a ``count`` key, found anywhere in the report -- the same walk
    ``tests/test_cross_filing_census.py`` uses to prove no count is reported without a
    population string beside it."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if "count" in node:
            found.append(cast("dict[str, Any]", node))
        for value in node.values():
            found.extend(_walk_subsets_with_counts(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_subsets_with_counts(item))
    return found


def test_every_subset_with_a_count_states_its_population(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    subsets = _walk_subsets_with_counts(result)
    assert len(subsets) >= 1  # likelyRepublications is the one {"count", "population"} subset
    for subset in subsets:
        assert isinstance(subset.get("population"), str) and subset["population"].strip()

    # The report's other counts are flat top-level fields paired with a sibling "<name>Population"
    # (or the report's overall "population") string rather than a nested {"count", "population"}
    # object; check those pairings explicitly since the generic walk above cannot find them.
    assert isinstance(result["population"], str) and result["population"].strip()
    assert isinstance(result["distinctDocumentsPopulation"], str) and result["distinctDocumentsPopulation"].strip()
    assert (
        isinstance(result["trueReobservationsPopulation"], str) and result["trueReobservationsPopulation"].strip()
    )
    assert (
        isinstance(result["differingFieldCountsPopulation"], str)
        and result["differingFieldCountsPopulation"].strip()
    )
    adjudication_limit = cast("dict[str, Any]", result["adjudicationLimit"])
    assert (
        isinstance(adjudication_limit["capturedFieldsPopulation"], str)
        and adjudication_limit["capturedFieldsPopulation"].strip()
    )


def test_captured_fields_reflect_the_evidence_rows_actually_read(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    adjudication_limit = cast("dict[str, Any]", result["adjudicationLimit"])
    assert adjudication_limit["capturedFields"] == sorted(
        {"document_number", "publication_date", "type", "title", "agencies", "abstract"}
    )
    # correction_of was never requested by the acquisition policy captured here.
    assert adjudication_limit["correctionOfCaptured"] is False


def test_population_string_names_the_release_root_and_evidence_member_count(tmp_path: Path) -> None:
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
