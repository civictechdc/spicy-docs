"""The DeltaTrack diff adapter: the rows it shapes, the provenance it keeps, and what upstream decides.

Two kinds of case. The adapter's own: that its recomposition of upstream's stage
sequence produces exactly what ``diff_bills`` produces, that the rows carry the
columns the diff tables hold, and that a version against itself reports nothing.
And the measurement cases: each of the divergences and bugs
``docs/research/billtrax-value-inventory-2026-09-19.md`` §4.4 and §4.5 recorded
between the two BillTrax copies, asserted against the pinned engine, so the
port's premise ("upstream already decides this, and this is how") is checked
rather than claimed. What upstream does *not* have is listed in
``docs/sources/congress-bill-tree.md`` and is deliberately not patched in here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spicy_docs.interpretation.section_diff import (
    OPS,
    AmountPair,
    SectionDiff,
    VersionRef,
    diff_sections,
    engine_available,
    pair_type,
)
from spicy_docs.sources.congress.bill_tree import BillDocument, parse_bill_tree

pytestmark = pytest.mark.skipif(not engine_available(), reason="needs the 'bill-diff' extra: uv sync --extra bill-diff")

CONSTRUCTED = Path(__file__).parent / "fixtures/congress_bill_tree"
CAPTURED = Path(__file__).parent / "fixtures/govinfo_bills"


def _document(directory: Path, name: str, version: str = "") -> BillDocument:
    return parse_bill_tree((directory / name).read_bytes(), version=version)


@pytest.fixture(scope="module")
def introduced() -> BillDocument:
    return _document(CONSTRUCTED, "constructed-bill-divisions.xml", "ih")


@pytest.fixture(scope="module")
def engrossed() -> BillDocument:
    return _document(CONSTRUCTED, "constructed-bill-divisions-engrossed.xml", "eh")


@pytest.fixture(scope="module")
def staged(introduced: BillDocument, engrossed: BillDocument) -> SectionDiff:
    return diff_sections(introduced, engrossed, from_version="ih", to_version="eh")


# --- the adapter sits on upstream, and is pinned to it ----------------------


def test_the_recomposed_stage_sequence_reproduces_diff_bills(
    introduced: BillDocument, engrossed: BillDocument, staged: SectionDiff
) -> None:
    """The adapter runs upstream's stages itself to keep the evidence; this is the guard.

    Upstream changing what ``diff_bills`` composes must fail here rather than
    quietly leaving this module running an older pipeline.
    """
    from deltatrack.diff_bill import diff_bills

    upstream = diff_bills(introduced.tree, engrossed.tree)
    assert [change.change_type for change in upstream.changes] == [item.op for item in staged.items]
    assert [change.match_path for change in upstream.changes] == [item.match_path for item in staged.items]
    assert [change.old_text for change in upstream.changes] == [item.from_text for item in staged.items]
    assert [change.new_text for change in upstream.changes] == [item.to_text for item in staged.items]
    assert upstream.summary == dict(staged.summary)


def test_the_rows_carry_the_diff_table_columns(staged: SectionDiff) -> None:
    assert (staged.from_version, staged.to_version) == ("ih", "eh")
    assert set(staged.summary) == set(OPS)
    assert [item.seq for item in staged.items] == list(range(len(staged.items)))
    for item in staged.items:
        assert item.op in OPS
        assert item.moved == (item.op == "moved")
        assert isinstance(item.match_path, tuple)


def test_every_paired_row_names_the_rule_and_the_score(staged: SectionDiff) -> None:
    """Neither former copy recorded why two sections were paired."""
    paired = [item for item in staged.items if item.from_text is not None and item.to_text is not None]
    assert paired
    for item in paired:
        assert item.pairing_rule in ("path-round", "move-round")
        assert "body_unchanged" in item.evidence
    modified = [item for item in paired if item.op == "modified"]
    assert modified
    for item in modified:
        assert item.similarity is not None and 0.0 <= item.similarity <= 1.0
        assert item.evidence["word_overlap"] == pytest.approx(item.similarity, abs=1e-4)


def test_an_unpaired_row_says_so(staged: SectionDiff) -> None:
    unpaired = [item for item in staged.items if item.op in ("added", "removed")]
    assert unpaired
    for item in unpaired:
        assert item.pairing_rule == "unpaired"
        assert item.similarity is None
        assert dict(item.evidence) == {}


def test_the_publisher_ids_travel_with_each_row(staged: SectionDiff) -> None:
    by_op = {item.op: item for item in staged.items if item.from_element_id.startswith("HD")}
    modified = next(item for item in staged.items if item.op == "modified" and item.from_element_id == "HDA0S1")
    assert modified.to_element_id == "HDA0S1"
    assert by_op
    removed = next(item for item in staged.items if item.op == "removed")
    assert removed.from_element_id and removed.to_element_id == ""


def test_two_stages_of_one_bill_report_the_expected_ops(staged: SectionDiff) -> None:
    assert dict(staged.summary) == {"added": 1, "removed": 1, "modified": 2, "unchanged": 8, "moved": 0}
    modified = next(item for item in staged.items if item.from_element_id == "HDA0S1")
    assert modified.financial is not None
    assert modified.financial.amounts_changed is True
    assert modified.financial.pairs == (AmountPair("Authorized construction", 4_500_000, 5_250_000, 750_000),)
    assert modified.text_diff is not None


def test_a_cross_division_collision_pairs_within_its_own_division(staged: SectionDiff) -> None:
    """Both divisions carry a Sec. 101, so the match path collides; the division key resolves it."""
    colliding = [item for item in staged.items if item.match_path[-1:] == ("sec. 101",)]
    assert len(colliding) == 2
    for item in colliding:
        assert item.from_element_id == item.to_element_id


@pytest.mark.parametrize(
    ("directory", "name"),
    [
        (CONSTRUCTED, "constructed-bill-divisions.xml"),
        (CONSTRUCTED, "constructed-resolution-appropriations.xml"),
        (CAPTURED, "text-119hjres25enr.xml"),
        (CAPTURED, "text-119s5enr.xml"),
    ],
)
def test_a_version_against_itself_reports_no_change(directory: Path, name: str) -> None:
    document = _document(directory, name)
    diff = diff_sections(document, document, from_version="v1", to_version="v1")
    assert diff.summary["unchanged"] == len(document.sections)
    assert sum(diff.summary[op] for op in OPS if op != "unchanged") == 0
    assert all(item.text_diff is None for item in diff.items)
    assert all(item.op == "unchanged" for item in diff.items)


def test_an_appropriations_resolution_diffs_by_appropriations_node() -> None:
    document = _document(CONSTRUCTED, "constructed-resolution-appropriations.xml")
    kept = [node for node in document.sections if node.element_id != "HAS03"]
    trimmed = BillDocument(
        tree=type(document.tree)(
            document.tree.congress,
            document.tree.bill_type,
            document.tree.bill_number,
            document.tree.version,
            kept,
            document.tree.official_title,
        ),
        root_tag=document.root_tag,
        body_tags=document.body_tags,
        stage=document.stage,
        element_counts=document.element_counts,
        kept_elements=document.kept_elements,
        discarded_elements=document.discarded_elements,
    )
    diff = diff_sections(document, trimmed, from_version="v1", to_version="v2")
    assert diff.summary["removed"] == 1
    removed = next(item for item in diff.items if item.op == "removed")
    assert removed.from_element_id == "HAS03"
    assert removed.financial is not None
    assert removed.financial.from_amounts == (175_000_000,)


# --- what the two BillTrax copies disagreed about, measured on the pinned engine ---


def _body(document: BillDocument, element_id: str) -> str:
    return next(node.body_text for node in document.sections if node.element_id == element_id)


def test_d1_cdata_reaches_the_section_body() -> None:
    """§4.4 D1: the TypeScript fork dropped CDATA from bodies while keeping it for enum."""
    document = parse_bill_tree(
        b'<bill bill-stage="Introduced-in-House"><legis-body>'
        b'<section id="S1"><enum>1.</enum><text>alpha<![CDATA[BETA]]>gamma</text></section>'
        b"</legis-body></bill>"
    )
    assert _body(document, "S1") == "alphaBETAgamma"


def test_d2_u_feff_is_not_a_word_separator() -> None:
    """§4.4 D2: JavaScript's \\s splits on U+FEFF and Python's str.split does not."""
    document = parse_bill_tree(
        b'<bill bill-stage="Introduced-in-House"><legis-body>'
        b'<section id="S1"><enum>1.</enum><text>a\xef\xbb\xbfb c</text></section>'
        b"</legis-body></bill>"
    )
    assert _body(document, "S1").split() == ["a﻿b", "c"]


def test_d3_enum_markup_does_not_re_key_the_section() -> None:
    """§4.4 D3: the fork read enum textContent, so an enum with markup changed the match path."""
    document = parse_bill_tree(
        b'<bill bill-stage="Introduced-in-House"><legis-body>'
        b'<section id="S1"><enum>1.<short-title>x</short-title></enum><text>Body.</text></section>'
        b"</legis-body></bill>"
    )
    section = next(node for node in document.sections if node.element_id == "S1")
    assert section.section_number == "Sec. 1"
    assert section.match_path == ("sec. 1",)


def test_d5_the_amendment_chain_is_found_at_any_depth() -> None:
    """§4.4 D5: the fork walked strict direct children and threw one level deeper."""
    document = parse_bill_tree(
        b"<amendment-doc><amendment-form><engrossed-amendment-body><amendment><amendment-block>"
        b'<section id="S1"><enum>1.</enum><text>Strike everything.</text></section>'
        b"</amendment-block></amendment></engrossed-amendment-body></amendment-form></amendment-doc>"
    )
    assert _body(document, "S1") == "Strike everything."


def test_the_dollar_regex_does_not_swallow_an_abutting_percentage() -> None:
    """§4.5: financial.ts read $17,400,022 where the bill says $17,400 and then 22%."""
    from deltatrack.amounts import extract_amounts

    assert extract_amounts("...appropriated $17,40022% of the fund and $5,000,000 more...") == (17_400, 5_000_000)


def test_the_annotation_search_is_stateless_across_both_sides() -> None:
    """§4.5: a global JavaScript regex carried lastIndex, so the second test() answered False."""
    from deltatrack.diff_bill import compute_financial_change

    # The left annotation sits past the right one's position, which is what made
    # the fork's second `.test()` answer False against a `g`-flagged regex.
    left = "For expenses, $400, " + "x" * 50 + " (increased by $1,000)"
    right = "(increased by $2,000) For expenses, $1,400"
    change = compute_financial_change(left, right)
    assert change is not None
    assert change.has_amendment_annotations is True
    # Both sides, in either order, and repeatedly: nothing carries state.
    assert compute_financial_change(right, left).has_amendment_annotations is True
    assert compute_financial_change(None, right).has_amendment_annotations is True
    assert compute_financial_change(left, None).has_amendment_annotations is True


def test_amounts_changed_compares_multisets() -> None:
    """§4.5: JSON.stringify of a comparator-less sort is a lexicographic multiset comparison."""
    from deltatrack.diff_bill import compute_financial_change

    same = compute_financial_change("$9 and $10 and $100", "$100 and $10 and $9")
    assert same is not None and same.amounts_changed is False
    duplicated = compute_financial_change("$9 and $9", "$9")
    assert duplicated is not None and duplicated.amounts_changed is True


def test_the_financial_label_carries_the_section_heading(staged: SectionDiff) -> None:
    """BillTrax wrote "" into this column at every construction site."""
    labelled = [
        pair for item in staged.items if item.financial is not None for pair in item.financial.pairs if pair.label
    ]
    assert labelled
    assert all(pair.label == "Authorized construction" for pair in labelled if pair.from_amount == 4_500_000)


def test_upstream_states_the_two_thresholds_once() -> None:
    from deltatrack.similarity import MOVE_THRESHOLD, SIMILARITY_THRESHOLD

    assert (SIMILARITY_THRESHOLD, MOVE_THRESHOLD) == (0.4, 0.6)


def test_upstream_gates_the_move_matrix_with_the_two_cheap_ratios() -> None:
    """The bridge's three-stage bail-out; upstream has it, at the place the matrix is."""
    import difflib

    from deltatrack.similarity import move_candidates

    calls: list[int] = []
    original = difflib.SequenceMatcher.ratio
    difflib.SequenceMatcher.ratio = lambda self: (calls.append(1), original(self))[1]  # type: ignore[method-assign]
    try:
        left = [" ".join(f"alpha{index}" for index in range(2_000))]
        right = [" ".join(f"omega{index}" for index in range(2_000))]
        assert move_candidates(left, right, 0.6) == []
    finally:
        difflib.SequenceMatcher.ratio = original  # type: ignore[method-assign]
    assert calls == []


# --- pair_type, which upstream has no counterpart for ----------------------


def _versions() -> list[VersionRef]:
    return [
        VersionRef("xml-1", "congress"),
        VersionRef("xml-2", "congress"),
        VersionRef("pdf-1", "govinfo-pdf", equivalent_xml_version_id="xml-1"),
        VersionRef("upload-1", "upload"),
    ]


def test_pair_type_of_two_published_versions_is_xml_xml() -> None:
    assert pair_type("xml-1", "xml-2", _versions()) == "xml-xml"


def test_pair_type_with_an_upload_and_a_pdf_twin_is_pdf_pdf() -> None:
    assert pair_type("upload-1", "xml-1", _versions()) == "pdf-pdf"
    assert pair_type("xml-1", "upload-1", _versions()) == "pdf-pdf"


def test_pair_type_with_an_upload_and_no_twin_is_pdf_xml() -> None:
    assert pair_type("upload-1", "xml-2", _versions()) == "pdf-xml"


def test_pair_type_of_an_unknown_version_falls_back_to_xml_xml() -> None:
    assert pair_type("missing", "xml-1", _versions()) == "xml-xml"
