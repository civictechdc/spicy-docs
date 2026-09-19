"""Four loops over every registered contract, and the shaped rows they run against.

Each loop is one property the whole layer has to hold, asserted once rather
than twenty-two times:

1. every contract is internally consistent;
2. every shaped row round-trips through its own column tuple;
3. identity is unique over the fixtures;
4. every column has a description.

The rows come from this repository's real fixtures wherever a captured one
exists. Two cases are built from less than a capture, each named where it is
built: the diff of three printings, which uses the constructed division
fixtures because they are the only files here that differ in an amount, an
addition and a move; and the hearing transcript, which reads a captured CRPT
package under a CHRG identity because no CHRG body has been captured yet.

The diff-dependent cases skip cleanly without the ``bill-diff`` extra, the way
``tests/test_section_diff.py`` does.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages
from spicy_docs.interpretation.bill_family import BillFamilyCapture
from spicy_docs.interpretation.release_matching import compile_bill_patterns, match_releases
from spicy_docs.interpretation.section_diff import diff_sections
from spicy_docs.interpretation.vote_matching import (
    index_vote_references,
    match_votes,
    recorded_vote_references,
)
from spicy_docs.schemas import TABLE_CONTRACTS, TableContract, TableContractError
from spicy_docs.schemas.activity_events import NO_SUBJECT, activity_events, snapshot_from_rows
from spicy_docs.schemas.committee_report_tables import (
    shape_committee_report,
    shape_hearing_transcript,
    shape_report_section,
)
from spicy_docs.schemas.congress_activity_tables import (
    member_key,
    press_release_id,
    shape_amendment,
    shape_member_vote,
    shape_press_release,
    shape_roll_call_vote,
    vote_id,
)
from spicy_docs.schemas.legislator_tables import shape_member, shape_member_term
from spicy_docs.schemas.tables import bill_id, digest, joined
from spicy_docs.sources.agency_reports.report_blocks import parse_agency_blocks
from spicy_docs.sources.congress.bill_status import BillIdentity
from spicy_docs.sources.congress.bill_tree import engine_available
from spicy_docs.sources.congress.press_releases import PRESS_RELEASE_FEEDS, parse_press_release_feed
from spicy_docs.sources.congress.votes import VoteLocator, parse_clerk_vote, parse_senate_vote
from spicy_docs.sources.govinfo.bodies import (
    PackageBodyIdentity,
    parse_package_id,
    validate_package_body,
    validate_package_mods,
    validate_package_summary,
)
from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyBudget, GovInfoPackageBody
from spicy_docs.sources.legislators import parse_legislators
from spicy_docs.transport.captured import CapturedBodyResponse
from tests.test_bill_family import (
    HR6028,
    OBSERVED_AT,
    ROW_TABLES,
    StubClassifier,
    StubDiffSummarizer,
    captured_pair_capture,
    family,
    modelled_family,
    status_for,
    three_printing_capture,
)

FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(frozen=True, slots=True)
class ShapedCase:
    """One shaped row, the identity rebuilt independently of it, and its JSON columns.

    ``identity`` is built from the source record by hand, not read back out of
    the row: a round-trip that recomputes the key from the row it is checking
    would agree with itself whatever the shaper did.
    """

    contract: TableContract
    row: dict[str, str | None]
    identity: tuple[str, ...]
    json_columns: dict[str, Any]


def _case(contract_name: str, row, identity, **json_columns) -> ShapedCase:
    return ShapedCase(TABLE_CONTRACTS[contract_name], row, tuple(identity), json_columns)


# ---------------------------------------------------------------------------
# The bill family: one real pair of captured printings, all three seams stubbed.
# ---------------------------------------------------------------------------


#: Every captured BILLSTATUS document, with what each one is here to reach.
#: H.R. 6028 carries no ``<committees>`` at all -- the publisher's ordinary
#: answer for a measure that took no committee action -- so the referral table
#: needs another bill; S. 5 is the only enacted one, so it is the only document
#: that fills the law-number and signing-provenance columns.  None of them needs
#: a printing, so none of them needs the diff engine.
BILLSTATUS_FIXTURES: tuple[tuple[str, BillIdentity], ...] = (
    ("status-119hres10.xml", BillIdentity(119, "hres", 10)),
    ("status-119hres214.xml", BillIdentity(119, "hres", 214)),
    ("status-119hres1376.xml", BillIdentity(119, "hres", 1376)),
    ("status-119s5.xml", BillIdentity(119, "s", 5)),
    ("status-119hr300.xml", BillIdentity(119, "hr", 300)),
)


def _billstatus_only_cases() -> list[ShapedCase]:
    """Every BILLSTATUS table, over every captured status document."""
    cases: list[ShapedCase] = []
    for name, identity in BILLSTATUS_FIXTURES:
        status = status_for(name, identity)
        tables = family(BillFamilyCapture(status=status, observed_at=OBSERVED_AT), diff=False)
        key = bill_id(identity)
        cases.append(_case("congress_bills", tables.bills[0], (key,), subjects_json=list(status.subjects)))
        for index, row in enumerate(tables.bill_actions):
            cases.append(_case("bill_actions", row, (key, str(index))))
        for row, committee in zip(tables.bill_committees, status.committees, strict=True):
            cases.append(_case("bill_committees", row, (key, committee.system_code)))
        for row, summary in zip(tables.bill_publisher_summaries, status.summaries, strict=True):
            cases.append(_case("bill_publisher_summaries", row, (key, summary.version_code, summary.action_date)))
    return cases


def _family_cases() -> list[ShapedCase]:
    cases: list[ShapedCase] = []
    status = captured_pair_capture().status
    tables = modelled_family()
    changed = family(three_printing_capture(), pair_amounts=True)
    summarized = family(three_printing_capture(), summarize_diff=StubDiffSummarizer())

    key = bill_id(status.identity)
    cases.append(
        _case(
            "congress_bills",
            tables.bills[0],
            (key,),
            subjects_json=list(status.subjects),
            related_bills_json=[],
        )
    )
    for index, row in enumerate(tables.bill_actions):
        cases.append(_case("bill_actions", row, (key, str(index))))
    for row, summary in zip(tables.bill_publisher_summaries, status.summaries, strict=True):
        cases.append(_case("bill_publisher_summaries", row, (key, summary.version_code, summary.action_date)))
    for row, printing in zip(tables.bill_versions, captured_pair_capture().versions, strict=True):
        cases.append(
            _case(
                "bill_versions",
                row,
                (key, printing.version_code, printing.source),
                offered_formats_json=[
                    {"url": link.url, "type": link.type, "package_id": link.package_id}
                    for link in printing.version.formats
                ],
                discarded_elements_json=dict(printing.document.discarded_elements),
            )
        )
    # Sections, and the two model tables keyed on them, are walked from the
    # parsed documents rather than read back out of the rows under test: the
    # stub labels every section, so one walk of the nodes gives every identity.
    sections = [
        (printing, seq, node)
        for printing in captured_pair_capture().versions
        for seq, node in enumerate(printing.document.sections)
    ]
    for row, (printing, _, node) in zip(tables.bill_sections, sections, strict=True):
        cases.append(
            _case(
                "bill_sections",
                row,
                (key, printing.version_code, printing.source, joined(node.match_path), str(node.body_index)),
                match_path_json=list(node.match_path),
                display_path_json=list(node.display_path),
            )
        )
    for row, (printing, _, node) in zip(tables.section_classifications, sections, strict=True):
        cases.append(
            _case(
                "section_classifications",
                row,
                (
                    key,
                    printing.version_code,
                    printing.source,
                    joined(node.match_path),
                    str(node.body_index),
                    StubClassifier().label,
                ),
            )
        )
    for row, printing in zip(tables.bill_summaries, captured_pair_capture().versions, strict=True):
        cases.append(
            _case(
                "bill_summaries",
                row,
                (key, printing.version_code, printing.source),
                top_provisions_json=["First provision", "Second provision"],
            )
        )

    # The diff identities are rebuilt from the pairs the builder was given and
    # from the engine's own records, recomputed here rather than read off the
    # rows: `seq` is the position of the correspondence in `diff_sections`'s
    # output, and `amount_index` the position of the pairing within its item.
    printings = three_printing_capture().versions
    diffed = [(printings[index], printings[index + 1]) for index in range(len(printings) - 1)]
    items_by_pair = {
        (older.version_code, newer.version_code): diff_sections(
            older.document,
            newer.document,
            from_version=older.version_code,
            to_version=newer.version_code,
            pair_amounts=True,
        ).items
        for older, newer in diffed
    }
    for row, (older, newer) in zip(changed.section_diffs, diffed, strict=True):
        cases.append(
            _case(
                "section_diffs",
                row,
                (key, older.version_code, older.source, newer.version_code, newer.source),
            )
        )
    item_cases = [
        (older, newer, seq, item)
        for older, newer in diffed
        for seq, item in enumerate(items_by_pair[(older.version_code, newer.version_code)])
    ]
    for row, (older, newer, seq, item) in zip(changed.section_diff_items, item_cases, strict=True):
        cases.append(
            _case(
                "section_diff_items",
                row,
                (key, older.version_code, older.source, newer.version_code, newer.source, str(seq)),
                match_path_json=list(item.match_path),
            )
        )
    amount_cases = [
        (older, newer, seq, amount_index)
        for older, newer, seq, item in item_cases
        for amount_index, _ in enumerate(() if item.financial is None else item.financial.pairs)
    ]
    for row, (older, newer, seq, amount_index) in zip(changed.financial_changes, amount_cases, strict=True):
        cases.append(
            _case(
                "financial_changes",
                row,
                (
                    key,
                    older.version_code,
                    older.source,
                    newer.version_code,
                    newer.source,
                    str(seq),
                    str(amount_index),
                ),
            )
        )
    for row, (older, newer) in zip(summarized.diff_summaries, diffed, strict=True):
        cases.append(
            _case(
                "diff_summaries",
                row,
                (key, older.version_code, older.source, newer.version_code, newer.source),
                key_changes_json=["A section's amount rose"],
            )
        )

    # A first run against an empty prior produces one event per row it found,
    # in table order: the bill, then each version, then each summary.  The
    # identities are rebuilt from those rows -- the events' own source records
    # -- rather than read back out of the events.
    prior = snapshot_from_rows()
    current = snapshot_from_rows(
        bills=tables.bills, bill_versions=tables.bill_versions, bill_summaries=tables.bill_summaries
    )
    expected_events = [
        ("bill_added", NO_SUBJECT, tables.bills[0]["introduced_date"]),
        *(
            ("version_added", joined(TABLE_CONTRACTS["bill_versions"].key(row)), row["version_date"])
            for row in tables.bill_versions
        ),
        *(
            ("summary_generated", joined(TABLE_CONTRACTS["bill_summaries"].key(row)), row["completed_at"])
            for row in tables.bill_summaries
        ),
    ]
    events = activity_events(prior, current, detected_at=OBSERVED_AT)
    for row, (event_type, subject, occurred) in zip(events, expected_events, strict=True):
        cases.append(_case("public_activity_events", row, (key, event_type, subject, occurred)))
    return cases


# ---------------------------------------------------------------------------
# The tables one publisher document each fills.
# ---------------------------------------------------------------------------


def _amendment_cases() -> list[ShapedCase]:
    records = json.loads((FIXTURES / "listings/congress-amendment-list.json").read_text())["amendments"]
    return [
        _case(
            "amendments",
            shape_amendment(record),
            (str(record["congress"]), str(record["type"]).lower(), str(record["number"])),
        )
        for record in records
    ]


#: Bills the captured House feed actually names in a release title, so the
#: match columns carry a real match rather than an unmatched row in every case.
RELEASE_BILLS = (
    BillIdentity(119, "hr", 6500),
    BillIdentity(119, "hr", 9770),
    BillIdentity(119, "hr", 8595),
)


def _press_release_cases() -> list[ShapedCase]:
    cases: list[ShapedCase] = []
    patterns = compile_bill_patterns((HR6028, BillIdentity(119, "s", 5), *RELEASE_BILLS))
    for chamber, name in (("house", "house-rss.xml"), ("senate", "senate-rss-press.xml")):
        feed = PRESS_RELEASE_FEEDS[chamber]
        channel = parse_press_release_feed((FIXTURES / "press_releases" / name).read_bytes(), feed)
        matches = {
            match.release_id: match
            for match in match_releases(
                [
                    {"release_id": release.link, "title": release.title, "excerpt": release.description_text}
                    for release in channel.releases
                ],
                patterns,
            )
        }
        for release in channel.releases:
            cases.append(
                _case(
                    "press_releases",
                    shape_press_release(
                        release,
                        channel,
                        feed=feed,
                        observed_at=OBSERVED_AT,
                        match=matches[release.link],
                    ),
                    (press_release_id(chamber, release.link),),
                    categories_json=list(release.categories),
                )
            )
    return cases


def _vote_cases() -> list[ShapedCase]:
    """Both captured roll-call files, with the bill linkage the status document states."""
    cases: list[ShapedCase] = []
    identity = BillIdentity(119, "s", 5)
    s5 = status_for("status-119s5.xml", identity)
    read = recorded_vote_references(identity, s5.actions)
    index = index_vote_references(read.references)
    by_key = {reference.vote: reference for reference in read.references}

    votes = (
        parse_clerk_vote(
            (FIXTURES / "congress_votes/clerk-roll240.xml").read_bytes(),
            VoteLocator(chamber="house", congress=119, session=1, roll_number=240),
        ),
        parse_senate_vote(
            (FIXTURES / "congress_votes/senate-vote-119-1-00001.xml").read_bytes(),
            VoteLocator(chamber="senate", congress=119, session=1, roll_number=1),
        ),
    )
    for vote in votes:
        matched = match_votes([vote.vote_key()], index)[0]
        reference = by_key.get(vote.vote_key())
        cases.append(
            _case(
                "roll_call_votes",
                shape_roll_call_vote(
                    vote,
                    match=matched,
                    tally=vote.tallies,
                    member_vote_count=len(vote.member_votes),
                    source_url=vote.source_url,
                    question=vote.question,
                    result=vote.result,
                    vote_date=vote.date,
                    action_index=None if reference is None else reference.action_index,
                    conflict_count=len(index.conflicts),
                ),
                (str(vote.congress), vote.chamber, str(vote.session), str(vote.roll_number)),
            )
        )
        for member in vote.member_votes:
            # Rebuilt from the member record, not read off the row: the LIS id
            # the Senate file states, else the bioguide the Clerk file states,
            # else the publisher's name.
            expected_key = f"lis:{member.lis_id}" if member.lis_id else (member.bioguide_id or f"name:{member.name}")
            cases.append(
                _case(
                    "member_votes",
                    shape_member_vote(member, vote=vote),
                    (
                        str(vote.congress),
                        vote.chamber,
                        str(vote.session),
                        str(vote.roll_number),
                        expected_key,
                    ),
                )
            )

    # The two captured roll-call files are not the two S. 5 names, so the
    # linkage columns above are NULL on both.  These are the rows S. 5's own
    # recordedVotes establish: a real bill-to-vote join with no tally, which is
    # the shape a run has whenever the reference lands before the file does.
    for reference in read.references:
        matched = match_votes([reference.vote], index)[0]
        cases.append(
            _case(
                "roll_call_votes",
                shape_roll_call_vote(
                    reference.vote,
                    match=matched,
                    action_index=reference.action_index,
                    conflict_count=len(index.conflicts),
                ),
                (
                    str(reference.vote.congress),
                    reference.vote.chamber,
                    str(reference.vote.session),
                    str(reference.vote.roll_number),
                ),
            )
        )
    return cases


def _legislator_cases() -> list[ShapedCase]:
    cases: list[ShapedCase] = []
    for roster, name in (
        ("current", "legislators-current-excerpt.json"),
        ("historical", "legislators-historical-excerpt.json"),
    ):
        people = parse_legislators((FIXTURES / "legislators" / name).read_bytes(), max_bytes=8_000_000)
        for person in people.records:
            cases.append(
                _case(
                    "members",
                    shape_member(person, roster=roster, observed_at=OBSERVED_AT),
                    (person.bioguide,),
                    fec_ids_json=list(person.fec),
                )
            )
            for index, term in enumerate(person.terms):
                cases.append(
                    _case(
                        "member_terms",
                        shape_member_term(term, bioguide_id=person.bioguide, term_index=index, observed_at=OBSERVED_AT),
                        (person.bioguide, str(index)),
                    )
                )
    return cases


CRPT = "CRPT-119hrpt1"
#: No CHRG body has been captured into this repository yet, so the hearing case
#: reuses the captured CRPT response under a CHRG identity.  It establishes the
#: two columns that differ and the chamber lookup; it establishes nothing about
#: what GovInfo serves for a hearing package.
CHRG = "CHRG-119hhrg64242"


def _package_body(package_id: str) -> GovInfoPackageBody:
    bodies = FIXTURES / "govinfo_bodies"
    summary_bytes = (bodies / f"summary-{CRPT}.json").read_bytes()
    mods_bytes = (bodies / f"mods-{CRPT}.xml").read_bytes()
    body_bytes = (bodies / f"body-{CRPT}.htm").read_bytes()
    summary_url = f"https://api.govinfo.gov/packages/{CRPT}/summary"
    mods_url = f"https://api.govinfo.gov/packages/{CRPT}/mods"
    body_url = f"https://www.govinfo.gov/content/pkg/{CRPT}/html/{CRPT}.htm"
    identity = parse_package_id(package_id)
    body_identity: PackageBodyIdentity = replace(
        validate_package_body(
            body_bytes,
            package=CRPT,
            format="htm",
            content_type="text/html",
            final_url=body_url,
            max_bytes=1_000_000,
        ),
        identity=identity,
    )

    def capture(url: str, payload: bytes, media_type: str) -> CapturedBodyResponse:
        return CapturedBodyResponse(
            requested_url=url,
            resolved_url=url,
            status_code=200,
            content_type=media_type,
            observed_at=OBSERVED_AT,
            body=payload,
        )

    return GovInfoPackageBody(
        identity=identity,
        format="htm",
        preference=("xml", "htm", "txt"),
        offered_formats=("htm", "pdf"),
        summary=replace(
            validate_package_summary(summary_bytes, package=CRPT, final_url=summary_url, max_bytes=1_000_000),
            identity=identity,
        ),
        mods=replace(
            validate_package_mods(mods_bytes, package=CRPT, final_url=mods_url, max_bytes=1_000_000),
            identity=identity,
        ),
        body=body_identity,
        summary_capture=capture(summary_url, summary_bytes, "application/json"),
        mods_capture=capture(mods_url, mods_bytes, "application/xml"),
        body_capture=capture(body_url, body_bytes, "text/html"),
        request_count=3,
        budget=GovInfoBodyBudget(
            max_requests=3,
            max_body_bytes=1_000_000,
            max_metadata_bytes=1_000_000,
            timeout_seconds=5.0,
            min_request_interval_seconds=0.0,
        ),
    )


def _report_cases() -> list[ShapedCase]:
    text = (FIXTURES / "agency_reports/crpt-119hrpt105.txt").read_text()
    # ``page_count`` and ``text_sha256`` describe the extraction, not the
    # response, so the caller that ran the extraction supplies them.
    extracted = digest(text)
    cases: list[ShapedCase] = [
        _case(
            "committee_reports",
            shape_committee_report(_package_body(CRPT), bill_id="119-hr-6028", page_count=12, text_sha256=extracted),
            (CRPT,),
        ),
        _case(
            "hearing_transcripts",
            shape_hearing_transcript(_package_body(CHRG), page_count=12, text_sha256=extracted),
            (CHRG,),
        ),
    ]
    for seq, block in enumerate(parse_agency_blocks(text)):
        cases.append(
            _case(
                "report_sections",
                shape_report_section(block, package_id=CRPT, seq=seq, last_modified=OBSERVED_AT),
                (CRPT, str(seq)),
            )
        )
    return cases


def all_cases() -> list[ShapedCase]:
    cases = (
        _billstatus_only_cases()
        + _amendment_cases()
        + _press_release_cases()
        + _vote_cases()
        + _legislator_cases()
        + _report_cases()
    )
    if engine_available():
        cases = _family_cases() + cases
    return cases


CASES = all_cases()


# ---------------------------------------------------------------------------
# Loop 1: every contract is internally consistent.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract", TABLE_CONTRACTS.values(), ids=lambda c: c.name)
def test_every_contract_is_internally_consistent(contract: TableContract) -> None:
    assert contract.name == contract.name.lower()
    assert len(set(contract.columns)) == len(contract.columns)
    assert set(contract.identity) <= set(contract.columns)
    assert contract.version_column is None or contract.version_column in contract.columns
    assert set(contract.descriptions) == set(contract.columns)
    assert contract.grain.strip()


def test_the_registry_is_keyed_by_each_contracts_own_name() -> None:
    assert all(name == contract.name for name, contract in TABLE_CONTRACTS.items())


def test_a_contract_that_names_a_column_it_does_not_have_refuses() -> None:
    from spicy_docs.schemas.tables import table_contract

    with pytest.raises(TableContractError, match="identity column"):
        table_contract(
            "broken", grain="x.", identity=("missing",), version_column=None, columns={"present": "A column."}
        )
    with pytest.raises(TableContractError, match="version column"):
        table_contract(
            "broken", grain="x.", identity=("present",), version_column="missing", columns={"present": "A column."}
        )
    with pytest.raises(TableContractError, match="snake_case"):
        table_contract("Broken", grain="x.", identity=("a",), version_column=None, columns={"a": "A column."})


# ---------------------------------------------------------------------------
# Loop 2: every shaped row round-trips through its own column tuple.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.contract.name}:{'|'.join(case.identity)}")
def test_every_shaped_row_round_trips_through_its_column_tuple(case: ShapedCase) -> None:
    contract, row = case.contract, case.row
    assert tuple(row) == contract.columns
    assert all(value is None or isinstance(value, str) for value in row.values())
    assert contract.key(row) == case.identity
    # Every *_json column reads back as JSON (json.loads raises otherwise), and
    # the ones this case names read back as the record's own value.
    for column, value in row.items():
        if column.endswith("_json") and value is not None:
            json.loads(value)
    for column, expected in case.json_columns.items():
        assert json.loads(row[column]) == expected
    assert contract.checked(row) is row
    short = {name: value for name, value in row.items() if name != contract.columns[-1]}
    with pytest.raises(TableContractError):
        contract.checked(short)


def test_the_fixtures_reach_every_registered_contract() -> None:
    """A contract with no shaped row is a contract nothing has ever filled."""
    if not engine_available():
        pytest.skip("needs the 'bill-diff' extra: uv sync --extra bill-diff")
    covered = {case.contract.name for case in CASES}
    assert covered == set(TABLE_CONTRACTS)


# ---------------------------------------------------------------------------
# Loop 3: identity is unique over the fixtures.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted({case.contract.name for case in CASES}))
def test_identity_is_unique_over_the_fixtures(name: str) -> None:
    contract = TABLE_CONTRACTS[name]
    keys = [contract.key(case.row) for case in CASES if case.contract.name == name]
    assert len(set(keys)) == len(keys)


# ---------------------------------------------------------------------------
# Loop 4: every column has a description.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract", TABLE_CONTRACTS.values(), ids=lambda c: c.name)
def test_every_column_is_described_in_one_sentence(contract: TableContract) -> None:
    for column in contract.columns:
        sentence = contract.descriptions[column]
        assert sentence.strip(), column
        assert sentence.rstrip().endswith("."), column


#: Where each table's values are produced, so a description naming one can be
#: held to it.  Every registered contract needs an entry: a new table has to say
#: which code fills it before its prose can be checked at all.
SOURCE = Path(__file__).parent.parent / "src" / "spicy_docs"
FILLED_BY: dict[str, tuple[str, ...]] = {
    "congress_bills": ("schemas/bill_tables.py", "interpretation/bill_stage.py", "interpretation/money_bills.py"),
    "bill_actions": ("schemas/bill_tables.py", "interpretation/bill_stage.py"),
    "bill_committees": ("schemas/bill_tables.py", "interpretation/money_bills.py"),
    "bill_publisher_summaries": ("schemas/bill_tables.py",),
    "bill_versions": (
        "schemas/bill_version_tables.py",
        "interpretation/version_kind.py",
        "sources/congress/bill_versions.py",
        "extraction/gpo_normalize.py",
    ),
    "bill_sections": ("schemas/bill_version_tables.py",),
    "section_diffs": ("schemas/bill_diff_tables.py", "interpretation/section_diff.py"),
    "section_diff_items": ("schemas/bill_diff_tables.py", "interpretation/section_diff.py"),
    "financial_changes": ("schemas/bill_diff_tables.py", "interpretation/section_diff.py"),
    "section_classifications": ("schemas/bill_model_tables.py", "interpretation/section_classification.py"),
    "bill_summaries": ("schemas/bill_model_tables.py", "interpretation/bill_summaries.py"),
    "diff_summaries": ("schemas/bill_model_tables.py", "interpretation/bill_summaries.py"),
    "public_activity_events": ("schemas/activity_events.py",),
    "amendments": ("schemas/congress_activity_tables.py",),
    "press_releases": (
        "schemas/congress_activity_tables.py",
        "sources/congress/press_releases.py",
        "interpretation/release_matching.py",
    ),
    "roll_call_votes": (
        "schemas/congress_activity_tables.py",
        "sources/congress/votes.py",
        "interpretation/vote_matching.py",
    ),
    "member_votes": ("schemas/congress_activity_tables.py", "sources/congress/votes.py"),
    "members": ("schemas/legislator_tables.py", "sources/legislators.py"),
    "member_terms": ("schemas/legislator_tables.py", "sources/legislators.py"),
    "committee_reports": ("schemas/committee_report_tables.py", "sources/govinfo/bodies.py"),
    "report_sections": ("schemas/committee_report_tables.py", "sources/agency_reports/report_blocks.py"),
    "hearing_transcripts": ("schemas/committee_report_tables.py", "sources/govinfo/bodies.py"),
}

#: A value a description names in backticks.  Prose that says a column carries
#: ``full_text_slug_thin`` is a claim about the data, and this is where it is
#: held to one: the string has to appear in the code that fills that column.
_BACKTICKED = re.compile(r"`([^`]+)`")


def test_every_contract_declares_where_its_values_come_from() -> None:
    assert set(FILLED_BY) == set(TABLE_CONTRACTS)


@pytest.mark.parametrize("contract", TABLE_CONTRACTS.values(), ids=lambda c: c.name)
def test_a_description_that_names_a_value_names_one_the_code_produces(contract: TableContract) -> None:
    """The floor under the data dictionary: a named value has to exist somewhere.

    A grep, deliberately: it cannot prove the column carries the value on any
    given row, only that the string is not invented. That is enough to catch the
    failure that matters here -- a sentence that survives a rename, or names a
    value a reader will then look for and never find.
    """
    filled = "\n".join((SOURCE / path).read_text() for path in FILLED_BY[contract.name])
    for column in contract.columns:
        for value in _BACKTICKED.findall(contract.descriptions[column]):
            assert value in filled, f"{contract.name}.{column} names {value!r}, which its code never produces"


def test_the_value_check_would_notice_an_invented_value() -> None:
    """The check above passes trivially if nothing is ever named; prove it bites."""
    filled = "\n".join((SOURCE / path).read_text() for path in FILLED_BY["bill_versions"])
    assert "full_text_slug_thin" in filled
    assert "full_text_slug_thinned" not in filled


# ---------------------------------------------------------------------------
# The helpers the shapers lean on, checked directly.
# ---------------------------------------------------------------------------


def test_the_publishers_titles_and_related_bills_reach_their_own_columns() -> None:
    """H.R. 300 is the one captured status carrying both ``<titles>`` and ``<relatedBills>``."""
    identity = BillIdentity(119, "hr", 300)
    status = status_for("status-119hr300.xml", identity)
    row = family(BillFamilyCapture(status=status, observed_at=OBSERVED_AT), diff=False).bills[0]

    short = next(entry for entry in status.titles if entry.title_type == "Short Title(s) as Introduced")
    official = next(entry for entry in status.titles if entry.title_type == "Official Title as Introduced")
    # The short title is the short-title entry, not the first entry (a Display
    # Title here) and not the official one, which is a sentence.
    assert row["short_title"] == short.title
    assert row["short_title"] != official.title
    assert row["short_title"] != status.titles[0].title_type

    assert row["related_bill_count"] == str(len(status.related_bills))
    related = json.loads(row["related_bills_json"])
    assert [entry["number"] for entry in related] == [entry.number for entry in status.related_bills]
    # The publisher's relationship details are nested, not a JSON document
    # quoted inside a JSON document.
    assert related[0]["relationship_details"] == [{"identifiedBy": "CRS", "type": "Related bill"}]


def test_member_key_prefers_the_id_the_file_states_over_a_crosswalked_one() -> None:
    """A Senate bioguide comes from the crosswalk, so it cannot be the identity.

    The failure this precedence prevents: a member the crosswalk misses on one
    run and resolves on the next would get ``name:...`` once and a bioguide
    once -- one member's vote as two permanent rows.  The LIS id is on the page
    either way.
    """

    @dataclass(frozen=True, slots=True)
    class _Member:
        bioguide_id: str | None
        lis_id: str | None
        name: str

    senate = _Member(bioguide_id="M000133", lis_id="S1234", name="Murray (D-WA)")
    unresolved = replace(senate, bioguide_id=None)
    house = _Member(bioguide_id="C000266", lis_id=None, name="Cole")
    neither = _Member(bioguide_id=None, lis_id=None, name="Nobody")

    # The Senate member keys the same whether or not the crosswalk resolved.
    assert member_key(senate) == member_key(unresolved) == "lis:S1234"
    assert member_key(house) == "C000266"
    assert member_key(neither) == "name:Nobody"

    # And on the captured Senate file, with the drift made real: the same 99
    # votes read twice, once with a crosswalk and once without.  The crosswalk
    # resolves 3 of the 99 bioguide ids, and not one key moves.
    body = (FIXTURES / "congress_votes/senate-vote-119-1-00001.xml").read_bytes()
    locator = VoteLocator(chamber="senate", congress=119, session=1, roll_number=1)
    crosswalk = parse_legislators(
        (FIXTURES / "legislators/legislators-current-excerpt.json").read_bytes(), max_bytes=8_000_000
    )
    without = parse_senate_vote(body, locator)
    with_ids = parse_senate_vote(body, locator, crosswalk)

    resolved = [shape_member_vote(member, vote=with_ids) for member in with_ids.member_votes]
    unresolved = [shape_member_vote(member, vote=without) for member in without.member_votes]
    assert len(resolved) == 99
    assert sum(row["bioguide_id"] is not None for row in unresolved) == 0
    assert sum(row["bioguide_id"] is not None for row in resolved) == 3
    assert [row["member_key"] for row in resolved] == [row["member_key"] for row in unresolved]
    assert all(row["member_key"].startswith("lis:") for row in resolved)
    assert len({row["member_key"] for row in resolved}) == len(resolved)


def test_a_null_identity_part_refuses_rather_than_keying_on_none() -> None:
    contract = TABLE_CONTRACTS["bill_publisher_summaries"]
    row = dict.fromkeys(contract.columns)
    row["bill_id"] = "119-hr-1"
    with pytest.raises(TableContractError, match="is null"):
        contract.key(row)


def test_one_truth_value_has_one_spelling_everywhere() -> None:
    from spicy_docs.schemas.tables import flag, text

    assert text(True) == flag(True) == "true"
    assert text(False) == flag(False) == "false"
    assert text(None) is flag(None) is None


def test_a_word_diff_over_the_cap_is_truncated_and_says_so() -> None:
    from spicy_docs.schemas.bill_diff_tables import _capped_json

    entries = tuple(f"token-{index}" for index in range(5_000))
    whole, truncated = _capped_json(entries, 10_000_000)
    assert truncated is False
    assert json.loads(whole) == list(entries)

    capped, truncated = _capped_json(entries, 1_000)
    assert truncated is True
    kept = json.loads(capped)
    assert kept == list(entries[: len(kept)])
    assert len(capped.encode("utf-8")) <= 1_000
    assert _capped_json(None, 1_000) == (None, None)


def test_the_gpo_cleanup_record_reaches_the_version_row() -> None:
    """``cleanup_json`` is processing provenance, and it has to survive shaping."""
    if not engine_available():
        pytest.skip("needs the 'bill-diff' extra: uv sync --extra bill-diff")
    from spicy_docs.schemas.bill_version_tables import shape_bill_version

    pages = json.loads((FIXTURES / "gpo_pdf_text/BILLS-119hr4727ih.json").read_text())
    _, record = normalize_gpo_pages(pages)
    printing = replace(captured_pair_capture().versions[0], cleanup=record, document=None)
    row = shape_bill_version(
        printing,
        identity=HR6028,
        kind=_KindStub(),
        kind_label="Full bill text",
        kind_warning=None,
    )
    assert row["cleanup_line_numbers"] == ("true" if record.line_numbers else "false")
    assert row["cleanup_hyphen_rejoins"] == str(record.hyphen_rejoin_count)
    assert [page["page"] for page in json.loads(row["cleanup_json"])] == [page.page for page in record.pages]
    assert TABLE_CONTRACTS["bill_versions"].checked(row) is row


@dataclass(frozen=True, slots=True)
class _KindStub:
    kind: str = "full_text"
    rule: str = "full_text_slug"
    section_count: int | None = None
    body_bytes: int | None = None


def test_an_activity_subject_id_is_the_versions_own_published_key() -> None:
    if not engine_available():
        pytest.skip("needs the 'bill-diff' extra: uv sync --extra bill-diff")
    tables = modelled_family()
    versions = {joined(TABLE_CONTRACTS["bill_versions"].key(row)) for row in tables.bill_versions}
    events = activity_events(
        snapshot_from_rows(),
        snapshot_from_rows(bills=tables.bills, bill_versions=tables.bill_versions),
        detected_at=OBSERVED_AT,
    )
    subjects = {row["subject_id"] for row in events if row["event_type"] == "version_added"}
    assert subjects == versions


def test_the_family_tables_and_the_registry_agree_on_names() -> None:
    """Every ``BillFamilyTables`` field is a registered table, under the same name."""
    names = {"congress_bills" if field == "bills" else field for field in ROW_TABLES}
    assert names <= set(TABLE_CONTRACTS)


def test_a_vote_id_and_a_release_id_are_stable_functions_of_their_parts() -> None:
    key = BillIdentity(119, "hr", 1)
    assert bill_id(key) == "119-hr-1"
    assert press_release_id("house", "https://x.invalid/a") == press_release_id("house", "https://x.invalid/a")
    assert press_release_id("house", "https://x.invalid/a") != press_release_id("senate", "https://x.invalid/a")

    @dataclass(frozen=True, slots=True)
    class _Key:
        congress: int = 119
        chamber: str = "house"
        session: int = 1
        roll_number: int = 23

    assert vote_id(_Key()) == "119-house-1-23"
