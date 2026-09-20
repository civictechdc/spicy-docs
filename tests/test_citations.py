"""The citation rules, and the two activity reports they are pinned on.

Three things are asserted here and nowhere else:

1. **Each rule rejects its own lookalikes.** A rule that widened into prose
   fails here rather than showing up as a high hit rate in a report.
2. **A span means what it says.** Re-reading the normalized text at each
   finding's offsets returns the matched text, and the page attribution agrees
   with an independently computed page map.
3. **The library and the measurement agree.** The per-print counts the
   2026-09-20 rollup sidecar records for CRPT-118hrpt968 -- 179 distinct
   bills, 3 public laws, 9 printed committee candidates of which 8 occurrences
   settle to a ``system_code`` -- are reproduced by
   ``interpretation.citations`` from the same retained text.

The fixtures are two of the eight activity reports that measurement read,
rebuilt from its retained bytes and never re-fetched: the normalized text
whose digest the sidecar states, a provenance sidecar holding the page lengths
that rejoin to it, and the package summary and MODS, the MODS reduced to its
root record.  ``tests/fixtures/document_citations/*.json`` names every digest
and both receipts.
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
    DOCUMENT_CITATION_KINDS,
    CitationError,
    canonical_alnum,
    committee_vocabulary,
    find_citations,
    page_starts,
    rejected_lookalikes,
    resolve_committee_names,
)
from spicy_docs.schemas.document_citation_tables import index_stated_keys
from spicy_docs.sources.congress.committee_rosters import parse_house_member_data, parse_senate_cvc
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
    return validate_package_summary(
        (CITATION_FIXTURES / f"summary-{package}.json").read_bytes(),
        package=package,
        final_url=package_summary_locator(package),
        max_bytes=1_000_000,
    )


def mods_for(package: str):
    return validate_package_mods(
        (CITATION_FIXTURES / f"mods-{package}.xml").read_bytes(),
        package=package,
        final_url=package_mods_locator(package),
        max_bytes=1_000_000,
    )


def rosters() -> tuple[tuple[str, str], ...]:
    """The pinned chamber rosters, read through this repository's own readers.

    The House file is the complete ``<committees>`` block; the Senate excerpt
    states only the committees its sampled senators sit on, so anything it
    does not reach stays unresolved rather than being guessed at.
    """
    house = parse_house_member_data((ROSTERS / "memberdata-119-excerpt.xml").read_bytes(), congress=119)
    senate = parse_senate_cvc((ROSTERS / "cvc-member-data-excerpt.xml").read_bytes())
    return committee_vocabulary(house=(house,), senate=(senate,))


def citations_for(package: str):
    body = body_for(package)
    return find_citations(
        body.text,
        pages=body.pages,
        congress=summary_for(package).identity.congress,
        committees=rosters(),
    )


# ---------------------------------------------------------------------------
# The rules themselves.
# ---------------------------------------------------------------------------


def test_every_rule_rejects_its_own_lookalikes() -> None:
    assert rejected_lookalikes() == {}


@pytest.mark.parametrize("rule", CITATION_RULES, ids=lambda rule: rule.name)
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


def test_the_three_rules_whose_published_key_changed_moved_their_version() -> None:
    """``rin``, ``docket_number`` and ``us_reports_cite`` gained a target reader.

    Each had been publishing its measurement-comparison form -- ``RIN3133AF97``
    rather than the ``3133-AF97`` ``regulation_id_numbers_json`` holds -- which
    is a change to the key a consumer joins on, so the procedure applies: move
    the version, re-pin the digest, re-pin the fixture counts.
    """
    moved = {rule.name for rule in CITATION_RULES if rule.version != "001"}
    assert moved == {"rin", "docket_number", "us_reports_cite"}


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
    assert CITATION_RULE_SET_VERSION == "568f1c894232"


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


def test_a_reject_check_that_never_bit_would_be_worthless() -> None:
    """Prove the rejection check can fail, by widening one rule until it does."""
    from dataclasses import replace

    widened = replace(next(r for r in CITATION_RULES if r.name == "public_law"), pattern=r"P\.?L")
    assert [candidate for candidate in widened.rejects if widened.compiled().search(candidate)]


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
    findings = find_citations("The Committee reported H.R. 471 to the House.", congress=119)
    assert [finding.page for finding in findings] == [None]
    assert findings[0].target_key == "119-hr-471"


def test_a_page_split_that_does_not_rejoin_is_refused() -> None:
    """A wrong page map would mis-attribute every span, and silently."""
    with pytest.raises(CitationError, match="rejoin"):
        find_citations("H.R. 471 and S. 5", pages=("H.R. 471", "and S. 6"))


def test_page_starts_is_the_join_it_claims_to_be() -> None:
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
    (finding,) = find_citations(printed, kinds=(kind,))
    assert (finding.target_key, finding.target_resolved) == (expected, True)


def test_an_unknown_kind_is_refused_rather_than_ignored() -> None:
    with pytest.raises(CitationError, match="no such citation rule"):
        find_citations("anything", kinds=("bill_numbers",))


# ---------------------------------------------------------------------------
# Committee resolution.
# ---------------------------------------------------------------------------


def test_the_resolver_settles_a_name_four_ways_and_names_the_route() -> None:
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


def test_an_unresolved_committee_is_kept_as_evidence_not_dropped() -> None:
    (finding,) = find_citations("Committee on China", kinds=("committee_name",), committees=rosters())
    assert (finding.target_key, finding.target_resolved, finding.target_rule) == (
        "COMMITTEEONCHINA",
        False,
        "unresolved",
    )


def test_a_finding_names_the_route_its_committee_key_came_from() -> None:
    (finding,) = find_citations("Committee on Foreign Affairs", kinds=("committee_name",), committees=rosters())
    assert (finding.target_key, finding.target_rule) == ("hsfa00", "exact")


def test_every_other_kind_reports_its_own_rule_name_as_the_route() -> None:
    (finding,) = find_citations("H.R. 471", kinds=("bill_number",), congress=119)
    assert finding.target_rule == "bill_number"


def test_the_pinned_rosters_reach_both_chambers() -> None:
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
    """CRPT-118hrpt968, as the 2026-09-20 sidecar records it.

    179 distinct bills and 3 public laws are its ``distinct_count``s; the
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
    assert len({f.target_key for f in laws}) == 3
    assert {f.target_key for f in laws} == {"107-public-40", "107-public-228", "117-public-263"}

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
    mods = _inline_mods('<law congress="118" isPrivate="true" number="3"/><law congress="118" number="4"/>')
    assert [(law.number, law.law_type) for law in mods.laws] == [("3", "private"), ("4", "public")]


def test_a_us_code_block_with_no_title_or_no_section_number_yields_nothing() -> None:
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
    assert _inline_mods('<cfr><part number="60"/></cfr>').cfr_parts == ()
    assert _inline_mods('<statuteAtLarge><page pages="1234"/></statuteAtLarge>').statutes == ()
    assert _inline_mods("<rin/>").rins == ()
