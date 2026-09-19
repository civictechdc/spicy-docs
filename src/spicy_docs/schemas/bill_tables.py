"""The four tables one BILLSTATUS document fills: the bill, its actions, its committees, its summaries.

The placement study published one ``bills`` table; the value inventory (§6.1)
found that the entire action history, the committee list and every publisher
summary were discarded on the way in.  All three are typed on ``BillStatus``
now, so they are tables here (change C1), and ``bill_publisher_summaries`` is
named apart from the model-backed ``bill_summaries`` because BillTrax used one
name for two different things (C12).

``congress_bills``'s first ten columns keep the exact order and spelling of
spicy-regs's live ``build_congress_bills.COLUMNS``: other repositories pin that
prefix by digest through ``catalog.json``, so it is frozen on purpose and new
columns are appended.

Every function here reads its input by attribute, never by import: this module
is a leaf (see :mod:`spicy_docs.schemas.tables`).  Anything that would need the
``interpretation`` package's own vocabularies -- a committee's referral signal,
a version-kind label -- is a named argument supplied by the caller that owns
the vocabulary.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import (
    Row,
    bill_id,
    flag,
    joined,
    json_column,
    read_json_column,
    table_contract,
    text,
)

#: The rule name ``bill_committees.referral_signal`` is produced by.  The six
#: system codes it reads live in ``interpretation.money_bills.COMMITTEE_CODES``
#: and the lookup happens there; this table records which rule was applied.
COMMITTEE_REFERRAL_RULE = "committee_system_code"

CONGRESS_BILLS = table_contract(
    "congress_bills",
    grain="One row per bill or resolution, as one BILLSTATUS document states it.",
    identity=("bill_id",),
    version_column="update_date",
    columns={
        # --- frozen prefix: spicy-regs build_congress_bills.COLUMNS 1-10 ---
        "bill_id": "Natural key: congress, bill type and number joined with hyphens (119-hr-6028).",
        "congress": "The numbered Congress this measure belongs to.",
        "bill_type": "Lowercase publisher bill or resolution type (hr, s, hjres, sres...).",
        "bill_number": "The measure's number within its Congress and type.",
        "title": "The measure's official title as BILLSTATUS states it.",
        "origin_chamber": "The chamber the measure originated in, as the publisher states it.",
        "latest_action_date": "Date of the publisher's own latestAction entry.",
        "latest_action_text": "Text of the publisher's own latestAction entry.",
        "update_date": "The publisher's updateDate for this record; the merge prefers the larger value.",
        "url": "The publisher's own legislation URL for this measure.",
        # --- appended ---
        "schema_version": "The BILLSTATUS schema version the document declared (3.0.0 today).",
        "update_date_including_text": "The publisher's updateDateIncludingText, which moves when a text version posts.",
        "introduced_date": "The date the measure was introduced, as the publisher states it.",
        "policy_area": "The publisher's single policy-area term for this measure.",
        "subjects_json": "Every legislative subject term the publisher lists, as a JSON array in publisher order.",
        "subject_count": "How many legislative subject terms the publisher listed.",
        "sponsor_bioguide_id": "Bioguide id of the first sponsor the publisher lists.",
        "sponsor_full_name": "Full name string of the first sponsor, exactly as the publisher spells it.",
        "cosponsor_count": "Sponsors after the first, which is how BILLSTATUS states cosponsors here.",
        "latest_action_code": (
            "Action code of the actions[] entry the publisher's latestAction names; "
            "latestAction itself states no code, so the two are linked on date and text."
        ),
        "latest_action_time": "The publisher's actionTime on the latestAction entry.",
        "latest_action_source_system_code": "Source-system code of that same actions[] entry.",
        "latest_action_source_system_name": "Source-system name of that same actions[] entry.",
        "action_count": "How many action entries this document carries; the bill_actions row count for this bill.",
        "committee_count": (
            "How many committees and subcommittees this document names, at any nesting depth.  This is "
            "the bill_committees row count except where the publisher states a committee with no "
            "systemCode, which cannot be keyed and is refused."
        ),
        "version_count": (
            "How many text versions this BILLSTATUS document offers.  Not the bill_versions row count: "
            "a PDF twin and an upload are rows the publisher's own list does not name."
        ),
        "public_law_number": "Public law number from the publisher's laws entry, when the measure was enacted.",
        "law_type": "The publisher's law type for the first laws entry (Public Law or Private Law).",
        "statutes_at_large_cite": (
            "NULL here on purpose: the citation is published on laws.statutes_at_large_cite, read from the PLAW "
            "USLM meta, and the host fills this column by joining laws on bill_id at merge time. The family "
            "build sees one BILLSTATUS document and its printings; the PLAW is a different package the laws "
            "rollup acquires once per law, so filling it here would fetch every PLAW twice or read another "
            "table's output, which the one-pass rule forbids."
        ),
        "stage": "Interpreted legislative stage of the latest action any stage rule classified.",
        "stage_rule": "Which stage rule fired, or NULL when no rule fired and the default stood.",
        "stage_matcher": "The exact matcher string within that rule that matched.",
        "stage_action_index": "Position in the publisher's action list of the action the stage was read from.",
        "stage_action_date": "Date of the action the stage was read from.",
        "stage_source_text": "The full action text the stage rule matched against, never shortened.",
        "signed_date": "Interpreted signing date, from the coded became-law action.",
        "signed_date_rule": "Which of the three signed-date rules produced that answer.",
        "signed_date_action_index": "Position of the became-law action the signing date was read from.",
        "signed_date_action_code": "The publisher's action code on that became-law action.",
        "money_bill_kind": "Interpreted money-bill kind, or NULL when no rule claimed the measure.",
        "money_bill_rule": "Which money-bill rule fired, or NULL alongside a NULL kind.",
        "money_bill_reason_codes": (
            "The rule's reason codes, unit-separator joined; BillTrax computed and then discarded these."
        ),
        "fiscal_year": "Fiscal year detected in the title, spelled FY plus the year.",
        "appropriations_subcommittee": "Which of the twelve appropriations subcommittees the title names.",
        "referral_signals": (
            "The referral signals the money-bill classifier was given, sorted and unit-separator joined; "
            "this is the classifier's input, recorded so a classification can be re-derived."
        ),
        "short_title": (
            "The publisher's short title, from the first titles[] entry whose titleType names a short title; "
            "NULL where the measure states none, which is ordinary."
        ),
        "related_bills_json": (
            "Every relatedBills entry the publisher states, as a JSON array, with each one's relationship "
            "details nested; this replaces BillTrax's hand-set related_bill_id with the publisher's own fact."
        ),
        "related_bill_count": "How many related bills the publisher states.",
    },
)

BILL_ACTIONS = table_contract(
    "bill_actions",
    grain="One row per action entry in a bill's BILLSTATUS document, in publisher order.",
    identity=("bill_id", "action_index"),
    version_column="action_date",
    columns={
        "bill_id": "The bill this action belongs to.",
        "action_index": "Zero-based position in the publisher's own action list; part of the identity.",
        "action_date": "The publisher's actionDate for this action.",
        "action_time": "The publisher's actionTime, where the source system states one.",
        "action_text": "The action text exactly as written, whitespace included; NULL when the publisher stated none.",
        "action_code": "The publisher's action code, which is what the became-law rule keys on.",
        "action_type": "The publisher's action type (IntroReferral, Floor, BecameLaw...).",
        "source_system_code": "Code of the system that reported the action.",
        "source_system_name": "Name of the system that reported the action.",
        "recorded_vote_count": "How many recordedVote entries this action carries.",
        "is_latest_action": ("True on the one actions[] entry the publisher's separate latestAction element names."),
        "stage": "Stage this one action's text classifies as, which makes the bill's stage auditable action by action.",
        "stage_rule": "Which stage rule fired on this action, or NULL when none did.",
        "stage_matcher": "The exact matcher string within that rule that matched this action's text.",
    },
)

BILL_COMMITTEES = table_contract(
    "bill_committees",
    grain="One row per committee or subcommittee a bill reached, as its BILLSTATUS document names it.",
    identity=("bill_id", "system_code"),
    version_column="snapshot_update_date",
    columns={
        "bill_id": "The bill this referral belongs to.",
        "system_code": "The publisher's own committee identifier (hsap00); what a referral rule keys on.",
        "name": "The committee's name as prose, which no rule reads.",
        "chamber": "The chamber, which the publisher states for a committee and omits for a subcommittee.",
        "committee_type": "The publisher's committee type (Standing, Select...); absent on a subcommittee.",
        "parent_system_code": "The parent committee's system code when this row is a subcommittee.",
        "is_subcommittee": "True when this row came from another committee's subcommittees list.",
        "snapshot_update_date": "The parent document's updateDate, so a committee list is versioned with its bill.",
        "referral_signal": (
            "The money-bill referral signal this system code raises, from the six full-committee codes; "
            "NULL outside them, supplied by the caller that owns the vocabulary."
        ),
        "referral_rule": "The rule applied to produce referral_signal; a system-code lookup, never a name match.",
    },
)

BILL_PUBLISHER_SUMMARIES = table_contract(
    "bill_publisher_summaries",
    grain="One row per CRS summary the publisher states on a bill, at the version and action it describes.",
    identity=("bill_id", "summary_version_code", "action_date"),
    version_column="update_date",
    columns={
        "bill_id": "The bill this summary describes.",
        "summary_version_code": "The publisher's two-digit summary version code (00 introduced, 53 passed House...).",
        "action_date": "The date of the action this summary describes.",
        "action_desc": "The publisher's description of that action.",
        "update_date": "When the publisher last updated this summary; the merge prefers the larger value.",
        "summary_html": "The summary exactly as the publisher escaped it, from either placement, untruncated.",
        "summary_chars": "Character length of summary_html, so a truncation upstream is visible without reading it.",
    },
)


def _committee_rows(committees: object) -> int:
    total = 0
    for committee in committees or ():
        total += 1 + _committee_rows(committee.subcommittees)
    return total


def latest_action_index(status: object) -> int | None:
    """Where in ``actions`` the publisher's ``latestAction`` entry sits, if anywhere.

    ``<latestAction>`` is a separate element, not a pointer, and it states only
    ``actionDate``, ``actionTime`` and ``text`` -- never the ``actionCode``,
    ``type`` or ``sourceSystem`` that the matching ``<actions>`` entry carries.
    So the link has to be made on the two fields both elements do state, and the
    coded fields are then read from the action itself rather than published
    NULL.  The last match wins: a repeated date and text is the same event
    stated twice, and the later entry is the one a newest-last list ends on.
    """
    latest = status.latest_action
    if latest is None:
        return None
    found: int | None = None
    for index, action in enumerate(status.actions):
        if action.action_date == latest.action_date and action.text == latest.text:
            found = index
    return found


def _short_title(titles: object) -> str | None:
    """The first ``titles[]`` entry whose ``title_type`` names a short title.

    The publisher versions a short title by chamber and text version ("Short
    Titles as Introduced", "Short Title(s) as Passed House"), so the first entry
    is the earliest printing's.  ``None`` when the measure states no short title
    at all, which is ordinary: an official title is not a short one.
    """
    for entry in titles or ():
        title_type = entry.title_type
        if isinstance(title_type, str) and "short title" in title_type.lower():
            return entry.title
    return None


def _related_bill(entry: object) -> dict[str, object]:
    """One ``relatedBills`` entry, with its relationship details nested rather than re-quoted.

    ``RelatedBill.relationship_details_json`` is already canonical JSON, so it
    is read back before being embedded: a JSON document inside a JSON string is
    a second escaping every consumer would have to undo.
    """
    return {
        "congress": entry.congress,
        "bill_type": entry.bill_type,
        "number": entry.number,
        "title": entry.title,
        "latest_action_date": entry.latest_action_date,
        "latest_action_text": entry.latest_action_text,
        "relationship_details": read_json_column(entry.relationship_details_json),
    }


def shape_bill(
    status: object,
    *,
    referrals: frozenset[str],
    stage: object,
    signing: object,
    money: object,
) -> Row:
    """One ``congress_bills`` row from one BILLSTATUS document and three findings.

    ``referrals`` is what the money-bill classifier was given and is published
    beside the classification, so the answer can be re-derived from the row.
    ``stage``, ``signing`` and ``money`` are ``interpretation`` findings; each
    interpreted column is published beside the provenance columns of the finding
    that produced it.
    """
    identity = status.identity
    latest = status.latest_action
    # The coded fields live on the action, not on <latestAction>; see
    # latest_action_index for why the two have to be linked rather than read
    # from one element.
    index = latest_action_index(status)
    coded = status.actions[index] if index is not None else None
    related = status.related_bills
    laws = status.laws or ()
    return {
        "bill_id": bill_id(identity),
        "congress": text(identity.congress),
        "bill_type": text(identity.bill_type),
        "bill_number": text(identity.number),
        "title": text(status.title),
        "origin_chamber": text(status.origin_chamber),
        "latest_action_date": text(None if latest is None else latest.action_date),
        "latest_action_text": text(None if latest is None else latest.text),
        "update_date": text(status.update_date),
        "url": text(status.legislation_url),
        "schema_version": text(status.schema_version),
        "update_date_including_text": text(status.update_date_including_text),
        "introduced_date": text(status.introduced_date),
        "policy_area": text(status.policy_area),
        "subjects_json": json_column(list(status.subjects)),
        "subject_count": text(len(status.subjects)),
        "sponsor_bioguide_id": text(status.sponsors[0].bioguide_id if status.sponsors else None),
        "sponsor_full_name": text(status.sponsors[0].full_name if status.sponsors else None),
        "cosponsor_count": text(max(len(status.sponsors) - 1, 0)),
        "latest_action_code": text(None if coded is None else coded.action_code),
        "latest_action_time": text(None if latest is None else latest.action_time),
        "latest_action_source_system_code": text(None if coded is None else coded.source_system_code),
        "latest_action_source_system_name": text(None if coded is None else coded.source_system_name),
        "action_count": text(len(status.actions)),
        "committee_count": text(_committee_rows(status.committees)),
        "version_count": text(len(status.text_versions)),
        "public_law_number": text(signing.public_law_number),
        "law_type": text(laws[0].type if laws else None),
        # Published on the laws table and joined at merge time; see this column's description.
        "statutes_at_large_cite": None,
        "stage": text(stage.stage),
        "stage_rule": text(stage.rule),
        "stage_matcher": text(stage.matcher),
        "stage_action_index": text(stage.action_index),
        "stage_action_date": text(stage.action_date),
        "stage_source_text": text(stage.source_text),
        "signed_date": text(signing.signed_date),
        "signed_date_rule": text(signing.rule),
        "signed_date_action_index": text(signing.action_index),
        "signed_date_action_code": text(signing.action_code),
        "money_bill_kind": text(money.kind),
        "money_bill_rule": text(money.rule),
        "money_bill_reason_codes": joined(money.reason_codes) or None,
        "fiscal_year": text(money.fiscal_year),
        "appropriations_subcommittee": text(money.subcommittee),
        "referral_signals": joined(sorted(referrals)) or None,
        "short_title": text(_short_title(status.titles)),
        "related_bills_json": json_column([_related_bill(entry) for entry in related]),
        "related_bill_count": text(len(related)),
    }


def shape_bill_action(
    identity: object,
    action: object,
    *,
    action_index: int,
    is_latest: bool,
    stage: object,
) -> Row:
    """One ``bill_actions`` row, with the stage this one action's own text classifies as."""
    return {
        "bill_id": bill_id(identity),
        "action_index": text(action_index),
        "action_date": text(action.action_date),
        "action_time": text(action.action_time),
        "action_text": text(action.text),
        "action_code": text(action.action_code),
        "action_type": text(action.action_type),
        "source_system_code": text(action.source_system_code),
        "source_system_name": text(action.source_system_name),
        "recorded_vote_count": text(len(action.recorded_votes)),
        "is_latest_action": flag(is_latest),
        "stage": text(stage.stage),
        "stage_rule": text(stage.rule),
        "stage_matcher": text(stage.matcher),
    }


def shape_bill_committee(
    identity: object,
    committee: object,
    *,
    parent_system_code: str | None,
    update_date: str | None,
    referral_signal: str | None = None,
) -> Row:
    """One ``bill_committees`` row for a committee or one of its subcommittees.

    ``referral_signal`` is passed in rather than looked up: the six full-committee
    system codes are ``interpretation.money_bills.COMMITTEE_CODES``, and this
    module does not import that package.  ``referral_rule`` still records which
    rule produced the answer, including when that answer is NULL.
    """
    return {
        "bill_id": bill_id(identity),
        "system_code": text(committee.system_code),
        "name": text(committee.name),
        "chamber": text(committee.chamber),
        "committee_type": text(committee.type),
        "parent_system_code": text(parent_system_code),
        "is_subcommittee": flag(parent_system_code is not None),
        "snapshot_update_date": text(update_date),
        "referral_signal": text(referral_signal),
        "referral_rule": COMMITTEE_REFERRAL_RULE,
    }


def shape_bill_publisher_summary(identity: object, summary: object) -> Row:
    """One ``bill_publisher_summaries`` row: the CRS summary the publisher states."""
    return {
        "bill_id": bill_id(identity),
        "summary_version_code": text(summary.version_code),
        "action_date": text(summary.action_date),
        "action_desc": text(summary.action_desc),
        "update_date": text(summary.update_date),
        "summary_html": text(summary.text),
        "summary_chars": text(len(summary.text)),
    }


__all__ = [
    "BILL_ACTIONS",
    "BILL_COMMITTEES",
    "BILL_PUBLISHER_SUMMARIES",
    "COMMITTEE_REFERRAL_RULE",
    "CONGRESS_BILLS",
    "latest_action_index",
    "shape_bill",
    "shape_bill_action",
    "shape_bill_committee",
    "shape_bill_publisher_summary",
]
