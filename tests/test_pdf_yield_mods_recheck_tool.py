"""The MODS recheck's readings and the sidecar the report is written from.

Pins which sampled documents GovInfo serves and what a MODS states (bill, law,
code, CFR, RIN, committee and member keys as the publisher spells them), the
print-side range flags and congress-blind exposure, credential scrubbing in the
request log, and that the committed sidecar and report block come from these
readings.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from spicy_docs.sources.govinfo.mods import parse_govinfo_mods
from tools.analysis.pdf_yield_mods_recheck import (
    DOCUMENT_REFERENCE_ELEMENTS,
    JOIN_KEY_RULES,
    MARK_END,
    MARK_START,
    MODS_KINDS,
    GovInfoDocument,
    RecheckError,
    RequestLog,
    compare_document,
    congress_blind_exposure,
    element_census,
    govinfo_documents,
    implausible,
    lossy_dollar_keys,
    main,
    mods_facts,
    render_block,
    sanity_flags,
)
from tools.analysis.pdf_yield_mods_recheck import _compact as compact_report
from tools.analysis.pdf_yield_mods_recheck import _print_sets as print_sets
from tools.analysis.pdf_yield_mods_recheck import _prove_identity as prove_identity
from tools.analysis.pdf_yield_mods_recheck import _request_counts as request_counts
from tools.analysis.pdf_yield_mods_recheck import _restate as restate
from tools.analysis.pdf_yield_mods_recheck import _safe as safe_name
from tools.analysis.pdf_yield_mods_recheck import _sanity_summary as sanity_summary

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "docs/research/pdf-yield-mods-recheck-2026-09-20.json"
REPORT = ROOT / "docs/research/pdf-yield-mods-recheck-2026-09-20.md"

#: One package MODS in miniature, spelled as GovInfo spells it: every element
#: this tool reads, with the attribute names and nesting measured on
#: CRPT-118hrpt968 and BUDGET-2027-APP.
MODS = b"""<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <extension>
    <accessId>CRPT-118hrpt968</accessId>
    <collectionCode>CRPT</collectionCode>
    <bill congress="118" context="PRIMARY" number="1093" type="HR"/>
    <bill congress="118" context="OTHER" number="21" type="HCONRES"/>
    <bill congress="117" number="5376" type="HR"/>
    <law congress="107" isPrivate="false" number="228"/>
    <law congress="110" isPrivate="true" number="4"/>
    <USCode title="5"><section detail="(a)(1)(B)" number="57a"/><chapter number="8"/></USCode>
    <cfr title="10"><part number="830"/></cfr>
    <statuteAtLarge volume="60"><pages pages="812"/></statuteAtLarge>
    <rin number="0584-AE88"/>
    <congCommittee authorityId="hsif00" chamber="H" congress="119" type="S">
      <name type="authority-standard">Committee on Energy and Commerce</name>
    </congCommittee>
    <congMember bioGuideId="M001157" chamber="H" congress="119" role="SUBMITTEDBY" state="TX">
      <name type="parsed">Mr. McCaul</name>
    </congMember>
    <congReport congress="118" number="52" type="H"/>
    <field name="Fiscal Year">2026</field>
  </extension>
</mods>
"""


@pytest.fixture(scope="module")
def facts() -> dict:
    return mods_facts(MODS)


def test_the_bill_element_reads_as_both_a_natural_key_and_a_congress_blind_key(facts: dict) -> None:
    """The print rule captures no Congress, so both spellings of the key are needed."""
    assert facts["stated"]["bill_number"] == ["HCONRES21", "HR1093", "HR5376"]
    assert facts["bill_natural_keys"] == ["117-hr-5376", "118-hconres-21", "118-hr-1093"]


def test_a_private_law_is_not_read_as_a_public_one(facts: dict) -> None:
    """``isPrivate`` is the only thing that separates them, and it is a string."""
    assert facts["stated"]["public_law"] == ["107-228", "110-4"]
    assert facts["law_natural_keys"] == ["107-public-228", "110-private-4"]


def test_a_code_section_a_chapter_and_a_cfr_part_each_keep_their_own_key(facts: dict) -> None:
    """A chapter cite keeps its own key rather than collapsing onto the section's and reading as already stated."""
    assert facts["stated"]["usc_section"] == ["5USC57A", "5USCCHAPTER8"]
    assert facts["stated"]["cfr_section"] == ["10CFR830"]
    assert facts["stated"]["statutes_at_large"] == ["60-812"]
    assert facts["stated"]["rin"] == ["RIN0584AE88"]


def test_the_mods_states_a_committee_system_code_and_a_member_bioguide_id(facts: dict) -> None:
    """Both are hosted-table keys already; neither needs a crosswalk or an extractor."""
    assert facts["stated"]["committee_name"] == ["hsif00"]
    assert facts["stated"]["bioguide_id"] == ["M001157"]


def test_a_member_without_a_bioguide_id_is_not_invented(facts: dict) -> None:
    """One of the eight sampled activity reports states exactly this shape."""
    without = MODS.replace(b'<congMember bioGuideId="M001157" ', b"<congMember ")
    assert mods_facts(without)["stated"]["bioguide_id"] == []


def test_the_document_references_are_read_as_congress_type_number(facts: dict) -> None:
    """Document references read as congress-type-number across report, doc, hearing and serial elements."""
    assert facts["document_references"] == {"congReport": ["118-H-52"]}
    assert set(DOCUMENT_REFERENCE_ELEMENTS) >= {"congReport", "congDoc", "congHearing", "congSerial"}


def test_the_element_census_reports_paths_rather_than_a_guessed_vocabulary() -> None:
    """Which kinds a collection states is measured from the bytes, never assumed."""
    census = element_census(parse_govinfo_mods(MODS).package.element)

    assert census["mods/extension/bill"] == 3
    assert census["mods/extension/USCode/section"] == 1
    assert census["mods/extension/congCommittee/name"] == 1


def test_a_key_the_mods_states_is_not_counted_as_print_only(facts: dict) -> None:
    """The owner's rule, in one case: the print repeats what the MODS already states."""
    printed = {"bill_number": ["HR1093"], "public_law": ["107-228"], "usc_section": ["5USC57A"]}
    compared = compare_document(printed, facts)

    assert compared["bill_number"]["print_only"] == []
    assert compared["public_law"]["print_only"] == []
    assert compared["usc_section"]["print_only"] == []
    # What the index knows that the capped read did not see is its own column.
    assert compared["bill_number"]["mods_only"] == 2


def test_a_key_the_mods_lacks_survives_as_yield(facts: dict) -> None:
    """A key the MODS lacks survives as print-only yield, and its kind reports as not stated."""
    compared = compare_document({"bill_number": ["HR9999"], "gao_product_id": ["GAO26109302"]}, facts)

    assert compared["bill_number"]["print_only"] == ["HR9999"]
    assert compared["gao_product_id"]["print_only"] == ["GAO26109302"]
    assert compared["gao_product_id"]["mods_states_this_kind"] is False


def test_a_printed_committee_is_compared_as_a_resolved_system_code(facts: dict) -> None:
    """Both sides are system codes: the MODS states one, the print's candidate is settled."""
    compared = compare_document({"committee_name": ["COMMITTEEONENERGYANDCOMMERCE", "COMMITTEEONAGRICULTURE"]}, facts)

    assert compared["committee_name"]["print_only"] == ["hsag00"]
    assert compared["committee_name"]["intersection"] == 1


def test_a_fiscal_year_compares_on_the_year_not_the_spelling(facts: dict) -> None:
    """``FY2026`` and ``FISCALYEAR2026`` are two print keys for one year."""
    compared = compare_document({"fiscal_year": ["FY2026", "FISCALYEAR2026", "FY2030"]}, facts)

    assert compared["fiscal_year"]["print_only"] == ["2030"]


@pytest.mark.parametrize(
    ("package_id", "granule_id", "expected"),
    [
        ("CRPT-118hrpt968", None, "https://api.govinfo.gov/packages/CRPT-118hrpt968/mods"),
        # Neither collection is in ``bodies.py``'s package-id grammar, so the
        # locator falls back to the published route shape and identity is
        # proved from the MODS's own accessId instead.
        ("BUDGET-2027-APP", None, "https://api.govinfo.gov/packages/BUDGET-2027-APP/mods"),
        (
            "GPO-CDOC-119sdoc6",
            "GPO-CDOC-119sdoc6-1",
            "https://api.govinfo.gov/packages/GPO-CDOC-119sdoc6/granules/GPO-CDOC-119sdoc6-1/mods",
        ),
    ],
)
def test_the_mods_locator_is_the_repositorys_own_where_the_grammar_reaches(
    package_id: str, granule_id: str | None, expected: str
) -> None:
    """The MODS locator is the repository's own where the grammar reaches, else the published route shape."""
    document = GovInfoDocument("f", "id", package_id, granule_id, "https://www.govinfo.gov/")

    assert document.mods_url == expected


def test_the_collection_is_read_apart_from_the_gpo_reprints() -> None:
    """``GPO-CDOC-119sdoc3`` is a GPO-collection reprint, not a CDOC package."""
    assert GovInfoDocument("f", "i", "GPO-CDOC-119sdoc3", None, "u").collection == "GPO-CDOC"
    assert GovInfoDocument("f", "i", "CRPT-118hrpt968", None, "u").collection == "CRPT"
    assert GovInfoDocument("f", "i", "BUDGET-2027-APP", None, "u").collection == "BUDGET"


def test_the_committed_sidecar_was_written_by_these_readings() -> None:
    """A report drifting from the code it cites is the failure this prevents."""
    sidecar = json.loads(SIDECAR.read_text())

    assert sidecar["mods_kinds"] == sorted(MODS_KINDS)
    assert sidecar["supersedes"] == "docs/research/pdf-family-rollup-yield-2026-09-20.json"
    assert sorted(sidecar["families"]) == ["budget", "house_activity", "senate_secretary"]


def test_the_committed_sidecar_states_the_number_the_correction_turns_on() -> None:
    """The 883 bills and 75 laws the rollup called print-only are zero against the MODS, capped and uncapped."""
    sidecar = json.loads(SIDECAR.read_text())
    capped = sidecar["families"]["house_activity"]["restated"]
    uncapped = sidecar["uncapped"]["restated"]["house_activity"]

    assert capped["bill_number"]["print_distinct_values"] == 883
    assert capped["bill_number"]["print_only_distinct_values"] == 0
    assert capped["public_law"]["print_distinct_values"] == 75
    assert capped["public_law"]["print_only_distinct_values"] == 0
    # And it is not an artifact of the rollup's 60-page cap: every page, same answer.
    assert sidecar["uncapped"]["pages_read"]["house_activity"] == 1249
    assert uncapped["bill_number"]["print_distinct_values"] == 1406
    assert uncapped["bill_number"]["print_only_distinct_values"] == 0
    assert uncapped["public_law"]["print_only_distinct_values"] == 1


def test_the_committed_sidecar_states_what_survives_as_pdf_only_value() -> None:
    """Budget laws and the activity reports' RIN, docket and committee keys are what survives as print-only value."""
    sidecar = json.loads(SIDECAR.read_text())
    activity = sidecar["uncapped"]["restated"]["house_activity"]
    budget = sidecar["uncapped"]["restated"]["budget"]

    # The budget volumes, not the activity reports, are the citation family.
    assert budget["public_law"]["print_only_distinct_values"] == 504
    # What the activity-report print still holds that no MODS states.
    assert activity["rin"]["print_only_distinct_values"] == 87
    assert activity["docket_number"]["print_only_distinct_values"] == 38
    assert activity["committee_name"]["print_only_distinct_values"] == 27
    assert activity["rin"]["mods_states_this_kind"] is False
    assert activity["docket_number"]["mods_states_this_kind"] is False


def test_the_committed_sidecar_states_which_kinds_each_collection_carries() -> None:
    """Per-record counts, because one record stating a kind is not a collection property."""
    stated = json.loads(SIDECAR.read_text())["collection_kinds_stated"]

    assert stated["CRPT"]["records"] == 8
    assert stated["CRPT"]["bill_number"] == 8
    assert stated["CRPT"]["bioguide_id"] == 7, "one sampled report states a congMember with no bioGuideId"
    assert stated["CRPT"]["cfr_section"] == 0
    assert stated["GPO-CDOC"]["bill_number"] == 0
    assert stated["BUDGET"]["committee_name"] == 0


def test_the_committed_sidecar_carries_no_per_document_key_lists() -> None:
    """The full sets are receipt-sized; the repository keeps the counts and a sample."""
    sidecar = json.loads(SIDECAR.read_text())
    cells = [
        cell
        for family in sidecar["families"].values()
        for document in family["documents"]
        for cell in (document.get("comparison") or {}).values()
    ]

    assert cells, "the sidecar states no document it compared"
    assert all(isinstance(cell["print_distinct"], int) for cell in cells)
    assert all("mods_values" not in cell for cell in cells)
    assert all(len(cell["print_only"]) <= 12 for cell in cells)


# --- the credential path, the identity proof, and which documents are read -----------


def test_a_planted_credential_survives_in_no_recorded_field(tmp_path: Path) -> None:
    """The one check AGENTS.md makes non-negotiable, run against what the log writes.

    Both fields are planted, so removing *either* ``scrub`` call in
    ``RequestLog.record`` fails this test rather than only one of them.
    """
    key = "planted-credential-0123456789abcdef"
    log = RequestLog(tmp_path, secrets=(key,))
    log.record(
        purpose="package-mods",
        mods_key="CRPT-118hrpt968",
        url=f"https://api.govinfo.gov/packages/CRPT-118hrpt968/mods?api_key={key}",
        status=200,
        media_type="application/xml",
        body=b"<mods/>",
        note=f"refused, and the message quoted the key {key}",
    )
    row = log.rows[-1]

    assert key not in row["url"], "the URL scrub was not applied"
    assert key not in row["note"], "the note scrub was not applied"
    assert "api_key=<redacted>" in row["url"]
    assert key not in (tmp_path / "requests.jsonl").read_text()


def test_a_credential_prefix_cannot_survive_truncation(tmp_path: Path) -> None:
    """Scrubbing happens before anything is shortened; half a key is still a key."""
    key = "abcdefgh12345678"
    log = RequestLog(tmp_path, secrets=(key,))

    assert log.scrub(f"...{key}...") == "...<redacted>..."
    assert key[:8] not in log.scrub(f"...{key}...")


def _mods_naming(access_id: str, host: str | None = None) -> bytes:
    host_block = (
        ""
        if host is None
        else f'<relatedItem type="host"><extension><accessId>{host}</accessId></extension></relatedItem>'
    )
    return (
        '<?xml version="1.0"?><mods xmlns="http://www.loc.gov/mods/v3">'
        f"<extension><accessId>{access_id}</accessId></extension>{host_block}</mods>"
    ).encode()


#: A real id from a neighbouring collection that a collection-scoped
#: ``published`` walk returns and ``bodies.py``'s grammar still refuses.  The
#: fallback's two cases were written on ``BUDGET-*`` and ``GPO-CDOC-*``, which
#: the grammar covered from 2026-09-20 (``docs/decisions.md``), so exercising
#: it needs a collection that is still outside the grammar or the branch is
#: never entered.
UNCOVERED = "ERP-2009"


def test_a_mods_that_names_another_package_is_refused() -> None:
    """The fallback's whole job: a record that does not name itself is not read."""
    document = GovInfoDocument("budget", UNCOVERED, UNCOVERED, None, "https://www.govinfo.gov/")

    with pytest.raises(RecheckError, match="accessId differs"):
        prove_identity(_mods_naming("ERP-2010"), document, document.mods_url)
    assert prove_identity(_mods_naming(UNCOVERED), document, document.mods_url) == "accessId"


def test_a_granule_mods_must_also_name_its_host_package() -> None:
    """A granule MODS must name its host package, and a different host refuses."""
    document = GovInfoDocument("budget", "x", UNCOVERED, f"{UNCOVERED}-1", "https://www.govinfo.gov/")
    granule = f"{UNCOVERED}-1"

    with pytest.raises(RecheckError, match="states no host package"):
        prove_identity(_mods_naming(granule), document, document.mods_url)
    with pytest.raises(RecheckError, match="host package differs"):
        prove_identity(_mods_naming(granule, host="ERP-2010"), document, document.mods_url)
    proof = prove_identity(_mods_naming(granule, host=UNCOVERED), document, document.mods_url)
    assert proof == "accessId+host"


def test_the_two_families_this_receipt_measured_no_longer_take_the_fallback() -> None:
    """BUDGET and GPO-CDOC now pass the sealed validators, whose own errors are raised before the fallback."""
    from spicy_docs.sources.govinfo.bodies import GovInfoBodySourceError

    package = GovInfoDocument("budget", "BUDGET-2027-APP", "BUDGET-2027-APP", None, "https://www.govinfo.gov/")
    assert prove_identity(_mods_naming("BUDGET-2027-APP"), package, package.mods_url) == "validate_package_mods"
    with pytest.raises(GovInfoBodySourceError, match="accessId differs"):
        prove_identity(_mods_naming("BUDGET-2027-BUD"), package, package.mods_url)

    granule = GovInfoDocument(
        "senate_secretary", "x", "GPO-CDOC-119sdoc6", "GPO-CDOC-119sdoc6-1", "https://www.govinfo.gov/"
    )
    proof = prove_identity(_mods_naming("GPO-CDOC-119sdoc6-1", host="GPO-CDOC-119sdoc6"), granule, granule.mods_url)
    assert proof == "validate_granule_mods"
    with pytest.raises(GovInfoBodySourceError, match="states no host package"):
        prove_identity(_mods_naming("GPO-CDOC-119sdoc6-1"), granule, granule.mods_url)


def test_only_govinfo_locators_are_read_and_only_the_first_eight(tmp_path: Path) -> None:
    """A superseded index kept beside the live one is skipped, and the sample stays at eight."""
    index = tmp_path / "index"
    index.mkdir()
    documents = [
        {
            "id": f"CRPT-118hrpt{n}",
            "url": f"https://www.govinfo.gov/content/pkg/CRPT-118hrpt{n}/pdf/CRPT-118hrpt{n}.pdf",
        }
        for n in range(960, 972)
    ]
    documents.append({"id": "gao-26-1", "url": "https://files.gao.gov/assets/gao-26-1.pdf"})
    (index / "house_activity.json").write_text(json.dumps({"documents": documents}))
    (index / "budget.superseded-wrong-collection-route.json").write_text(
        json.dumps(
            {
                "documents": [
                    {"id": "X", "url": "https://www.govinfo.gov/content/pkg/BUDGET-2027-APP/pdf/BUDGET-2027-APP.pdf"}
                ]
            }
        )
    )
    found = govinfo_documents(tmp_path)

    assert len(found) == 8, "the sample is the first eight documents of each index"
    assert all(document.package_id.startswith("CRPT-") for document in found)
    assert "BUDGET-2027-APP" not in {document.package_id for document in found}


# --- the print side's own false positives --------------------------------------------


@pytest.mark.parametrize(
    ("kind", "value", "expected"),
    [
        ("public_law", "188-11", "names Congress 188"),
        ("public_law", "118-11", None),
        ("bill_number", "S08", "zero-padded"),
        ("bill_number", "S8", None),
        ("usc_section", "99USC1", "outside 1-54"),
        ("usc_section", "42USC1983", None),
        ("cfr_section", "77CFR1", "outside 1-50"),
        ("docket_number", "APHIS20290068", "docket year 2029"),
        ("docket_number", "APHIS20190068", None),
        ("dollar_amount", "000000000", "not usable"),
        ("dollar_amount", "1250000", None),
        ("gao_product_id", "GAO23105523", None),
    ],
)
def test_a_surviving_key_is_tested_against_the_publishers_real_ranges(
    kind: str, value: str, expected: str | None
) -> None:
    """The mirror of the rollup's lookalike check, on the keys a contract would publish."""
    reason = implausible(kind, value)

    assert (reason is None) if expected is None else (expected in (reason or ""))


def test_the_flagged_key_carries_the_line_it_was_read_from() -> None:
    """``188-11`` is only obviously wrong once the print's own sentence is beside it."""
    text = "Passed House under suspension by voice vote. Public Law 188-11. (H.R. 548) To take certain lands"
    flags = sanity_flags(text, {"public_law": {"print_only": ["188-11"]}})

    assert flags["flagged"]["public_law"][0]["value"] == "188-11"
    assert "Passed House under suspension" in flags["flagged"]["public_law"][0]["evidence"]


def test_the_dollar_canonical_hides_the_decimal_separator() -> None:
    """``$28.4 billion`` and ``$284 billion`` are one key, which deflates the count."""
    lossy = lossy_dollar_keys("We spent $28.4 billion in 2026 and $284 billion over the decade.")

    assert lossy == {"284BILLION": ["28.4billion", "284billion"]}
    assert lossy_dollar_keys("We spent $28.4 billion and $1,000.") == {}


def test_the_congress_blind_comparison_reports_its_own_exposure() -> None:
    """A print naming an earlier Congress's bill is what a congress-blind key could hide."""
    facts = {"bill_natural_keys": ["117-hr-2773", "118-hr-1093"]}

    assert congress_blind_exposure(facts, ["HR2773", "HR1093"], "CRPT-118hrpt977") == ["HR2773"]
    assert congress_blind_exposure(facts, ["HR1093"], "CRPT-118hrpt977") == []


# --- the report is rendered from the sidecar -----------------------------------------


def test_the_report_block_renders_from_the_sidecar_and_matches_what_is_committed() -> None:
    """A report drifting from its own measurement fails here instead of being believed."""
    block = render_block(json.loads(SIDECAR.read_text()))
    assert block.startswith(MARK_START) and block.endswith(MARK_END)

    committed = REPORT.read_text()
    start, end = committed.find(MARK_START), committed.find(MARK_END) + len(MARK_END)
    assert start >= 0, "the report carries no generated-block markers"
    assert committed[start:end] == block, "run `render` to bring the report back in line with its sidecar"


def test_the_rendered_block_states_every_number_the_report_leads_with() -> None:
    """The numbers a reader would act on, named so a silent drop fails."""
    block = render_block(json.loads(SIDECAR.read_text()))

    for number in ("24 keyed requests", "18,119 pages", "1,494", "1,500", "1,249"):
        assert number in block, number
    for survivor in ("**504**", "**97**", "**87**", "**37**", "**27**", "**5**", "**65,261**", "**2,827**"):
        assert survivor in block, survivor
    for flagged in ("188-11", "S08", "APHIS20290068"):
        assert flagged in block, flagged


def test_the_prose_numbers_agree_with_the_measurement_too() -> None:
    """Numbers the report states in its own words still have to match the sidecar."""
    sidecar = json.loads(SIDECAR.read_text())
    report = REPORT.read_text()
    references = sum(
        sum(document.get("mods_document_references", {}).values())
        for document in sidecar["families"]["house_activity"]["documents"]
    )

    assert f"{references} entries" in report, references
    assert f"{sidecar['collection_kinds_stated']['CRPT']['bioguide_id']}/8" in report
    assert f"0 of {sidecar['uncapped']['restated']['house_activity']['public_law']['print_distinct_values']}" in report
    assert (
        f"0 of {sidecar['uncapped']['restated']['house_activity']['bill_number']['print_distinct_values']:,}" in report
    )
    exposure = sidecar["uncapped"]["restated"]["house_activity"]["sanity"]["congress_blind_exposure"]
    assert f"`{exposure[0]}`" in report, exposure


def test_the_sidecar_carries_no_credential() -> None:
    """The committed bytes, checked the way the sibling measurement checks its own."""
    text = SIDECAR.read_text()

    assert "api_key=" not in text
    assert "x-api-key" not in text.casefold()
    assert "<redacted>" not in text, "a redaction in the sidecar means a credential reached it first"


# --- the phases' own bookkeeping -----------------------------------------------------


def test_the_family_restatement_keeps_rows_and_distinct_values_apart() -> None:
    """One document citing one key is one row; two documents citing it are two rows, one key."""
    cell = {
        "print_distinct": ["HR1", "HR2"],
        "mods_distinct": 1,
        "mods_values": ["HR1"],
        "intersection": 1,
        "print_only": ["HR2"],
        "mods_only": 0,
        "mods_states_this_kind": True,
    }
    documents = [
        {"comparison": {"bill_number": cell}, "sanity": {"lossy_dollar_keys": 0, "lossy_dollar_examples": {}}},
        {"comparison": {"bill_number": cell}, "sanity": {"lossy_dollar_keys": 0, "lossy_dollar_examples": {}}},
    ]
    restated = restate(
        [
            {**document, "comparison": {name: dict(c) for name, c in document["comparison"].items()}}
            for document in documents
        ]
    )
    bills = restated["bill_number"]

    assert bills["print_link_rows"] == 4
    assert bills["print_distinct_values"] == 2
    assert bills["print_only_link_rows"] == 2
    assert bills["print_only_distinct_values"] == 1
    assert bills["print_only_against_family_union"] == 1
    assert bills["mods_reader_exists"] is True
    assert bills["mods_states_this_kind"] is True


def test_a_kind_with_a_reader_that_no_record_states_is_not_called_stated() -> None:
    """A CRPT MODS has a ``rin`` reader and states no RIN; the table must say so."""
    cell = {
        "print_distinct": ["RIN0503AA75"],
        "mods_distinct": 0,
        "mods_values": [],
        "intersection": 0,
        "print_only": ["RIN0503AA75"],
        "mods_only": 0,
        "mods_states_this_kind": True,
    }
    restated = restate([{"comparison": {"rin": cell}, "sanity": {"lossy_dollar_keys": 0, "lossy_dollar_examples": {}}}])

    assert restated["rin"]["mods_reader_exists"] is True
    assert restated["rin"]["mods_states_this_kind"] is False


def test_the_family_sanity_summary_unions_the_flagged_keys() -> None:
    """The family sanity summary unions flagged values, sums lossy keys and counts congress-blind exposure."""
    documents = [
        {
            "sanity": {
                "flagged": {"public_law": [{"value": "188-11", "reason": "names Congress 188", "evidence": "x"}]},
                "lossy_dollar_keys": 2,
                "lossy_dollar_examples": {"284BILLION": ["28.4billion", "284billion"]},
            },
            "congress_blind_exposure": ["HR2773"],
        },
        {
            "sanity": {
                "flagged": {"public_law": [{"value": "188-11", "reason": "names Congress 188", "evidence": "y"}]},
                "lossy_dollar_keys": 1,
                "lossy_dollar_examples": {},
            },
            "congress_blind_exposure": [],
        },
    ]
    summary = sanity_summary(documents)

    assert summary["flagged_distinct_values"] == {"public_law": 1}
    assert summary["flagged_reasons"]["public_law"]["188-11"] == "names Congress 188"
    assert summary["lossy_dollar_keys"] == 3
    assert summary["congress_blind_exposure_count"] == 1


def test_the_committed_sidecar_drops_the_receipt_sized_lists() -> None:
    """Compaction turns receipt-sized lists into counts and keeps at most twelve examples."""
    report = {
        "families": {
            "x": {
                "documents": [
                    {
                        "law_natural_keys_stated": ["119-public-21"],
                        "comparison": {
                            "bill_number": {
                                "print_distinct": ["HR1"] * 20,
                                "mods_distinct": 1,
                                "mods_values": ["HR1"],
                                "intersection": 1,
                                "print_only": ["HR2"] * 20,
                                "mods_only": 0,
                                "mods_states_this_kind": True,
                            },
                            "rin": {
                                "print_distinct": [],
                                "mods_distinct": 0,
                                "mods_values": [],
                                "intersection": 0,
                                "print_only": [],
                                "mods_only": 0,
                                "mods_states_this_kind": False,
                            },
                        },
                    }
                ]
            }
        }
    }
    document = compact_report(report)["families"]["x"]["documents"][0]

    assert "law_natural_keys_stated" not in document
    assert list(document["comparison"]) == ["bill_number"]
    assert document["comparison"]["bill_number"]["print_distinct"] == 20
    assert document["comparison"]["bill_number"]["print_only_count"] == 20
    assert len(document["comparison"]["bill_number"]["print_only"]) == 12
    assert "mods_values" not in document["comparison"]["bill_number"]


def test_the_request_count_is_read_back_from_the_log_not_asserted(tmp_path: Path) -> None:
    """A measurement that states its own spend from memory is stating a wish."""
    log = RequestLog(tmp_path, secrets=())
    assert log.request_count == 0
    assert log.retained("CRPT-118hrpt968") is None

    log.record(
        purpose="package-mods",
        mods_key="CRPT-118hrpt968",
        url="https://api.govinfo.gov/packages/CRPT-118hrpt968/mods",
        status=200,
        media_type="application/xml",
        body=b"<mods/>",
        note="validate_package_mods",
    )
    (tmp_path / "mods" / "CRPT-118hrpt968.xml").write_bytes(b"<mods/>")
    counts = request_counts(tmp_path)

    assert log.request_count == 1
    assert log.retained("CRPT-118hrpt968") is not None
    assert counts == {
        "total": 1,
        "keyed": 1,
        "bytes": 7,
        "by_status": {"200": 1},
        "by_purpose": {"package-mods": 1},
        "by_identity_proof": {"validate_package_mods": 1},
    }


def test_render_rewrites_only_the_block_between_the_markers(tmp_path: Path) -> None:
    """The prose around the generated numbers is the author's and is never touched."""
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(SIDECAR.read_text())
    report = tmp_path / "report.md"
    report.write_text(f"before\n\n{MARK_START}\nstale\n{MARK_END}\n\nafter\n")

    assert main(["render", "--sidecar", str(sidecar), "--report", str(report)]) == 0

    rewritten = report.read_text()
    assert rewritten.startswith("before\n\n")
    assert rewritten.endswith("\n\nafter\n")
    assert "stale" not in rewritten
    assert "24 keyed requests" in rewritten


def test_render_refuses_a_report_with_no_markers(tmp_path: Path) -> None:
    """Rendering refuses a report with no generated-block markers."""
    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(SIDECAR.read_text())
    report = tmp_path / "report.md"
    report.write_text("no markers here\n")

    with pytest.raises(RecheckError, match="no generated-block markers"):
        main(["render", "--sidecar", str(sidecar), "--report", str(report)])


def test_a_receipt_filename_is_safe_for_a_granule_key() -> None:
    """A granule key carries a slash; the retained file must not become a directory."""
    assert safe_name("GPO-CDOC-119sdoc6/GPO-CDOC-119sdoc6-1") == "GPO-CDOC-119sdoc6_GPO-CDOC-119sdoc6-1"
    assert "/" not in safe_name("a/b/c")


def test_the_print_side_is_read_from_the_rollups_own_retained_key_sets() -> None:
    """Every rule gets a set, including the ones the rollup's compaction dropped."""
    document = {"join_keys": {"bill_number": {"distinct": ["HR1093"], "count": 1}}}
    sets = print_sets(document)

    assert sets["bill_number"] == ["HR1093"]
    assert sets["rin"] == [], "a rule with no entry is an empty set, never a missing key"
    assert set(sets) == {rule.name for rule in JOIN_KEY_RULES}
