"""The citation rules and the two activity reports they are pinned on.

Each rule rejects its own lookalikes; re-reading normalized text at every
finding's offsets returns the matched text, and page attribution agrees with an
independently computed page map; and the library reproduces the 2026-09-20
rollup sidecar's per-print counts (179 distinct bills, 3 public laws, 9 printed
committee candidates of which 8 resolve). Fixtures are two of the eight reports
that measurement read, rebuilt from its retained bytes, never re-fetched.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from spicy_docs.interpretation.citations import (
    CITATION_RULE_SET_VERSION,
    CITATION_RULES,
    CITATION_RULES_BY_NAME,
    DOCUMENT_CITATION_KINDS,
    CitationError,
    canonical_alnum,
    committee_vocabulary,
    congress_subheading_scopes,
    find_citations,
    named_chamber,
    page_starts,
    rejected_lookalikes,
    resolve_committee_names,
)
from spicy_docs.schemas.document_citation_tables import index_stated_keys
from spicy_docs.sources.congress.committee_rosters import parse_house_member_data, parse_senate_cvc
from spicy_docs.sources.govinfo.activity_reports import covered_congress
from spicy_docs.sources.govinfo.bodies import (
    ModsLaw,
    ModsUsCodeSection,
    package_mods_locator,
    package_summary_locator,
    validate_package_mods,
    validate_package_summary,
)

FIXTURES = Path(__file__).parent / "fixtures"
CITATION_FIXTURES = FIXTURES / "document_citations"
ROSTERS = FIXTURES / "congress_rosters"

#: The activity report the rollup sidecar's own per-document numbers are
#: quoted against below, and the truncated one beside it.
DENSE = "CRPT-118hrpt968"
TRUNCATED = "CRPT-118hrpt965"


@dataclass(frozen=True, slots=True)
class FixtureBody:
    """A ``BodyText``'s three facts, rebuilt from the retained text and its page map.

    Structural on purpose: what ``rendition_text`` would produce for these
    bytes is what the rollup already produced and retained, and re-running
    PyMuPDF in a unit test would make the test a PDF-library test.
    ``test_the_retained_text_is_the_one_the_measurement_read`` is what holds
    the two equal.
    """

    text: str
    pages: tuple[str, ...]
    rendition: str = "pdf"
    derivation: str = "pdf-extraction-gpo-normalized"


def provenance(package: str) -> dict:
    """The fixture's recorded provenance sidecar."""
    return json.loads((CITATION_FIXTURES / f"{package}.json").read_text())


def body_for(package: str) -> FixtureBody:
    """The retained normalized text, split back into pages by the recorded lengths."""
    text = (CITATION_FIXTURES / f"{package}.txt").read_text()
    pages: list[str] = []
    cursor = 0
    for length in provenance(package)["page_lengths"]:
        pages.append(text[cursor : cursor + length])
        cursor += length + 1
    return FixtureBody(text=text, pages=tuple(pages))


def summary_for(package: str):
    """The retained package summary for a package id."""
    return validate_package_summary(
        (CITATION_FIXTURES / f"summary-{package}.json").read_bytes(),
        package=package,
        final_url=package_summary_locator(package),
        max_bytes=1_000_000,
    )


def mods_for(package: str):
    """The retained package MODS for a package id."""
    return validate_package_mods(
        (CITATION_FIXTURES / f"mods-{package}.xml").read_bytes(),
        package=package,
        final_url=package_mods_locator(package),
        max_bytes=1_000_000,
    )


def rosters(chamber: str = "house", *, own_only: bool = False) -> tuple[tuple[str, str], ...]:
    """The pinned chamber rosters, read through this repository's own readers, for one chamber's print.

    The House file is the complete ``<committees>`` block; the Senate excerpt
    states only the committees its sampled senators sit on, so anything it
    does not reach stays unresolved rather than being guessed at. Both
    fixture reports are House committees' (``hrpt``).
    """
    house = parse_house_member_data((ROSTERS / "memberdata-119-excerpt.xml").read_bytes(), congress=119)
    senate = parse_senate_cvc((ROSTERS / "cvc-member-data-excerpt.xml").read_bytes())
    return committee_vocabulary(house=(house,), senate=(senate,), chamber=chamber, own_only=own_only)


def covered_for(package: str):
    """The Congress a fixture report says it covers, read the way a host reads it: title, cover, front matter."""
    return covered_congress(summary_for(package).title, body_for(package).pages)


def citations_for(package: str):
    """Every citation the shared rules find in a fixture's retained text, read as a host reads a House report."""
    body = body_for(package)
    return find_citations(
        body.text,
        pages=body.pages,
        congress=covered_for(package).congress,
        committees=rosters(),
        chamber_committees={chamber: rosters(chamber, own_only=True) for chamber in ("house", "senate")},
    )


# ---------------------------------------------------------------------------
# The rules themselves.
# ---------------------------------------------------------------------------


def test_every_rule_rejects_its_own_lookalikes() -> None:
    """Every rule rejects every string in its own lookalike list."""
    assert rejected_lookalikes() == {}


PATTERN_RULES = tuple(rule for rule in CITATION_RULES if rule.reader is None)
#: The kinds the shared grammar reads (citation_grammar and identifier_shapes).
GRAMMAR_KINDS = (
    "public_law",
    "statutes_at_large",
    "usc_section",
    "cfr_section",
    "federal_register_cite",
    "rin",
    "docket_number",
)


@pytest.mark.parametrize("rule", PATTERN_RULES, ids=lambda rule: rule.name)
def test_a_rule_matches_one_string_and_not_a_tuple_of_groups(rule) -> None:
    """No capturing group, so ``findall`` and ``finditer`` agree about what matched.

    The measurement reads matches with ``findall``, which returns tuples as
    soon as a pattern captures; this table alone keeps the two readers'
    answers the same string.  A rule needing the parts reads them in its own
    target function.
    """
    assert rule.compiled().groups == 0


@pytest.mark.parametrize("rule", CITATION_RULES, ids=lambda rule: rule.name)
def test_every_rule_states_a_version_a_merge_can_order(rule) -> None:
    """Zero-padded decimal: the published column is a string, so ``v10 < v2``."""
    assert re.fullmatch(r"\d{3}", rule.version), rule.version


def test_the_rules_whose_published_keys_changed_moved_their_version() -> None:
    """Ten rules have changed which keys they publish, and each moved its version.

    ``us_reports_cite`` gained a target reader, publishing ``600-183`` rather
    than its measurement-comparison form. The seven grammar kinds read
    through the shared grammar since 2026-09-23, which respells, splits and
    newly reads keys; ``rin`` and ``docket_number`` had already moved once
    for their own target readers. ``bill_number`` 002 refuses a designator
    after a letter and a period (``R.S. 2477``), 003 a number carrying a
    subdivision (``CLAUSE S 2(N)``) or a year heading wrapped under a
    designator (``S. Con. Res.\n2022:``), and 004 keys a bill printed under a
    Congress subheading (``116th Congress``) in that Congress. ``committee_name`` 002 reads a
    chamber the print names before a committee. In every case the procedure
    applied: move the version, re-pin the digests, re-pin the fixture counts.
    """
    moved = {rule.name: rule.version for rule in CITATION_RULES if rule.version != "001"}
    assert moved == {
        "us_reports_cite": "002",
        "bill_number": "004",
        "public_law": "003",
        "statutes_at_large": "002",
        "usc_section": "003",
        "cfr_section": "003",
        "federal_register_cite": "002",
        "rin": "004",
        "docket_number": "003",
        "committee_name": "002",
    }
    assert {rule.name for rule in CITATION_RULES if rule.reader is not None} == set(GRAMMAR_KINDS)


def test_the_rule_set_version_is_pinned_to_these_rules() -> None:
    """Editing a pattern or a reject moves this digest even when the version is forgotten.

    The digest is derived from every rule's name, version, pattern and
    rejects, so this assertion is the gate: a rule change fails here, and the
    fix is to move that rule's ``version`` and re-pin the fixture counts below
    (``docs/decisions.md``).  The rejects are in the input because a deleted
    reject is a silent weakening -- removing three of ``public_law``'s once
    passed the whole suite, since a reject that is no longer asserted cannot
    fail.
    """
    assert CITATION_RULE_SET_VERSION == "a357ba180082"


def test_the_stored_kinds_are_every_rule_that_reaches_a_key() -> None:
    """Thirteen of the sixteen, and the three left out each for its own reason.

    ``rin`` and ``docket_number`` are stored because the MODS re-check found
    them to be the activity reports' largest real yield -- 87 RINs and 38
    agency dockets across the eight prints, none in any CRPT MODS -- where the
    bills and laws the rollup led with are all already stated.
    """
    names = {rule.name for rule in CITATION_RULES}
    assert set(DOCUMENT_CITATION_KINDS) <= names
    # A printed identifier no publisher prints, and two quantities that
    # address nothing.
    assert names - set(DOCUMENT_CITATION_KINDS) == {"bioguide_id", "dollar_amount", "fiscal_year"}
    assert {"rin", "docket_number"} <= set(DOCUMENT_CITATION_KINDS)


#: A retained sample of the parsing survey's Federal Register titles and
#: abstracts, chosen for the shapes the grammar kinds read (README beside it).
GRAMMAR_SPECIMENS = CITATION_FIXTURES / "grammar-specimens.jsonl"
A10_REGRESSIONS = json.loads((CITATION_FIXTURES / "a10-regressions.json").read_text())


def grammar_fixture_texts() -> list[str]:
    """Every committed text a grammar kind is pinned over: both activity reports, both budget volumes, the specimens."""
    from tests.test_budget_volumes import BEYOND_CAP, WHOLE
    from tests.test_budget_volumes import body_for as budget_body

    specimens = [json.loads(line)["text"] for line in GRAMMAR_SPECIMENS.read_text(encoding="utf-8").splitlines()]
    return [
        body_for(DENSE).text,
        body_for(TRUNCATED).text,
        budget_body(WHOLE).text,
        budget_body(BEYOND_CAP).text,
        *specimens,
        *(case["text"] for case in A10_REGRESSIONS),
    ]


@pytest.mark.parametrize("case", A10_REGRESSIONS, ids=lambda case: f"{case['source']}-{case['kind']}")
def test_production_citation_regressions(case: dict) -> None:
    """Source snippets retained by the 2026-09-24 print-citations audit."""
    findings = find_citations(case["text"], kinds=(case["kind"],))
    assert [finding.target_key for finding in findings] == case["keys"]
    assert all(finding.target_resolved for finding in findings)
    assert all(case["text"][finding.span_start : finding.span_end] == finding.matched_text for finding in findings)


PRINT_CITATIONS_2026_09_26 = json.loads(
    (CITATION_FIXTURES / "print-citations-2026-09-26.json").read_text(encoding="utf-8")
)
BILL_SNIPPETS_2026_09_26 = PRINT_CITATIONS_2026_09_26["bill_snippets"]
PRINT_SUBHEADINGS = CITATION_FIXTURES / "print-subheadings-2026-09-26.json"
SUBHEADING_SNIPPETS = json.loads(PRINT_SUBHEADINGS.read_text(encoding="utf-8"))["subheading_snippets"]


@pytest.mark.parametrize("case", BILL_SNIPPETS_2026_09_26, ids=lambda case: f"{case['package']}-{case['span_start']}")
def test_the_2026_09_26_misreads_are_refused_and_their_nearest_true_readings_kept(case: dict) -> None:
    """``CLAUSE S 2(N)`` and ``S. Con. Res.\\n2022:`` name no bill; a wrapped ``H.R.\\n2021`` and ``H.R. 7593:`` do.

    Every snippet's ``keys`` were stated by reading it, not by running the
    rule, and they are every bill it names, so a refusal that widened past its
    one shape would drop a key here.
    """
    findings = find_citations(case["text"], kinds=("bill_number",), congress=case["covered_congress"])
    assert [finding.target_key for finding in findings] == case["keys"]
    assert all(finding.target_resolved for finding in findings)
    assert all(case["text"][finding.span_start : finding.span_end] == finding.matched_text for finding in findings)


@pytest.mark.parametrize("case", SUBHEADING_SNIPPETS, ids=lambda case: case["id"])
def test_a_congress_subheading_keys_the_bills_under_it_until_the_next_entry(case: dict) -> None:
    """``116th Congress`` over a bill's history keys the bills under it in the 116th, and the next entry is not under it.

    Real report lines (``print-subheadings-2026-09-26.json``): a subheading ended
    by another and then by an entry heading naming a law, the join-gaps orphan
    ``117-hr-5119``, bills restated as a paragraph's subject that stay in scope,
    a committee-history section with its law table, a wrapped heading's tail
    that is no subheading, and ``Prior Congresses``, which ends a scope. Each
    snippet's ``keys`` were read from it, except the ``floor`` entries: bills
    under ``Prior Congresses`` whose Congress the print states inline, which
    this rule does not read, so they keep the document's.
    """
    findings = find_citations(case["text"], kinds=("bill_number",), congress=case["covered_congress"])
    assert [finding.target_key for finding in findings] == case["keys"]
    assert all(finding.target_resolved for finding in findings)
    assert all(case["text"][finding.span_start : finding.span_end] == finding.matched_text for finding in findings)
    for reading, index in case.get("floor", ()):
        assert findings[index].target_key.split("-", 1) == [str(case["covered_congress"]), reading.split("-", 1)[1]]


@pytest.mark.parametrize(
    "text",
    [
        *("\n".join(case["pages"]) for case in PRINT_CITATIONS_2026_09_26["covered"]),
        *(case["text"] for case in SUBHEADING_SNIPPETS if case["id"] == "wrapped-heading-tail"),
    ],
    ids=[*(case["package"] for case in PRINT_CITATIONS_2026_09_26["covered"]), "wrapped-heading-tail"],
)
def test_filing_headers_roster_headings_and_wrapped_phrases_open_no_scope(text: str) -> None:
    """``118TH CONGRESS``, ``ONE HUNDRED EIGHTEENTH CONGRESS``, ``(118th Congress)`` and a heading's wrapped tail.

    The first three are a Senate report's filing header and roster headings,
    naming the Congress after the one its bills belong to; read as subheadings
    they would undo ``covered_congress`` for every bill after page one.
    """
    assert congress_subheading_scopes(text) == ()


def test_the_committed_activity_reports_state_no_subheading() -> None:
    """Neither full-text fixture prints one, so the counts pinned on them below cannot move with this rule."""
    assert congress_subheading_scopes(body_for(DENSE).text) == ()
    assert congress_subheading_scopes(body_for(TRUNCATED).text) == ()


@pytest.mark.parametrize(
    "text", ["A6013-Public Law 114-254", "pre-6013-Pub. L. 114-254", "6012-6013-Public Law 114-254"]
)
def test_public_law_label_does_not_start_inside_a_word_compound(text: str) -> None:
    assert find_citations(text, kinds=("public_law",)) == ()


@pytest.mark.parametrize("text", ["30 CFR 1940-G", "30 CFR 1940–G"])
def test_a_hyphenated_subpart_is_not_a_bare_part(text: str) -> None:
    assert find_citations(text, kinds=("cfr_section",)) == ()


def test_repeated_part_mentions_keep_separate_occurrences() -> None:
    text = "30 CFR 250 subparts D, E, F, and Q; later 30 CFR 250 subpart D."
    findings = find_citations(text, kinds=("cfr_section",))
    assert [finding.target_key for finding in findings] == ["30-250", "30-250"]
    assert findings[0].span_end < findings[1].span_start


@pytest.mark.parametrize("text", ["22 U.S.C. 2151p1(f)", "22 U.S.C. 286e2(a)", "21 U.S.C. 379-j31"])
def test_damaged_section_evidence_survives_without_a_link_to_its_prefix(text: str) -> None:
    from spicy_docs.interpretation.citation_grammar import find_usc_citations

    (occurrence,) = find_usc_citations(text)
    assert occurrence.text == text
    assert occurrence.refusal == "usc_coordinate_continuation_unresolved"
    assert find_citations(text, kinds=("usc_section",)) == ()


def test_unread_scope_keeps_its_unresolved_coordinate() -> None:
    (finding,) = find_citations("44 U.S.C. 3508(copyright)(2)(A)", kinds=("usc_section",))
    assert finding.target_key == "44-3508"
    assert not finding.target_resolved


def grammar_reading() -> dict[str, tuple[str, str]]:
    """Per grammar kind: its rule version, and a digest of everything it reads over the committed texts."""
    lines: dict[str, list[str]] = {kind: [] for kind in GRAMMAR_KINDS}
    for index, text in enumerate(grammar_fixture_texts()):
        for f in find_citations(text, kinds=GRAMMAR_KINDS):
            lines[f.kind].append(f"{index}|{f.span_start}|{f.span_end}|{f.target_key}|{f.target_resolved}")
    return {
        kind: (CITATION_RULES_BY_NAME[kind].version, hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16])
        for kind, rows in lines.items()
    }


#: What each grammar kind reads over the committed texts, at its version. The
#: rule-set digest above sees a grammar kind's reader only by name, so a change
#: inside ``citation_grammar`` or ``identifier_shapes`` moves nothing there;
#: this is what catches it.
PINNED_GRAMMAR_READING = {
    "public_law": ("003", "c88e99a4d7752d5d"),
    "statutes_at_large": ("002", "ec88c4ad033cbbf0"),
    "usc_section": ("003", "2b33e21e303a3be0"),
    "cfr_section": ("003", "ad16a44f020d1ed6"),
    "federal_register_cite": ("002", "7c1ec1de2286fb0e"),
    "rin": ("004", "5199b682929eb361"),
    "docket_number": ("003", "71c8b621b8e6e5fe"),
}


def test_a_grammar_change_moves_the_rule_version() -> None:
    """A change in what a grammar kind reads must come with a new version of that kind.

    The procedure when this fails: if the digest moved and the version did
    not, move that rule's ``version`` in ``interpretation/citations.py`` (the
    published rows change, and the merge must prefer them); then re-pin both
    here, and the rule-set digest above.
    """
    for kind, (version, digest) in grammar_reading().items():
        pinned_version, pinned_digest = PINNED_GRAMMAR_READING[kind]
        if digest != pinned_digest and version == pinned_version:
            pytest.fail(
                f"{kind}: the grammar reads the committed fixtures differently (digest {digest}, pinned "
                f"{pinned_digest}) -- move the rule version of {kind} in interpretation/citations.py, then re-pin"
            )
        assert (version, digest) == (pinned_version, pinned_digest), f"{kind}: re-pin to ({version!r}, {digest!r})"


def test_the_grammar_pin_reads_every_grammar_kind() -> None:
    """A kind that reads nothing over the fixtures would pin an empty digest and guard nothing."""
    counts = {kind: 0 for kind in GRAMMAR_KINDS}
    for text in grammar_fixture_texts():
        for f in find_citations(text, kinds=GRAMMAR_KINDS):
            counts[f.kind] += 1
    assert min(counts.values()) >= 10, counts


def test_a_reject_check_that_never_bit_would_be_worthless() -> None:
    """Prove the rejection check can fail, by widening one rule of each reading until it does."""
    from dataclasses import replace

    widened = replace(CITATION_RULES_BY_NAME["bill_number"], pattern=r"S")
    assert [candidate for candidate in widened.rejects if widened.reads(candidate)]
    # A grammar-read rule is held to its rejects by what the grammar reads.
    lax = replace(CITATION_RULES_BY_NAME["usc_section"], rejects=("42 U.S.C. 7401",))
    assert [candidate for candidate in lax.rejects if lax.reads(candidate)] == ["42 U.S.C. 7401"]


def test_a_rule_is_read_one_way() -> None:
    """A pattern and a grammar reader together, or neither, is refused at construction."""
    from dataclasses import replace

    with pytest.raises(CitationError, match="exactly one"):
        replace(CITATION_RULES_BY_NAME["usc_section"], pattern=r"U\.S\.C")
    with pytest.raises(CitationError, match="not by a pattern"):
        CITATION_RULES_BY_NAME["usc_section"].compiled()


def test_deleting_a_reject_moves_the_rule_set_digest() -> None:
    """The gate above only bites if the rejects are part of what it hashes."""
    from dataclasses import replace

    from spicy_docs.interpretation.citations import _rule_set_version

    weakened = tuple(
        replace(rule, rejects=rule.rejects[:1]) if rule.name == "public_law" else rule for rule in CITATION_RULES
    )
    assert _rule_set_version(weakened) != CITATION_RULE_SET_VERSION


# ---------------------------------------------------------------------------
# Spans and pages.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", [DENSE, TRUNCATED])
def test_every_span_re_reads_as_its_own_matched_text(package: str) -> None:
    """Re-reading the normalized text at each finding's offsets returns its matched text."""
    body = body_for(package)
    findings = citations_for(package)
    assert findings
    for finding in findings:
        assert body.text[finding.span_start : finding.span_end] == finding.matched_text


@pytest.mark.parametrize("package", [DENSE, TRUNCATED])
def test_the_page_a_span_is_attributed_to_is_the_page_holding_it(package: str) -> None:
    """Checked against a second, independent page map, not against ``page_starts``.

    Walking the pages and asking which one's own text contains the offset is a
    different computation from the bisect the finder runs, so the two agreeing
    is a witness rather than a restatement.
    """
    body = body_for(package)
    bounds = []
    cursor = 0
    for number, page in enumerate(body.pages, start=1):
        bounds.append((number, cursor, cursor + len(page)))
        cursor += len(page) + 1
    for finding in citations_for(package):
        expected = next(number for number, start, end in bounds if start <= finding.span_start < end)
        assert finding.page == expected, finding


def test_a_rendition_with_no_page_boundary_reports_no_page() -> None:
    """Without a page map, findings report no page and an unresolved key."""
    findings = find_citations("The Committee reported H.R. 471 to the House.", congress=119)
    assert [finding.page for finding in findings] == [None]
    assert findings[0].target_key == "119-hr-471"


def test_a_page_split_that_does_not_rejoin_is_refused() -> None:
    """A wrong page map would mis-attribute every span, and silently."""
    with pytest.raises(CitationError, match="rejoin"):
        find_citations("H.R. 471 and S. 5", pages=("H.R. 471", "and S. 6"))


def test_page_starts_is_the_join_it_claims_to_be() -> None:
    """page_starts offsets rejoin the pages exactly."""
    pages = ("alpha", "", "gamma")
    starts = page_starts(pages)
    text = "\n".join(pages)
    assert starts == (0, 6, 7)
    assert [text[start : start + len(page)] for start, page in zip(starts, pages, strict=True)] == list(pages)


# ---------------------------------------------------------------------------
# Target keys.
# ---------------------------------------------------------------------------


def test_a_bill_key_is_built_only_from_a_stated_congress() -> None:
    """A print never writes the Congress, so guessing one would invent a join."""
    (with_congress,) = find_citations("H.R. 7806", kinds=("bill_number",), congress=118)
    assert (with_congress.target_key, with_congress.target_resolved) == ("118-hr-7806", True)
    (without,) = find_citations("H.R. 7806", kinds=("bill_number",))
    assert (without.target_key, without.target_resolved) == ("HR7806", False)


@pytest.mark.parametrize(
    ("printed", "expected"),
    [
        ("S. Res. 21", "119-sres-21"),
        ("S. 21", "119-s-21"),
        ("H. Con. Res. 7", "119-hconres-7"),
        ("H.J. Res. 164", "119-hjres-164"),
    ],
)
def test_the_bill_type_split_prefers_the_longer_name(printed: str, expected: str) -> None:
    """Bill-type splitting prefers the longer type name."""
    (finding,) = find_citations(printed, kinds=("bill_number",), congress=119)
    assert finding.target_key == expected


@pytest.mark.parametrize(
    ("kind", "printed", "expected"),
    [
        ("public_law", "Pub. L. No. 89-136", "89-public-136"),
        ("public_law", "Public Law 117-263", "117-public-263"),
        ("usc_section", "2 U.S.C. 190", "2-190"),
        ("cfr_section", "40 C.F.R. part 60", "40-60"),
        ("federal_register_cite", "88 Fed. Reg. 12,345", "88-12345"),
        ("gao_product_id", "GAO-24-106221", "GAO-24-106221"),
        ("crs_report_id", "R49351", "R49351"),
        ("case_docket_number", "No. 24-1260", "24-1260"),
        # The three whose stored key is the publisher's spelling and not the
        # measurement's comparison form.
        ("rin", "RIN 3133-AF97", "3133-AF97"),
        ("docket_number", "FAA-2016-6907", "FAA-2016-6907"),
        ("us_reports_cite", "600 U. S. 183", "600-183"),
        ("statutes_at_large", "136 Stat. 1234", "136-1234"),
    ],
)
def test_each_kind_reaches_its_stated_key_shape(kind: str, printed: str, expected: str) -> None:
    """Each kind's target key matches its documented shape and resolves."""
    (finding,) = find_citations(printed, kinds=(kind,))
    assert (finding.target_key, finding.target_resolved) == (expected, True)


# The four grammar kinds. Every specimen was read off a 001 key the published
# ``document_citations`` held or a cite the 001 patterns missed in the 60,000
# Federal Register titles and abstracts the parsing survey retained
# (``docs/research/parsing-survey-2026-09-23.md`` sections 2 and 5).


@pytest.mark.parametrize(
    ("kind", "printed", "keys"),
    [
        # 001 kept the sentence's period, and a dangling hyphen, in the key.
        ("cfr_section", "40 CFR 60.5.", ["40-60.5"]),
        ("usc_section", "5 U.S.C. 552.", ["5-552"]),
        ("usc_section", "Paperwork Reduction Act (44 U.S.C. 3506(C)(2)(A)).", ["44-3506"]),
        # 001 published a range as one token; the grammar states both ends,
        # and an en dash is the same dash.
        ("usc_section", "42 U.S.C. 7401-7671q", ["42-7401", "42-7671q"]),
        ("usc_section", "42 U.S.C. 7401\u20137671q", ["42-7401", "42-7671q"]),
        ("usc_section", "16 U.S.C. 1531 through 1544", ["16-1531", "16-1544"]),
        ("cfr_section", "40 CFR 60.1 through 60.5", ["40-60.1", "40-60.5"]),
        ("cfr_section", "40 CFR parts 1500 through 1508", ["40-1500", "40-1508"]),
        # 001 read only lower-case singular "part".
        ("cfr_section", "40 CFR Part 60", ["40-60"]),
        ("cfr_section", "40 CFR PART 60", ["40-60"]),
        ("cfr_section", "24 CFR parts 813 and 913", ["24-813", "24-913"]),
        ("cfr_section", "40 CFR Parts 60, 61, and 63", ["40-60", "40-61", "40-63"]),
        ("cfr_section", "part 60 of title 40, Code of Federal Regulations", ["40-60"]),
        # A compound section name is one section, not a range.
        ("usc_section", "42 U.S.C. 1395w-4", ["42-1395w-4"]),
        ("cfr_section", "46 CFR 1.01-15", ["46-1.01-15"]),
        # An appendix is a different place, spelled the way law_code_sections spells it.
        ("usc_section", "50 U.S.C. app. 2401", ["50A-2401"]),
        # Spellings 001 missed.
        ("public_law", "Public Law 92- 463", ["92-public-463"]),
        # A zero pad is read through, not refused: 111-5 is the Recovery Act.
        ("public_law", "(Pub. L. 111-05, approved February 17, 2009)", ["111-public-5"]),
        ("public_law", "Pub. L. 111-008", ["111-public-8"]),
        ("public_law", "PUBLIC LAW 91\u2013510", ["91-public-510"]),
        ("statutes_at_large", "86 Stat.770", ["86-770"]),
        ("statutes_at_large", "116 Stat 2962", ["116-2962"]),
        ("statutes_at_large", "113 Stat. 1501A-293", ["113-1501A-293"]),
        ("statutes_at_large", "114 Stat. 2763A-326 to 2763A-328", ["114-2763A-326", "114-2763A-328"]),
        ("statutes_at_large", "70A Stat. 157", ["70A-157"]),
    ],
)
def test_a_grammar_kind_publishes_keys_that_are_citations(kind: str, printed: str, keys: list[str]) -> None:
    """Each key is clean, resolved, and one per endpoint; endpoints of one range share one span."""
    findings = find_citations(printed, kinds=(kind,))
    assert [f.target_key for f in findings] == keys
    assert all(f.target_resolved for f in findings)
    assert len({(f.span_start, f.span_end) for f in findings if f.matched_text == findings[0].matched_text}) == 1


@pytest.mark.parametrize(
    ("kind", "printed", "keys"),
    [
        # A hyphen between two parts is ambiguous to the grammar -- real
        # section numbers carry one -- so the printed token stands, unresolved.
        ("cfr_section", "40 CFR Part 1500-1508", [("40-1500-1508", False)]),
        # An abbreviated span's end was expanded, not printed.
        ("usc_section", "20 U.S.C. 1484-86", [("20-1484", True), ("20-1486", False)]),
        # A title that cannot exist, and a part longer than any real part.
        ("cfr_section", "99 CFR 12", [("99-12", False)]),
        ("cfr_section", "42 CFR 412106", [("42-412106", False)]),
        ("usc_section", "99 U.S.C. 12", [("99-12", False)]),
        # A law number before the numbered series is damage, not a law --
        # read, so the print's evidence is kept, but never a resolved join.
        ("public_law", "Pub. L. 4-13", [("4-public-13", False)]),
        ("public_law", "(Pub. L. 04-13)", [("4-public-13", False)]),
        # "et seq." is scope, not a doubt about the section it follows.
        ("usc_section", "42 U.S.C. 7401 et seq.", [("42-7401", True)]),
    ],
)
def test_a_key_the_grammar_doubts_is_published_unresolved(kind: str, printed: str, keys: list) -> None:
    """Kept as evidence, as every unsettled key is, but never as a resolved join."""
    assert [(f.target_key, f.target_resolved) for f in find_citations(printed, kinds=(kind,))] == keys


@pytest.mark.parametrize(
    ("kind", "printed"),
    [
        ("cfr_section", "under 40 CFR 60- and"),  # 001 published "40-60-"
        ("cfr_section", "Title 40 CFR"),
        ("usc_section", "42 U.S.C. chapter 85"),
    ],
)
def test_a_cite_with_no_readable_coordinate_has_no_key(kind: str, printed: str) -> None:
    """Nothing is published where the grammar read no coordinate, rather than a malformed key."""
    assert find_citations(printed, kinds=(kind,)) == ()


# The four shapes the grammar read as no coordinate, or as a range's first
# endpoint alone, until 2026-09-23 -- counts over the parsing survey's 60,000
# Federal Register titles and abstracts.


@pytest.mark.parametrize(
    ("kind", "printed", "keys"),
    [
        # A part followed by its printed heading (155 part citations; em dash
        # folds to one hyphen) and a section likewise (8, which read the
        # heading into the section).
        ("cfr_section", "30 CFR part 886--State and Tribal Reclamation Grants", ["30-886"]),
        ("cfr_section", "10 CFR part 33-Specific Domestic Licenses", ["10-33"]),
        ("cfr_section", "10 CFR Part 34-- Licenses for Industrial Radiography", ["10-34"]),
        ("cfr_section", "10 CFR Part 33\u2014Specific Domestic Licenses", ["10-33"]),
        ("cfr_section", "30 CFR 77.1901--Reporting", ["30-77.1901"]),
        # A hyphen then a space inside a part (66): a title-41 compound, and a
        # plural label's range.
        ("cfr_section", "Per 41 CFR 102- 3.140(d), any oral presentations", ["41-102-3.140"]),
        ("cfr_section", "the CEQ regulations at 40 CFR Parts 1500- 1508", ["40-1500", "40-1508"]),
        # A doubled dash (27) and a one-sided spaced dash (81) between two
        # U.S. Code sections: a range, both ends read.
        ("usc_section", "Paperwork Reduction Act of 1995, 44 U.S.C. 3501--3520.", ["44-3501", "44-3520"]),
        ("usc_section", "42 USC 4321--4347 (NEPA)", ["42-4321", "42-4347"]),
        ("usc_section", "the Act, 21 U.S.C. 1901- 1908, authorizes", ["21-1901", "21-1908"]),
        # The same lost space inside one section's name (30 such keys): one
        # section, not a range's first endpoint left unresolved.
        ("usc_section", "under 16 U.S.C. 460l- 9 and", ["16-460l-9"]),
        ("usc_section", "42 U.S.C. 288- 5", ["42-288-5"]),
        ("usc_section", "42 U.S.C. 300ff- 51--300ff-67", ["42-300ff-51", "42-300ff-67"]),
        ("usc_section", "Civil Rights Act of 1964, 42 U.S.C. 2000d- 2000d-42, as amended", ["42-2000d", "42-2000d-42"]),
        # A comma page before another comma is a page.
        ("federal_register_cite", "88 Fed. Reg. 12,345, 12,350 (Mar. 1, 2023)", ["88-12345"]),
        ("federal_register_cite", "85 FR 43,304, the agency", ["85-43304"]),
    ],
)
def test_the_shapes_the_grammar_used_to_drop_are_read(kind: str, printed: str, keys: list[str]) -> None:
    """Each is read, resolved, and spanned without its heading or its trailing punctuation."""
    findings = find_citations(printed, kinds=(kind,))
    assert [(f.target_key, f.target_resolved) for f in findings] == [(key, True) for key in keys]


def test_a_heading_is_not_part_of_the_span() -> None:
    """The span ends at the coordinate, so the matched text is the citation, not its heading."""
    (finding,) = find_citations("30 CFR part 886--State and Tribal Reclamation Grants", kinds=("cfr_section",))
    assert finding.matched_text == "30 CFR part 886"


@pytest.mark.parametrize(
    ("kind", "printed", "keys"),
    [
        # 002 cut the docket at its first all-letter segment, and read an ITC
        # investigation as one.
        ("docket_number", "Docket No. EPA-HQ-OAR-2004-0015.", ["EPA-HQ-OAR-2004-0015"]),
        ("docket_number", "Docket Number CERCLA-02-2011-2003 (referred", ["CERCLA-02-2011-2003"]),
        ("docket_number", "investigation Nos. 731-TA-1199-1200 (Preliminary)", []),
        # A Regulations.gov document id names a document, not a docket.
        ("docket_number", "comment EPA-HQ-OAR-2004-0015-0001", []),
        # The Register's own spelling, which 001 did not read.
        ("federal_register_cite", "published at 89 FR 12345 on", ["89-12345"]),
        ("federal_register_cite", "(60 FR 17388), HUD published", ["60-17388"]),
        # Every RIN in a list, labelled once; a damaged or placeholder one is
        # found and never keyed.
        (
            "rin",
            "under RINs 1018-AU04, 1018-AU09, 1018-AU13, and 1018-AU28",
            ["1018-AU04", "1018-AU09", "1018-AU13", "1018-AU28"],
        ),
        ("rin", "corrects the RIN number from 0701- AA81 to 0701-AA94.", ["0701-AA94"]),
        ("rin", "RIN 1625-AAOO and RIN 2060-XXXX", []),
        # An OMB control number a FEMA collection shapes like a RIN is the OMB number.
        ("rin", "OMB Number: 1660-NW32. Abstract: The purpose", []),
        ("rin", "OMB No. 1660-NW32 and RIN 1660-AA12", ["1660-AA12"]),
    ],
)
def test_an_identifier_kind_is_keyed_by_identifier_shapes(kind: str, printed: str, keys: list[str]) -> None:
    """Dockets through the label-aware docket normalizer, RINs through the one published RIN shape."""
    assert [f.target_key for f in find_citations(printed, kinds=(kind,))] == keys


def _rendered(kind: str, key: str) -> str:
    """A key written back as the citation it names, by the key's own documented shape."""
    if kind == "public_law":
        congress, _, number = key.split("-")
        return f"Pub. L. {congress}-{number}"
    if kind == "rin":
        return f"RIN {key}"
    if kind == "docket_number":
        return f"Docket No. {key}"
    head, _, rest = key.partition("-")
    if kind == "federal_register_cite":
        return f"{head} FR {rest}"
    if kind == "usc_section":
        return f"{head[:-1]} U.S.C. app. {rest}" if head.endswith("A") else f"{head} U.S.C. {rest}"
    if kind == "cfr_section":
        return f"{head} CFR {rest}"
    return f"{head} Stat. {rest}"


#: What a grammar key may look like, written without the grammar: no space,
#: no en dash, nothing but a letter or digit at either end.
_KEY_SHAPE = re.compile(r"[0-9A-Za-z](?:[0-9A-Za-z.-]*[0-9A-Za-z])?")


#: Texts beside the fixtures carrying every key shape the prints do not: a
#: range, an appendix title, an abbreviated span, a refused hyphen, a compound
#: section and lettered Statutes volumes and pages.
_KEY_SHAPE_SPECIMENS = (
    "42 U.S.C. 7401-7671q, 50 U.S.C. app. 2401, 42 U.S.C. 1395w-4 and 20 U.S.C. 1484-86; "
    "40 CFR Parts 60 and 61, 40 CFR Part 1500-1508 and 46 CFR 1.01-15; "
    "114 Stat. 2763A-326 to 2763A-328 and 70A Stat. 157; Pub. L. No. 118-31 and Pub. L. 111-05; "
    "88 Fed. Reg. 12,345 and 89 FR 91529; RINs 1018-AU04 and 1018-AU09; Docket No. EPA-HQ-OAR-2004-0015."
)


@pytest.mark.parametrize("package", [DENSE, TRUNCATED, None])
def test_every_grammar_key_parses_back_to_itself(package: str | None) -> None:
    """The A10 gate: a published key, written back as a citation, reads as that key and nothing else.

    Checked by two different means: a plain shape test that knows nothing of
    the grammar, and the round trip through the rule itself.
    """
    text = _KEY_SHAPE_SPECIMENS if package is None else body_for(package).text
    pairs = {(f.kind, f.target_key) for f in find_citations(text, kinds=GRAMMAR_KINDS)}
    assert pairs
    for kind, key in sorted(pairs):
        assert _KEY_SHAPE.fullmatch(key), (kind, key)
        assert [f.target_key for f in find_citations(_rendered(kind, key), kinds=(kind,))] == [key], (kind, key)


@pytest.mark.parametrize(
    ("printed", "key"),
    [
        ("Public Law 98-369", "98-public-369"),
        ("P.L. 98-369", "98-public-369"),
        ("PL 98-369", "98-public-369"),
        ("Pub. L. No. 89-136", "89-public-136"),
        ("Pub. L. 119-21", "119-public-21"),
    ],
)
def test_the_public_law_rule_reads_every_spelling_the_sample_printed(printed: str, key: str) -> None:
    """Four spellings, the Bluebook ``Pub. L. No.`` among them, which the rollup's first rule missed."""
    assert [f.target_key for f in find_citations(printed, kinds=("public_law",))] == [key]


def test_an_unknown_kind_is_refused_rather_than_ignored() -> None:
    """An unknown kind is refused rather than ignored."""
    with pytest.raises(CitationError, match="no such citation rule"):
        find_citations("anything", kinds=("bill_numbers",))


# ---------------------------------------------------------------------------
# Committee resolution.
# ---------------------------------------------------------------------------


def test_the_resolver_settles_a_name_four_ways_and_names_the_route() -> None:
    """The committee resolver settles names through four routes and names which route settled each."""
    # Two committees share the FOREIG prefix, the way the real rosters do, so
    # route 2 cannot settle a short fragment and route 4 has to.
    vocabulary = (
        ("COMMITTEEONFOREIGNAFFAIRS", "hsfa00"),
        ("COMMITTEEONFOREIGNRELATIONS", "ssfr00"),
        ("COMMITTEEONWAYSANDMEANS", "hswm00"),
    )
    settled = resolve_committee_names(
        [
            "COMMITTEEONFOREIGNAFFAIRS",  # is a roster name
            "COMMITTEEONFOREIGNAF",  # a line-wrapped prefix of exactly one
            "COMMITTEEONWAYSANDMEANSREPUB",  # runs into following prose
            "COMMITTEEONFOREI",  # ambiguous in the roster; its siblings settle it
            "COMMITTEEONCHINA",  # no roster reaches it
        ],
        vocabulary,
    )
    assert {name: (out.system_code, out.route) for name, out in settled.items()} == {
        "COMMITTEEONFOREIGNAFFAIRS": ("hsfa00", "exact"),
        "COMMITTEEONFOREIGNAF": ("hsfa00", "roster_prefix"),
        "COMMITTEEONWAYSANDMEANSREPUB": ("hswm00", "name_prefix"),
        "COMMITTEEONFOREI": ("hsfa00", "sibling_prefix"),
        "COMMITTEEONCHINA": (None, "unresolved"),
    }


@pytest.mark.parametrize(
    "candidate",
    [
        # Each is a *longer* Senate committee whose name begins with a House
        # committee's whole name. Route 3 published hshm00 and hssm00 for the
        # first two: a plausible, wrong, unflagged join.
        "COMMITTEEONHOMELANDSECURITYANDGOVERNMENTALAFFAIRS",
        "COMMITTEEONSMALLBUSINESSANDENTREPRENEURSHIP",
        # And the same shape inside the corpus: two committees printed as one
        # run-on, which is not the Judiciary with prose after it.
        "COMMITTEEONTHEJUDICIARYANDCOMMITTEE",
    ],
)
def test_a_candidate_that_continues_into_a_longer_name_is_refused(candidate: str) -> None:
    """A candidate that continues into a longer roster name stays unresolved."""
    outcome = resolve_committee_names([candidate], rosters())[candidate]
    assert (outcome.system_code, outcome.route) == (None, "unresolved")


def test_a_roster_name_running_into_prose_still_resolves() -> None:
    """The guard must not take route 3 away from what it is for."""
    outcome = resolve_committee_names(["COMMITTEEONWAYSANDMEANSREPUB"], rosters())["COMMITTEEONWAYSANDMEANSREPUB"]
    assert (outcome.system_code, outcome.route) == ("hswm00", "name_prefix")


def test_a_fragment_too_short_to_mean_anything_is_refused() -> None:
    """``Committee on A`` would otherwise take whichever sibling shared its letter."""
    settled = resolve_committee_names(["COMMITTEEONA", "COMMITTEEONAPPROPRIATIONS"], rosters())
    assert settled["COMMITTEEONA"].system_code is None
    assert settled["COMMITTEEONAPPROPRIATIONS"].system_code == "hsap00"


def test_the_resolver_takes_its_vocabulary_and_reads_no_file() -> None:
    """Purity, asserted: with an empty vocabulary nothing settles."""
    assert resolve_committee_names(["COMMITTEEONRULES"], ())["COMMITTEEONRULES"].system_code is None


def test_a_name_both_chambers_hold_is_the_committee_of_the_chamber_whose_print_it_is() -> None:
    """CRPT-118srpt3, a Senate report, says ``from the Committee on Veterans' Affairs``: that is ``ssva00``.

    Until 2026-09-26 the vocabulary gave every shared name to the House, and
    this line published ``hsvr00``. The pinned excerpts share three names;
    the two chambers' vocabularies differ on exactly those and nothing else.
    """
    audit = json.loads((CITATION_FIXTURES / "print-citations-2026-09-26.json").read_text(encoding="utf-8"))
    (front,) = [case["pages"] for case in audit["covered"] if case["package"] == "CRPT-118srpt3"]
    assert "from the Committee on Veterans' Affairs" in front[0]
    read = {
        chamber: {
            f.target_key
            for f in find_citations(front[0], kinds=("committee_name",), committees=rosters(chamber))
            if f.target_resolved
        }
        for chamber in ("senate", "house")
    }
    assert read == {"senate": {"ssva00"}, "house": {"hsvr00"}}
    senate, house = dict(rosters("senate")), dict(rosters("house"))
    assert senate.keys() == house.keys()
    assert {name: (house[name], senate[name]) for name in senate if senate[name] != house[name]} == {
        "COMMITTEEONAPPROPRIATIONS": ("hsap00", "ssap00"),
        "COMMITTEEONARMEDSERVICES": ("hsas00", "ssas00"),
        "COMMITTEEONVETERANSAFFAIRS": ("hsvr00", "ssva00"),
    }


COMMITTEE_SNIPPETS_2026_09_26 = json.loads(
    (CITATION_FIXTURES / "print-citations-2026-09-26.json").read_text(encoding="utf-8")
)["committee_snippets"]


def _named(text: str, chamber: str, *, named: bool = True) -> list[list]:
    """The committee findings a report of ``chamber`` publishes for ``text``, reading a named chamber or not."""
    own = {side: rosters(side, own_only=True) for side in ("house", "senate")}
    findings = find_citations(
        text, kinds=("committee_name",), committees=rosters(chamber), chamber_committees=own if named else None
    )
    return [[f.target_key, f.target_resolved] for f in findings]


@pytest.mark.parametrize(
    "case", COMMITTEE_SNIPPETS_2026_09_26, ids=lambda case: f"{case['package']}-{case['span_start']}"
)
def test_a_chamber_the_print_names_before_a_committee_selects_that_chambers_committees(case: dict) -> None:
    """``Senate Committee on Armed Services`` in a House report is ``ssas00``; the report's own chamber does not win.

    The retained lines name the other chamber (and, in CRPT-118hrpt961, both
    chambers' committees of one name, one line apart). A Senate-named name no
    Senate committee reaches -- the pinned Senate excerpt holds no Homeland
    Security and Governmental Affairs -- stays unresolved rather than taking
    the House's ``hshm00``.
    """
    assert _named(case["text"], case["report_chamber"]) == case["keys"]


def test_without_the_named_chamber_the_report_chamber_took_every_shared_name() -> None:
    """What committee_name 001 published for CRPT-118hrpt961's two lines: the House code twice."""
    (case,) = [c for c in COMMITTEE_SNIPPETS_2026_09_26 if c["package"] == "CRPT-118hrpt961"]
    assert _named(case["text"], "house", named=False) == [["hsas00", True], ["hsas00", True]]


@pytest.mark.parametrize(
    ("text", "chamber"),
    [
        ("the House Committee on Armed Services", "house"),
        ("the Senate\nCommittee on Armed Services", "senate"),
        ("the Senate Select Committee on Armed Services", None),
        ("the Housing Committee on Armed Services", None),
        ("xSenate Committee on Armed Services", None),
    ],
)
def test_the_named_chamber_is_the_word_right_before_the_committee(text: str, chamber: str | None) -> None:
    assert named_chamber(text, text.index("Committee")) == chamber


@pytest.mark.parametrize("chamber", ["joint", "", None])
def test_a_vocabulary_is_read_for_a_stated_chamber_or_not_at_all(chamber) -> None:
    """No default: a caller that cannot say whose print it is must not be handed the House's answer."""
    with pytest.raises(CitationError, match="chamber must be one of"):
        committee_vocabulary(chamber=chamber)  # type: ignore[arg-type]


def test_an_unresolved_committee_is_kept_as_evidence_not_dropped() -> None:
    """An unresolved committee cite is kept as evidence under its own rule, not dropped."""
    (finding,) = find_citations("Committee on China", kinds=("committee_name",), committees=rosters())
    assert (finding.target_key, finding.target_resolved, finding.target_rule) == (
        "COMMITTEEONCHINA",
        False,
        "unresolved",
    )


def test_a_finding_names_the_route_its_committee_key_came_from() -> None:
    """A committee finding's target_rule names the route that produced its key."""
    (finding,) = find_citations("Committee on Foreign Affairs", kinds=("committee_name",), committees=rosters())
    assert (finding.target_key, finding.target_rule) == ("hsfa00", "exact")


def test_every_other_kind_reports_its_own_rule_name_as_the_route() -> None:
    """Non-committee kinds report their rule name as the route."""
    (finding,) = find_citations("H.R. 471", kinds=("bill_number",), congress=119)
    assert finding.target_rule == "bill_number"


def test_the_pinned_rosters_reach_both_chambers() -> None:
    """The pinned rosters resolve committee names from both chambers."""
    vocabulary = dict(rosters())
    assert vocabulary["COMMITTEEONFOREIGNAFFAIRS"] == "hsfa00"
    assert vocabulary["COMMITTEEONCOMMERCESCIENCEANDTRANSPORTATION"] == "sscm00"


# ---------------------------------------------------------------------------
# The fixtures, and the measurement they are pinned to.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", [DENSE, TRUNCATED])
def test_the_retained_text_is_the_one_the_measurement_read(package: str) -> None:
    """The fixture is the rollup's own extract, not a re-extraction of it.

    The digest is the one ``docs/research/pdf-family-rollup-yield-2026-09-20.json``
    states for this package, so every count below is measured over the same
    characters the report was.
    """
    recorded = provenance(package)
    body = body_for(package)
    assert hashlib.sha256(body.text.encode()).hexdigest() == recorded["text_sha256"]
    assert "\n".join(body.pages) == body.text
    assert len(body.pages) == recorded["pages_read"]


def test_the_dense_report_reproduces_the_measurements_own_counts() -> None:
    """CRPT-118hrpt968, as the 2026-09-20 sidecar records it -- and two laws it could not see.

    179 distinct bills are its ``distinct_count``. It counted 3 public laws
    with the 001 pattern; the grammar the rule reads through since 002 also
    reads ``PUBLIC LAW 91–510`` in capitals and ``P.L. 117–`` wrapped onto
    the next line before ``81``, and the package MODS states both (see
    ``test_the_dense_reports_mods_laws_are_read_exactly``). The
    committee line needs saying carefully, because the sidecar counts
    candidates and this table counts rows.  The sidecar records 9 printed
    candidate occurrences over 5 distinct candidate strings, 4 of which
    resolve, to 3 distinct ``system_code``s, leaving 1 unresolved -- and that
    one candidate is printed once, so 8 of the 9 occurrences resolve.  Both
    statements are asserted so neither can be read as the other.
    """
    findings = citations_for(DENSE)
    bills = [f for f in findings if f.kind == "bill_number"]
    laws = [f for f in findings if f.kind == "public_law"]
    committees = [f for f in findings if f.kind == "committee_name"]

    assert len({f.target_key for f in bills}) == 179
    assert len(bills) == 267
    assert {f.target_key for f in laws} == {
        "91-public-510",
        "107-public-40",
        "107-public-228",
        "117-public-81",
        "117-public-263",
    }
    stated = {f"{law.congress}-public-{law.number}" for law in mods_for(DENSE).laws}
    assert {f.target_key for f in laws} <= stated

    assert len(committees) == 9
    assert sum(1 for f in committees if f.target_resolved) == 8
    assert {f.target_key for f in committees if f.target_resolved} == {"hsap00", "hsfa00", "hsha00"}
    assert {f.target_key for f in committees if not f.target_resolved} == {"COMMITTEEONOVERSIGHTANDACCOUNTABILITY"}
    assert len({canonical_alnum(f.matched_text) for f in committees}) == 5


def test_the_truncated_report_reproduces_the_measurements_own_counts() -> None:
    """CRPT-118hrpt965, read 60 pages into a 282-page print.

    Its counts are a floor on the document and the row says so through
    ``pages_capped``; what is pinned here is the read, not the print.
    """
    findings = citations_for(TRUNCATED)
    assert len({f.target_key for f in findings if f.kind == "bill_number"}) == 39
    assert len({f.target_key for f in findings if f.kind == "public_law"}) == 1
    committees = [f for f in findings if f.kind == "committee_name"]
    assert len(committees) == 70
    assert len({f.target_key for f in committees if f.target_resolved}) == 7
    # ``COMMITTEEONEN`` is eleven-plus-two characters, below the sibling-route
    # floor, so it is refused even though one sibling would have taken it. The
    # seven codes above are unchanged by that refusal: the print spells Energy
    # and Commerce in full elsewhere.
    assert {f.target_key for f in committees if not f.target_resolved} == {
        "COMMITTEEONCHINA",
        "COMMITTEEONEN",
        "COMMITTEEONFOREIGNINVESTMENTS",
    }


# ---------------------------------------------------------------------------
# The do-not-recreate rule, measured rather than assumed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", [DENSE, TRUNCATED])
def test_the_package_mods_already_states_every_key_of_three_kinds_the_print_names(package: str) -> None:
    """The finding the contract's shape rests on, pinned so it cannot be forgotten.

    The rollup measured "beyond the index" against the ``published`` listing
    row, which states seven fields and no bill, and so reported 883 bills as
    yield.  The package MODS -- which the body acquirer already fetches for
    every package it reads -- states them all, and not only the bills:
    ``<law>`` covers the public laws and ``<USCode><section>`` the Code
    sections.  CRPT-118hrpt968's entire printed Code yield is ``2 U.S.C.
    190``, which its MODS states; an earlier version of this test compared no
    Code set at all and so passed while the claim beside it was wrong.

    A row of these kinds is therefore worth its evidence span, not its key,
    and says so in ``stated_by_index``.

    Measured on these two packages only: six of the eight sampled activity
    reports have no MODS retained and are unmeasured.
    """
    stated = index_stated_keys(mods_for(package))
    findings = citations_for(package)
    printed = {
        kind: {f.target_key for f in findings if f.kind == kind}
        for kind in ("bill_number", "public_law", "usc_section")
    }
    assert printed["bill_number"] and printed["public_law"]
    for kind, keys in printed.items():
        assert keys <= stated[kind], f"{package}: the MODS does not state every {kind}"


def test_the_index_states_keys_a_capped_read_never_reaches() -> None:
    """The comparison runs the other way too, which is the sharper half.

    CRPT-118hrpt965's MODS names 380 bills and ``15 U.S.C. 57a`` where the
    60-page read saw 39 bills and no Code section at all.
    """
    stated = index_stated_keys(mods_for(TRUNCATED))
    printed = {f.target_key for f in citations_for(TRUNCATED) if f.kind == "bill_number"}
    assert len(stated["bill_number"]) == 380
    assert len(printed) == 39
    assert stated["usc_section"] == {"15-57a"}
    assert not [f for f in citations_for(TRUNCATED) if f.kind == "usc_section"]


def test_the_print_still_reaches_what_no_govinfo_record_states() -> None:
    """The other half of the same rule: the yield that survives it.

    CRPT-118hrpt968's MODS names one committee, its own; the print names four
    more occurrences belonging to two other committees and one it cannot
    settle.  That committee surface, not the bills or the Code, is this
    family's largest genuinely-new yield.
    """
    stated = index_stated_keys(mods_for(DENSE))
    findings = citations_for(DENSE)
    committees = {f.target_key for f in findings if f.kind == "committee_name"}
    assert stated["committee_name"] == {"hsfa00"}
    assert committees - stated["committee_name"] == {
        "hsap00",
        "hsha00",
        "COMMITTEEONOVERSIGHTANDACCOUNTABILITY",
    }


@pytest.mark.parametrize("package", [DENSE, TRUNCATED])
def test_neither_mods_states_a_cfr_part_although_it_could(package: str) -> None:
    """A printed CFR cite is new outright -- and this is a `false`, not a NULL.

    ``cfr_section`` is in the comparison mapping with an empty set, because a
    GovInfo MODS *can* carry ``<cfr title><part number>`` (two of the eight
    sampled budget volumes do) and these records simply carry none.  That is a
    different fact from a kind the vocabulary has no element for at all, which
    stays out of the mapping and lands as NULL.
    """
    raw = (CITATION_FIXTURES / f"mods-{package}.xml").read_text()
    assert "CFR" not in raw.upper()
    assert index_stated_keys(mods_for(package))["cfr_section"] == frozenset()


@pytest.mark.parametrize(
    "kind",
    ["federal_register_cite", "gao_product_id", "crs_report_id", "docket_number", "case_docket_number"],
)
def test_a_kind_the_mods_vocabulary_cannot_state_is_left_out_of_the_comparison(kind: str) -> None:
    """NULL, not `false`: claiming a comparison that no element makes possible.

    The MODS re-check censused every root-level ``extension`` child of 24
    records across three collections and found no element of any of these
    shapes, so a print's cite of these kinds has nothing to be compared with.
    """
    assert kind not in index_stated_keys(mods_for(DENSE))


def test_a_row_of_an_uncomparable_kind_carries_a_null_rather_than_false() -> None:
    """A row of an uncomparable kind carries NULL rather than false."""
    from spicy_docs.schemas.document_citation_tables import (
        GOVINFO_PACKAGE,
        document_provenance,
        shape_document_citation,
    )

    provenance = document_provenance(body_for(DENSE), document_key=DENSE, document_kind=GOVINFO_PACKAGE)
    (finding,) = find_citations("GAO-24-106221", kinds=("gao_product_id",))
    row = shape_document_citation(finding, provenance, stated_by_index=index_stated_keys(mods_for(DENSE)))
    assert row["stated_by_index"] is None


def test_the_keyed_records_state_the_fields_the_contract_reads_from_them() -> None:
    """Session and page count are the publisher's, so the row never re-derives them."""
    summary = summary_for(TRUNCATED)
    assert (summary.session, summary.pages) == ("2", "282")
    assert summary.identity.congress == 118
    mods = mods_for(TRUNCATED)
    assert [committee.authority_id for committee in mods.committees] == ["hsif00"]
    assert mods.session == "2"
    # An activity report is a Congress of work, not one bill: no `<bill>` in
    # either package's MODS carries the PRIMARY context.
    assert mods.primary_bill is None


def test_the_dense_reports_mods_laws_are_read_exactly() -> None:
    """The whole list, not a count: a reader that dropped one would still count six."""
    assert mods_for(DENSE).laws == (
        ModsLaw(congress=91, number="510", law_type="public"),
        ModsLaw(congress=92, number="136", law_type="public"),
        ModsLaw(congress=107, number="40", law_type="public"),
        ModsLaw(congress=107, number="228", law_type="public"),
        ModsLaw(congress=117, number="81", law_type="public"),
        ModsLaw(congress=117, number="263", law_type="public"),
    )


def test_the_us_code_reader_keeps_sections_and_drops_chapters() -> None:
    """Both fixtures carry a chapter-only ``<USCode>`` block; neither yields a key."""
    assert mods_for(DENSE).usc_sections == (ModsUsCodeSection(title="2", number="190", detail="(d)"),)
    assert mods_for(TRUNCATED).usc_sections == (ModsUsCodeSection(title="15", number="57a", detail="(a)(1)(B)"),)
    assert "<chapter" in (CITATION_FIXTURES / f"mods-{DENSE}.xml").read_text()


def test_the_submitter_is_read_and_its_absent_id_is_not_invented() -> None:
    """One package states the bioguide id and the other states the member without one."""
    assert mods_for(DENSE).submitted_by.bioguide_id == "M001157"
    submitter = mods_for(TRUNCATED).submitted_by
    assert (submitter.role, submitter.state, submitter.bioguide_id) == ("SUBMITTEDBY", "WA", None)


def test_the_related_reports_are_read_as_package_ids() -> None:
    """Related reports are read as package ids carrying their congress."""
    reports = mods_for(DENSE).reports
    assert len(reports) == 11
    assert reports[0].package_id == "CRPT-118hrpt29"
    assert [report.congress for report in reports] == [118] * 11


# ---------------------------------------------------------------------------
# The MODS readers' own boundaries, on markup written for the purpose.
# ---------------------------------------------------------------------------


def _mods_bytes(extension: str) -> bytes:
    """A minimal package MODS carrying ``extension`` inside its root extension.

    Written here rather than captured: what these check is the reader's
    refusal on a shape the two retained packages do not contain, and a fixture
    cannot state a shape its publisher never sent.
    """
    return (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        "<extension><accessId>CRPT-118hrpt968</accessId>"
        "<collectionCode>CRPT</collectionCode>"
        f"{extension}</extension></mods>"
    ).encode()


def _inline_mods(extension: str):
    """Build a minimal MODS body around the given inline markup."""
    return validate_package_mods(
        _mods_bytes(extension),
        package=DENSE,
        final_url=package_mods_locator(DENSE),
        max_bytes=100_000,
    )


def test_a_committee_without_an_authority_id_is_skipped() -> None:
    """The id is the whole point of reading the element; a name alone is the citation rule's job."""
    mods = _inline_mods(
        '<congCommittee chamber="H"><name type="authority-standard">Committee on Rules</name></congCommittee>'
        '<congCommittee authorityId="hsru00" chamber="H">'
        '<name type="authority-standard">Committee on Rules</name></congCommittee>'
    )
    assert [committee.authority_id for committee in mods.committees] == ["hsru00"]


def test_a_committee_falls_back_to_whatever_name_it_states() -> None:
    """A committee with no authority id falls back to its stated name."""
    mods = _inline_mods('<congCommittee authorityId="hsru00"><name type="authority-short">Rules</name></congCommittee>')
    assert mods.committees[0].name == "Rules"


@pytest.mark.parametrize(
    "law",
    [
        '<law congress="one" isPrivate="false" number="510"/>',
        '<law congress="91" isPrivate="false" number="ten"/>',
        '<law isPrivate="false" number="510"/>',
        '<law congress="91" isPrivate="false"/>',
    ],
)
def test_a_law_without_a_numeric_congress_and_number_is_skipped(law: str) -> None:
    """Skipped, not guessed at: the same boundary the bill reader draws."""
    assert _inline_mods(law).laws == ()


def test_a_private_law_keeps_the_publishers_own_flag() -> None:
    """A private law keeps the publisher's own private/public flag."""
    mods = _inline_mods('<law congress="118" isPrivate="true" number="3"/><law congress="118" number="4"/>')
    assert [(law.number, law.law_type) for law in mods.laws] == [("3", "private"), ("4", "public")]


def test_a_us_code_block_with_no_title_or_no_section_number_yields_nothing() -> None:
    """A USCode block missing its title or section number yields no sections."""
    assert _inline_mods('<USCode><section number="190"/></USCode>').usc_sections == ()
    assert _inline_mods('<USCode title="2"><section detail="(d)"/></USCode>').usc_sections == ()
    assert _inline_mods('<USCode title="5"><chapter number="8"/></USCode>').usc_sections == ()


def test_the_cfr_statute_and_rin_readers_produce_the_keys_the_rules_compare_on() -> None:
    """Three shapes no retained CRPT MODS carries, so they are exercised on markup.

    The element shapes are the publisher's, read off the collections that do
    carry them (two of eight budget volumes state ``<cfr>`` and one a
    ``<rin>``; one activity report states a ``<statuteAtLarge>``).  Reading
    them here is what lets `stated_by_index` be `false` rather than NULL for a
    kind this record could have stated and did not.
    """
    mods = _inline_mods(
        '<cfr title="40"><part number="60"/></cfr>'
        '<statuteAtLarge volume="136"><page pages="1234"/></statuteAtLarge>'
        '<rin number="3133-AF97"/>'
    )
    assert [(part.title, part.part) for part in mods.cfr_parts] == [("40", "60")]
    assert [(s.volume, s.pages) for s in mods.statutes] == [("136", "1234")]
    assert mods.rins == ("3133-AF97",)

    stated = index_stated_keys(mods)
    assert stated["cfr_section"] == {"40-60"}
    assert stated["statutes_at_large"] == {"136-1234"}
    assert stated["rin"] == {"3133-AF97"}
    # And each is the spelling the print rule's own target reader produces.
    assert find_citations("40 C.F.R. part 60", kinds=("cfr_section",))[0].target_key == "40-60"
    assert find_citations("136 Stat. 1234", kinds=("statutes_at_large",))[0].target_key == "136-1234"
    assert find_citations("RIN 3133-AF97", kinds=("rin",))[0].target_key == "3133-AF97"


def test_a_cfr_or_statute_block_missing_its_outer_number_yields_nothing() -> None:
    """CFR, statute and RIN blocks missing their outer number yield nothing."""
    assert _inline_mods('<cfr><part number="60"/></cfr>').cfr_parts == ()
    assert _inline_mods('<statuteAtLarge><page pages="1234"/></statuteAtLarge>').statutes == ()
    assert _inline_mods("<rin/>").rins == ()


def test_the_identifier_detection_runs_once_per_document(monkeypatch: pytest.MonkeyPatch) -> None:
    """``rin`` and ``docket_number`` read one detection of the text, not one each."""
    from spicy_docs.interpretation import citations

    calls = 0
    real = citations.detect_identifier_shapes

    def counting(text):
        nonlocal calls
        calls += 1
        return real(text)

    monkeypatch.setattr(citations, "detect_identifier_shapes", counting)
    citations._identifiers_in.cache_clear()
    findings = find_citations("Docket No. EPA-HQ-OAR-2004-0015 and RIN 2060-AU12.", kinds=("rin", "docket_number"))
    assert calls == 1
    assert [f.target_key for f in findings] == ["EPA-HQ-OAR-2004-0015", "2060-AU12"]


def test_doubling_a_document_does_not_quadruple_the_reading_of_every_grammar_kind() -> None:
    """All seven grammar kinds through ``find_citations``, identifier kinds included; best of three.

    The grammar's own guard (``tests/test_citation_grammar.py``) times its
    readers; this one times the rules as the table reads them.
    """
    import time

    block = (
        "The Clean Air Act (42 U.S.C. 7401, 7402 and 7403), Pub. L. 92-463, 86 Stat. 770, 89 FR 12345, 40 CFR "
        "parts 60 and 61; Docket No. EPA-HQ-OAR-2004-0015, RINs 2060-AU12 and 2060-AU13. "
    )

    def best(copies: int) -> float:
        text = block * copies
        times = []
        for _ in range(3):
            started = time.perf_counter()
            find_citations(text, kinds=GRAMMAR_KINDS)
            times.append(time.perf_counter() - started)
        return min(times)

    small, large = best(300), best(600)
    assert large < 3 * small, (small, large)
