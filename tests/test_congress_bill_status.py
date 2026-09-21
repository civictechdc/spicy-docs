"""Literal BILLSTATUS fields, offered versions and refusal boundaries.

Pins sponsors vs cosponsors, current status fields and offered versions,
literal strings/duplicates/unknown format links, summary CDATA placement,
absent vs blank action text, superseded-schema naming, policy-area
reconciliation, identity/selection/DOCTYPE/nesting refusals, and enacted laws,
recorded votes, committees, titles and related bills.
"""

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

from spicy_docs.sources.congress.bill_status import (
    BillIdentity,
    BillSourceError,
    BillStatus,
    BillTitle,
    RelatedBill,
    bill_package_id_from_url,
    bill_status_locator,
    bill_xml_locator,
    parse_bill_status,
    select_bill_xml,
)

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
IDENTITY = BillIdentity(119, "hr", 6028)
PACKAGE = "BILLS-119hr6028eh"
XML_URL = bill_xml_locator(IDENTITY, PACKAGE)


def status_body() -> bytes:
    """The retained BILLSTATUS fixture bytes."""
    return (FIXTURES / "status-119hr6028.xml").read_bytes()


def test_cosponsors_are_separate_from_the_sponsor_list() -> None:
    """Sponsors and cosponsors are read as separate lists with bioguide ids and full names."""
    status = parse_bill_status(
        (FIXTURES / "status-118hr1-cosponsors.xml").read_bytes(), identity=BillIdentity(118, "hr", 1)
    )
    assert len(status.sponsors) == 1
    assert len(status.cosponsors) == 49
    assert status.cosponsors[0].bioguide_id == "M001159"
    assert status.cosponsors[0].full_name == "Rep. McMorris Rodgers, Cathy [R-WA-5]"
    assert status.cosponsors[1].bioguide_id == "W000821"


def test_no_listed_cosponsors_is_an_empty_observation() -> None:
    """A bill with no listed cosponsors yields an empty tuple, not None."""
    assert parse_bill_status(status_body(), identity=IDENTITY).cosponsors == ()


def test_current_status_preserves_fields_and_offered_versions() -> None:
    """Current status keeps identity, schema, dates, policy area, subjects, actions, sponsors, summaries and offered
    versions, and the record is frozen.
    """
    status = parse_bill_status(status_body(), identity=IDENTITY)
    assert status.identity == IDENTITY
    assert status.schema_version == "3.0.0"
    assert status.title == "Legislative Branch Agencies Clarification Act"
    assert status.origin_chamber == "House"
    assert status.introduced_date == "2025-11-12"
    assert status.update_date == "2026-09-09T17:31:22Z"
    assert status.update_date_including_text == status.update_date
    assert status.policy_area == "Congress"
    assert status.subjects == ("Congressional agencies", "Congressional operations and organization")
    assert status.latest_action.text == "Received in the Senate."
    assert status.actions[0].source_system_name == "Senate"
    assert status.actions[0].source_system_code is None
    assert status.actions[1].action_time == "15:48:09"
    assert status.actions[1].action_code == "H38310"
    assert status.actions[1].action_type == "Floor"
    assert status.actions[1].source_system_code == "2"
    assert status.sponsors[0].bioguide_id == "G000568"
    assert status.sponsors[0].full_name == "Rep. Griffith, H. Morgan [R-VA-9]"
    assert [summary.version_code for summary in status.summaries] == ["00", "53"]
    assert status.summaries[0].text == "<p><strong>Legislative Branch Agencies Clarification Act</strong></p>"
    assert [version.package_id for version in status.text_versions] == [PACKAGE, "BILLS-119hr6028ih"]
    version, format_ = select_bill_xml(status, PACKAGE)
    assert version.type == "Engrossed in House"
    assert version.date == "2026-06-08T04:00:00Z"
    assert format_.url == XML_URL
    assert format_.type is None
    with pytest.raises(FrozenInstanceError):
        status.title = "changed"


def test_literal_strings_duplicates_and_unrecognized_format_links_survive() -> None:
    """Literal strings, duplicate action texts and unrecognized format links survive unchanged, including a
    package-less version.
    """
    body = status_body().replace(b"<title>Legislative", b"<title>  Legislative")
    body = body.replace(b"<name>Congressional agencies</name>", "<name>  A—B &amp; C  </name>".encode())
    body = body.replace(
        b"<textVersions>",
        b"<textVersions>\n<item><type>Unfamiliar stage</type><formats>"
        b"<item><type>Future format</type><url>https://example.invalid/source.json</url></item>"
        b"</formats></item>",
    )
    body = body.replace(b"<actions>", b"<actions><item><text> same. </text></item><item><text> same. </text></item>")
    status = parse_bill_status(body, identity=IDENTITY)
    assert status.title.startswith("  Legislative")
    assert status.subjects[0] == "  A—B & C  "
    assert [action.text for action in status.actions[:2]] == [" same. ", " same. "]
    assert status.text_versions[0].formats[0].type == "Future format"
    assert status.text_versions[0].package_id is None


def test_summary_cdata_is_literal_html_and_not_bill_text() -> None:
    """Summary CDATA stays literal HTML and is never read as bill text."""
    body = status_body().replace(
        b"<summaries>", b"<summaries><summary><text><![CDATA[<p>  A &amp; B. </p>]]></text></summary>"
    )
    status = parse_bill_status(body, identity=IDENTITY)
    assert status.summaries[0].text == "<p>  A &amp; B. </p>"
    assert status.summaries[0].version_code is None
    assert len(status.text_versions) == 2


def test_summary_text_is_read_from_either_publisher_placement_and_never_from_both() -> None:
    """Decision 4, measured: 984 of 12,938 files state summary text inside a ``<cdata>`` element."""
    wrapped = parse_bill_status(
        (FIXTURES / "status-119hres10.xml").read_bytes(), identity=BillIdentity(119, "hres", 10)
    )
    assert [summary.version_code for summary in wrapped.summaries] == ["00"]
    assert wrapped.summaries[0].text.startswith("<p><strong>House Endeavor to Accelerate")
    assert wrapped.summaries[0].action_desc == "Introduced in House"
    both = status_body().replace(
        b"<summaries>", b"<summaries><summary><text>a</text><cdata><text>b</text></cdata></summary>"
    )
    with pytest.raises(BillSourceError, match="states its text twice"):
        parse_bill_status(both, identity=IDENTITY)
    empty = status_body().replace(b"<summaries>", b"<summaries><summary><cdata/><text>a</text></summary>")
    assert parse_bill_status(empty, identity=IDENTITY).summaries[0].text == "a"


def test_an_action_without_text_keeps_every_other_field_the_publisher_stated() -> None:
    """Decision 4, measured: the guide calls every ``<actions>`` child one it "may include"."""
    status = parse_bill_status(
        (FIXTURES / "status-119hres214.xml").read_bytes(), identity=BillIdentity(119, "hres", 214)
    )
    untexted = status.actions[-1]
    assert untexted.text is None
    assert (untexted.action_code, untexted.action_type, untexted.action_date) == (
        "Intro-H",
        "IntroReferral",
        "2025-03-11",
    )
    assert untexted.source_system_name == "Library of Congress"
    assert [action.text is None for action in status.actions] == [False, False, False, True]
    assert status.latest_action.text == "Motion to reconsider laid on the table Agreed to without objection."
    assert status.summaries == ()


def test_an_action_text_that_is_present_but_blank_reads_as_absent() -> None:
    """Two states, not three. No measured file does this; a caller still should not have to tell them apart."""
    for blank in (b"<text/>", b"<text></text>", b"<text>  \n </text>"):
        body = status_body().replace(b"<actions>", b"<actions><item>" + blank + b"</item>", 1)
        assert parse_bill_status(body, identity=IDENTITY).actions[0].text is None
    kept = status_body().replace(b"<actions>", b"<actions><item><text> . </text></item>", 1)
    assert parse_bill_status(kept, identity=IDENTITY).actions[0].text == " . "


def test_the_superseded_schema_is_named_instead_of_refused_for_a_missing_type() -> None:
    """One file in 40,260 measured is still 1.0.0; a backfill needs to read why, not guess."""
    body = (
        b"<billStatus><bill><billNumber>4200</billNumber><billType>HR</billType>"
        b"<congress>113</congress><title>SBIC Advisers Relief Act of 2014</title>"
        b"<version>1.0.0</version></bill></billStatus>"
    )
    with pytest.raises(BillSourceError, match="superseded 1.0.0 element names"):
        parse_bill_status(body, identity=BillIdentity(113, "hr", 4200))


def test_policy_area_reconciles_both_current_source_locations() -> None:
    """Both policy-area locations are read, and a disagreement between them is refused."""
    assert parse_bill_status(status_body(), identity=IDENTITY).policy_area == "Congress"
    top_only = (
        b"<billStatus><version>3.0.0</version><bill><congress>119</congress><type>HR</type>"
        b"<number>6028</number><title>Title</title><policyArea><name> Congress </name></policyArea></bill></billStatus>"
    )
    assert parse_bill_status(top_only, identity=IDENTITY).policy_area == " Congress "
    nested_only = top_only.replace(b"<policyArea>", b"<subjects><policyArea>").replace(
        b"</policyArea>", b"</policyArea></subjects>"
    )
    assert parse_bill_status(nested_only, identity=IDENTITY).policy_area == " Congress "
    with pytest.raises(BillSourceError, match="policy area fields disagree"):
        parse_bill_status(
            status_body().replace(b"<name>Congress</name>", b"<name>Different</name>", 1), identity=IDENTITY
        )


@pytest.mark.parametrize(
    "identity", [BillIdentity(118, "hr", 6028), BillIdentity(119, "s", 6028), BillIdentity(119, "hr", 1)]
)
def test_status_refuses_wrong_bill(identity: BillIdentity) -> None:
    """A status whose identity differs from the requested one is refused."""
    with pytest.raises(BillSourceError, match="identity differs"):
        parse_bill_status(status_body(), identity=identity)


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b" ",
        b"<html><body>Checking browser</body></html>",
        b"<error/>",
        b"<billStatus/>",
        b"<billStatus",
        b'<billStatus xmlns="urn:other"/>',
    ],
)
def test_status_refuses_empty_error_and_unsupported_xml(body: bytes) -> None:
    """Empty, error and unsupported XML are refused."""
    with pytest.raises(BillSourceError):
        parse_bill_status(body, identity=IDENTITY)


@pytest.mark.parametrize(
    "before,after",
    [
        (b"<number>6028</number>", b"<number>6028</number><number>1</number>"),
        (b"<number>6028</number>", b"<number><value>6028</value></number>"),
        (b"<textVersions>", b"<textVersions><unexpected/>"),
        (b"<policyArea>", b"<policyArea><name>Another</name>"),
        (b"</billStatus>", b"<bill/></billStatus>"),
    ],
)
def test_status_refuses_ambiguous_or_unsupported_known_fields(before: bytes, after: bytes) -> None:
    """Ambiguous or unsupported known fields are refused."""
    with pytest.raises(BillSourceError):
        parse_bill_status(status_body().replace(before, after), identity=IDENTITY)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "200"])
def test_status_requires_positive_integer_byte_limit(limit: object) -> None:
    """A non-positive or non-integer byte limit is refused."""
    with pytest.raises(BillSourceError, match="max_bytes"):
        parse_bill_status(status_body(), identity=IDENTITY, max_bytes=limit)


def test_status_byte_bound_is_inclusive() -> None:
    """The byte bound is inclusive: exactly the body size passes, one byte less refuses."""
    body = status_body()
    assert parse_bill_status(body, identity=IDENTITY, max_bytes=len(body)).identity == IDENTITY
    with pytest.raises(BillSourceError, match="max_bytes"):
        parse_bill_status(body, identity=IDENTITY, max_bytes=len(body) - 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("congress", True),
        ("number", False),
        ("congress", 0),
        ("number", -1),
        ("number", "6028"),
        ("bill_type", "HR"),
        ("bill_type", "hr/../../"),
        ("bill_type", []),
    ],
)
def test_identity_refuses_noncanonical_arguments(field: str, value: object) -> None:
    """Non-canonical identity arguments are refused."""
    args = {"congress": 119, "bill_type": "hr", "number": 6028, field: value}
    with pytest.raises(BillSourceError):
        BillIdentity(**args)


def test_locators_are_canonical_and_other_links_are_not_selected() -> None:
    """Locators are canonical and package ids are read only from matching bill URLs."""
    assert (
        bill_status_locator(IDENTITY) == "https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr6028.xml"
    )
    assert bill_package_id_from_url(IDENTITY, XML_URL) == PACKAGE
    for url in [
        XML_URL + "?key=secret",
        XML_URL.replace("https://", "http://"),
        XML_URL.replace("www.govinfo.gov", "other.invalid"),
        XML_URL.replace("/xml/", "/pdf/"),
    ]:
        assert bill_package_id_from_url(IDENTITY, url) is None
    for package in [
        "BILLS-119s6028eh",
        "BILLS-118hr6028eh",
        "BILLS-119hr6029eh",
        "BILLS-119hr6028eh/../other",
        "BILLS-0119hr6028eh",
    ]:
        with pytest.raises(BillSourceError):
            bill_xml_locator(IDENTITY, package)


def test_selection_needs_exactly_one_offered_xml_link_and_never_infers_from_pdf() -> None:
    """Selection needs exactly one offered XML link and never infers one from a PDF."""
    status = parse_bill_status(status_body(), identity=IDENTITY)
    with pytest.raises(BillSourceError, match="offered exactly once"):
        select_bill_xml(status, "BILLS-119hr6028enr")
    pdf_body = status_body().replace(
        XML_URL.encode(), XML_URL.replace("/xml/", "/pdf/").replace(".xml", ".pdf").encode()
    )
    with pytest.raises(BillSourceError, match="offered exactly once"):
        select_bill_xml(parse_bill_status(pdf_body, identity=IDENTITY), PACKAGE)
    duplicate_body = status_body().replace(b"</formats>", f"<item><url>{XML_URL}</url></item></formats>".encode(), 1)
    with pytest.raises(BillSourceError, match="offered exactly once"):
        select_bill_xml(parse_bill_status(duplicate_body, identity=IDENTITY), PACKAGE)


def test_status_refuses_cross_bill_and_mixed_version_package_links() -> None:
    """Cross-bill links and mixed-version package links are refused."""
    with pytest.raises(BillSourceError, match="identity differs"):
        parse_bill_status(status_body().replace(b"BILLS-119hr6028eh", b"BILLS-119hr6029eh"), identity=IDENTITY)
    body = status_body().replace(
        b"</formats>", f"<item><url>{XML_URL.replace('6028eh', '6028ih')}</url></item></formats>".encode(), 1
    )
    with pytest.raises(BillSourceError, match="disagree"):
        parse_bill_status(body, identity=IDENTITY)


def test_status_refuses_doctype_and_excessive_nesting() -> None:
    """DOCTYPE declarations and excessive nesting are refused."""
    body = status_body().split(b"?>", 1)[1]
    with pytest.raises(BillSourceError, match="DOCTYPE"):
        parse_bill_status(
            b'<!DOCTYPE billStatus SYSTEM "https://example.invalid/never-load.dtd">' + body, identity=IDENTITY
        )
    with pytest.raises(BillSourceError, match="nesting"):
        parse_bill_status(b"<a>" * 257 + b"</a>" * 257, identity=IDENTITY)


def test_public_entry_points_refuse_objects_without_validated_identity() -> None:
    """Public entry points refuse objects whose identity was not validated."""
    identity = SimpleNamespace(congress="../bad", bill_type="hr", number=6028)
    for operation in [
        lambda: bill_status_locator(identity),
        lambda: bill_xml_locator(identity, PACKAGE),
        lambda: bill_package_id_from_url(identity, XML_URL),
        lambda: parse_bill_status(status_body(), identity=identity),
    ]:
        with pytest.raises(BillSourceError, match="BillIdentity"):
            operation()


# --- laws, committees and recorded votes: the three elements the interpretation
# rules key on, read end to end from real publisher bytes.

ENACTED_IDENTITY = BillIdentity(119, "s", 5)


def enacted_status() -> BillStatus:
    """The retained enacted-bill BILLSTATUS fixture bytes."""
    return parse_bill_status((FIXTURES / "status-119s5.xml").read_bytes(), identity=ENACTED_IDENTITY)


def test_enacted_status_reads_its_laws_entry() -> None:
    """An enacted status reads its laws entry with type and number."""
    status = enacted_status()
    assert status.title == "Laken Riley Act"
    assert [(law.type, law.number) for law in status.laws] == [("Public Law", "119-1")]


def test_recorded_votes_are_read_on_the_actions_that_carry_them() -> None:
    """Recorded votes are read on their actions with chamber, roll, session, URL, date and congress; a
    documented-but-absent field stays None.
    """
    votes = [vote for action in enacted_status().actions for vote in action.recorded_votes]
    assert [(vote.chamber, vote.roll_number, vote.session_number) for vote in votes] == [
        ("House", "23", "1"),
        ("Senate", "7", "1"),
    ]
    assert votes[0].url == "https://clerk.house.gov/evs/2025/roll023.xml"
    assert votes[0].date == "2025-01-22T22:04:55Z"
    assert votes[0].congress == "119"
    # Documented by the guide, absent from every entry measured; carried, not dropped.
    assert all(vote.full_action_name is None for vote in votes)


def test_a_bill_without_the_optional_elements_reads_them_as_empty() -> None:
    """A bill without optional elements reads laws and recorded votes as empty."""
    status = parse_bill_status(status_body(), identity=IDENTITY)
    assert status.laws == ()
    assert all(action.recorded_votes == () for action in status.actions)


def test_committees_are_read_with_their_system_codes() -> None:
    """Committees are read with system code, chamber and type."""
    status = parse_bill_status((FIXTURES / "status-119hres10.xml").read_bytes(), identity=BillIdentity(119, "hres", 10))
    assert [(c.system_code, c.chamber, c.type) for c in status.committees] == [("hsru00", "House", "Standing")]
    assert status.committees[0].name == "Rules Committee"
    assert status.committees[0].subcommittees == ()


def test_a_subcommittee_is_read_as_a_committee_without_chamber_or_type() -> None:
    """A subcommittee is read as a committee with no chamber or type."""
    body = (
        (FIXTURES / "status-119hres10.xml")
        .read_bytes()
        .replace(
            b"</activities>\n      </item>\n    </committees>",
            b"</activities>"
            b"<subcommittees><item><systemCode>hsru13</systemCode><name>Legislative and Budget Process</name>"
            b"</item></subcommittees>"
            b"</item>\n    </committees>",
            1,
        )
    )
    status = parse_bill_status(body, identity=BillIdentity(119, "hres", 10))
    subcommittee = status.committees[0].subcommittees[0]
    assert (subcommittee.system_code, subcommittee.name) == ("hsru13", "Legislative and Budget Process")
    assert (subcommittee.chamber, subcommittee.type) == (None, None)


# --- titles and relatedBills: neither carried by status-119hr6028.xml or status-119s5.xml -------------
#
# The govinfo_bills README records status-119s5.xml as reduced with both `titles` and
# `relatedBills` dropped; only the three hres fixtures carry `titles`, and none of the five
# original fixtures carries `relatedBills` at all. status-119hr300.xml was added (measured
# live 2026-09-19, see the README) specifically because it is small and carries both.


def test_a_bill_without_titles_or_relatedbills_reads_them_as_empty() -> None:
    """A bill without titles or related bills reads both as empty."""
    status = parse_bill_status(status_body(), identity=IDENTITY)
    assert status.titles == ()
    assert status.related_bills == ()


def test_titles_are_read_with_chamber_and_text_version_fields_where_the_publisher_states_them() -> None:
    """Titles keep optional chamber and text-version fields where stated and leave them None where omitted."""
    status = parse_bill_status(
        (FIXTURES / "status-119hres214.xml").read_bytes(), identity=BillIdentity(119, "hres", 214)
    )
    display, official_eh, official_intro = status.titles
    assert display == BillTitle(
        title="Electing Members to certain standing committees of the House of Representatives.",
        title_type="Display Title",
        chamber_code=None,
        chamber_name=None,
        bill_text_version_code=None,
        bill_text_version_name=None,
        update_date="2026-07-11T21:24:28Z",
    )
    # Only this title carries chamberCode/chamberName in this fixture -- the guide names them
    # optional, and the corpus agrees most titles omit them.
    assert (official_eh.chamber_code, official_eh.chamber_name) == ("H", "House")
    assert (official_eh.bill_text_version_code, official_eh.bill_text_version_name) == ("EH", "Engrossed in House")
    assert official_intro.title_type == "Official Title as Introduced"
    assert (official_intro.chamber_code, official_intro.bill_text_version_code) == (None, None)


def test_related_bills_read_the_publisher_s_title_element_not_the_guide_s_latesttitle() -> None:
    """The guide names this child `latestTitle`; live BILLSTATUS from the 108th, 113th and
    119th Congresses (measured 2026-09-19) states it as `<title>` instead -- see the module
    docstring on `RelatedBill`."""
    status = parse_bill_status((FIXTURES / "status-119hr300.xml").read_bytes(), identity=BillIdentity(119, "hr", 300))
    assert status.related_bills == (
        RelatedBill(
            congress="119",
            bill_type="HR",
            number="1630",
            title="To allow States to elect to observe year-round daylight saving time, and for other purposes.",
            latest_action_date="2025-02-26",
            latest_action_text="Referred to the House Committee on Energy and Commerce.",
            relationship_details_json='[{"identifiedBy":"CRS","type":"Related bill"}]',
        ),
    )


def test_related_bills_falls_back_to_the_guide_s_latesttitle_spelling_when_present() -> None:
    """No measured record uses `<latestTitle>` (see the test above), but a historical one that
    does must still yield the title instead of `None`."""
    body = (
        (FIXTURES / "status-119hr300.xml")
        .read_bytes()
        .replace(
            b"<title>To allow States to elect to observe year-round daylight saving time, and for other "
            b"purposes.</title>",
            b"<latestTitle>To allow States to elect to observe year-round daylight saving time, and for other "
            b"purposes.</latestTitle>",
            1,
        )
    )
    status = parse_bill_status(body, identity=BillIdentity(119, "hr", 300))
    (related,) = status.related_bills
    assert (
        related.title == "To allow States to elect to observe year-round daylight saving time, and for other purposes."
    )


def test_related_bills_relationship_details_keeps_every_item_as_canonical_json() -> None:
    """A related bill can carry more than one relationshipDetails item (measured live against
    BILLSTATUS-108hr1.xml, which the offline fixtures do not need to hold to prove the shape)."""
    body = (
        (FIXTURES / "status-119hr300.xml")
        .read_bytes()
        .replace(
            b"          <item>\n            <type>Related bill</type>\n"
            b"            <identifiedBy>CRS</identifiedBy>\n          </item>\n        </relationshipDetails>",
            b"          <item>\n            <type>Related bill</type>\n"
            b"            <identifiedBy>CRS</identifiedBy>\n          </item>\n"
            b"          <item>\n            <type>Related document</type>\n"
            b"            <identifiedBy>Senate</identifiedBy>\n          </item>\n        </relationshipDetails>",
            1,
        )
    )
    status = parse_bill_status(body, identity=BillIdentity(119, "hr", 300))
    (related,) = status.related_bills
    assert related.relationship_details_json == (
        '[{"identifiedBy":"CRS","type":"Related bill"},{"identifiedBy":"Senate","type":"Related document"}]'
    )
