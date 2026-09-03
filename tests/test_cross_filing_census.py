"""Fixture coverage for the ``tools/cross_filing_census.py`` receipt helper (SD-16)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from rulespec_artifacts import Producer

from spicy_docs.regulations_gov_source_native import iter_regulations_gov_document_pages
from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher
from spicy_docs.source_native_profiles import REGULATIONS_GOV_DOCUMENT_PROFILE
from spicy_docs.source_native_store import LocalSourceNativeBlobStore
from tools.cross_filing_census import census

_IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
_PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=_IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="1.0",
    verifier_implementation_id=_IMPLEMENTATION_ID,
)
_WINDOW = {"agencies": ["placeholder"], "publishedFrom": "2020-01-01", "publishedThrough": "2025-12-31"}


@dataclass(frozen=True, slots=True)
class _Object:
    key: str
    etag: str
    version_id: str | None
    content: bytes


class _Reader:
    def __init__(self, objects: list[_Object]) -> None:
        self.objects = objects

    def iter_source_objects(self, *, max_bytes: int) -> list[_Object]:
        return list(self.objects)


def _document(identity: str, *, agency: str, docket_id: str, posted_date: str, **attributes: object) -> dict:
    values: dict[str, object] = {"agencyId": agency, "docketId": docket_id, "postedDate": posted_date}
    values.update(attributes)
    return {"data": {"id": identity, "type": "documents", "attributes": values}}


def _object(document: dict, *, agency: str, docket_id: str) -> _Object:
    identity = document["data"]["id"]
    content = json.dumps(document).encode()
    return _Object(
        key=f"raw-data/{agency}/{docket_id}/text-1/documents/{identity}.json",
        etag=f'"{identity}-etag"',
        version_id=None,
        content=content,
    )


def _clock() -> datetime:
    return datetime(2026, 9, 2, 0, 0, 1, tzinfo=UTC)


def _publish(tmp_path: Path, agency: str, *objects: _Object) -> tuple[str, str]:
    """Publish one agency's regulations-gov-documents release and return its (root, artifactDigest)."""
    window = {**_WINDOW, "agencies": [agency]}
    published = SourceNativeReleasePublisher(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_clock,
    ).publish(
        iter_regulations_gov_document_pages(lambda _agency: _Reader(list(objects)), query_scope=window),
        build=SourceNativeReleaseBuild(query_scope=window, producer=_PRODUCER, started_at="2026-09-02T00:00:00Z"),
        destination=tmp_path / f"regs-documents-{agency}",
    )
    return str(published.root), published.artifact.pin.artifact_digest


def _run_census(tmp_path: Path, releases: list[list[str]]) -> dict[str, Any]:
    releases_path = tmp_path / "releases.json"
    releases_path.write_text(json.dumps(releases))
    return census(releases_path, tmp_path / "blobs")


def _fixture(tmp_path: Path) -> dict[str, Any]:
    """Publish five agencies' worth of documents covering every scenario this census reports on.

    OBJ-A: two EPA documents sharing an objectId, identical content (same-agency, content agrees).
    OBJ-B: DOI's catch-all-docket filing plus BOEM's real docket, same objectId, titles differ
      (cross-agency, single real docket -- a parent/component pairing, not a co-issued rule).
    OBJ-C: EPA and DOT real dockets sharing an objectId, pageCount differs (cross-agency, two real
      dockets from different agencies -- a genuine co-issued rule; also a suspects hit).
    OBJ-D: two EPA documents sharing an objectId, frDocNum both null, pageCount differs (same-agency,
      content disagrees, also a suspects hit with every frDocNum null).
    OBJ-E: two FOO documents with identical content (content agrees, same-agency), but the FOO release
      is listed twice in the input list, so every row -- and every id -- is observed twice (a
      repeated sourceRecordId within the group; also two agency-level repeats).
    A grammar-only EPA document carries no objectId (excluded from every objectId-keyed count) and an
    id with a letters segment between its docket and document sequence numbers.
    """
    epa_root, epa_digest = _publish(
        tmp_path,
        "EPA",
        _object(
            _document(
                "EPA-2020-0001-0001",
                agency="EPA",
                docket_id="EPA-2020-0001",
                posted_date="2020-01-01T00:00:00Z",
                objectId="OBJ-A",
                title="Final Rule On Air",
                pageCount=10,
                frDocNum="2020-10001",
                documentType="Rule",
            ),
            agency="EPA",
            docket_id="EPA-2020-0001",
        ),
        _object(
            _document(
                "EPA-2020-0001-0002",
                agency="EPA",
                docket_id="EPA-2020-0001",
                posted_date="2020-01-01T00:00:00Z",
                objectId="OBJ-A",
                title="Final Rule On Air",
                pageCount=10,
                frDocNum="2020-10001",
                documentType="Rule",
            ),
            agency="EPA",
            docket_id="EPA-2020-0001",
        ),
        _object(
            _document(
                "EPA-2022-0010-0001",
                agency="EPA",
                docket_id="EPA-2022-0010",
                posted_date="2022-01-01T00:00:00Z",
                objectId="OBJ-C",
                title="Joint Notice",
                pageCount=5,
                frDocNum="2022-10001",
                documentType="Notice",
            ),
            agency="EPA",
            docket_id="EPA-2022-0010",
        ),
        _object(
            _document(
                "EPA-2023-0003-0001",
                agency="EPA",
                docket_id="EPA-2023-0003",
                posted_date="2023-01-01T00:00:00Z",
                objectId="OBJ-D",
                title="Undated Filing",
                pageCount=3,
                frDocNum=None,
                documentType="Notice",
            ),
            agency="EPA",
            docket_id="EPA-2023-0003",
        ),
        _object(
            _document(
                "EPA-2023-0003-0002",
                agency="EPA",
                docket_id="EPA-2023-0003",
                posted_date="2023-01-01T00:00:00Z",
                objectId="OBJ-D",
                title="Undated Filing",
                pageCount=4,
                frDocNum=None,
                documentType="Notice",
            ),
            agency="EPA",
            docket_id="EPA-2023-0003",
        ),
        _object(
            _document(
                "EPA-HQ-OW-2025-0322-DRAFT-29781",
                agency="EPA",
                docket_id="EPA-HQ-OW-2025-0322",
                posted_date="2025-01-01T00:00:00Z",
                title="Grammar-only filing",
            ),
            agency="EPA",
            docket_id="EPA-HQ-OW-2025-0322",
        ),
    )
    doi_root, doi_digest = _publish(
        tmp_path,
        "DOI",
        _object(
            _document(
                "DOI-2021-0005-0001",
                agency="DOI",
                docket_id="DOI_FRDOC_0001",
                posted_date="2021-01-01T00:00:00Z",
                objectId="OBJ-B",
                title="Parent Notice",
                pageCount=2,
                frDocNum="2021-10005",
                documentType="Notice",
            ),
            agency="DOI",
            docket_id="DOI_FRDOC_0001",
        ),
    )
    boem_root, boem_digest = _publish(
        tmp_path,
        "BOEM",
        _object(
            _document(
                "BOEM-2021-0007-0001",
                agency="BOEM",
                docket_id="BOEM-2021-0007",
                posted_date="2021-01-01T00:00:00Z",
                objectId="OBJ-B",
                title="Component Notice",
                pageCount=2,
                frDocNum="2021-10005",
                documentType="Notice",
            ),
            agency="BOEM",
            docket_id="BOEM-2021-0007",
        ),
    )
    dot_root, dot_digest = _publish(
        tmp_path,
        "DOT",
        _object(
            _document(
                "DOT-2022-0020-0001",
                agency="DOT",
                docket_id="DOT-2022-0020",
                posted_date="2022-01-01T00:00:00Z",
                objectId="OBJ-C",
                title="Joint Notice",
                pageCount=9,
                frDocNum="2022-10001",
                documentType="Notice",
            ),
            agency="DOT",
            docket_id="DOT-2022-0020",
        ),
    )
    foo_root, foo_digest = _publish(
        tmp_path,
        "FOO",
        _object(
            _document(
                "FOO-2024-0001-0001",
                agency="FOO",
                docket_id="FOO-2024-0001",
                posted_date="2024-01-01T00:00:00Z",
                objectId="OBJ-E",
                title="Repeated Filing One",
                pageCount=1,
                frDocNum="2024-10001",
                documentType="Rule",
            ),
            agency="FOO",
            docket_id="FOO-2024-0001",
        ),
        _object(
            _document(
                "FOO-2024-0001-0002",
                agency="FOO",
                docket_id="FOO-2024-0001",
                posted_date="2024-01-01T00:00:00Z",
                objectId="OBJ-E",
                title="Repeated Filing One",
                pageCount=1,
                frDocNum="2024-10001",
                documentType="Rule",
            ),
            agency="FOO",
            docket_id="FOO-2024-0001",
        ),
    )

    return _run_census(
        tmp_path,
        [
            [epa_root, epa_digest, "regulations-gov-documents"],
            [doi_root, doi_digest, "regulations-gov-documents"],
            [boem_root, boem_digest, "regulations-gov-documents"],
            [dot_root, dot_digest, "regulations-gov-documents"],
            [foo_root, foo_digest, "regulations-gov-documents"],
            [foo_root, foo_digest, "regulations-gov-documents"],  # listed twice on purpose: see OBJ-E
            ["/does/not/exist", "sha256:" + "0" * 64, "regulations-gov-dockets"],  # must be skipped, never opened
        ],
    )


def test_scope_reports_records_not_items_and_the_documents_only_filter(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    scope = cast("dict[str, Any]", result["scope"])
    assert "not built catalog items" in scope["unitOfCount"]
    assert scope["profileConsidered"] == "regulations-gov-documents"
    assert scope["releasesConsidered"] == 6
    assert scope["releasesSkipped"] == 1
    assert "regulations-gov-dockets" in scope["releasesSkippedPopulation"]


def test_totals_count_records_including_the_objectid_less_grammar_document(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    totals = cast("dict[str, Any]", result["totals"])
    # 6 EPA + 1 DOI + 1 BOEM + 1 DOT + (2 FOO x 2 listings) = 13.
    assert totals["documentsScanned"] == 13
    assert totals["distinctObjectIds"] == 5  # OBJ-A..E; the grammar document carries no objectId
    assert totals["documentsInFrdocCatchAllDockets"] == 1  # DOI's row only
    assert "docketId ends with" in totals["documentsInFrdocCatchAllDocketsPopulation"]


def test_duplicate_groups_split_by_repeated_id_and_agency(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    groups = cast("dict[str, Any]", result["duplicateGroups"])
    assert groups["count"] == 5  # OBJ-A, B, C, D, E
    assert groups["withRepeatedSourceRecordId"]["count"] == 1  # OBJ-E only
    assert groups["sameAgency"]["count"] == 3  # OBJ-A, D, E
    assert groups["crossAgency"]["count"] == 2  # OBJ-B, C
    for subset in (groups, groups["withRepeatedSourceRecordId"], groups["sameAgency"], groups["crossAgency"]):
        assert isinstance(subset["population"], str) and subset["population"]


def test_cross_agency_breakdown_separates_co_issued_from_parent_child(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    breakdown = cast("dict[str, Any]", result["crossAgencyBreakdown"])
    assert breakdown["withThreeOrMoreObservationRows"] == 0
    assert breakdown["coIssued"]["count"] == 1  # OBJ-C: real EPA + real DOT dockets
    assert {e["objectId"] for e in breakdown["coIssued"]["examples"]} == {"OBJ-C"}
    assert breakdown["singleRealDocket"]["count"] == 1  # OBJ-B: DOI's row is the catch-all docket
    for subset in (breakdown, breakdown["coIssued"], breakdown["singleRealDocket"]):
        assert isinstance(subset["population"], str) and subset["population"]


def test_content_comparison_agrees_disagrees_and_names_the_differing_fields(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    comparison = cast("dict[str, Any]", result["contentComparison"])
    assert comparison["fieldsCompared"] == ["title", "pageCount", "frDocNum", "documentType", "postedDate"]
    assert comparison["agree"] == 2  # OBJ-A, OBJ-E
    assert comparison["disagree"] == 3  # OBJ-B, OBJ-C, OBJ-D
    breakdown = comparison["disagreeingFieldBreakdown"]
    assert breakdown["counts"] == {
        "title": 1,  # OBJ-B
        "pageCount": 2,  # OBJ-C, OBJ-D
        "frDocNum": 0,
        "documentType": 0,
        "postedDate": 0,
    }
    assert isinstance(breakdown["population"], str) and "contentComparison.disagree" in breakdown["population"]
    assert isinstance(comparison["population"], str) and comparison["population"]


def test_suspects_is_narrower_than_content_disagreement_and_tracks_null_fr_doc_num(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    suspects = cast("dict[str, Any]", result["suspects"])
    # OBJ-B disagrees (title) but not on frDocNum/pageCount, so it must NOT be a suspect.
    assert suspects["count"] == 2  # OBJ-C, OBJ-D
    assert {e["objectId"] for e in suspects["examples"]} == {"OBJ-C", "OBJ-D"}
    assert suspects["allFrDocNumNull"]["count"] == 1  # OBJ-D only
    assert "narrower than contentComparison.disagree" in suspects["population"]
    assert isinstance(suspects["allFrDocNumNull"]["population"], str) and suspects["allFrDocNumNull"]["population"]


def test_id_grammar_finds_the_letters_segment_and_its_agencies(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    grammar = cast("dict[str, Any]", result["idGrammar"])
    assert grammar["matched"] == 1
    assert grammar["distinctSegmentValues"] == 1
    segment = grammar["segments"]["DRAFT"]
    assert segment == {
        "population": "of idGrammar.matched, records whose letters segment is 'DRAFT'",
        "count": 1,
        "agencyCount": 1,
        "agencies": ["EPA"],
        "examples": ["EPA-HQ-OW-2025-0322-DRAFT-29781"],
    }
    assert isinstance(grammar["population"], str) and grammar["population"]


def test_document_id_repeats_within_agency_counts_the_doubly_listed_foo_release(tmp_path: Path) -> None:
    result = _fixture(tmp_path)

    repeats = cast("dict[str, Any]", result["documentIdRepeatsWithinAgency"])
    # The FOO release is listed twice in the input list, so both of its ids repeat within FOO.
    assert repeats["count"] == 2
    assert "same sourceRecordId" in repeats["population"]


def _walk_subsets_with_counts(node: object) -> list[dict[str, Any]]:
    """Every dict carrying a ``count`` key, found anywhere in the report -- used to prove
    the CRITICAL rule: no count is reported without a population string beside it."""
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
    assert len(subsets) >= 10  # duplicateGroups (x4), crossAgencyBreakdown (x2), suspects (x2), and more
    for subset in subsets:
        assert isinstance(subset.get("population"), str) and subset["population"].strip()
