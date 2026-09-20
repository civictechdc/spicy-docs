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


def test_the_rule_set_version_is_pinned_to_these_rules() -> None:
    """Editing a pattern moves this digest even when its own version is forgotten.

    The digest is derived from every rule's name, version and pattern, so this
    assertion is the gate: a rule change fails here, and the fix is to move
    that rule's ``version`` and re-pin the fixture counts below
    (``docs/decisions.md``).
    """
    assert CITATION_RULE_SET_VERSION == "ff7841613ee7"


def test_the_stored_kinds_are_rules_that_reach_a_key() -> None:
    names = {rule.name for rule in CITATION_RULES}
    assert set(DOCUMENT_CITATION_KINDS) <= names
    # Deliberately not stored: a measured-zero identifier and two quantities.
    assert {"bioguide_id", "dollar_amount", "fiscal_year"}.isdisjoint(DOCUMENT_CITATION_KINDS)


def test_a_reject_check_that_never_bit_would_be_worthless() -> None:
    """Prove the rejection check can fail, by widening one rule until it does."""
    from dataclasses import replace

    widened = replace(next(r for r in CITATION_RULES if r.name == "public_law"), pattern=r"P\.?L")
    assert [candidate for candidate in widened.rejects if widened.compiled().search(candidate)]


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


def test_the_resolver_settles_a_name_four_ways_and_refuses_a_fifth() -> None:
    vocabulary = (("COMMITTEEONFOREIGNAFFAIRS", "hsfa00"), ("COMMITTEEONWAYSANDMEANS", "hswm00"))
    settled = resolve_committee_names(
        [
            "COMMITTEEONFOREIGNAFFAIRS",  # is a roster name
            "COMMITTEEONFOREIGNAF",  # a line-wrapped prefix of exactly one
            "COMMITTEEONWAYSANDMEANSREPUB",  # runs into following prose
            "COMMITTEEONF",  # settles only through its own siblings
            "COMMITTEEONCHINA",  # no roster reaches it
        ],
        vocabulary,
    )
    assert settled == {
        "COMMITTEEONFOREIGNAFFAIRS": "hsfa00",
        "COMMITTEEONFOREIGNAF": "hsfa00",
        "COMMITTEEONWAYSANDMEANSREPUB": "hswm00",
        "COMMITTEEONF": "hsfa00",
        "COMMITTEEONCHINA": None,
    }


def test_the_resolver_takes_its_vocabulary_and_reads_no_file() -> None:
    """Purity, asserted: with an empty vocabulary nothing settles."""
    assert resolve_committee_names(["COMMITTEEONRULES"], ()) == {"COMMITTEEONRULES": None}


def test_an_unresolved_committee_is_kept_as_evidence_not_dropped() -> None:
    (finding,) = find_citations("Committee on China", kinds=("committee_name",), committees=rosters())
    assert (finding.target_key, finding.target_resolved) == ("COMMITTEEONCHINA", False)


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
    assert {f.target_key for f in committees if not f.target_resolved} == {
        "COMMITTEEONCHINA",
        "COMMITTEEONFOREIGNINVESTMENTS",
    }


# ---------------------------------------------------------------------------
# The do-not-recreate rule, measured rather than assumed.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("package", [DENSE, TRUNCATED])
def test_the_package_mods_already_states_every_bill_and_law_the_print_names(package: str) -> None:
    """The finding the contract's shape rests on, pinned so it cannot be forgotten.

    The rollup measured "beyond the index" against the ``published`` listing
    row, which states seven fields and no bill, and so reported 883 bills as
    yield.  The package MODS -- which the body acquirer already fetches for
    every package it reads -- states them all.  A bill row's value here is its
    evidence span, not its key, and the row says so in ``stated_by_index``.

    Measured on these two packages only: six of the eight sampled activity
    reports have no MODS retained and are unmeasured.
    """
    stated = index_stated_keys(mods_for(package))
    findings = citations_for(package)
    printed_bills = {f.target_key for f in findings if f.kind == "bill_number"}
    printed_laws = {f.target_key for f in findings if f.kind == "public_law"}
    assert printed_bills and printed_laws
    assert printed_bills <= stated["bill_number"]
    assert printed_laws <= stated["public_law"]


def test_the_print_still_reaches_what_no_govinfo_record_states() -> None:
    """The other half of the same rule: the yield that survives it.

    CRPT-118hrpt968's MODS names one committee, its own; the print names four
    more occurrences belonging to two other committees and one it cannot
    settle, and one U.S. Code section the MODS never mentions.
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
    assert {f.target_key for f in findings if f.kind == "usc_section"} == {"2-190"}


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
