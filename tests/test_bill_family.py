"""One bill through the family builder: the rows it produces and the refusals it files.

The three model seams (section classifier, version summarizer, diff summarizer)
are stubbed rather than mocked at a client, so runs stay hermetic and never
reach a model; passing none of them is the keyless CI path. The capture helpers
are shared with ``test_table_contracts.py`` and ``test_activity_events.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from spicy_docs.extraction.model import ExtractionError
from spicy_docs.interpretation.bill_family import (
    BillFamilyCapture,
    BillFamilyTables,
    BillVersionCapture,
    EngineStamp,
    build_bill_family,
    classification_vocabulary_hash,
    installed_engine_stamp,
    section_reference,
)
from spicy_docs.interpretation.bill_summaries import (
    BillSummaryResult,
    BillVersionText,
    DiffItemText,
    DiffSummaryResult,
)
from spicy_docs.interpretation.model_call import ModelCallError
from spicy_docs.interpretation.section_classification import (
    PROMPT_VERSION as CLASSIFY_PROMPT_VERSION,
)
from spicy_docs.interpretation.section_classification import (
    ClassifiableSection,
    SectionClassification,
)
from spicy_docs.schemas import BILL_SECTIONS, BILL_VERSIONS, TABLE_CONTRACTS
from spicy_docs.schemas.bill_diff_tables import CONSECUTIVE_PAIR_RULE
from spicy_docs.sources.congress.bill_status import BillIdentity, BillTextVersion, parse_bill_status
from spicy_docs.sources.congress.bill_tree import engine_available, parse_bill_tree
from spicy_docs.sources.congress.bill_versions import version_slug
from spicy_docs.transport.captured import CapturedBodyResponse
from spicy_docs.transport.credentials import CredentialRefusedError

FIXTURES = Path(__file__).parent / "fixtures"
CAPTURED = FIXTURES / "govinfo_bills"
CONSTRUCTED = FIXTURES / "congress_bill_tree"

NOW = datetime(2026, 9, 19, tzinfo=UTC)
OBSERVED_AT = "2026-09-19T00:00:00Z"
#: A stamp with a literal revision, for the cases that never reach the engine.
TEST_ENGINE = EngineStamp(name="deltatrack", version="0.1.0", revision="0" * 40)

HR6028 = BillIdentity(119, "hr", 6028)
HR983 = BillIdentity(119, "hr", 983)


def test_bill_row_counts_the_native_cosponsor_list() -> None:
    """cosponsor_count is the literal count, ``"0"`` for an empty list and NULL for an absent one."""
    status = parse_bill_status(
        (CAPTURED / "status-118hr1-cosponsors.xml").read_bytes(), identity=BillIdentity(118, "hr", 1)
    )
    capture = BillFamilyCapture(status=status, versions=(), observed_at=OBSERVED_AT)
    assert family(capture).bills[0]["cosponsor_count"] == "49"
    assert family(replace(capture, status=replace(status, cosponsors=()))).bills[0]["cosponsor_count"] == "0"
    assert family(replace(capture, status=replace(status, cosponsors=None))).bills[0]["cosponsor_count"] is None


needs_engine = pytest.mark.skipif(
    not engine_available(), reason="needs the 'bill-diff' extra: uv sync --extra bill-diff"
)


def clock() -> datetime:
    """The fixed observation instant every test builds against."""
    return NOW


def status_for(name: str, identity: BillIdentity) -> Any:
    """Parse a captured BILLSTATUS fixture under the given identity."""
    return parse_bill_status((CAPTURED / name).read_bytes(), identity=identity)


def capture_of(path: Path, *, content_type: str = "application/xml") -> CapturedBodyResponse:
    """A capture of exactly these bytes, at a URL that cannot be mistaken for a publisher's."""
    return CapturedBodyResponse(
        requested_url=f"https://fixture.invalid/{path.name}",
        resolved_url=f"https://fixture.invalid/{path.name}",
        status_code=200,
        content_type=content_type,
        observed_at=OBSERVED_AT,
        body=path.read_bytes(),
    )


def printing(
    path: Path,
    *,
    version: BillTextVersion,
    version_code: str,
    source: str = "govinfo",
    parse: bool = True,
) -> BillVersionCapture:
    """One acquired printing of ``version``, whose body is exactly ``path``'s bytes.

    ``chosen_format`` is the version's single offered link, because that link is
    the XML rendition these fixtures were captured from -- a statement about the
    fixture, checkable by reading it, not a guess at which format was preferred.
    """
    return BillVersionCapture(
        version=version,
        version_code=version_code,
        source=source,
        package_id=version.package_id,
        chosen_format=version.formats[0] if version.formats else None,
        body=capture_of(path),
        document=parse_bill_tree(path.read_bytes(), version=version_code) if parse else None,
    )


def constructed_version(version_type: str, date: str) -> BillTextVersion:
    """A version record for a constructed document, which no publisher offers a link for."""
    return BillTextVersion(type=version_type, date=date, formats=(), package_id=None)


def captured_pair_capture() -> BillFamilyCapture:
    """H.R. 6028 with both of its captured printings: a real consecutive pair."""
    status = status_for("status-119hr6028.xml", HR6028)
    by_package = {version.package_id: version for version in status.text_versions}
    return BillFamilyCapture(
        status=status,
        versions=(
            printing(
                CAPTURED / "text-119hr6028ih.xml",
                version=by_package["BILLS-119hr6028ih"],
                version_code="introduced-in-house",
            ),
            printing(
                CAPTURED / "text-119hr6028eh.xml",
                version=by_package["BILLS-119hr6028eh"],
                version_code="engrossed-in-house",
            ),
        ),
        observed_at=OBSERVED_AT,
    )


def native_capture(identity: BillIdentity, bodies: dict[str, str]) -> BillFamilyCapture:
    """A native BILLSTATUS with the named printings' native XML, keyed by version slug; other printings are absent."""
    status = status_for(f"status-{identity.congress}{identity.bill_type}{identity.number}.xml", identity)
    return BillFamilyCapture(
        status=status,
        versions=tuple(
            printing(CAPTURED / bodies[slug], version=version, version_code=slug)
            for version in status.text_versions
            if (slug := version_slug(version.type)) in bodies
        ),
        observed_at=OBSERVED_AT,
    )


HR983_BODIES = {
    "introduced-in-house": "text-119hr983ih.xml",
    "engrossed-in-house": "text-119hr983eh.xml",
    "rfs": "text-119hr983rfs.xml",
    "enrolled-bill": "text-119hr983enr.xml",
    "public-law": "text-119hr983enr.xml",
}


def three_printing_capture() -> BillFamilyCapture:
    """One bill with three printings, so "consecutive pairs only" is a testable claim.

    The three documents are the constructed division fixtures, which are the only
    files in this repository that differ from each other in an amount, an added
    section and a move. They establish what the builder does with three
    printings; they establish nothing about what GPO publishes.
    """
    return BillFamilyCapture(
        status=status_for("status-119hr6028.xml", HR6028),
        versions=(
            printing(
                CONSTRUCTED / "constructed-bill-divisions.xml",
                version=constructed_version("Introduced in House", "2025-11-12T05:00:00Z"),
                version_code="introduced-in-house",
            ),
            printing(
                CONSTRUCTED / "constructed-bill-divisions-engrossed.xml",
                version=constructed_version("Engrossed in House", "2026-06-08T04:00:00Z"),
                version_code="engrossed-in-house",
            ),
            printing(
                CONSTRUCTED / "constructed-bill-divisions-reported.xml",
                version=constructed_version("Reported in House", "2026-07-01T04:00:00Z"),
                version_code="reported-in-house",
            ),
        ),
        observed_at=OBSERVED_AT,
    )


@dataclass(frozen=True, slots=True)
class StubClassifier:
    """Label every section the builder offers, with fixed, checkable provenance."""

    label: str = "directive"

    def __call__(self, sections: list[ClassifiableSection]) -> tuple[SectionClassification, ...]:
        return tuple(
            SectionClassification(
                section_id=section.section_id,
                label=self.label,
                confidence=0.9,
                model="stub-model",
                prompt_version=CLASSIFY_PROMPT_VERSION,
                prompt_hash="sha256:" + "0" * 64,
                batch_index=0,
                requested_at="2026-09-19T00:00:00+00:00",
                completed_at="2026-09-19T00:00:01+00:00",
            )
            for section in sections
        )


@dataclass(frozen=True, slots=True)
class StubSummarizer:
    """Answer every version, or decline the ones whose codes are named."""

    declines: frozenset[str] = frozenset()
    content_hash: str = "sha256:" + "1" * 64

    def __call__(self, version: BillVersionText) -> BillSummaryResult | None:
        if version.version_id in self.declines:
            return None
        return BillSummaryResult(
            identity=version.identity,
            version_id=version.version_id,
            summary="A plain-language paragraph long enough to satisfy the reader this stub stands in for.",
            audience="People who read appropriations bills",
            top_provisions=("First provision", "Second provision"),
            model="stub-model",
            prompt_version="v1",
            content_hash=self.content_hash,
            input_tokens=100,
            output_tokens=50,
            requested_at="2026-09-19T00:00:00+00:00",
            completed_at="2026-09-19T00:00:02+00:00",
        )


class StubDiffSummarizer:
    """Answer any pair whose diff carries a changed item, the way the real one does.

    Keeps its own call log, so a test can assert what the generator was handed
    as well as what came back.
    """

    content_hash = "sha256:" + "2" * 64

    def __init__(self) -> None:
        self.seen: list[tuple[str, str, tuple[DiffItemText, ...]]] = []

    def __call__(
        self,
        identity: BillIdentity,
        *,
        from_version_id: str,
        to_version_id: str,
        items: tuple[DiffItemText, ...],
    ) -> DiffSummaryResult | None:
        self.seen.append((from_version_id, to_version_id, tuple(items)))
        if all(item.op == "unchanged" for item in items):
            return None
        return DiffSummaryResult(
            identity=identity,
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            headline="One section's funding changed.",
            key_changes=("A section's amount rose",),
            sections_added=("Energy resilience",),
            sections_removed=("Leases",),
            dollar_changes=("Authorized construction rose by $750,000",),
            model="stub-model",
            prompt_version="v1",
            content_hash=self.content_hash,
            input_tokens=200,
            output_tokens=80,
            requested_at="2026-09-19T00:00:00+00:00",
            completed_at="2026-09-19T00:00:03+00:00",
        )


def family(
    capture: BillFamilyCapture | None = None,
    *,
    classify: Any = None,
    summarize: Any = None,
    summarize_diff: Any = None,
    engine: EngineStamp | None = None,
    **arguments: Any,
) -> BillFamilyTables:
    """Build the default modelled-or-pair capture with TEST_ENGINE and the fixed clock."""
    return build_bill_family(
        capture if capture is not None else captured_pair_capture(),
        engine=engine if engine is not None else TEST_ENGINE,
        classify=classify,
        summarize=summarize,
        summarize_diff=summarize_diff,
        clock=clock,
        **arguments,
    )


def modelled_family() -> BillFamilyTables:
    """The pair capture with all three seams stubbed; shared with the contract tests."""
    return family(
        classify=StubClassifier(),
        summarize=StubSummarizer(),
        summarize_diff=StubDiffSummarizer(),
    )


ROW_TABLES = tuple(field for field in BillFamilyTables.__dataclass_fields__ if field != "refusals")


@needs_engine
def test_one_pass_fills_every_family_table_and_every_row_passes_its_contract() -> None:
    """One pass fills nine tables (financial_changes and diff_summaries stay empty for these fixtures), each row
    passing contract checks, column order and key.
    """
    tables = modelled_family()
    produced = {name: getattr(tables, name) for name in ROW_TABLES}
    # Two tables are empty here on purpose. financial_changes needs
    # pair_amounts and a changed figure, and the two captured printings of
    # H.R. 6028 state no dollar figures at all; diff_summaries needs a changed
    # section, and the reduced fixtures differ in nothing the engine settles.
    assert {name for name, rows in produced.items() if rows} == {
        "bills",
        "bill_actions",
        "bill_publisher_summaries",
        "bill_versions",
        "bill_sections",
        "section_diffs",
        "section_diff_items",
        "section_classifications",
        "bill_summaries",
    }
    for name, rows in produced.items():
        contract = TABLE_CONTRACTS["congress_bills" if name == "bills" else name]
        for row in rows:
            assert contract.checked(row) is row
            assert tuple(row) == contract.columns
            assert contract.key(row)


@needs_engine
def test_a_changed_pair_produces_one_diff_summary_row_per_compared_pair() -> None:
    """Each changed consecutive pair yields one diff summary keyed by from/to version codes; the generator reads
    engine records with no from_heading.
    """
    generator = StubDiffSummarizer()
    tables = family(three_printing_capture(), summarize_diff=generator)
    assert [(row["from_version_code"], row["to_version_code"]) for row in tables.diff_summaries] == [
        ("introduced-in-house", "engrossed-in-house"),
        ("engrossed-in-house", "reported-in-house"),
    ]
    assert {row["from_source"] for row in tables.diff_summaries} == {"govinfo"}
    for row in tables.diff_summaries:
        assert TABLE_CONTRACTS["diff_summaries"].checked(row) is row
    # The generator reads the engine's own records, not this pass's rows: the
    # adapter composes one heading, which reaches the later side.
    assert [pair[:2] for pair in generator.seen] == [
        ("introduced-in-house", "engrossed-in-house"),
        ("engrossed-in-house", "reported-in-house"),
    ]
    assert all(item.from_heading is None for _, _, items in generator.seen for item in items)


@needs_engine
def test_a_diff_the_generator_declines_is_a_refusal_not_a_gap() -> None:
    """A declined diff is filed as a diff_summaries refusal with its five-part identity and unchanged reason."""
    tables = family(summarize_diff=StubDiffSummarizer())
    assert tables.diff_summaries == ()
    declined = [refusal for refusal in tables.refusals if refusal.table == "diff_summaries"]
    assert [refusal.identity for refusal in declined] == [
        ("119-hr-6028", "introduced-in-house", "govinfo", "engrossed-in-house", "govinfo")
    ]
    assert "every settled correspondence is unchanged" in declined[0].reason


@needs_engine
def test_every_section_names_a_version_row_that_exists() -> None:
    """Every bill_sections row names a (bill, version_code, source) that exists among the bill_versions keys."""
    tables = modelled_family()
    parents = {BILL_VERSIONS.key(row) for row in tables.bill_versions}
    for row in tables.bill_sections:
        assert (row["bill_id"], row["version_code"], row["source"]) in parents


@needs_engine
def test_only_consecutive_pairs_are_diffed() -> None:
    """Three printings diff only their date-consecutive pairs, all marked with the pairing rule and xml-xml."""
    tables = family(three_printing_capture())
    pairs = [(row["from_version_code"], row["to_version_code"]) for row in tables.section_diffs]
    assert pairs == [
        ("introduced-in-house", "engrossed-in-house"),
        ("engrossed-in-house", "reported-in-house"),
    ]
    assert all(row["pair_rule"] == CONSECUTIVE_PAIR_RULE for row in tables.section_diffs)
    assert all(row["pair_type"] == "xml-xml" for row in tables.section_diffs)


@needs_engine
def test_a_dateless_enrolled_printing_is_compared_from_the_printing_before_it() -> None:
    """119 HR 983: BILLSTATUS dates every printing but the enrolled one, which once sorted first."""
    tables = family(native_capture(HR983, HR983_BODIES))
    assert [(row["from_version_code"], row["to_version_code"]) for row in tables.section_diffs] == [
        ("introduced-in-house", "engrossed-in-house"),
        ("engrossed-in-house", "rfs"),
        ("rfs", "enrolled-bill"),
        ("enrolled-bill", "public-law"),
    ]
    assert {row["pair_rule"] for row in tables.section_diffs} == {CONSECUTIVE_PAIR_RULE}
    assert [row for row in tables.refusals if row.table == "section_diffs"] == []


@needs_engine
def test_a_pair_no_date_or_stage_orders_is_refused_by_name() -> None:
    capture = native_capture(HR983, HR983_BODIES)
    undated = tuple(
        replace(entry, version=replace(entry.version, date="")) if entry.version_code == "rfs" else entry
        for entry in capture.versions
    )
    tables = family(replace(capture, versions=undated))
    assert ("rfs", "introduced-in-house") not in {
        (row["from_version_code"], row["to_version_code"]) for row in tables.section_diffs
    }
    (refusal,) = [row for row in tables.refusals if row.table == "section_diffs"]
    assert refusal.identity == ("119-hr-983", "rfs", "govinfo", "introduced-in-house", "govinfo")
    assert "not established" in refusal.reason


@needs_engine
def test_a_pdf_twin_resolves_through_both_halves_of_its_reference() -> None:
    """A twin reference needs both the code and the source, or the pair reads as pdf-xml instead of pdf-pdf; the XML
    side here is sourced ``congress``, which a hardcoded ``govinfo`` would miss.
    """
    pair = captured_pair_capture()
    xml_side = replace(pair.versions[0], source="congress")
    twin = replace(
        pair.versions[1],
        version_code=xml_side.version_code,
        source="govinfo-pdf",
        document=None,
        equivalent_xml_version_code=xml_side.version_code,
        equivalent_xml_source="congress",
    )
    rows = family(replace(pair, versions=(xml_side, twin))).bill_versions
    assert [row["equivalent_xml_source"] for row in rows] == [None, "congress"]

    from spicy_docs.interpretation.section_diff import VersionRef, pair_type

    refs = [
        VersionRef(
            version_id=entry.reference_id,
            source=entry.source,
            equivalent_xml_version_id=entry.equivalent_xml_reference_id,
        )
        for entry in (xml_side, twin)
    ]
    assert pair_type(xml_side.reference_id, twin.reference_id, refs) == "pdf-pdf"

    # Drop the source half and the same pair reads as pdf-xml again.
    half = replace(twin, equivalent_xml_source=None)
    blind = [refs[0], replace(refs[1], equivalent_xml_version_id=half.equivalent_xml_reference_id)]
    assert half.equivalent_xml_reference_id is None
    assert pair_type(xml_side.reference_id, half.reference_id, blind) == "pdf-xml"


@needs_engine
def test_financial_rows_appear_only_when_the_caller_asks_for_the_pairing() -> None:
    """financial_changes stays empty unless pair_amounts is requested, then each word_alignment row sits under a
    section_diff_items row from the same pass.
    """
    capture = replace(three_printing_capture(), versions=three_printing_capture().versions[:2])
    assert family(capture).financial_changes == ()
    paired = family(capture, pair_amounts=True).financial_changes
    assert paired
    assert {row["pairing_claim"] for row in paired} == {"word_alignment"}
    # Every pairing sits under a section_diff_items row this same pass produced.
    items = {
        (
            row["bill_id"],
            row["from_version_code"],
            row["from_source"],
            row["to_version_code"],
            row["to_source"],
            row["seq"],
        )
        for row in family(capture, pair_amounts=True).section_diff_items
    }
    for row in paired:
        key = (
            row["bill_id"],
            row["from_version_code"],
            row["from_source"],
            row["to_version_code"],
            row["to_source"],
            row["seq"],
        )
        assert key in items


@needs_engine
def test_no_model_seam_means_no_model_rows_and_no_refusal() -> None:
    """With no model seams the model-backed tables are empty and no refusal is filed."""
    tables = family()
    assert tables.section_classifications == ()
    assert tables.bill_summaries == ()
    assert tables.diff_summaries == ()
    assert tables.refusals == ()


@needs_engine
def test_a_printing_with_no_parsed_document_is_a_named_refusal_not_a_gap() -> None:
    """An unparsed printing still gets a version row with NULL section_count, while its sections and diff refuse by
    table and identity.
    """
    capture = captured_pair_capture()
    unread = replace(capture.versions[1], document=None)
    tables = family(replace(capture, versions=(capture.versions[0], unread)))

    # The version row still exists: the bytes were fetched and are described.
    assert len(tables.bill_versions) == 2
    assert [row["section_count"] for row in tables.bill_versions] == ["3", None]
    # Its sections and its diff are refusals naming the table and the identity.
    refusals = {(refusal.table, refusal.identity) for refusal in tables.refusals}
    assert ("bill_sections", ("119-hr-6028", "engrossed-in-house", "govinfo")) in refusals
    assert (
        "section_diffs",
        ("119-hr-6028", "introduced-in-house", "govinfo", "engrossed-in-house", "govinfo"),
    ) in refusals
    assert tables.section_diffs == ()
    assert all(refusal.reason for refusal in tables.refusals)


@needs_engine
def test_a_declined_summary_is_a_refusal_rather_than_a_silently_missing_row() -> None:
    """A declined version summary is filed as a refusal naming the version, not omitted."""
    tables = family(
        classify=None,
        summarize=StubSummarizer(declines=frozenset({"introduced-in-house"})),
    )
    assert [row["version_code"] for row in tables.bill_summaries] == ["engrossed-in-house"]
    declined = [refusal for refusal in tables.refusals if refusal.table == "bill_summaries"]
    assert [refusal.identity for refusal in declined] == [("119-hr-6028", "introduced-in-house", "govinfo")]


# --- an answer the model's own reader refused (2026-09-20) ---
#
# Found by spicy-regs adopting 0.21.3: `ModelCallError` escaped
# `build_bill_family` and aborted the whole rollup, and catching it outside
# left the family filing a *declined* refusal -- "its text is below the
# minimum" -- for an answer that was refused, which is false about the
# printing.

REFUSAL = "summary answer is missing audience, topThreeProvisions"


def refusing(error: Exception):
    """A model seam that raises instead of answering, whatever it is handed."""

    def call(*arguments: Any, **keywords: Any):
        raise error

    return call


@needs_engine
@pytest.mark.parametrize(
    "seam,table,identity",
    [
        ("summarize", "bill_summaries", ("119-hr-6028", "introduced-in-house", "govinfo")),
        ("classify", "section_classifications", ("119-hr-6028", "introduced-in-house", "govinfo")),
    ],
    ids=["summary", "classification"],
)
def test_an_answer_the_reader_refused_is_a_named_refusal_and_the_pass_finishes(seam, table, identity) -> None:
    """A ModelCallError from the summary or classification seam is a named refusal carrying only its message (never
    the answer details), and the bill still builds.
    """
    tables = family(**{seam: refusing(ModelCallError(REFUSAL, details={"summary": "model prose"}))})

    # The bill is still built: twelve tables do not depend on one answer.
    assert [row["bill_id"] for row in tables.bills] == ["119-hr-6028"]
    assert len(tables.bill_versions) == 2
    assert getattr(tables, table) == ()
    refusals = [refusal for refusal in tables.refusals if refusal.table == table]
    assert identity in [refusal.identity for refusal in refusals]
    # The model's own reason, and *only* the message: `details` is the answer
    # itself, which is model prose about the document.
    assert all(REFUSAL in refusal.reason for refusal in refusals)
    assert all("model prose" not in refusal.reason for refusal in refusals)


@needs_engine
def test_a_refused_diff_summary_is_a_named_refusal_and_the_pass_finishes() -> None:
    """A refused diff summary is a named refusal while the diff itself and the rest of the pass continue."""
    tables = family(three_printing_capture(), summarize_diff=refusing(ModelCallError("diff summary answer is missing")))
    assert tables.diff_summaries == ()
    refusals = [refusal for refusal in tables.refusals if refusal.table == "diff_summaries"]
    assert refusals and all("was refused" in refusal.reason for refusal in refusals)
    assert tables.section_diffs, "the diff itself is unaffected by the summary being refused"


@needs_engine
def test_a_refused_answer_and_a_declined_one_are_different_records() -> None:
    """Refused and declined summary reasons are disjoint: a refused answer is never recorded as "below the minimum"."""
    # The whole point: a caller reading the refusal must be able to tell "the
    # model answered something the reader would not take" from "the generator
    # never asked, because this printing is too short to summarize".
    refused = family(summarize=refusing(ModelCallError(REFUSAL)))
    declined = family(summarize=StubSummarizer(declines=frozenset({"introduced-in-house", "engrossed-in-house"})))
    reasons = {
        name: {refusal.reason for refusal in tables.refusals if refusal.table == "bill_summaries"}
        for name, tables in (("refused", refused), ("declined", declined))
    }
    assert not reasons["refused"] & reasons["declined"]
    assert all("below the minimum" in reason for reason in reasons["declined"])
    assert all("below the minimum" not in reason for reason in reasons["refused"])


@needs_engine
@pytest.mark.parametrize(
    "error",
    [CredentialRefusedError("Gemini refused credentials (401)"), ExtractionError("Gemini HTTP 502")],
    ids=["credential refusal", "transport failure"],
)
def test_a_credential_refusal_or_a_transport_failure_still_aborts_the_pass(error) -> None:
    """A credential refusal or transport failure aborts the whole pass rather than being filed per row."""
    # Neither is a fact about this printing. A 401 must end the run rather than
    # be filed once per row, and a 502 establishes nothing to record.
    with pytest.raises(type(error)):
        family(summarize=refusing(error))


@needs_engine
def test_classifications_resolve_through_the_section_row_not_the_model_answer() -> None:
    """Every classification row resolves to a published section key and carries the current vocabulary hash."""
    tables = modelled_family()
    sections = {BILL_SECTIONS.key(row) for row in tables.bill_sections}
    for row in tables.section_classifications:
        key = (row["bill_id"], row["version_code"], row["source"], row["match_path"], row["body_index"])
        assert key in sections
        assert row["vocabulary_hash"] == classification_vocabulary_hash()


@needs_engine
def test_a_model_answer_naming_an_unpublished_section_is_refused() -> None:
    """A classification naming a section outside the published rows is refused once per version."""

    def stray(sections: list[ClassifiableSection]) -> tuple[SectionClassification, ...]:
        answers = StubClassifier()(sections)
        return (*answers, replace(answers[0], section_id="not-a-section"))

    tables = family(classify=stray)
    refusals = [r for r in tables.refusals if r.table == "section_classifications"]
    assert len(refusals) == len(tables.bill_versions)
    assert all("did not publish a row" in refusal.reason for refusal in refusals)
    assert all(refusal.identity[0] == "119-hr-6028" for refusal in refusals)


@needs_engine
def test_every_refusal_this_pass_files_names_its_bill_first() -> None:
    """Every refusal identity starts with the bill id, including section_classifications."""
    # A rollup collecting refusals across bills reads identity[0] as the bill.
    # The section_classifications refusals used to omit it, alone among the
    # twelve tables', so a printing could not be traced back to its bill.
    tables = family(
        three_printing_capture(),
        classify=refusing(ModelCallError("classification names a section outside its batch")),
        summarize=refusing(ModelCallError(REFUSAL)),
        summarize_diff=refusing(ModelCallError("diff summary answer is missing headline")),
    )
    assert tables.refusals
    assert {refusal.identity[0] for refusal in tables.refusals} == {"119-hr-6028"}


def test_section_reference_is_unique_per_printing_and_position() -> None:
    """Section references differ by source and by body index."""
    assert section_reference("ih", "govinfo", 3) != section_reference("ih", "govinfo-pdf", 3)
    assert section_reference("ih", "govinfo", 3) != section_reference("ih", "govinfo", 4)


def test_a_version_type_outside_the_sealed_vocabulary_refuses_one_row_not_the_bill() -> None:
    """An unknown version slug must not abort the bill: only its sections refuse, and reprint ambiguity is
    ``"false"`` for an unnamed type while a genuinely ambiguous one is ``"true"``.
    """
    # Unparsed printings: the vocabulary guard has nothing to do with the diff
    # engine, so this case runs whether or not the extra is installed.
    stray = printing(
        CAPTURED / "text-119hr6028ih.xml",
        version=constructed_version("Heretofore Unknown Printing", "2025-01-01T00:00:00Z"),
        version_code="introduced-in-house",
        parse=False,
    )
    known = printing(
        CAPTURED / "text-119hr6028eh.xml",
        version=constructed_version("Engrossed in House", "2026-06-08T04:00:00Z"),
        version_code="engrossed-in-house",
        parse=False,
    )
    capture = BillFamilyCapture(
        status=status_for("status-119hr6028.xml", HR6028), versions=(stray, known), observed_at=OBSERVED_AT
    )
    tables = family(capture, diff=False)

    # The bill, its actions and its summaries all survive, and so does the
    # unrecognised printing: the slug is unknown, not the row.
    assert len(tables.bills) == 1
    assert len(tables.bill_versions) == 2
    # Neither printing was parsed, so both refuse their sections and nothing
    # refuses a version row.
    assert [refusal.table for refusal in tables.refusals] == ["bill_sections", "bill_sections"]
    # An unnamed type is not ambiguous -- nothing else claims it -- while
    # "Engrossed in House" beside it genuinely is, naming both eh and eh1s.
    assert [row["version_code_is_reprint_ambiguous"] for row in tables.bill_versions] == ["false", "true"]


def test_a_shaper_that_refuses_becomes_a_named_refusal_not_an_abort() -> None:
    """Whatever a shaper refuses with, the identity it would have had is recorded."""
    from spicy_docs.interpretation import bill_family as module
    from spicy_docs.sources.congress.bill_versions import VersionCodeError

    admit = module._Admitter()
    rows: list[dict[str, str | None]] = []
    for error in (VersionCodeError("no such slug"), TypeError("wrong shape")):

        def build(raised: Exception = error) -> dict[str, str | None]:
            raise raised

        assert admit(TABLE_CONTRACTS["bill_versions"], rows, ("119-hr-1", "ih", "govinfo"), build) is None
    assert rows == []
    assert [refusal.identity for refusal in admit.refusals] == [("119-hr-1", "ih", "govinfo")] * 2
    assert all(refusal.table == "bill_versions" for refusal in admit.refusals)
    assert [reason.split(":")[-1].strip() for reason in (r.reason for r in admit.refusals)] == [
        "no such slug",
        "wrong shape",
    ]


@needs_engine
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_engine_evidence_refuses_only_its_diff_item(monkeypatch, number: float) -> None:
    """A constructed engine defect on the retained real pair must name its row."""
    from spicy_docs.interpretation import section_diff
    from spicy_docs.schemas.bill_diff_tables import shape_section_diff_item
    from spicy_docs.schemas.tables import TableContractError

    capture = captured_pair_capture()
    older, newer = capture.versions
    comparison = section_diff.diff_sections(
        older.document, newer.document, from_version=older.version_code, to_version=newer.version_code
    )
    original = family(capture)
    first, *remaining = comparison.items
    bad = replace(first, evidence={**first.evidence, "unexpected_signal": [{"nested": number}]})
    with pytest.raises(TableContractError, match="non-finite"):
        shape_section_diff_item(bad, bill_id="119-hr-6028", from_ref=older, to_ref=newer)
    monkeypatch.setattr(
        section_diff, "diff_sections", lambda *args, **kwargs: replace(comparison, items=(bad, *remaining))
    )

    result = family(capture)
    assert result.bills == original.bills
    assert result.bill_versions == original.bill_versions
    assert result.bill_sections == original.bill_sections
    assert result.section_diffs == original.section_diffs
    assert result.section_diff_items == tuple(
        row for row in original.section_diff_items if row["seq"] != str(first.seq)
    )
    [refusal] = result.refusals
    assert refusal.table == "section_diff_items"
    assert refusal.identity == (
        "119-hr-6028",
        older.version_code,
        older.source,
        newer.version_code,
        newer.source,
        str(first.seq),
    )
    assert "non-finite" in refusal.reason


def test_concat_is_one_pass_where_folding_merged_is_quadratic() -> None:
    """concat is linear where folding ``merged`` copies on the order of N^2 rows, asserted as counted row copies
    rather than wall-clock so a slow machine cannot make it flap.
    """
    copies = 0
    original = tuple.__add__

    class _Counted(tuple):
        def __add__(self, other):
            nonlocal copies
            copies += len(self) + len(other)
            return _Counted(original(self, other))

    one = BillFamilyTables(bills=_Counted(({"a": None},)), bill_actions=_Counted(({"b": None},)))
    count = 4_000

    folded = BillFamilyTables(bills=_Counted(()), bill_actions=_Counted(()))
    for _ in range(count):
        folded = folded.merged(one)
    quadratic = copies

    copies = 0
    joined_tables = BillFamilyTables.concat([one] * count)
    linear = copies

    assert len(folded.bills) == len(joined_tables.bills) == count
    assert folded.bills == joined_tables.bills
    # The fold copies on the order of N^2 rows; concat copies none, because it
    # extends one list per field and builds each tuple once.
    assert quadratic > count * count
    assert linear == 0


def test_concat_refuses_anything_that_is_not_a_family() -> None:
    """concat raises TypeError for non-family input and returns an empty family for an empty list."""
    with pytest.raises(TypeError):
        BillFamilyTables.concat([BillFamilyTables(), {"bills": ()}])
    assert BillFamilyTables.concat([]) == BillFamilyTables()


def test_merged_concatenates_every_table_and_keeps_every_refusal() -> None:
    """merged concatenates every table's rows in order and merging empty families yields an empty family."""
    left = BillFamilyTables(bills=({"a": None},), refusals=())
    right = BillFamilyTables(bills=({"b": None},), bill_actions=({"c": None},))
    merged = left.merged(right)
    assert merged.bills == ({"a": None}, {"b": None})
    assert merged.bill_actions == ({"c": None},)
    assert BillFamilyTables().merged(BillFamilyTables()) == BillFamilyTables()


def test_merged_refuses_anything_that_is_not_a_family() -> None:
    """merged raises TypeError for non-family input."""
    with pytest.raises(TypeError):
        BillFamilyTables().merged({"bills": ()})


def test_the_vocabulary_hash_moves_when_a_definition_is_reworded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rewording a classification label definition changes the vocabulary hash."""
    from spicy_docs.interpretation import bill_family, section_classification

    before = classification_vocabulary_hash()
    reworded = (
        replace(section_classification.CLASSIFICATION_LABELS[0], definition="something else entirely"),
        *section_classification.CLASSIFICATION_LABELS[1:],
    )
    monkeypatch.setattr(bill_family, "CLASSIFICATION_LABELS", reworded)
    assert classification_vocabulary_hash() != before


@needs_engine
def test_the_engine_stamp_is_read_from_the_installed_distribution() -> None:
    """The installed stamp names deltatrack, states a version, and has a 40-character revision or an empty one."""
    stamp = installed_engine_stamp()
    assert stamp.name == "deltatrack"
    assert stamp.version
    # A git install records its resolved commit; a wheel install states none,
    # and the stamp says so rather than reporting a revision it does not know.
    assert stamp.revision == "" or len(stamp.revision) == 40


def test_a_missing_engine_distribution_refuses_by_name() -> None:
    """An uninstalled distribution raises BillFamilyError naming the bill-diff extra."""
    from spicy_docs.interpretation.bill_family import BillFamilyError

    with pytest.raises(BillFamilyError, match="bill-diff"):
        installed_engine_stamp("not-an-installed-distribution")


def test_the_family_builds_without_the_diff_and_names_every_pair_it_skipped() -> None:
    """``diff=False`` is the documented fallback for an environment that cannot vendor the engine."""
    capture = BillFamilyCapture(
        status=status_for("status-119hr6028.xml", HR6028),
        versions=(
            printing(
                CAPTURED / "text-119hr6028ih.xml",
                version=constructed_version("Introduced in House", "2025-11-12T05:00:00Z"),
                version_code="introduced-in-house",
                parse=False,
            ),
        ),
        observed_at=OBSERVED_AT,
    )
    tables = family(capture, diff=False)
    assert tables.section_diffs == ()
    assert len(tables.bills) == 1
    assert [refusal.table for refusal in tables.refusals] == ["bill_sections"]


def test_a_referral_signal_reaches_both_the_committee_row_and_the_bills_row() -> None:
    """An appropriations system code sets the committee row's referral signal and the bill's, using a constructed
    signal since no captured status refers to one of the six; the vocabulary lives in
    ``tests/test_interpretation_money_bills.py``.
    """
    status = status_for("status-119hres10.xml", BillIdentity(119, "hres", 10))
    referred = replace(status, committees=(replace(status.committees[0], system_code="hsap00"),))
    tables = family(BillFamilyCapture(status=referred, observed_at=OBSERVED_AT), diff=False)

    assert [row["referral_signal"] for row in tables.bill_committees] == ["appropriations"]
    assert [row["referral_rule"] for row in tables.bill_committees] == ["committee_system_code"]
    assert tables.bills[0]["referral_signals"] == "appropriations"
    # Outside the six the rule still ran and still says so; only the answer is NULL.
    unreferred = family(BillFamilyCapture(status=status, observed_at=OBSERVED_AT), diff=False)
    assert unreferred.bill_committees[0]["referral_signal"] is None
    assert unreferred.bill_committees[0]["referral_rule"] == "committee_system_code"
    assert unreferred.bills[0]["referral_signals"] is None


@pytest.mark.parametrize(
    ("name", "identity", "code", "source_name"),
    [
        # H.R. 6028's latest action is a Senate receipt: the publisher states a
        # source system for it and no code at all, which is a real absence.
        ("status-119hr6028.xml", HR6028, None, "Senate"),
        ("status-119s5.xml", BillIdentity(119, "s", 5), "36000", "Library of Congress"),
        ("status-119hres10.xml", BillIdentity(119, "hres", 10), "H11100", "House floor actions"),
        ("status-119hres214.xml", BillIdentity(119, "hres", 214), "H38310", "House floor actions"),
    ],
)
def test_exactly_one_action_is_flagged_latest_and_carries_the_coded_fields(
    name: str, identity: BillIdentity, code: str | None, source_name: str
) -> None:
    """Exactly one action is flagged latest -- matched to ``<latestAction>`` on date and text, since whole records
    never compare equal -- and the bill's coded fields are read from that action; expectations come from the
    fixtures, not the row under test.
    """
    status = status_for(name, identity)
    tables = family(BillFamilyCapture(status=status, observed_at=OBSERVED_AT), diff=False)

    flagged = [row for row in tables.bill_actions if row["is_latest_action"] == "true"]
    assert len(flagged) == 1
    assert flagged[0]["action_text"] == status.latest_action.text
    assert flagged[0]["action_date"] == status.latest_action.action_date

    bill = tables.bills[0]
    assert bill["latest_action_code"] == code
    assert bill["latest_action_source_system_name"] == source_name
    assert bill["latest_action_source_system_code"] == flagged[0]["source_system_code"]


def test_a_bill_whose_latest_action_is_not_in_its_list_flags_nothing() -> None:
    """A reduced or truncated action list is a NULL code, not a wrong one."""
    status = status_for("status-119hr6028.xml", HR6028)
    trimmed = replace(status, actions=status.actions[1:])
    tables = family(BillFamilyCapture(status=trimmed, observed_at=OBSERVED_AT), diff=False)
    assert all(row["is_latest_action"] == "false" for row in tables.bill_actions)
    assert tables.bills[0]["latest_action_code"] is None
    # The uncoded fields latestAction does state are still published.
    assert tables.bills[0]["latest_action_text"] == status.latest_action.text


def test_committee_count_equals_the_committee_rows_at_any_nesting_depth() -> None:
    """The column's description promises the row count, so the two walks must agree."""
    status = status_for("status-119hres10.xml", BillIdentity(119, "hres", 10))
    parent = status.committees[0]
    nested = replace(
        parent,
        subcommittees=(replace(parent, system_code="hsru01", subcommittees=(replace(parent, system_code="hsru02"),)),),
    )
    tables = family(
        BillFamilyCapture(status=replace(status, committees=(nested,)), observed_at=OBSERVED_AT),
        diff=False,
    )
    assert tables.bills[0]["committee_count"] == str(len(tables.bill_committees)) == "3"
    assert [row["parent_system_code"] for row in tables.bill_committees] == [None, "hsru00", "hsru01"]


def test_a_money_bill_publishes_its_kind_beside_every_input_the_rule_read() -> None:
    """A constructed appropriations title reaches money_bill_kind, rule, reason codes, fiscal year and subcommittee
    columns beside the referral signals, so a row can be re-derived from itself; the rule itself is covered in
    ``tests/test_interpretation_money_bills.py``.
    """
    status = status_for("status-119hres10.xml", BillIdentity(119, "hres", 10))
    appropriation = replace(
        status,
        title="Making appropriations for the Department of Defense for fiscal year 2027.",
        committees=(replace(status.committees[0], system_code="hsap00"),),
    )
    row = family(BillFamilyCapture(status=appropriation, observed_at=OBSERVED_AT), diff=False).bills[0]
    assert row["money_bill_kind"] == "regular_appropriations"
    assert row["money_bill_rule"]
    assert row["money_bill_reason_codes"]
    assert row["fiscal_year"] == "FY2027"
    assert row["appropriations_subcommittee"] == "Defense"
    assert row["referral_signals"] == "appropriations"


def test_an_enacted_bill_carries_its_law_number_and_its_signing_provenance() -> None:
    """S. 5 is the one enacted measure here: Public Law 119-1, with a coded became-law action."""
    status = status_for("status-119s5.xml", BillIdentity(119, "s", 5))
    row = family(BillFamilyCapture(status=status, observed_at=OBSERVED_AT), diff=False).bills[0]
    assert row["public_law_number"] == "119-1"
    assert row["law_type"] == "Public Law"
    assert row["signed_date"] == "2025-01-29"
    assert row["signed_date_rule"] == "public_law_and_became_law_action"
    assert row["signed_date_action_code"] == "36000"
    assert row["stage"] == "law"
