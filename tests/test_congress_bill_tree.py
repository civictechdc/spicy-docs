"""The DeltaTrack adapter: the gate, the bodies it reads, and the element inventory.

These do not test the engine — upstream's own suite does that, 3,822 cases at the
pinned revision. They test the seam: that the publisher's bytes reach it only
through this repository's bounded XML entry point, that the shapes the former
copies refused now parse, and that what the flattening drops is counted.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.parsers import expat

import pytest

from spicy_docs.reading.xml import _configure_xml_parser
from spicy_docs.sources.congress.bill_status import BillSourceError
from spicy_docs.sources.congress.bill_tree import (
    DEFAULT_MAX_BYTES,
    BillDocument,
    engine_available,
    parse_bill_tree,
)

pytestmark = pytest.mark.skipif(not engine_available(), reason="needs the 'bill-diff' extra: uv sync --extra bill-diff")

CAPTURED = Path(__file__).parent / "fixtures/govinfo_bills"
CONSTRUCTED = Path(__file__).parent / "fixtures/congress_bill_tree"

# Any start tag, from the raw bytes. A regex over the source is a different tool
# family from the expat parse under test, so agreement between the two is
# evidence rather than the parser confirming itself.
_START_TAG = re.compile(rb"<([A-Za-z_][\w:.\-]*)")
_NOT_AN_ELEMENT = re.compile(rb"<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>", re.DOTALL)


def _document(name: str) -> bytes:
    """The bytes of a captured bill-tree fixture."""
    directory = CONSTRUCTED if name.startswith("constructed-") else CAPTURED
    return (directory / name).read_bytes()


def _tree(name: str, *, version: str = "") -> BillDocument:
    """Parse a captured fixture through the adapter, optionally naming the version code."""
    return parse_bill_tree(_document(name), version=version)


def _wrap(body: str, *, root: str = "bill", body_tag: str = "legis-body") -> bytes:
    """Wrap body markup in a minimal bill root."""
    return f'<{root} {root}-stage="Introduced-in-House"><{body_tag}>{body}</{body_tag}></{root}>'.encode()


# --- bodies the two former copies refused ----------------------------------


def test_a_captured_resolution_body_parses() -> None:
    """The publisher's own resolution bytes. BillTrax's fork and its vendored snapshot both threw here."""
    document = _tree("text-119hjres25enr.xml", version="enr")
    assert (document.root_tag, document.body_tags, document.stage) == (
        "resolution",
        ("resolution-body",),
        "Enrolled-Bill",
    )
    bodies = [node for node in document.sections if node.tag != "front-matter"]
    assert len(bodies) == 1
    assert bodies[0].body_text.startswith("That Congress disapproves the rule submitted")


@pytest.mark.parametrize(
    ("name", "root_tag", "body_tag", "stage"),
    [
        ("text-119hjres25enr.xml", "resolution", "resolution-body", "Enrolled-Bill"),
        ("text-119hr6028ih.xml", "bill", "legis-body", "Introduced-in-House"),
        ("text-119hr6028eh.xml", "bill", "legis-body", "Engrossed-in-House"),
        ("text-119s5enr.xml", "bill", "legis-body", "Enrolled-Bill"),
        ("constructed-resolution-appropriations.xml", "resolution", "resolution-body", "Introduced-in-House"),
        ("constructed-bill-divisions.xml", "bill", "legis-body", "Introduced-in-House"),
    ],
)
def test_root_body_and_stage(name: str, root_tag: str, body_tag: str, stage: str) -> None:
    """Each root/body/stage combination parses with sections."""
    document = _tree(name)
    assert (document.root_tag, document.body_tags, document.stage) == (root_tag, (body_tag,), stage)
    assert document.sections


def test_every_captured_text_fixture_yields_sections() -> None:
    """Resolution-body coverage on the captured sample: every text fixture parses, one of them a resolution."""
    documents = [parse_bill_tree(path.read_bytes()) for path in sorted(CAPTURED.glob("text-*.xml"))]
    assert documents
    assert all(document.sections for document in documents)
    assert sum(document.body_tags == ("resolution-body",) for document in documents) == 1


def test_an_amendment_block_is_found_at_any_depth() -> None:
    """An amendment block at any depth is found, with no stage and its text retained."""
    nested = (
        b"<amendment-doc><amendment-form><engrossed-amendment-body><amendment>"
        b"<amendment-block><section><enum>1.</enum><text>Strike all after the enacting clause.</text>"
        b"</section></amendment-block></amendment></engrossed-amendment-body></amendment-form></amendment-doc>"
    )
    document = parse_bill_tree(nested)
    assert document.body_tags == ("amendment-block",)
    assert document.stage is None
    assert any("Strike all after the enacting clause." in node.body_text for node in document.sections)


def test_a_document_with_no_body_refuses_in_this_package_s_words() -> None:
    """A document with no body refuses with the adapter's own wording."""
    with pytest.raises(BillSourceError, match="cannot be flattened"):
        parse_bill_tree(b"<bill><form><legis-num>H. R. 1</legis-num></form></bill>")


def test_a_resolution_with_paired_committee_variants_refuses_rather_than_choosing() -> None:
    """Upstream fails loudly here; the adapter must not turn that into a silent half-document."""
    paired = (
        b"<resolution>"
        b'<resolution-body changed="deleted"><section><enum>1.</enum><text>Struck text.</text></section></resolution-body>'
        b'<resolution-body changed="added"><section><enum>1.</enum><text>Amended text.</text></section></resolution-body>'
        b"</resolution>"
    )
    with pytest.raises(BillSourceError, match="paired committee-amendment variants"):
        parse_bill_tree(paired)


# --- the gate ---------------------------------------------------------------


def test_the_parse_is_bounded_before_the_engine_sees_anything() -> None:
    """The byte bound refuses before the engine sees the document."""
    with pytest.raises(BillSourceError, match="within max_bytes"):
        parse_bill_tree(_document("constructed-bill-divisions.xml"), max_bytes=64)


def test_the_default_bound_is_the_measured_one() -> None:
    """DEFAULT_MAX_BYTES is the measured 24 MiB."""
    assert DEFAULT_MAX_BYTES == 24 * 1024 * 1024


def test_an_internal_dtd_subset_refuses() -> None:
    """An internal DTD subset is refused."""
    declared = (
        b'<!DOCTYPE bill SYSTEM "bill.dtd" [<!ENTITY x "expanded">]>'
        b"<bill><legis-body><section><enum>1.</enum><text>&x;</text></section></legis-body></bill>"
    )
    with pytest.raises(BillSourceError):
        parse_bill_tree(declared)


def test_the_external_dtd_is_accepted_and_never_resolved() -> None:
    """A relative DTD beside the document must be tolerated and never fetched.

    Tolerated is asserted on the bytes: the fixture declares `res.dtd` and still
    parses. *Never fetched* cannot be asserted from the bytes at all — a parser
    that resolved it would produce the same sections — so it is asserted where
    the guarantee lives, on the parser configuration itself.
    """
    # The publisher writes a PUBLIC id and then a SYSTEM id relative to the document.
    assert b'PUBLIC "-//US Congress//DTDs/res.dtd//EN" "res.dtd"' in _document("text-119hjres25enr.xml")
    assert _tree("text-119hjres25enr.xml").sections

    class _Recorder:
        """Stands in for an expat parser and records what the configuration asks of it."""

        def __init__(self) -> None:
            self.param_entity_parsing: list[int] = []

        # expat's own spelling; the configuration calls it by this name.
        def SetParamEntityParsing(self, setting: int) -> None:
            self.param_entity_parsing.append(setting)

    parser = _Recorder()
    _configure_xml_parser(
        parser,
        start=lambda *_: None,
        end=lambda *_: None,
        data=lambda *_: None,
        error_type=BillSourceError,
        label="probe",
        allow_external_doctype=True,
    )
    assert parser.param_entity_parsing == [expat.XML_PARAM_ENTITY_PARSING_NEVER]
    # And the one handler that could fetch anything refuses instead.
    with pytest.raises(BillSourceError, match="forbidden"):
        parser.ExternalEntityRefHandler("ctx", "base", "res.dtd", None)


# --- what the engine recovers that the TypeScript fork did not ---------------


def test_identity_comes_from_the_document() -> None:
    """Congress, bill type and number are read from the document, not the request."""
    resolution = _tree("constructed-resolution-appropriations.xml", version="ih")
    assert (resolution.tree.congress, resolution.tree.bill_type, resolution.tree.bill_number) == (119, "hjres", 143)
    enrolled = _tree("text-119s5enr.xml")
    assert (enrolled.tree.congress, enrolled.tree.bill_type, enrolled.tree.bill_number) == (119, "s", 5)


def test_a_joint_resolution_number_is_not_read_as_type_j() -> None:
    """The vendored snapshot's `([A-Z])\\.` regex read "H. J. RES. 25" as type "j"."""
    assert _tree("text-119hjres25enr.xml").tree.bill_type == "hjres"


def test_the_version_code_reaches_the_engine_through_the_file_name() -> None:
    """The version code reaches the engine through the file name and is empty when not given."""
    assert _tree("text-119hr6028ih.xml", version="ih").tree.version == "ih"
    assert _tree("text-119hr6028ih.xml").tree.version == ""


def test_divisions_titles_and_subsections_build_paths() -> None:
    """Division keys are built from the header alone, and engine-emitted subsections get their own match paths."""
    document = _tree("constructed-bill-divisions.xml")
    by_id = {node.element_id: node for node in document.sections}

    military = by_id["HDA0S1"]
    assert military.match_path[-1] == "sec. 101"
    assert military.division_label == "Division A: Military Construction"
    # The key is built from the header alone, so a change to the label's wrapper
    # cannot silently move a section into another bucket.
    assert military.division_key == "military construction"

    veterans = by_id["HDB0S1"]
    assert veterans.match_path == military.match_path
    assert veterans.division_key == "veterans affairs"

    # The engine emits subsection nodes of its own; the copies this replaces did not.
    assert by_id["HDA0S2a"].match_path[-1] == "(a)"


def test_appropriations_structure_inside_a_resolution_body() -> None:
    """The appropriations walker, reachable in the sample only through a resolution."""
    document = _tree("constructed-resolution-appropriations.xml")
    tags = [node.tag for node in document.sections]
    assert tags.count("appropriations-major") == 2
    assert tags.count("appropriations-intermediate") == 2
    assert tags.count("appropriations-small") == 3

    by_id = {node.element_id: node for node in document.sections}
    assert by_id["HAM01"].match_path[-1] == "office of the secretary"
    # A parenthetical header continues the block above it rather than naming a new one.
    assert by_id["HAS02"].header_text == "(Including Transfer of Funds)"
    assert by_id["HAS02"].match_path == by_id["HAS01"].match_path


# --- the element inventory --------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "text-119hjres25enr.xml",
        "text-119hr6028ih.xml",
        "text-119s5enr.xml",
        "constructed-resolution-appropriations.xml",
        "constructed-bill-divisions.xml",
    ],
)
def test_the_inventory_accounts_for_every_element_in_the_document(name: str) -> None:
    """Kept plus discarded is the whole document, counted a second way.

    The second count is a regex over the raw bytes, so a parse that quietly
    dropped a subtree could not make this agree with itself.
    """
    body = _document(name)
    document = parse_bill_tree(body)

    from_bytes = len(_START_TAG.findall(_NOT_AN_ELEMENT.sub(b"", body)))
    assert from_bytes > 0
    assert sum(document.element_counts.values()) == from_bytes

    for tag, count in document.element_counts.items():
        assert document.kept_elements.get(tag, 0) + document.discarded_elements.get(tag, 0) == count
    assert sum(document.kept_elements.values()) + sum(document.discarded_elements.values()) == from_bytes
    assert sum(document.discarded_elements.values()) > 0


def test_the_inventory_names_what_the_output_does_not_contain() -> None:
    """The inventory names dropped tags and never marks text or section as dropped."""
    document = _tree("constructed-bill-divisions.xml")
    # Sponsorship and Dublin Core are in the bytes and nowhere in the nodes.
    for tag in ("sponsor", "cosponsor", "dublinCore", "metadata"):
        assert document.discarded_elements[tag] >= 1
    # The section text is, by definition, in the output.
    assert "text" not in document.discarded_elements
    assert "section" not in document.discarded_elements


def test_front_matter_text_is_not_reported_dropped() -> None:
    """The engine composes the form block into nodes without naming the elements it read."""
    document = _tree("text-119hr6028ih.xml")
    for tag in ("congress", "legis-num", "form"):
        assert tag not in document.discarded_elements


def test_a_committee_report_reference_and_an_action_are_reported_dropped() -> None:
    """Committee report references and actions are reported as dropped."""
    document = _tree("constructed-resolution-appropriations.xml")
    for tag in ("action", "action-date", "committee-name"):
        assert document.discarded_elements[tag] >= 1


def test_a_table_of_contents_is_reported_dropped() -> None:
    """The count must not be fooled by GPO spelling a toc entry exactly like its title.

    Crediting the engine's composed display labels marked every `<toc-entry>`
    read and then, by the container rule, the whole `<toc>` — a whole structure
    vanishing from the report of what was dropped. The accounted set is node
    text only for this reason; `_accounted_text` says so.
    """
    document = _tree("constructed-resolution-appropriations.xml")
    assert document.element_counts["toc-entry"] == 2
    assert document.discarded_elements["toc-entry"] == 2
    assert document.discarded_elements["toc"] == 1


def test_container_numbering_reports_dropped_because_it_survives_only_fused() -> None:
    """The over-reporting side of the same trade, pinned so the direction is deliberate."""
    document = _tree("constructed-bill-divisions.xml")
    # Three <title>s and one <subtitle>, each with an <enum> whose text reaches
    # the output only inside a composed label like "TITLE I—Active Components".
    assert document.discarded_elements["title"] == 3
    assert document.discarded_elements["enum"] >= 4
