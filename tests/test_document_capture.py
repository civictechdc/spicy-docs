"""The DocumentCapture v1 profiles and the six worked conversions, checked from what is committed.

Nothing here fetches: every capture is re-validated against the vendored
parent and its profile, its text stream is re-derived from the retained
document with another parser, every selector of every rendition fragment is
resolved against the bytes it names, and each validator is shown to refuse a
mutation of a committed capture. The one PDF-derived input is the retained
extractor document, never the PDF; the PDFs themselves are not committed, so
a page region is checked against the retained page geometry rather than
against a render.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
from pathlib import Path

import pytest

from tools.analysis import document_capture as dc

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "research" / "document-capture-schema-2026-09-19"
PINS = json.loads(dc.SCHEMAS.joinpath("PINS.json").read_text())
CAPTURES = sorted(OUTPUT.glob("*.capture.json"))


@pytest.fixture(scope="module")
def validators():
    return dc.validators()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def fragments_of(path: Path) -> list[dict]:
    return json.loads(path.with_name(path.name.replace(".capture.json", ".fragments.json")).read_text())


def stream_bytes(capture: dict) -> bytes:
    """The bytes the text stream was derived from: the extractor document when there is one."""
    source = capture["rendition"].get("intermediate") or capture["artifact"]
    return (ROOT / source["locator"]["path"]).read_bytes()


# --- the vendored schemas and the one validator ----------------------------------


def test_vendored_schemas_match_their_pins() -> None:
    assert dc.schema_pin(dc.PARENT_SCHEMA) == PINS["parent"]
    assert dc.schema_pin(dc.PROFILE_META_SCHEMA) == PINS["profileMetaSchema"]
    assert dc.schema_pin("rulespec/source-fragment.schema.json") == PINS["sourceFragment"]
    vendored = dc.SCHEMAS.joinpath(dc.VENDORED_INVARIANTS).read_bytes()
    assert hashlib.sha256(vendored).hexdigest() == PINS["invariantValidator"]["sha256"]
    for name, pin in PINS["profiles"].items():
        assert dc.schema_pin(f"profiles/{name}.schema.json") == pin, name


def test_the_vendored_copies_equal_the_wheel_when_the_wheel_carries_them() -> None:
    """The vendored parent, meta-schema and validator are Rulespec's, pinned until the wheel bump.

    The pinned ``rulespec-artifacts`` wheel predates all three. When it carries
    them, byte equality is the contract and a divergence is a failure here
    rather than a surprise in a consumer; at that point the vendored copies and
    the loader shim in ``document_capture.py`` go away together.
    """
    from importlib.metadata import version

    resources = pytest.importorskip("rulespec_artifacts.resources")
    # Gate on the version the schemas shipped in, not on a capability probe: a
    # wheel that renamed the accessor must fail here, not skip.
    if tuple(int(part) for part in version("rulespec-artifacts").split(".")[:3]) < (1, 0, 14):
        pytest.skip("the pinned rulespec-artifacts wheel predates 1.0.14, which ships the capture schemas")
    assert hasattr(resources, "document_capture_schema_bytes")
    assert resources.document_capture_schema_bytes() == dc.SCHEMAS.joinpath(dc.PARENT_SCHEMA).read_bytes()
    assert resources.document_capture_profile_schema_bytes() == dc.SCHEMAS.joinpath(dc.PROFILE_META_SCHEMA).read_bytes()
    # The validator swaps to the wheel's module the moment it imports, so its
    # bytes must equal the vendored copy too, or the pin guards a file nothing loads.
    shipped = dc.rulespec_invariants()
    assert Path(shipped.__file__).read_bytes() == dc.SCHEMAS.joinpath(dc.VENDORED_INVARIANTS).read_bytes()


def test_the_invariant_validator_in_use_is_rulespecs() -> None:
    module = dc.rulespec_invariants()
    assert {"check_invariants", "check_profile_bindings", "effective_source"} <= set(dir(module))


# --- the profiles ----------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(PINS["profiles"]))
def test_profile_composes_the_parent_without_redefining_it(name: str) -> None:
    profile = dc.load_schema(f"profiles/{name}.schema.json")
    assert dc.check_profile_composition(profile, dc.load_schema(dc.PARENT_SCHEMA)) == []
    assert profile["allOf"][1]["properties"]["profile"]["properties"]["name"]["const"] == name


def test_the_meta_schema_refuses_the_seven_tightenings_the_old_checker_admitted() -> None:
    """Each probe passed the hand-written whitelist this replaced; five changed what a capture validated as."""
    parent = dc.load_schema(dc.PARENT_SCHEMA)
    base = dc.load_schema("profiles/uslm-law.schema.json")

    def own(p):
        return p["allOf"][1]

    def clauses(p):
        return own(p)["properties"]["nodes"]["items"]["allOf"]

    probes = {
        "else on a node clause": lambda p: clauses(p)[0].__setitem__("else", {"properties": {"kind": {"const": "x"}}}),
        "required added to the narrowing": lambda p: own(p).__setitem__("required", ["artifact"]),
        "additionalProperties false on the narrowing": lambda p: own(p).__setitem__("additionalProperties", False),
        "not added to the narrowing": lambda p: own(p).__setitem__("not", {"required": ["unresolved"]}),
        "required on profile": lambda p: own(p)["properties"]["profile"].__setitem__("required", ["ext"]),
        "then loosening kind to any string": lambda p: clauses(p)[0]["then"]["properties"].__setitem__(
            "kind", {"type": "string"}
        ),
        "minItems on nodes": lambda p: own(p)["properties"]["nodes"].__setitem__("minItems", 2),
    }
    for name, mutate in probes.items():
        profile = copy.deepcopy(base)
        mutate(profile)
        assert dc.check_profile_composition(profile, parent), name


def test_the_meta_schema_refuses_a_foreign_kind_and_a_stale_pin() -> None:
    parent = dc.load_schema(dc.PARENT_SCHEMA)
    base = dc.load_schema("profiles/uslm-law.schema.json")
    for name, mutate in {
        "a stale parent pin": lambda p: p["x-parent"].__setitem__("sha256", "0" * 64),
        "a foreign kind in its own enum": lambda p: p["allOf"][1]["properties"]["nodes"]["items"]["allOf"][0]["then"][
            "properties"
        ]["kind"]["enum"].append("other:Foo"),
        "a refusal naming another profile": lambda p: p["allOf"][1]["properties"]["nodes"]["items"]["allOf"][1][
            "properties"
        ]["kind"]["not"].__setitem__("pattern", "^(?!other:)[a-z][a-z0-9-]*:"),
    }.items():
        profile = copy.deepcopy(base)
        mutate(profile)
        assert dc.check_profile_composition(profile, parent), name


def test_a_profile_refuses_another_familys_kind(validators) -> None:
    _, profiles, _ = validators
    capture = load(CAPTURES[0])
    doc = copy.deepcopy(capture)
    doc["nodes"][1]["kind"] = "other:Foo"
    assert [e.message for e in profiles[capture["profile"]["name"]].iter_errors(doc)]


# --- the six captures ------------------------------------------------------------


def test_every_family_has_a_worked_conversion() -> None:
    families = {load(p)["profile"]["name"] for p in CAPTURES}
    assert families == set(PINS["profiles"])


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_capture_validates_and_holds_its_invariants(path: Path, validators) -> None:
    parent, profiles, _ = validators
    capture = load(path)
    assert capture["schema"] == PINS["parent"]
    assert capture["profile"]["schema"] == PINS["profiles"][capture["profile"]["name"]]
    assert [e.message for e in parent.iter_errors(capture)] == []
    assert [e.message for e in profiles[capture["profile"]["name"]].iter_errors(capture)] == []
    assert dc.check_invariants(capture) == []


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_every_capture_names_when_its_bytes_were_read(path: Path) -> None:
    assert load(path)["artifact"].get("retrievedAt")


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_every_capture_names_the_converter_that_made_it(path: Path) -> None:
    """A stale converter pin is how the first draft's `revision` came to name a commit without the converter.

    The file digest is checkable from here, so it is checked: editing the
    converter without regenerating leaves a capture claiming a producer that no
    longer exists, and that is a provenance claim, not a formatting detail.
    """
    implementation = load(path)["converter"]["implementation"]
    assert implementation["repository"] == "spicy-docs"
    assert implementation["fileSha256"] == dc.sha256(Path(dc.__file__).read_bytes())


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_the_artifact_is_the_publishers_own_bytes(path: Path) -> None:
    """A consumer following locator.url and checking sha256 lands on the artifact, not on a derived file."""
    capture = load(path)
    artifact, intermediate = capture["artifact"], capture["rendition"].get("intermediate")
    if intermediate is None:
        assert dc.sha256((ROOT / artifact["locator"]["path"]).read_bytes()) == artifact["sha256"]
        return
    assert capture["rendition"]["kind"] == "pdf"
    assert artifact["mediaType"] == "application/pdf"
    assert artifact["sha256"] != intermediate["sha256"]
    assert artifact["sha256"] == capture["profile"]["ext"]["pdfSha256"]
    assert dc.sha256((ROOT / intermediate["locator"]["path"]).read_bytes()) == intermediate["sha256"]


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_text_stream_round_trips_from_the_retained_document(path: Path) -> None:
    capture = load(path)
    data = stream_bytes(capture)
    evidence = json.loads(data) if capture["rendition"].get("intermediate") else None
    kind = "evidence-lines" if evidence is not None else capture["rendition"]["kind"]
    independent, _ = dc.independent_text(kind, data, evidence)
    assert dc.sha256(independent) == capture["rendition"]["textStream"]["sha256"]
    assert "".join(s["exact"] for s in capture["evidence"]) == independent


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_leaf_fragments_are_valid_source_fragments(path: Path, validators) -> None:
    _, _, fragment_validator = validators
    capture = load(path)
    fragments = fragments_of(path)
    nodes = {n["id"]: n for n in capture["nodes"]}
    span_by_id = {s["id"]: s for s in capture["evidence"]}
    assert len(fragments) == 2
    assert dc.validate_fragments(fragments, fragment_validator) == []
    stream = "".join(s["exact"] for s in capture["evidence"])
    for entry in fragments:
        text = dc.node_text(capture, nodes[entry["node"]], span_by_id)
        for key in ("streamFragment", "renditionFragment"):
            quote = next(s for s in entry[key]["oa:hasSelector"] if s["@type"] == "oa:TextQuoteSelector")
            assert quote["oa:exact"] == text
            assert entry[key]["rkaf:fragmentContentDigest"] == "sha256:" + dc.sha256(text)
        positions = [s for s in entry["streamFragment"]["oa:hasSelector"] if s["@type"] == "oa:TextPositionSelector"]
        assert "".join(stream[s["oa:start"] : s["oa:end"]] for s in positions) == text
        if entry["carrierLocalFragmentUrn"]:
            assert entry["carrierLocalFragmentUrn"].endswith(
                f":{positions[0]['oa:start']}:{positions[0]['oa:end']}:sha256-{dc.sha256(text)}"
            )


@pytest.mark.parametrize("path", CAPTURES, ids=[p.name for p in CAPTURES])
def test_every_rendition_selector_resolves_against_the_bytes_it_names(path: Path) -> None:
    """The gap the 2026-09-19 architecture review found: the fragments were never resolved.

    Two XPaths selected nothing, and a multi-run leaf's byte range selected 93
    bytes of markup for 57 bytes of text. Each selector kind is resolved here
    against the document it addresses and compared with the leaf's own text.
    """
    capture = load(path)
    nodes = {n["id"]: n for n in capture["nodes"]}
    span_by_id = {s["id"]: s for s in capture["evidence"]}
    sizes = dc.page_sizes(capture)
    intermediate = capture["rendition"].get("intermediate")
    data = None if intermediate else (ROOT / capture["artifact"]["locator"]["path"]).read_bytes()
    checked = set()
    for entry in fragments_of(path):
        node = nodes[entry["node"]]
        text = dc.node_text(capture, node, span_by_id)
        literal = all(dc.effective_source(capture, span_by_id[s]).get("literal", True) for s in node["evidence"])
        for selector in entry["renditionFragment"]["oa:hasSelector"]:
            kind = selector["@type"]
            checked.add(kind)
            if kind == "oa:XPathSelector":
                etree = pytest.importorskip("lxml.etree")
                assert data is not None
                root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                found = root.xpath(selector["rdf:value"])
                assert len(found) == 1, (selector["rdf:value"], len(found))
                assert text.strip() in "".join(found[0].itertext())
            elif kind == "oa:TextPositionSelector":
                assert data is not None
                sliced = data[selector["oa:start"] : selector["oa:end"]].decode("utf-8")
                assert "<" not in sliced, "a byte range that spans markup is not this leaf's text"
                assert html.unescape(sliced) in text if not literal else sliced in text
            elif kind == "oa:FragmentSelector":
                assert "dcterms:conformsTo" in selector, "a permille box must not claim RFC 8118"
                page, viewrect = selector["rdf:value"].split("&")
                number = int(page.removeprefix("page="))
                width, height = sizes[number]
                x, y, w, h = (float(v) for v in viewrect.removeprefix("viewrect=").split(","))
                assert 0 <= x <= x + w <= width + 0.01, selector["rdf:value"]
                assert 0 <= y <= y + h <= height + 0.01, selector["rdf:value"]
    assert "oa:TextQuoteSelector" in checked
    if capture["rendition"]["kind"] == "pdf":
        assert "oa:FragmentSelector" in checked
    else:
        assert "oa:TextPositionSelector" in checked


# --- negative controls -----------------------------------------------------------


@pytest.mark.parametrize(
    "name,mutate",
    [
        ("partition", lambda d: d["evidence"][1].update(start=d["evidence"][1]["start"] + 1)),
        ("ownership", lambda d: [n["evidence"].clear() for n in d["nodes"][1:2]]),
        ("dangling evidence id", lambda d: d["nodes"][1]["evidence"].append("s9999")),
        ("kind namespace", lambda d: d["nodes"][1].__setitem__("kind", "other:Foo")),
        (
            "leaf text",
            lambda d: next(n for n in d["nodes"] if n.get("text")).__setitem__("text", "not this"),
        ),
        ("tree", lambda d: d["nodes"][-1].__setitem__("depth", 99)),
        (
            "span digest",
            lambda d: d["evidence"][0].__setitem__("sha256", "0" * 64),
        ),
    ],
)
def test_the_invariant_validator_names_each_defect(name: str, mutate) -> None:
    """Stubbing the three validators used to leave every test green; each now has a counterexample."""
    capture = load(CAPTURES[0])
    assert dc.check_invariants(capture) == []
    broken = copy.deepcopy(capture)
    mutate(broken)
    assert dc.check_invariants(broken), name


def test_the_schema_refuses_a_capture_whose_shape_moved(validators) -> None:
    parent, _, _ = validators
    for name, mutate in {
        "a rendition kind that is an extractor output": lambda d: d["rendition"].__setitem__("kind", "evidence-lines"),
        "an unknown node field": lambda d: d["nodes"][1].__setitem__("meaning", "a requirement"),
        "a page size in an unstated unit": lambda d: d["nodes"][1].__setitem__(
            "pageSize", {"width": 612, "height": 792, "unit": "permille"}
        ),
    }.items():
        broken = copy.deepcopy(load(CAPTURES[0]))
        mutate(broken)
        assert [e.message for e in parent.iter_errors(broken)], name


def test_the_fragment_validator_refuses_a_moved_digest(validators) -> None:
    _, _, fragment_validator = validators
    fragments = copy.deepcopy(fragments_of(CAPTURES[0]))
    assert dc.validate_fragments(fragments, fragment_validator) == []
    fragments[0]["streamFragment"]["rkaf:fragmentContentDigest"] = "not-a-digest"
    assert dc.validate_fragments(fragments, fragment_validator)


# --- what each family reads off its own rendition ---------------------------------


def test_family_kinds_stay_inside_their_profile_namespace() -> None:
    core = dc.core_kinds()
    for path in CAPTURES:
        capture = load(path)
        for node in capture["nodes"]:
            prefix, _, _ = node["kind"].partition(":")
            assert node["kind"] in core or prefix == capture["profile"]["name"], (path.name, node["kind"])


def test_the_slip_opinion_names_its_two_opinions_and_their_printed_pages() -> None:
    """The print marks the division three ways; the capture reads two of them and compares."""
    capture = load(OUTPUT / "scotus-26a274_l537.capture.json")
    assert [o["kind"] for o in capture["profile"]["ext"]["opinions"]] == [
        "slip-opinion-pdf:perCuriam",
        "slip-opinion-pdf:dissent",
    ]
    assert capture["profile"]["ext"]["opinions"][0]["pages"] == [1, 2, 3, 4]
    assert capture["profile"]["ext"]["opinions"][1] == {
        "kind": "slip-opinion-pdf:dissent",
        "pages": [5],
        "author": "JACKSON",
    }
    pages = [n for n in capture["nodes"] if n["kind"] == "page"]
    # The dissent restarts the printed numbering; the designation is what the
    # page prints and the PDF ordinal travels in ext.
    assert [p["designation"] for p in pages] == ["1", "2", "3", "4", "1"]
    assert [p["ext"]["pdfOrdinal"] for p in pages] == [1, 2, 3, 4, 5]
    assert all(p["pageSize"] == {"width": 612.0, "height": 792.0, "unit": "point"} for p in pages)
    assert not any(n["kind"] == "line" and not n["text"].strip() for n in capture["nodes"])


def test_the_committee_report_reads_its_ruled_vote_tables_and_centred_heads() -> None:
    capture = load(OUTPUT / "crpt-119hrpt1.capture.json")
    kinds = [n["kind"] for n in capture["nodes"]]
    assert kinds.count("table") == 4
    assert kinds.count("committee-report-html:heading") >= 6
    header = [n for n in capture["nodes"] if n["kind"] == "cell" and n["cell"]["row"] == 0][:4]
    assert [n["text"] for n in header] == ["Majority Members", "Vote", "Minority Members", "Vote"]
    assert all(n["cell"]["header"] for n in header)


def test_back_matter_and_levels_read_the_same_way_in_every_family() -> None:
    for path in CAPTURES:
        capture = load(path)
        for node in capture["nodes"]:
            if node["kind"] == "heading":
                assert node.get("level", 1) >= 1, (path.name, node["id"])
            if node["kind"] == "line" and not node.get("text", "x").strip():
                assert any(i["code"] == "empty-leaf" for i in node.get("issues", ())), (path.name, node["id"])
    with_back_matter = {
        load(p)["profile"]["name"] for p in CAPTURES if any(n["kind"] == "backMatter" for n in load(p)["nodes"])
    }
    assert {"uslm-law", "bill-xml", "federal-register-xml"} <= with_back_matter


def test_the_publishers_own_page_label_error_travels_as_an_issue() -> None:
    """GovInfo labels PLAW-119publ1's four page markers STAT. 3, 4, 4, 5; the print runs 3 to 6."""
    capture = load(OUTPUT / "plaw-119publ1.capture.json")
    flagged = [
        n
        for n in capture["nodes"]
        if n["kind"] == "pageNumber" and any(i["code"].startswith("page-designation") for i in n.get("issues", ()))
    ]
    assert [n["designation"] for n in flagged] == ["139 STAT. 4"]
