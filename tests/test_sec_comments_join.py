"""The SEC comments join connects rulemakings, retained mirror SEC documents, and comment files.

Every link carries the statement that proved it and its normalized forms. The
primary tier is the FR citation: the SEC side states it, the mirror side
derives it (``frDocNum`` -> Federal Register release -> volume/page), and the
fixture set shows both directions. The ``frDocNum``-only fallbacks -- release
number, then file number, through the Federal Register release's own
``docket_ids`` -- are accepted only because that map is on disk, and each
link says which tier produced it. Provenance of every fixture is in
``tests/fixtures/sec_comments/README.md``: the mirror and Federal Register
rows are real trimmed release records, the rule page is constructed from the
real captured index statements and real Federal Register records.
"""

import json
from pathlib import Path

import pytest

from spicy_docs.sources.sec_comments.join import (
    FrAgendaIndex,
    FrCitation,
    FrCollisionError,
    FrDocument,
    FrDocumentIndex,
    FrSecTitleIndex,
    MirrorSecIndex,
    SecCommentsJoinError,
    comments_by_docket,
    join_sec_comments,
    link_file_number_to_comments,
    link_rulemaking_to_mirror,
    match_sec_document_without_fr_doc_num,
    mirror_document_from_record,
    normalize_fr_citation,
    normalize_fr_doc_num,
    normalize_sec_title,
    stated_file_numbers,
    stated_release_numbers,
)
from spicy_docs.sources.sec_comments.pages import (
    SEC_SITE,
    SecCommentFile,
    SecCommentsSourceError,
    parse_rule_page,
    parse_rulemaking_index_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sec_comments"
#: Five real retained regulations.gov SEC document rows, trimmed to their join fields (README documents how).
MIRROR_JSONL = (FIXTURES / "mirror-sec-documents.jsonl").read_text()
#: Real Federal Register release rows for the documents those mirror rows derive to (plus the zero-padding case).
FR_JSONL = (FIXTURES / "federal-register-documents.jsonl").read_text()
#: The real captured rulemaking index render, whose S7-11-23 row states Release No. 34-103320.
INDEX = (FIXTURES / "rulemaking-index.html").read_bytes()
#: The rule page fixture: trimmed from the live 2026-09-24 capture (README documents the trim).
RULE_PAGE = (FIXTURES / "rule-page.html").read_bytes()
RULE_PAGE_URL = f"{SEC_SITE}/rules-regulations/2025/06/s7-11-23"
LISTING_URL = f"{SEC_SITE}/comments/s7-11-23/s71123.htm"


def mirror_index():
    return MirrorSecIndex.from_records(json.loads(line) for line in MIRROR_JSONL.splitlines())


def fr_index():
    return FrDocumentIndex.from_records(json.loads(line) for line in FR_JSONL.splitlines())


def rule_page(body=RULE_PAGE, url=RULE_PAGE_URL, **kwargs):
    return parse_rule_page(body, url=url, **kwargs)


def index_row():
    return parse_rulemaking_index_page(INDEX, url=f"{SEC_SITE}/rules-regulations/rulemaking-activity").rulemakings[2]


def comment(docket="s7-11-23", url=None, file_name=None, link_text="Cory", **kwargs):
    return SecCommentFile(
        docket=docket,
        url=url or f"{SEC_SITE}/comments/{docket}/{file_name or 's71123-x.htm'}",
        file_name=file_name or "s71123-x.htm",
        link_text=link_text,
        format=kwargs.pop("format", "htm"),
        letter_type=kwargs.pop("letter_type", "Public Comment"),
        date=kwargs.pop("date", "2024-02-02T12:00:00Z"),
    )


def test_a_citation_normalizes_to_itself_and_only_itself():
    cited = normalize_fr_citation("89 FR 45894")
    assert (cited.volume, cited.page, cited.normalized) == (89, 45894, "89 FR 45894")
    assert cited == FrCitation(89, 45894, "89 FR 45894")
    assert normalize_fr_citation(" 89   FR   45894 ") == cited
    # Pages below 1000 are citations too (the real E5-8282 starts at 71 FR 632).
    assert normalize_fr_citation("71 FR 632").normalized == "71 FR 632" and normalize_fr_citation("1 FR 1").page == 1
    for spelled in (
        "89FR45894",
        "89 F.R. 45894",
        "FR 89 45894",
        "89 CFR 45894",
        "89 FR 45894-45914",
        "",
        "89 FR",
        "089 FR 45894",
        "0 FR 12",
        "89 fr 45894",
        "89 FR 1234567",
    ):
        with pytest.raises(SecCommentsJoinError, match="FR citation"):
            normalize_fr_citation(spelled)


def test_an_fr_doc_num_normalizes_to_the_federal_register_release_spelling():
    assert normalize_fr_doc_num("2010-00239") == "2010-239"
    assert normalize_fr_doc_num("05-18895") == "05-18895"
    assert normalize_fr_doc_num("2024-31178") == "2024-31178"
    # One real mirror value carries an en dash where the release carries a hyphen.
    assert normalize_fr_doc_num("E8\u201327139") == "E8-27139"
    # The C/R series names a year segment, and the release pads some sequences.
    assert normalize_fr_doc_num("C1-2010-12986") == "C1-2010-12986"
    assert normalize_fr_doc_num("C1-2013-00201") == "C1-2013-201"
    for value in ("", "E8/27139", "2024-03-04", "no-number", None):
        with pytest.raises(SecCommentsJoinError, match="FR document number"):
            normalize_fr_doc_num(value)


def test_the_c7_mirror_series_remaps_to_z7_and_never_global_c_to_z():
    # Measured 2026-09-24: the mirror's C7-14563/C7-15181 are the Register's
    # Z7-14563/Z7-15181 (same dates, same titles, the 2007 SEC PRA notices).
    assert normalize_fr_doc_num("C7-14563") == "Z7-14563"
    assert normalize_fr_doc_num("C7-15181") == "Z7-15181"
    # The Register's own Z7 spelling is a fixed point.
    assert normalize_fr_doc_num("Z7-14563") == "Z7-14563"
    # The mirror's padded C7 corrections stay C7: the Register does serve C7-1476.
    assert normalize_fr_doc_num("C7-01476") == "C7-1476"
    # Never C -> Z in general: other series keep their letters.
    assert normalize_fr_doc_num("C9-26408") == "C9-26408"
    assert normalize_fr_doc_num("C1-2010-12986") == "C1-2010-12986"
    assert normalize_fr_doc_num("C6-653") == "C6-653"


def test_the_index_row_states_its_release_numbers_from_the_real_capture():
    row = index_row()
    assert row.file_number == "S7-11-23"
    # The captured info-button's regulation-node-release-number span, verbatim.
    assert row.release_numbers == ("34-103320",)
    page = parse_rulemaking_index_page(INDEX, url=f"{SEC_SITE}/rules-regulations/rulemaking-activity")
    assert [row.release_numbers for row in page.rulemakings] == [
        ("33-11439", "34-106385", "39-2566"),
        ("33-11438", "34-106345", "39-2565", "IC-36326"),
        ("34-103320",),
        ("33-11377", "34-103247", "IA-6885", "IC-35635"),
    ]


@pytest.mark.parametrize("release", ["IA-6885", "IC-36326", "IC-35635", "34-77617A"])
def test_alphabetic_release_numbers_survive_the_rule_page_and_fr_join(release):
    page = rule_page(RULE_PAGE.replace(b"34-103320", release.encode()))
    assert release in page.release_numbers
    assert list(stated_release_numbers([f"Release No. {release}"])) == [release]


@pytest.mark.parametrize(
    "docket_ids,expected",
    [
        # Every act-name spelling measured in the retained Federal Register release's docket_ids.
        (["Investment Company Act Release No. 24593"], ["IC-24593"]),
        (["Investment Company Act Release No.24593A"], ["IC-24593A"]),
        (["Investment Company Act of 1940 Release No. 27500/September 1, 2006"], ["IC-27500"]),
        (["Investment Company Act, Release No. 23124"], ["IC-23124"]),
        (["Investment Company Release No. 35740"], ["IC-35740"]),
        (["Investment Advisers Act Release No. 2106/File No. 803-00123"], ["IA-2106"]),
        (["International Series Release No. 692"], ["IS-692"]),
        (["International Release No. 878"], ["IS-878"]),
        (["Int'l Series Release No. 929"], ["IS-929"]),
        (["International Securities Release No. 828"], ["IS-828"]),
        (["Securities Exchange Act Release No. 34885/October 24, 1994"], ["34-34885"]),
        (["SECURITIES EXCHANGE ACT OF 1934 Release No. 35123/March 1, 1995"], ["34-35123"]),
        (["Securities Act of 1933, Release No. 7049/February 1, 1994"], ["33-7049"]),
        (
            ["Securities Exchange Act of 1934: Release No. 47683 and International Series Release No. 1273"],
            ["34-47683", "IS-1273"],
        ),
        # A name before an already-prefixed number reads it once, in its own spelling.
        (["Investment Company Act Release No. IC-24593"], ["IC-24593"]),
        (["Securities Exchange Act Release No. 34-35123"], ["34-35123"]),
    ],
)
def test_act_named_release_spellings_read_as_the_standard_prefix(docket_ids, expected):
    assert list(stated_release_numbers(docket_ids)) == expected


def test_numbered_file_series_beside_a_release_are_never_releases():
    # Only the acts' years number a release series; 812-, 811- and 70- are the application file numbers
    # the release lists beside IC and PUHCA releases (measured 2026-09-25).
    assert list(stated_release_numbers(["Investment Company Act Release No. 28000", "812-13456"])) == ["IC-28000"]
    assert list(stated_release_numbers(["Release No. IC-28000", "811-04321"])) == ["IC-28000"]
    assert list(stated_release_numbers(["Release No. 35-27955", "70-10287", "70-10268"])) == ["35-27955"]
    # Lettered series in a split list stay releases: FOIA and Privacy Act releases.
    ids = ["Release Nos. 34-43239", "FOIA-191", "PA-30", "File No. S7-14-99"]
    assert list(stated_release_numbers(ids)) == ["34-43239", "FOIA-191", "PA-30"]


@pytest.mark.parametrize(
    "docket_ids,expected",
    [
        (
            ["Release No. 34-75937", "File Nos. SR-NYSE-2015-31", "SR-NYSEMKT-2015-56"],
            ["sr-nyse-2015-31", "sr-nysemkt-2015-56"],
        ),
        (
            ["Release No. 34-84458", "File Nos. SR-DTC-2018-009", "SR-FICC-2018-010", "SR-NSCC-2018-009"],
            ["sr-dtc-2018-009", "sr-ficc-2018-010", "sr-nscc-2018-009"],
        ),
        (["File Nos. S7-28-98 and S7-29-98"], ["s7-28-98", "s7-29-98"]),
        (
            ["File Nos. SR-Amex-98-28", "SR-CBOE-98-32", "and SR- Phlx-98-33"],
            ["sr-amex-98-28", "sr-cboe-98-32", "sr-phlx-98-33"],
        ),
        # One space beside a dash, or an en dash, is the number's own; the old grammar truncated these.
        (["File No. SR-OPRA- 95-5"], ["sr-opra-95-5"]),
        (["File No. 812- 9182"], ["812-9182"]),
        (["File No. SR\u2013 FINRA\u20132023\u2013016"], ["sr-finra-2023-016"]),
    ],
)
def test_file_number_statements_read_lists_and_spaced_dashes(docket_ids, expected):
    assert list(stated_file_numbers(docket_ids)) == expected


def test_file_number_grammar_keeps_every_dash_less_reading_it_had():
    # The caution: a dash-required grammar would lose these (1,072 in the retained release, receipt
    # sec-file-number-grammar-2026-09-25), so a single dash-less number keeps its one-token reading.
    assert list(stated_file_numbers(["File No. 9823633"])) == ["9823633"]
    assert list(stated_file_numbers(["File No. 002 3229"])) == ["002"]
    assert list(stated_file_numbers(["File No. PCAOB 2004-03"])) == ["pcaob"]
    # A list continues with dashed numbers only; " - " never joins a phrase to a number, and a singular
    # statement reads one number, so a release element after it is not a file number.
    assert list(stated_file_numbers(["File Nos. 9823563 & 9823565"])) == ["9823563"]
    assert list(stated_file_numbers(["File No. S7-11-23 - Extension"])) == ["s7-11-23"]
    assert list(stated_file_numbers(["File No. SR-NYSE-2024-01", "34-12345"])) == ["sr-nyse-2024-01"]


def test_release_statements_read_whole_lists_even_split_across_docket_ids():
    # The real 2024-05625 record: the release splits one ``Release Nos.`` list across elements.
    split = ["Release Nos. 33-11232A", "34-98368A", "39-2551A", "IC-34996A", "File No. S7-15-23"]
    assert list(stated_release_numbers(split)) == ["33-11232A", "34-98368A", "39-2551A", "IC-34996A"]
    listed = ["Release Nos. 33-11275, 34-99679, IC-35170, and IA-6546, File No. S7-10-22"]
    assert list(stated_release_numbers(listed)) == ["33-11275", "34-99679", "IC-35170", "IA-6546"]
    assert list(stated_release_numbers(["Release No. IA-3984/34-73803"])) == ["IA-3984", "34-73803"]
    assert list(stated_release_numbers(["RELEASE NO. 34-64804"])) == ["34-64804"]
    # The prefix is read in any case, the number only in the publisher's uppercase grammar.
    assert list(stated_release_numbers(["Release No. ia-6885"])) == []
    # A bare number that does not continue a release list is not a release statement.
    assert list(stated_release_numbers(["File No. S7-11-23", "34-97877"])) == []


def test_the_rule_page_states_its_title_file_number_releases_and_citations():
    page = rule_page()
    # The live page's own h1, and its statement fields, read 2026-09-24 (see the fixture README).
    assert (
        page.title
        == "Daily Computation of Customer and Broker-Dealer Reserve Requirements under the Broker-Dealer Customer Protection Rule"
    )
    assert page.file_number == "s7-11-23"
    assert page.release_numbers == ("34-102022", "34-97877", "34-103320")
    assert page.fr_citations == ("88 FR 45836", "90 FR 2837")
    assert page.url == RULE_PAGE_URL
    assert page.comment_listing_urls == (LISTING_URL,)


def test_a_rule_page_stating_no_file_number_releases_or_citations_is_an_observation():
    bare = b"<html><body><h1>Only a title</h1><p>No statement fields.</p></body></html>"
    page = rule_page(bare)
    assert page.release_numbers == () and page.fr_citations == ()
    assert page.file_number is None


def test_void_and_unclosed_inline_tags_inside_statement_fields_keep_every_statement():
    body = (
        RULE_PAGE.replace(b">34-102022<", b">34-102022<br><", 1)
        .replace(b">Release Number<", b">Release<br>Number<", 1)
        .replace(b">S7-11-23</div>", b"><img src=x>S7-11-23</div>", 1)
        .replace(b"<p>88 FR 45836</p>", b"<p>88 FR 45836", 1)
    )
    assert rule_page(body) == rule_page()


def test_a_statement_field_left_open_refuses_instead_of_reading_as_not_stated():
    body = RULE_PAGE.replace(
        b'<div class="field__item">S7-11-23</div>', b'<div class="field__item"><div>S7-11-23</div>', 1
    )
    with pytest.raises(SecCommentsSourceError, match="leaves a statement field open"):
        rule_page(body)


def test_a_title_labeled_release_number_field_is_not_read():
    # The live page reuses the release-number template for Title fields; the label
    # is the publisher's witness, so those fields contribute no release numbers.
    page = rule_page()
    assert page.release_numbers == ("34-102022", "34-97877", "34-103320")


RULE_PAGE_REFUSALS = {
    "not a rulemaking route": (RULE_PAGE, f"{SEC_SITE}/comments/s7-11-23/s71123.htm", "rule page URL"),
    "a query on the locator": (RULE_PAGE, RULE_PAGE_URL + "?x=1", "rule page URL"),
    "no title": (b"<html><body><p>Release No. 34-103320</p></body></html>", RULE_PAGE_URL, "no title"),
    "an empty body": (b"", RULE_PAGE_URL, "empty"),
    "a bad file number statement": (
        RULE_PAGE.replace(b">S7-11-23</div>", b">S7 11 23</div>"),
        RULE_PAGE_URL,
        "docket grammar",
    ),
    "conflicting file numbers": (
        RULE_PAGE.replace(
            b'<div class="field__item">S7-11-23</div>',
            b'<div class="field__item">S7-11-23</div>'
            b'<div class="field field--name-field-file-number field--type-entity-reference field--label-above">'
            b'<div class="field__label">File Number</div><div class="field__item">S7-12-23</div></div>',
        ),
        RULE_PAGE_URL,
        "conflicting file numbers",
    ),
    "a release-number field that is not a release number": (
        RULE_PAGE.replace(b">34-102022<", b">S7 11 23<"),
        RULE_PAGE_URL,
        "not a release number",
    ),
    "a citation field stating no citation": (
        RULE_PAGE.replace(b"<p>88 FR 45836</p>", b"<p>no citation here</p>"),
        RULE_PAGE_URL,
        "no FR citation",
    ),
}


@pytest.mark.parametrize("case", RULE_PAGE_REFUSALS, ids=list(RULE_PAGE_REFUSALS))
def test_rule_page_refusals_name_the_failed_check(case):
    body, url, message = RULE_PAGE_REFUSALS[case]
    with pytest.raises(SecCommentsSourceError, match=message):
        rule_page(body, url=url)


def test_the_fr_index_resolves_doc_numbers_to_citations_and_states():
    index = fr_index()
    documents = index.citation_for_fr_doc_num("2023-15200")
    assert [document.citation.normalized for document in documents] == ["88 FR 45836"]
    assert [document.citation.normalized for document in index.citation_for_fr_doc_num("2010-00239")] == ["75 FR 1430"]
    by_file = index.records_stating_file_number("S7-11-23")
    assert {(d.document_number, d.citation.normalized) for d in by_file} == {
        ("2023-15200", "88 FR 45836"),
        ("2024-31178", "90 FR 2790"),
        ("2025-12016", "90 FR 27990"),
    }
    by_release = index.records_stating_release_number("34-103320")
    assert [(d.document_number, d.docket_ids) for d in by_release] == [
        ("2025-12016", ("Release No. 34-103320", "File No. S7-11-23"))
    ]


SEC = [{"raw_name": "SECURITIES AND EXCHANGE COMMISSION"}]


def test_the_fr_index_reads_sec_records_once_and_refuses_an_ambiguous_number():
    records = [
        # Two distinct Register numbers that normalize to one key (both served in 1994).
        {"document_number": "94-190", "volume": 59, "start_page": 1, "agencies": SEC},
        {"document_number": "94-0190", "volume": 59, "start_page": 2, "agencies": SEC},
        # A record naming one file number twice is indexed once.
        {
            "document_number": "2023-15200",
            "volume": 88,
            "start_page": 45836,
            "docket_ids": ["File No. S7-11-23", "Release No. 34-97877; File No. S7-11-23"],
            "agencies": SEC,
        },
        {"document_number": "2024-31178", "volume": 90, "start_page": 2790, "agencies": [{"raw_name": "EPA"}]},
    ]
    index = FrDocumentIndex.from_records(records)
    assert index.ambiguous_numbers == {"94-190"}
    assert index.citation_for_fr_doc_num("94-190") == index.citation_for_fr_doc_num("94-0190") == ()
    assert index.documents_at_citation(FrCitation(59, 1, "59 FR 1")) == ()
    assert [d.document_number for d in index.records_stating_file_number("S7-11-23")] == ["2023-15200"]
    # Only SEC-agency records are indexed: the mirror holds SEC documents.
    assert index.citation_for_fr_doc_num("2024-31178") == ()
    assert {d.document_number for d in index.documents} == {"94-190", "94-0190", "2023-15200"}


def test_the_mirror_index_reads_the_retained_rows_by_their_join_keys():
    index = mirror_index()
    assert len(index.documents) == 5
    document = mirror_document_from_record(json.loads(MIRROR_JSONL.splitlines()[0]))
    assert document.document_id == "SEC-2005-0010-0001"
    assert document.fr_doc_num == "05-18895" and document.docket_id is None
    assert [d.document_id for d in index.documents_for_fr_doc_num("2010-00239")] == ["SEC-2010-0055-0001"]
    assert index.documents_for_fr_doc_num("no-such-number") == ()
    assert index.documents_for_docket_id("SEC-2022-0655") == ()


def test_every_tier_links_what_the_earlier_tiers_did_not():
    page = rule_page()
    links = link_rulemaking_to_mirror(
        file_number="S7-11-23",
        release_numbers=page.release_numbers,
        fr_citations=page.fr_citations,
        mirror_index=mirror_index(),
        fr_index=fr_index(),
    )
    # The live page states 88 FR 45836 (the proposal) and 90 FR 2837, a citation the
    # retained FR records do not carry, so it yields no link, never a guessed one. Its
    # release numbers prove the adoption (34-102022) and the extension (34-103320); the
    # proposal's own release (34-97877) and the file number add nothing already linked.
    assert [(link.path, link.stated, link.mirror_document.document_id) for link in links] == [
        ("fr_citation", "88 FR 45836", "SEC-2023-0740-0001"),
        ("release_number", "34-102022", "SEC-2025-0062-0001"),
        ("release_number", "34-103320", "SEC-2025-1268-0001"),
    ]
    link = links[0]
    assert link.matched_field == "frDocNum"
    assert link.stated == "88 FR 45836" and link.citation.normalized == "88 FR 45836"
    assert link.mirror_document.fr_doc_num == "2023-15200"
    assert link.fr_document.docket_ids == ("Release No. 34-97877", "File No. S7-11-23")


def test_the_release_and_file_number_tiers_link_when_no_citation_is_stated():
    row = index_row()
    links = link_rulemaking_to_mirror(
        file_number=row.file_number,
        release_numbers=row.release_numbers,
        mirror_index=mirror_index(),
        fr_index=fr_index(),
    )
    assert [(link.path, link.stated, link.mirror_document.document_id) for link in links] == [
        ("release_number", "34-103320", "SEC-2025-1268-0001"),
        ("file_number", "S7-11-23", "SEC-2023-0740-0001"),
        ("file_number", "S7-11-23", "SEC-2025-0062-0001"),
    ]
    assert links[0].citation.normalized == "90 FR 27990"


#: The three real SEC corrections that all start at 89 FR 19292 (retained ``fr-full-1994-2026`` records).
FR_19292 = [
    ("2024-05623", ["Release Nos. 34-97990A", "IA-6353A", "File No. S7-12-23"]),
    ("2024-05625", ["Release Nos. 33-11232A", "34-98368A", "39-2551A", "IC-34996A", "File No. S7-15-23"]),
    ("2024-05624", ["Release No. IA-6354A", "File No. S7-13-23"]),
]


def shared_page_indexes():
    fr = FrDocumentIndex.from_records(
        {"document_number": number, "volume": 89, "start_page": 19292, "docket_ids": ids, "agencies": SEC}
        for number, ids in FR_19292
    )
    mirror = MirrorSecIndex.from_records(
        {"data": {"id": f"SEC-{number}", "attributes": {"frDocNum": number}}} for number, _ in FR_19292
    )
    return {"fr_index": fr, "mirror_index": mirror}


@pytest.mark.parametrize(
    "statements",
    [{"file_number": "S7-13-23"}, {"file_number": None, "release_numbers": ("IA-6354A",)}],
)
def test_a_citation_several_sec_records_share_is_narrowed_by_the_rulemakings_own_numbers(statements):
    links = link_rulemaking_to_mirror(fr_citations=("89 FR 19292",), **statements, **shared_page_indexes())
    assert [(link.path, link.fr_document.document_number) for link in links] == [("fr_citation", "2024-05624")]


def test_a_sub_1000_page_citation_reads_on_the_rule_page_and_joins():
    # The real E5-8282 (71 FR 632) and its retained mirror document SEC-2006-0008-0001.
    page = rule_page(b"<h1>SR-NASD-2005-066</h1><p>Published at 71 FR 632; see 17 CFR 240.3011 and Form 10-K.</p>")
    assert page.fr_citations == ("71 FR 632",)
    fr = FrDocumentIndex.from_records(
        [
            {
                "document_number": "E5-8282",
                "volume": 71,
                "start_page": 632,
                "docket_ids": ["Release No. 34-53030", "File No. SR-NASD-2005-066"],
                "agencies": SEC,
            }
        ]
    )
    mirror = MirrorSecIndex.from_records(
        [{"data": {"id": "SEC-2006-0008-0001", "attributes": {"frDocNum": "E5-08282"}}}]
    )
    links = link_rulemaking_to_mirror(
        file_number=None, fr_citations=page.fr_citations, mirror_index=mirror, fr_index=fr
    )
    assert [(link.path, link.mirror_document.document_id) for link in links] == [("fr_citation", "SEC-2006-0008-0001")]


def test_a_shared_sub_1000_page_is_narrowed_by_release_number_or_refused():
    # The real 71 FR 159: an SRO notice and a Sunshine Act meeting notice that states no number.
    fr = FrDocumentIndex.from_records(
        {"document_number": number, "volume": 71, "start_page": 159, "docket_ids": ids, "agencies": SEC}
        for number, ids in (("E5-8196", ["Release No. 34-53024", "File No. SR-NASD-2005-095"]), ("05-24702", []))
    )
    mirror = MirrorSecIndex.from_records(
        {"data": {"id": f"SEC-{number}", "attributes": {"frDocNum": number}}} for number in ("E5-8196", "05-24702")
    )
    statements = {"fr_citations": ("71 FR 159",), "mirror_index": mirror, "fr_index": fr}
    links = link_rulemaking_to_mirror(file_number=None, release_numbers=("34-53024",), **statements)
    assert [link.fr_document.document_number for link in links if link.path == "fr_citation"] == ["E5-8196"]
    with pytest.raises(FrCollisionError):
        link_rulemaking_to_mirror(file_number=None, **statements)


def test_a_shared_citation_no_record_resolves_refuses_with_a_named_error():
    with pytest.raises(FrCollisionError) as caught:
        link_rulemaking_to_mirror(
            file_number="S7-99-99", release_numbers=("34-1",), fr_citations=("89 FR 19292",), **shared_page_indexes()
        )
    assert caught.value.tier == "fr_citation"
    assert set(caught.value.document_numbers) == {number for number, _ in FR_19292}


def test_the_file_number_fallback_links_when_only_the_file_number_is_stated():
    links = link_rulemaking_to_mirror(file_number="S7-11-23", mirror_index=mirror_index(), fr_index=fr_index())
    assert [link.path for link in links] == ["file_number"] * 3
    assert {link.mirror_document.document_id for link in links} == {
        "SEC-2023-0740-0001",
        "SEC-2025-0062-0001",
        "SEC-2025-1268-0001",
    }
    assert all(link.stated == "S7-11-23" and link.matched_field == "frDocNum" for link in links)


def test_a_statement_that_names_no_fr_record_yields_no_link_not_a_guess():
    links = link_rulemaking_to_mirror(
        file_number=None,
        release_numbers=("34-999999",),
        mirror_index=mirror_index(),
        fr_index=fr_index(),
    )
    # No FR record states Release No. 34-999999, no file number exists, and
    # frDocNum is never matched directly against an SEC statement.
    assert links == ()


def test_the_comment_files_link_by_the_file_number_the_docket_directory_spells():
    own = comment(url=f"{SEC_SITE}/comments/s7-11-23/s71123-1.htm")
    foreign = comment(docket="s7-12-23", url=f"{SEC_SITE}/comments/s7-12-23/s71223-1.htm")
    links = link_file_number_to_comments("S7-11-23", [own, foreign])
    assert [link.comment.url for link in links] == [own.url]
    assert links[0].docket == "s7-11-23" and links[0].sec_file_number == "S7-11-23"
    assert links[0].matched_field == "file_number"


def test_the_combined_emission_links_a_docket_its_documents_and_its_comments():
    row = index_row()
    result = join_sec_comments(
        row,
        [comment()],
        mirror_index=mirror_index(),
        fr_index=fr_index(),
        rule_page=rule_page(),
    )
    docket = result["docket"]
    assert docket["kind"] == "sec-comments-docket"
    assert docket["file_number"] == "S7-11-23" and docket["docket"] == "s7-11-23"
    assert docket["rule_url"] == f"{SEC_SITE}/rules-regulations/2025/06/s7-11-23"
    assert docket["comment_index_url"] == LISTING_URL
    assert docket["release_numbers"] == ["34-103320", "34-102022", "34-97877"]
    # The live page states two citations; the join records both, then the citations the
    # release numbers derived for the adoption and the extension.
    assert [entry["normalized"] for entry in docket["fr_citations"]] == [
        "88 FR 45836",
        "90 FR 2837",
        "90 FR 27990",
        "90 FR 2790",
    ]
    assert [entry["provenance"][0]["path"] for entry in docket["fr_citations"][2:]] == ["release_number"] * 2
    citation = docket["fr_citations"][0]
    assert citation["volume"] == 88 and citation["page"] == 45836
    assert citation["provenance"][0]["path"] == "fr_citation"
    assert citation["provenance"][0]["fr_document_number"] == "2023-15200"
    assert citation["provenance"][0]["mirror_document_id"] == "SEC-2023-0740-0001"
    assert citation["provenance"][0]["fr_docket_ids"] == ["Release No. 34-97877", "File No. S7-11-23"]
    # The unstated-citation document (90 FR 2837) names no FR record and yields no provenance.
    assert docket["fr_citations"][1]["provenance"] == []
    # All three provable S7-11-23 documents: proposal, adoption and extension.
    assert [doc["document_id"] for doc in docket["mirror_documents"]] == [
        "SEC-2023-0740-0001",
        "SEC-2025-1268-0001",
        "SEC-2025-0062-0001",
    ]
    assert docket["comment_count"] == 1 and docket["mismatched_comment_dockets"] == []
    comment_record = result["comments"][0]
    assert comment_record["docket"] == "s7-11-23" and comment_record["file_number"] == "S7-11-23"
    assert comment_record["link"]["matched_field"] == "file_number"


def test_the_combined_emission_reports_a_foreign_comment_and_never_links_it():
    row = index_row()
    foreign = comment(docket="s7-12-23", url=f"{SEC_SITE}/comments/s7-12-23/s71223-1.htm")
    result = join_sec_comments(row, [foreign], mirror_index=mirror_index(), fr_index=fr_index())
    assert result["comments"] == []
    assert result["docket"]["mismatched_comment_dockets"] == ["s7-12-23"]
    assert result["docket"]["comment_count"] == 0


def test_a_batch_join_hands_each_rulemaking_its_own_docket_group():
    own = comment(url=f"{SEC_SITE}/comments/s7-11-23/s71123-1.htm")
    foreign = comment(docket="s7-12-23", url=f"{SEC_SITE}/comments/s7-12-23/s71223-1.htm")
    groups = comments_by_docket([own, foreign])
    assert groups == {"s7-11-23": (own,), "s7-12-23": (foreign,)}
    result = join_sec_comments(index_row(), groups["s7-11-23"], mirror_index=mirror_index(), fr_index=fr_index())
    assert [record["url"] for record in result["comments"]] == [own.url]
    assert result["docket"]["mismatched_comment_dockets"] == []


def test_the_emission_refuses_a_rule_page_that_is_not_this_rulemaking():
    row = index_row()
    other = rule_page(RULE_PAGE.replace(b">S7-11-23</div>", b">S7-12-23</div>"))
    with pytest.raises(SecCommentsJoinError, match="not the row"):
        join_sec_comments(row, [], mirror_index=mirror_index(), fr_index=fr_index(), rule_page=other)


def fr_document(number, publication_date, title, volume=75, start_page=1, docket_ids=(), agencies=()):
    """One synthesized FR record for the title+date matcher tests; no fixture files needed."""
    return FrDocument(
        document_number=number,
        volume=volume,
        start_page=start_page,
        end_page=None,
        publication_date=publication_date,
        docket_ids=docket_ids,
        title=title,
        agencies=agencies,
    )


def no_fr_documents():
    return FrAgendaIndex.from_fr_documents(()), FrSecTitleIndex.from_fr_documents(())


def test_title_normalization_folds_case_curly_quotes_and_whitespace():
    # The FR release spells curly quotes where the mirror spells straight ones (the C1-2018-08 pair,
    # measured), and FR titles carry trailing newlines; nothing fuzzier than this is accepted.
    fr_title = "Notice To Correct \u201cAs/of\u201d Trades\n"
    mirror_title = '  notice to correct "as/of" TRADES '
    assert normalize_sec_title(fr_title) == normalize_sec_title(mirror_title) == 'notice to correct "as/of" trades'
    assert normalize_sec_title(None) == "" and normalize_sec_title("") == ""


def test_the_agenda_tier_matches_title_family_plus_posted_date():
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document("2010-8964", "2010-04-26", "Regulatory Flexibility Agenda"),
            fr_document("2010-30469", "2010-12-20", "Regulatory Flexibility Agenda"),
        ]
    )
    result = match_sec_document_without_fr_doc_num(
        "Semiannual Regulatory Agenda - Spring 2010",
        "2010-04-26T04:00:00Z",
        agenda,
        FrSecTitleIndex.from_fr_documents(()),
    )
    assert result.tier == "title-date-agenda"
    assert result.fr_document.document_number == "2010-8964"
    assert result.citation.normalized == "75 FR 1"
    assert result.stated_title == "Semiannual Regulatory Agenda - Spring 2010"
    assert result.posted_date == "2010-04-26T04:00:00Z"


def test_the_agenda_tier_refuses_a_collision_with_a_named_error():
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document("2011-15504", "2011-07-07", "Unified Agenda of Federal Regulatory and Deregulatory Actions"),
            fr_document("2011-15505", "2011-07-07", "Regulatory Flexibility Agenda"),
        ]
    )
    with pytest.raises(FrCollisionError) as caught:
        match_sec_document_without_fr_doc_num(
            "Semiannual Regulatory Agenda - Spring 2011",
            "2011-07-07T04:00:00Z",
            agenda,
            FrSecTitleIndex.from_fr_documents(()),
        )
    assert caught.value.tier == "title-date-agenda"
    assert set(caught.value.document_numbers) == {"2011-15504", "2011-15505"}


def test_the_agenda_tie_break_prefers_the_single_sec_agency_record_naming_the_rung():
    # The measured Spring 2011 collision: the joint NRC/SEC unified-agenda header
    # beside the SEC regulatory-flexibility agenda. The mirror document is the SEC's
    # own posted copy, so the single-agency record wins and the result says which rung chose.
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document(
                "2011-15504",
                "2011-07-07",
                "Unified Agenda of Federal Regulatory and Deregulatory Actions",
                agencies=("NUCLEAR REGULATORY COMMISSION", "SECURITIES AND EXCHANGE COMMISSION"),
            ),
            fr_document(
                "2011-15505",
                "2011-07-07",
                "Regulatory Flexibility Agenda",
                agencies=("SECURITIES AND EXCHANGE COMMISSION",),
            ),
        ]
    )
    result = match_sec_document_without_fr_doc_num(
        "Semiannual Regulatory Agenda - Spring 2011",
        "2011-07-07T04:00:00Z",
        agenda,
        FrSecTitleIndex.from_fr_documents(()),
    )
    assert result.tier == "title-date-agenda"
    assert result.fr_document.document_number == "2011-15505"
    assert result.tie_break == "single SEC agency"


def test_the_agenda_tie_break_resolves_the_measured_fall_2012_pair():
    # The measured Fall 2012 collision: both candidates published 2013-01-08, fifteen days
    # after the mirror's posted date, so posted-date equality cannot choose; the
    # single-agency rung does.
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document(
                "2012-31518",
                "2013-01-08",
                "Regulatory Flexibility Agenda",
                agencies=("SECURITIES AND EXCHANGE COMMISSION",),
            ),
            fr_document(
                "2012-31674",
                "2013-01-08",
                "Unified Agenda of Federal Regulatory and Deregulatory Actions",
                agencies=("NUCLEAR REGULATORY COMMISSION", "SECURITIES AND EXCHANGE COMMISSION"),
            ),
        ]
    )
    result = match_sec_document_without_fr_doc_num(
        "Semiannual Regulatory Agenda - Fall 2012",
        "2012-12-24T05:00:00Z",
        agenda,
        FrSecTitleIndex.from_fr_documents(()),
    )
    assert result.fr_document.document_number == "2012-31518"
    assert result.tie_break == "single SEC agency"


def test_the_agenda_tie_break_prefers_the_posted_date_when_it_can():
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document("2010-00001", "2010-04-26", "Regulatory Flexibility Agenda", agencies=("SEC",)),
            fr_document("2010-00002", "2010-05-05", "Regulatory Flexibility Agenda", agencies=("SEC",)),
        ]
    )
    result = match_sec_document_without_fr_doc_num(
        "Semiannual Regulatory Agenda - Spring 2010",
        "2010-04-26T04:00:00Z",
        agenda,
        FrSecTitleIndex.from_fr_documents(()),
    )
    assert result.fr_document.document_number == "2010-00001"
    assert result.tie_break == "posted-date equality"


def test_the_agenda_tie_break_reads_the_title_season_word_when_dates_and_agencies_agree():
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document(
                "2011-00001",
                "2011-07-07",
                "Regulatory Flexibility Agenda",
                agencies=("SEC",),
            ),
            fr_document(
                "2011-00002",
                "2011-07-07",
                "Unified Agenda - Spring 2011",
                agencies=("SEC",),
            ),
        ]
    )
    result = match_sec_document_without_fr_doc_num(
        "Semiannual Regulatory Agenda - Spring 2011",
        "2011-07-07T04:00:00Z",
        agenda,
        FrSecTitleIndex.from_fr_documents(()),
    )
    assert result.fr_document.document_number == "2011-00002"
    assert result.tie_break == "title season word"


def test_the_agenda_tie_break_refuses_when_no_rung_can_choose():
    # Two single-agency records on the posted date, neither title carrying the season
    # phrase, and no season phrase in the mirror title either: no rung discriminates.
    agenda = FrAgendaIndex.from_fr_documents(
        [
            fr_document("2011-00001", "2011-07-07", "Regulatory Flexibility Agenda", agencies=("SEC",)),
            fr_document("2011-00002", "2011-07-07", "Regulatory Flexibility Agenda", agencies=("SEC",)),
        ]
    )
    with pytest.raises(FrCollisionError) as caught:
        match_sec_document_without_fr_doc_num(
            "Semi-annual agenda",
            "2011-07-07T04:00:00Z",
            agenda,
            FrSecTitleIndex.from_fr_documents(()),
        )
    assert set(caught.value.document_numbers) == {"2011-00001", "2011-00002"}


def test_the_agenda_family_never_falls_through_to_the_title_date_sec_tier():
    sec = FrSecTitleIndex.from_fr_documents([fr_document("2020-00001", "2006-04-24", "Semi-annual agenda")])
    result = match_sec_document_without_fr_doc_num(
        "Semi-annual agenda", "2006-04-24T04:00:00Z", FrAgendaIndex.from_fr_documents(()), sec
    )
    assert result.tier == "mirror-artifact"
    assert "agenda FR record" in result.reason


def test_the_title_date_sec_tier_matches_a_garbage_fr_doc_num_document():
    sec = FrSecTitleIndex.from_fr_documents(
        [
            fr_document("C1-2017-11151", "2017-06-14", "SRO; DTC; Notice To Correct \u201cAs/of\u201d Trades"),
            fr_document("2017-12345", "2017-08-01", "Some other notice"),
        ]
    )
    result = match_sec_document_without_fr_doc_num(
        'SRO; DTC; Notice To Correct "As/of" Trades', "2017-06-14T04:00:00Z", FrAgendaIndex.from_fr_documents(()), sec
    )
    assert result.tier == "title-date-sec"
    assert result.fr_document.document_number == "C1-2017-11151"
    assert result.citation.normalized == "75 FR 1"


def test_the_title_date_sec_tier_keeps_the_window_inclusive_and_day_based():
    sec = FrSecTitleIndex.from_fr_documents([fr_document("2010-00102", "2010-04-28", "Notice")])
    agenda, _ = no_fr_documents()
    assert match_sec_document_without_fr_doc_num("Notice", "2010-04-26T04:00:00Z", agenda, sec).tier == "title-date-sec"
    three_days = FrSecTitleIndex.from_fr_documents([fr_document("2010-00103", "2010-04-29", "Notice")])
    result = match_sec_document_without_fr_doc_num("Notice", "2010-04-26T04:00:00Z", agenda, three_days)
    assert result.tier == "mirror-artifact" and "no SEC agency FR record" in result.reason


def test_the_title_date_sec_tier_refuses_a_collision_with_a_named_error():
    sec = FrSecTitleIndex.from_fr_documents(
        [
            fr_document("2010-00100", "2010-04-26", "Notice"),
            fr_document("2010-00101", "2010-04-27", "Notice"),
        ]
    )
    with pytest.raises(FrCollisionError) as caught:
        match_sec_document_without_fr_doc_num(
            "Notice", "2010-04-26T04:00:00Z", FrAgendaIndex.from_fr_documents(()), sec
        )
    assert caught.value.tier == "title-date-sec"
    assert set(caught.value.document_numbers) == {"2010-00100", "2010-00101"}


def test_unmatched_documents_report_mirror_artifact_with_the_reason():
    agenda, sec = no_fr_documents()
    result = match_sec_document_without_fr_doc_num(
        "Agency information collection activities; proposals, submissions, and approvals",
        "2007-08-15T04:00:00Z",
        agenda,
        sec,
    )
    assert result.tier == "mirror-artifact"
    assert result.fr_document is None and result.citation is None
    assert "no SEC agency FR record" in result.reason


def test_missing_title_or_posted_date_is_a_mirror_artifact_naming_the_check():
    agenda, sec = no_fr_documents()
    assert match_sec_document_without_fr_doc_num(None, "2010-04-26", agenda, sec).reason == "no title"
    result = match_sec_document_without_fr_doc_num("Semiannual Regulatory Agenda - Spring 2010", None, agenda, sec)
    assert result.tier == "mirror-artifact" and result.reason == "no readable posted date"
