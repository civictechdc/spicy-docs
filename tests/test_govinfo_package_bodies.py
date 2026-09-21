"""Package-id grammar, locators and body identity rules, offline.

The three CRPT-119hrpt1 fixtures are exact publisher responses; the synthetic
cases cover shapes the publisher answered on other packages (a BILLS download
block, a USLM rendition) and the refusals themselves.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.sources.federal_register.body_sources import (
    FederalRegisterBodySourceError,
    validate_govinfo_granule,
)
from spicy_docs.sources.govinfo.bodies import (
    MEASURED_BUDGET_PARTS,
    PACKAGE_BODY_FORMATS,
    GovInfoBodySourceError,
    ModsBill,
    package_body_locator,
    package_mods_locator,
    package_summary_locator,
    parse_package_id,
    stated_collection_code,
    validate_package_body,
    validate_package_mods,
    validate_package_summary,
)

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bodies"
PACKAGE = "CRPT-119hrpt1"
SUMMARY = (FIXTURES / f"summary-{PACKAGE}.json").read_bytes()
MODS = (FIXTURES / f"mods-{PACKAGE}.xml").read_bytes()
BODY = (FIXTURES / f"body-{PACKAGE}.htm").read_bytes()
SUMMARY_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/summary"
MODS_URL = f"https://api.govinfo.gov/packages/{PACKAGE}/mods"
BODY_URL = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{PACKAGE}.htm"
ERROR_PAGE = b'<html><a href="https://www.govinfo.gov/error">Page Not Found</a></html>'

CPRT_PACKAGE = "CPRT-118HPRT57104"
CPRT_SUMMARY = (FIXTURES / f"summary-{CPRT_PACKAGE}.json").read_bytes()
CPRT_MODS = (FIXTURES / f"mods-{CPRT_PACKAGE}.xml").read_bytes()

#: The two collections the grammar was widened to on 2026-09-20. The budget
#: volume's records live with the rest of its fixture -- its text, its
#: provenance and both keyed records are one set and are not split across two
#: directories to save a second copy of 8 KB.
REPRINT_PACKAGE = "GPO-CDOC-119sdoc3"
BUDGET_PACKAGE = "BUDGET-2026-MSR"
BUDGET_FIXTURES = Path(__file__).parent / "fixtures" / "budget_volumes"

BILLS_FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
USLM_BILL_PACKAGE = "BILLS-119hconres11enr"
USLM_BILL_MODS = (BILLS_FIXTURES / "mods-119hconres11enr.xml").read_bytes()

#: One real package id per measured BUDGET part -- the id that showed it, which
#: is what the grammar's own comment asks an addition to carry. A fiscal year
#: and a part, with no Congress anywhere in the id.
#:
#: The first six were measured 2026-09-20 across the eight retained volumes; the
#: last seven are the parts a 2023-01-01 ``published/BUDGET`` walk served that
#: the sealed six refused, each proved on its own summary and MODS the same day
#: (receipt ``budget-parts-2026-09-20/``). This list is the independent side of
#: ``test_the_budget_part_vocabulary_is_exactly_what_an_id_proved``.
BUDGET_ID_CASES: tuple[tuple[str, dict[str, object]], ...] = (
    ("BUDGET-2027-APP", {"fiscal_year": "2027", "document_type": "APP", "congress": None}),
    ("BUDGET-2026-BALANCES", {"fiscal_year": "2026", "document_type": "BALANCES"}),
    ("BUDGET-2027-BUD", {"fiscal_year": "2027", "document_type": "BUD"}),
    ("BUDGET-2027-FCS", {"fiscal_year": "2027", "document_type": "FCS"}),
    ("BUDGET-2026-MSR", {"fiscal_year": "2026", "document_type": "MSR"}),
    ("BUDGET-2027-PER", {"fiscal_year": "2027", "document_type": "PER"}),
    ("BUDGET-2027-OBJCLASS", {"fiscal_year": "2027", "document_type": "OBJCLASS"}),
    ("BUDGET-2027-TAB", {"fiscal_year": "2027", "document_type": "TAB"}),
    ("BUDGET-2027-DB", {"fiscal_year": "2027", "document_type": "DB"}),
    ("BUDGET-2025-CLIMATE", {"fiscal_year": "2025", "document_type": "CLIMATE"}),
    ("BUDGET-2025-LRB", {"fiscal_year": "2025", "document_type": "LRB"}),
    ("BUDGET-2026-CROSSCUT", {"fiscal_year": "2026", "document_type": "CROSSCUT"}),
    ("BUDGET-2026-DOD", {"fiscal_year": "2026", "document_type": "DOD"}),
)


def mods_xml(*, access_id: str = PACKAGE, collection: str = "CRPT", urls: str = "") -> bytes:
    """A minimal shape-correct package MODS over the given parts."""
    renditions = urls or (
        f'<url displayLabel="HTML rendition" access="raw object">{BODY_URL}</url>'
        f'<url displayLabel="PDF rendition" access="raw object">'
        f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf</url>"
    )
    return (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><collectionCode>{collection}</collectionCode>"
        f"<accessId>{access_id}</accessId></extension>"
        f"<location>{renditions}</location></mods>"
    ).encode()


@pytest.mark.parametrize(
    ("package_id", "fields"),
    [
        ("CRPT-119hrpt1", {"congress": 119, "document_type": "hrpt", "number": "1"}),
        ("CRPT-118erpt5", {"congress": 118, "document_type": "erpt", "number": "5"}),
        ("CHRG-119hhrg64242", {"congress": 119, "document_type": "hhrg", "number": "64242"}),
        ("CHRG-116jhrg43189", {"congress": 116, "document_type": "jhrg", "number": "43189"}),
        ("CDOC-119tdoc2", {"congress": 119, "document_type": "tdoc", "number": "2"}),
        ("CDOC-113hdoc132", {"congress": 113, "document_type": "hdoc", "number": "132"}),
        # Upper-case, unlike CRPT's own hrpt/srpt/erpt -- measured on a real
        # package summary (CPRT-118HPRT57104); SPRT and JPRT confirmed real
        # via a published walk (fixture README).
        ("CPRT-118HPRT57104", {"congress": 118, "document_type": "HPRT", "number": "57104"}),
        ("CPRT-113SPRT52146", {"congress": 113, "document_type": "SPRT", "number": "52146"}),
        ("CPRT-116JPRT41347", {"congress": 116, "document_type": "JPRT", "number": "41347"}),
        ("CREC-2026-01-02", {"issue_date": "2026-01-02", "issue_suffix": None}),
        ("CREC-2019-01-03-v164", {"issue_date": "2019-01-03", "issue_suffix": "v164"}),
        ("CREC-2009-12-18-i194", {"issue_date": "2009-12-18", "issue_suffix": "i194"}),
        ("CDIR-2026-02-20", {"issue_date": "2026-02-20"}),
        ("BILLS-119hr1enr", {"congress": 119, "document_type": "hr", "number": "1", "version": "enr"}),
        ("BILLS-119hjres25enr", {"congress": 119, "document_type": "hjres", "number": "25", "version": "enr"}),
        *BUDGET_ID_CASES,
        # The Senate Secretary's CDOC reprints. The collection is the whole
        # two-segment prefix, which is what keeps GPO-J6-REPORT refused below.
        ("GPO-CDOC-119sdoc3", {"collection": "GPO-CDOC", "congress": 119, "document_type": "sdoc", "number": "3"}),
        ("GPO-CDOC-119sdoc6", {"collection": "GPO-CDOC", "congress": 119, "document_type": "sdoc", "number": "6"}),
    ],
)
def test_each_collection_grammar_keeps_the_publishers_own_parts(package_id: str, fields: dict[str, object]) -> None:
    """Each collection's grammar keeps the publisher's own id parts, with the collection as the id prefix."""
    identity = parse_package_id(package_id)
    assert identity.package_id == package_id
    # The collection is the id's own prefix, which is one path segment for
    # seven collections and two for the GPO-prefixed CDOC reprints.
    assert package_id.startswith(f"{identity.collection}-")
    for name, value in fields.items():
        assert getattr(identity, name) == value


@pytest.mark.parametrize(
    ("package_id", "message"),
    [
        # Real ids a collection-scoped published walk returns from neighboring
        # collections: ERP-2009 states collectionCode ERP and GPO-J6-REPORT
        # states GPO, so neither is a CDOC or CRPT address.
        ("ERP-2009", "collection is unsupported"),
        ("GPO-J6-REPORT", "collection is unsupported"),
        ("GPO-CRPT-116hrpt562", "collection is unsupported"),
        ("CHRG-119xhrg64242", "grammar"),
        ("CRPT-119hrpt0", "grammar"),
        ("CPRT-118hprt57104", "grammar"),  # lower-case: not the measured spelling
        ("BILLS-119hr1", "grammar"),
        ("CREC-2026-01-02-p3", "grammar"),
        ("CREC-2026-02-30", "calendar date"),
        ("CDIR-2026-2-20", "grammar"),
        ("FR-2026-01-02", "collection is unsupported"),
        ("CRPT119hrpt1", "collection is unsupported"),
        ("", "nonempty string"),
        ("CRPT-" + "1" * 200, "128 characters"),
        # A budget part no measurement has seen: refused rather than addressed
        # at a guessed URL, the rule every grammar here follows. The
        # vocabulary is additions-only and still sealed after the 2026-09-20
        # widening -- these are not near-misses of the thirteen, they are
        # plausible spellings the publisher has never been seen to use.
        ("BUDGET-2027-APPENDIX", "grammar"),
        ("BUDGET-2027-TOC", "grammar"),
        ("BUDGET-2027-SUPP", "grammar"),
        ("BUDGET-27-APP", "grammar"),
        ("BUDGET-2027-app", "grammar"),
        ("BUDGET-2027-objclass", "grammar"),
        # hdoc and tdoc are real CDOC document types and are deliberately not
        # inferred for the GPO-prefixed reprints: only sdoc has been measured.
        ("GPO-CDOC-119hdoc3", "grammar"),
        ("GPO-CDOC-119tdoc3", "grammar"),
        ("GPO-CDOC-119sdoc0", "grammar"),
        # And the id the two-segment prefix exists to keep refused: it states
        # collectionCode GPO too, and is a different family at another address.
        ("GPO-CDOC2-119sdoc3", "collection is unsupported"),
    ],
)
def test_unsupported_package_ids_refuse_by_name(package_id: str, message: str) -> None:
    """Unsupported package ids are refused by name."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        parse_package_id(package_id)


def test_package_id_must_be_a_string() -> None:
    """A package id must be a nonempty string."""
    with pytest.raises(GovInfoBodySourceError, match="nonempty string"):
        parse_package_id(None)


def test_the_budget_part_vocabulary_is_exactly_what_an_id_proved() -> None:
    """Sealed, not a token, and every part carries the id that showed it.

    ``MEASURED_BUDGET_PARTS`` is the vocabulary and the grammar's alternation
    is built from it, so asserting one against a copy of the other here would
    be the set agreeing with itself. It is checked against the independent
    thing instead: ``BUDGET_ID_CASES``, thirteen real package ids from
    measured ``published`` walks. A part added without the id that showed it
    fails the first assertion; an id whose part is not in the vocabulary makes
    ``parse_package_id`` raise. The count is pinned separately, so dropping a
    matched pair passes neither.

    Parsing each id is also what proves ``DB`` does not shadow ``DOD``: the
    alternation is sorted alphabetically, and only ``fullmatch``'s
    backtracking past a shorter alternative makes that safe.
    """
    assert {parse_package_id(package_id).document_type for package_id, _ in BUDGET_ID_CASES} == MEASURED_BUDGET_PARTS
    assert len(MEASURED_BUDGET_PARTS) == len(BUDGET_ID_CASES) == 13


@pytest.mark.parametrize(
    ("format", "expected"),
    [
        ("htm", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/html/{PACKAGE}.htm"),
        ("xml", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/xml/{PACKAGE}.xml"),
        # The publisher's text folder is "text", not the format name.
        ("txt", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/text/{PACKAGE}.txt"),
        ("pdf", f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf"),
    ],
)
def test_body_locators_follow_the_publishers_folders(format: str, expected: str) -> None:
    """Body locators follow the publisher's folders for each format and accept either a string or a parsed id."""
    assert package_body_locator(PACKAGE, format) == expected
    assert package_body_locator(parse_package_id(PACKAGE), format) == expected


def test_keyed_locators_carry_no_credential() -> None:
    """Keyed locators carry no credential in the URL."""
    assert package_summary_locator(PACKAGE) == SUMMARY_URL
    assert package_mods_locator(PACKAGE) == MODS_URL
    assert "api_key" not in SUMMARY_URL + MODS_URL


def test_unsupported_format_refuses() -> None:
    """An unsupported body format is refused."""
    with pytest.raises(GovInfoBodySourceError, match="body format must be"):
        package_body_locator(PACKAGE, "jpeg")


def test_real_summary_states_the_package_and_no_body_rendition() -> None:
    """The real CRPT summary states the package, dates and title but names only mods, premis and zip links."""
    summary = validate_package_summary(SUMMARY, package=PACKAGE, final_url=SUMMARY_URL, max_bytes=200_000)
    assert summary.identity.package_id == PACKAGE
    assert summary.collection_code == "CRPT"
    assert summary.date_issued == "2025-01-21"
    assert summary.last_modified == "2025-05-16T15:44:06Z"
    assert summary.title is not None and summary.title.startswith("PROVIDING FOR CONSIDERATION")
    # Measured 2026-09-19: the CRPT summary names only premis, zip and mods,
    # while the package does serve HTML and PDF. The links are kept as the
    # publisher spelled them; the offered set comes from the MODS instead.
    assert [name for name, _url in summary.download_links] == ["modsLink", "premisLink", "zipLink"]


def test_download_links_are_kept_as_evidence_including_a_repeated_name() -> None:
    """Download links are kept as evidence, including repeated names."""
    # GPO-J6-REPORT states five jpegLink entries as one list.
    document = {
        "packageId": PACKAGE,
        "collectionCode": "CRPT",
        "download": {
            "txtLink": f"https://api.govinfo.gov/packages/{PACKAGE}/htm",
            "jpegLink": [f"https://api.govinfo.gov/packages/{PACKAGE}/jpeg"] * 2,
        },
    }
    summary = validate_package_summary(
        json.dumps(document).encode(), package=PACKAGE, final_url=SUMMARY_URL, max_bytes=10_000
    )
    assert summary.download_links == (
        ("jpegLink", f"https://api.govinfo.gov/packages/{PACKAGE}/jpeg"),
        ("jpegLink", f"https://api.govinfo.gov/packages/{PACKAGE}/jpeg"),
        ("txtLink", f"https://api.govinfo.gov/packages/{PACKAGE}/htm"),
    )


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (json.dumps({"packageId": "CRPT-119hrpt2", "collectionCode": "CRPT"}).encode(), SUMMARY_URL, "packageId"),
        (json.dumps({"packageId": PACKAGE, "collectionCode": "CHRG"}).encode(), SUMMARY_URL, "collectionCode"),
        (json.dumps({"packageId": PACKAGE}).encode(), SUMMARY_URL, "collectionCode"),
        (json.dumps([PACKAGE]).encode(), SUMMARY_URL, "not a JSON object"),
        (b"{", SUMMARY_URL, "invalid"),
        (b"", SUMMARY_URL, "empty"),
        (SUMMARY, MODS_URL, "final URL"),
        (
            json.dumps({"packageId": PACKAGE, "collectionCode": "CRPT", "download": []}).encode(),
            SUMMARY_URL,
            "download block",
        ),
        (
            json.dumps({"packageId": PACKAGE, "collectionCode": "CRPT", "download": {"zipLink": 7}}).encode(),
            SUMMARY_URL,
            "download link",
        ),
    ],
)
def test_summary_refusals(body: bytes, final_url: str, message: str) -> None:
    """Summary refusals name the failed check."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_package_summary(body, package=PACKAGE, final_url=final_url, max_bytes=200_000)


def test_summary_over_its_byte_bound_refuses() -> None:
    """A summary over its byte bound refuses."""
    with pytest.raises(GovInfoBodySourceError, match="byte bound"):
        validate_package_summary(SUMMARY, package=PACKAGE, final_url=SUMMARY_URL, max_bytes=len(SUMMARY) - 1)


def test_real_mods_states_the_access_id_and_the_offered_renditions() -> None:
    """The real MODS states its access ids, collection code and offered renditions."""
    mods = validate_package_mods(MODS, package=PACKAGE, final_url=MODS_URL, max_bytes=200_000)
    assert mods.access_ids == (PACKAGE, PACKAGE)
    assert mods.collection_code == "CRPT"
    assert mods.offered_formats == ("htm", "pdf")
    assert mods.other_renditions == ()


def test_real_mods_states_every_bill_and_primary_bill_is_not_the_first_listed() -> None:
    """Every bill is stated and PRIMARY is selected by context, not by first listing."""
    mods = validate_package_mods(MODS, package=PACKAGE, final_url=MODS_URL, max_bytes=200_000)
    assert mods.bills == (
        ModsBill(congress=119, bill_type="S", number="5", context="OTHER", normalized_bill_type="s"),
        ModsBill(congress=119, bill_type="HRES", number="53", context="OTHER", normalized_bill_type="hres"),
        ModsBill(congress=119, bill_type="HRES", number="53", context="PRIMARY", normalized_bill_type="hres"),
        ModsBill(congress=119, bill_type="HR", number="471", context="OTHER", normalized_bill_type="hr"),
    )
    # First-listed is S. 5, which is not the bill this report is about.
    assert mods.bills[0].bill_type == "S" and mods.bills[0].context != "PRIMARY"
    assert mods.primary_bill == ModsBill(
        congress=119, bill_type="HRES", number="53", context="PRIMARY", normalized_bill_type="hres"
    )


def test_a_mods_with_no_bill_elements_has_no_primary_bill() -> None:
    """A MODS with no bill elements has no primary bill."""
    mods = validate_package_mods(mods_xml(), package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.bills == ()
    assert mods.primary_bill is None


def test_a_bill_element_missing_a_required_attribute_is_skipped_not_guessed() -> None:
    """A bill element missing a required attribute is skipped, not guessed."""
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId>"
        '<bill congress="119" context="PRIMARY" number="1"></bill>'  # no type
        '<bill congress="119" context="PRIMARY" number="2" type="HR"></bill>'
        "</extension></mods>"
    ).encode()
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.bills == (
        ModsBill(congress=119, bill_type="HR", number="2", context="PRIMARY", normalized_bill_type="hr"),
    )


def test_a_bill_element_with_a_non_numeric_number_is_skipped_not_guessed() -> None:
    """A bill element with a non-numeric number is skipped, not guessed."""
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId>"
        '<bill congress="119" context="PRIMARY" number="unknown" type="HR"></bill>'
        '<bill congress="119" context="PRIMARY" number="2" type="HR"></bill>'
        "</extension></mods>"
    ).encode()
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.bills == (
        ModsBill(congress=119, bill_type="HR", number="2", context="PRIMARY", normalized_bill_type="hr"),
    )


def test_a_bill_element_with_no_context_is_kept_as_an_empty_mention() -> None:
    """A bill element with no context is kept as an empty mention and never PRIMARY."""
    # spicy-regs's own MODS reader keeps a context-less <bill> as a mention
    # rather than dropping it; this module does the same.
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId>"
        '<bill congress="119" number="1" type="HR"></bill>'  # no context
        "</extension></mods>"
    ).encode()
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.bills == (ModsBill(congress=119, bill_type="HR", number="1", context="", normalized_bill_type="hr"),)
    # An empty context is never PRIMARY, so it does not become the primary bill.
    assert mods.primary_bill is None


def test_an_unrecognized_bill_type_normalizes_to_none() -> None:
    """An unrecognized bill type normalizes to None."""
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId>"
        '<bill congress="119" context="PRIMARY" number="1" type="XX"></bill>'
        "</extension></mods>"
    ).encode()
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.bills == (
        ModsBill(congress=119, bill_type="XX", number="1", context="PRIMARY", normalized_bill_type=None),
    )


def test_real_cprt_summary_and_mods_state_the_committee_print() -> None:
    """The real CPRT summary and MODS state the committee print, with XML offered and COVER context not mistaken for
    PRIMARY.
    """
    summary_url = f"https://api.govinfo.gov/packages/{CPRT_PACKAGE}/summary"
    mods_url = f"https://api.govinfo.gov/packages/{CPRT_PACKAGE}/mods"

    summary = validate_package_summary(CPRT_SUMMARY, package=CPRT_PACKAGE, final_url=summary_url, max_bytes=200_000)
    assert summary.identity.package_id == CPRT_PACKAGE
    assert summary.identity.collection == "CPRT"
    assert summary.identity.document_type == "HPRT"
    assert summary.collection_code == "CPRT"
    assert summary.title is not None and "KEEPING VIOLENT OFFENDERS" in summary.title

    mods = validate_package_mods(CPRT_MODS, package=CPRT_PACKAGE, final_url=mods_url, max_bytes=200_000)
    assert mods.access_ids == (CPRT_PACKAGE, CPRT_PACKAGE)
    assert mods.collection_code == "CPRT"
    # Unlike CRPT/CHRG/CDOC (htm, pdf only), the one committee print measured
    # also offers xml -- confirmed by the real MODS, not assumed.
    assert mods.offered_formats == ("htm", "pdf", "xml")
    assert mods.moved_renditions == ()
    assert mods.other_renditions == ()
    # This print's own <bill> states context="COVER", not "PRIMARY" -- a
    # third context spelling beyond the two CRPT-119hrpt1 measures, and
    # proof primary_bill does not mistake a cover-page mention for the
    # report's own bill.
    assert mods.bills == (
        ModsBill(congress=118, bill_type="HR", number="8205", context="COVER", normalized_bill_type="hr"),
    )
    assert mods.primary_bill is None


@pytest.mark.parametrize(
    ("package", "records", "fiscal_year", "laws"),
    [
        # Both families the grammar was widened to on 2026-09-20. Before it,
        # the MODS re-check could prove these records only by a fallback that
        # checks the root accessId alone: no final-URL check and no
        # collectionCode check, because this module derived neither for a
        # collection its grammar did not cover.
        (BUDGET_PACKAGE, BUDGET_FIXTURES, "2026", 1),
        (REPRINT_PACKAGE, FIXTURES, None, 6),
    ],
)
def test_the_two_widened_collections_prove_identity_through_the_sealed_validators(
    package: str, records: Path, fiscal_year: str | None, laws: int
) -> None:
    """The two widened collections state GPO as their code and prove identity against the grammar's recorded code,
    not the id prefix.
    """
    summary_url = f"https://api.govinfo.gov/packages/{package}/summary"
    mods_url = f"https://api.govinfo.gov/packages/{package}/mods"

    summary = validate_package_summary(
        (records / f"summary-{package}.json").read_bytes(), package=package, final_url=summary_url, max_bytes=200_000
    )
    assert summary.identity.package_id == package
    assert summary.collection_code == "GPO" != summary.identity.collection
    assert summary.pages is not None and summary.pages.isdecimal()

    mods = validate_package_mods(
        (records / f"mods-{package}.xml").read_bytes(), package=package, final_url=mods_url, max_bytes=200_000
    )
    assert mods.access_ids == (package,)
    assert mods.collection_code == "GPO"
    # PDF and nothing else, for every one of the eleven records measured, and
    # the rendition URL the publisher states is exactly this module's locator.
    assert mods.offered_formats == ("pdf",)
    assert mods.moved_renditions == ()
    assert mods.fiscal_year == fiscal_year
    assert len(mods.laws) == laws


@pytest.mark.parametrize("package", [BUDGET_PACKAGE, REPRINT_PACKAGE])
@pytest.mark.parametrize("record", ["summary", "mods"])
def test_a_widened_collections_record_offered_under_another_id_is_refused(package: str, record: str) -> None:
    """A widened collection's record offered under another real id, or at a wrong final URL, is refused."""
    other = {BUDGET_PACKAGE: "BUDGET-2027-BUD", REPRINT_PACKAGE: "GPO-CDOC-119sdoc5"}[package]
    records = BUDGET_FIXTURES if package == BUDGET_PACKAGE else FIXTURES
    if record == "summary":
        body = (records / f"summary-{package}.json").read_bytes()
        with pytest.raises(GovInfoBodySourceError, match="packageId"):
            validate_package_summary(body, package=other, final_url=package_summary_locator(other), max_bytes=200_000)
        # And the same bytes at the wrong final URL, the check the measurement
        # tool's fallback could not make at all.
        with pytest.raises(GovInfoBodySourceError, match="final URL"):
            validate_package_summary(body, package=package, final_url=package_mods_locator(package), max_bytes=200_000)
        return
    body = (records / f"mods-{package}.xml").read_bytes()
    with pytest.raises(GovInfoBodySourceError, match="accessId"):
        validate_package_mods(body, package=other, final_url=package_mods_locator(other), max_bytes=200_000)
    with pytest.raises(GovInfoBodySourceError, match="final URL"):
        validate_package_mods(body, package=package, final_url=package_summary_locator(package), max_bytes=200_000)


@pytest.mark.parametrize("collection", ["BUDGET", "GPO-CDOC"])
def test_a_widened_collection_still_refuses_a_record_stating_another_code(collection: str) -> None:
    """A widened collection still refuses a record stating another collection's real code."""
    package = f"{collection}-2026-MSR" if collection == "BUDGET" else f"{collection}-119sdoc3"
    document = json.dumps({"packageId": package, "collectionCode": "CRPT"}).encode()
    with pytest.raises(GovInfoBodySourceError, match="collectionCode"):
        validate_package_summary(
            document, package=package, final_url=package_summary_locator(package), max_bytes=10_000
        )
    mods = (
        '<mods xmlns="http://www.loc.gov/mods/v3"><extension>'
        f"<collectionCode>CRPT</collectionCode><accessId>{package}</accessId>"
        "</extension></mods>"
    ).encode()
    with pytest.raises(GovInfoBodySourceError, match="collectionCode"):
        validate_package_mods(mods, package=package, final_url=package_mods_locator(package), max_bytes=10_000)


def test_stated_collection_code_is_the_publishers_answer_not_the_prefix() -> None:
    """The stated collection code is the publisher's answer, not the id prefix, and unsupported collections refuse."""
    assert stated_collection_code("CRPT") == "CRPT"
    assert stated_collection_code("BUDGET") == stated_collection_code("GPO-CDOC") == "GPO"
    with pytest.raises(GovInfoBodySourceError, match="collection is unsupported"):
        stated_collection_code("ERP")


def test_real_bills_mods_offers_uslm_directly_not_moved() -> None:
    """The real BILLS MODS offers USLM directly at its own locator, not as a moved rendition."""
    mods_url = f"https://api.govinfo.gov/packages/{USLM_BILL_PACKAGE}/mods"
    mods = validate_package_mods(USLM_BILL_MODS, package=USLM_BILL_PACKAGE, final_url=mods_url, max_bytes=200_000)
    assert mods.access_ids == (USLM_BILL_PACKAGE,)
    assert mods.offered_formats == ("htm", "pdf", "xml", "uslm")
    # Before B7 this package's USLM rendition read as "moved" (a supported
    # file type at an address this module did not derive); it is now offered
    # directly, at its own locator.
    assert mods.moved_renditions == ()
    assert package_body_locator(USLM_BILL_PACKAGE, "uslm") == (
        f"https://www.govinfo.gov/content/pkg/{USLM_BILL_PACKAGE}/uslm/{USLM_BILL_PACKAGE}.xml"
    )


def test_this_packages_rendition_at_another_address_reads_as_disagreement() -> None:
    """This package's rendition at another address reads as a moved rendition, not an offer."""
    # A supported file type at the package's own content address, but a
    # folder this module does not derive -- before B7 this was BILLS's own
    # USLM rendition; now that uslm has its own locator (uslm/{id}.xml), any
    # other folder still demonstrates the same disagreement.
    moved = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/alt/{PACKAGE}.pdf"
    body = mods_xml(
        urls=(
            f'<url displayLabel="HTML rendition" access="raw object">{BODY_URL}</url>'
            f'<url displayLabel="PDF rendition" access="raw object">{moved}</url>'
            '<url displayLabel="Content Detail" access="object in context">'
            f"https://www.govinfo.gov/app/details/{PACKAGE}</url>"
        )
    )
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.offered_formats == ("htm",)
    assert mods.moved_renditions == (("pdf", moved),)
    assert mods.other_renditions == ()


def test_uslm_and_xml_share_an_extension_but_xml_wins_the_moved_label() -> None:
    """USLM and XML share an extension, and XML wins the moved-rendition label."""
    # uslm and xml both serve xml/{id}.xml-shaped addresses (folder differs,
    # extension does not), so a rendition found at neither locator can only
    # be labelled by extension; xml is the tie-break (bodies._FORMAT_BY_EXTENSION).
    moved = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/alt/{PACKAGE}.xml"
    body = mods_xml(urls=f'<url displayLabel="XML rendition" access="raw object">{moved}</url>')
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.moved_renditions == (("xml", moved),)


def test_another_packages_rendition_and_an_unsupported_file_type_say_nothing_here() -> None:
    """Another package's rendition and an unsupported file type are recorded as other renditions, not offers or
    moves.
    """
    other = "https://www.govinfo.gov/content/pkg/CRPT-119hrpt2/html/CRPT-119hrpt2.htm"
    jpeg = f"https://www.govinfo.gov/content/pkg/{PACKAGE}/jpeg/{PACKAGE}.jpg"
    body = mods_xml(
        urls=(
            f'<url displayLabel="HTML rendition" access="raw object">{other}</url>'
            f'<url displayLabel="Image" access="raw object">{jpeg}</url>'
        )
    )
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.offered_formats == ()
    assert mods.moved_renditions == ()
    assert mods.other_renditions == (("HTML rendition", other), ("Image", jpeg))


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (mods_xml(access_id="CRPT-119hrpt2"), MODS_URL, "accessId differs"),
        (mods_xml(collection="CHRG"), MODS_URL, "collectionCode differs"),
        (b'<mods xmlns="http://www.loc.gov/mods/v3"><location/></mods>', MODS_URL, "states no accessId"),
        (b"<notmods/>", MODS_URL, "unreadable"),
        (b"<mods", MODS_URL, "unreadable"),
        (mods_xml(), SUMMARY_URL, "final URL"),
        (b"", MODS_URL, "empty"),
    ],
)
def test_mods_refusals(body: bytes, final_url: str, message: str) -> None:
    """MODS refusals name the failed check."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_package_mods(body, package=PACKAGE, final_url=final_url, max_bytes=200_000)


def test_every_package_level_access_id_must_agree() -> None:
    """Every package-level access id must agree."""
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId></extension>"
        "<extension><accessId>CRPT-119hrpt9</accessId></extension></mods>"
    ).encode()
    with pytest.raises(GovInfoBodySourceError, match="accessId differs"):
        validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)


def test_a_constituent_access_id_names_a_granule_not_this_package() -> None:
    """A constituent access id names a granule, not this package, and does not become a package access id."""
    body = (
        '<mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{PACKAGE}</accessId></extension>"
        '<relatedItem type="constituent"><extension>'
        f"<accessId>{PACKAGE}-pt1</accessId></extension></relatedItem></mods>"
    ).encode()
    mods = validate_package_mods(body, package=PACKAGE, final_url=MODS_URL, max_bytes=10_000)
    assert mods.access_ids == (PACKAGE,)


def test_real_body_is_proved_by_its_locator_and_media_type() -> None:
    """The real body is proved by its locator and media type, carrying no printed package id."""
    identity = validate_package_body(
        BODY, package=PACKAGE, format="htm", content_type="text/html", final_url=BODY_URL, max_bytes=200_000
    )
    assert identity.format == "htm"
    assert identity.media_type == "text/html"
    assert identity.byte_size == len(BODY) == 13_953
    # The body names no package: identity rests on the locator, the MODS
    # rendition statement and the error-page exclusion, not on a printed id.
    assert PACKAGE.encode() not in BODY


@pytest.mark.parametrize(
    ("body", "format", "content_type", "final_url", "message"),
    [
        (b"", "htm", "text/html", BODY_URL, "empty"),
        (ERROR_PAGE, "htm", "text/html", BODY_URL, "error page"),
        (b"<html>whatever</html>", "htm", "text/html", "https://www.govinfo.gov/error", "error page"),
        (BODY, "htm", "application/pdf", BODY_URL, "Content-Type"),
        (BODY, "htm", None, BODY_URL, "Content-Type"),
        (BODY, "htm", "text/html", MODS_URL, "final URL"),
        (
            b"not a pdf",
            "pdf",
            "application/pdf",
            f"https://www.govinfo.gov/content/pkg/{PACKAGE}/pdf/{PACKAGE}.pdf",
            "%PDF-",
        ),
    ],
)
def test_body_refusals(body: bytes, format: str, content_type: str | None, final_url: str, message: str) -> None:
    """Body refusals name the failed check."""
    with pytest.raises(GovInfoBodySourceError, match=message):
        validate_package_body(
            body, package=PACKAGE, format=format, content_type=content_type, final_url=final_url, max_bytes=200_000
        )


def test_body_over_its_byte_bound_refuses() -> None:
    """A body over its byte bound refuses."""
    with pytest.raises(GovInfoBodySourceError, match="byte bound"):
        validate_package_body(
            BODY, package=PACKAGE, format="htm", content_type="text/html", final_url=BODY_URL, max_bytes=len(BODY) - 1
        )


@pytest.mark.parametrize("format", sorted(PACKAGE_BODY_FORMATS))
def test_every_supported_format_accepts_its_own_media_type(format: str) -> None:
    """Every supported format accepts its own media type."""
    body = b"%PDF-1.4\n" if format == "pdf" else b"<x/>"
    media_type = PACKAGE_BODY_FORMATS[format].media_types[0]
    identity = validate_package_body(
        body,
        package=PACKAGE,
        format=format,
        content_type=f"{media_type}; charset=utf-8",
        final_url=package_body_locator(PACKAGE, format),
        max_bytes=1_000,
    )
    assert identity.format == format and identity.media_type == media_type


def test_the_error_page_rule_is_the_same_one_the_federal_register_route_uses() -> None:
    """The soft-404 error-page rule is the same one the Federal Register route uses."""
    with pytest.raises(FederalRegisterBodySourceError, match="soft-404"):
        validate_govinfo_granule(
            ERROR_PAGE,
            source_document_number="98-14931",
            publication_date="1998-06-03",
            access_id="98-14931",
            final_url="https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm",
            max_bytes=1_024,
        )
