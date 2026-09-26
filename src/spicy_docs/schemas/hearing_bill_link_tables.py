"""One row per (hearing, bill, source) stating a hearing was held on or noticed for a bill.

``hearing_transcripts.bill_id`` stays NULL because a hearing is held on a list -- twelve bills on ``CHRG-118hhrg56198``
-- so a scalar column would have to pick one; the source is part of the identity so two publishers agreeing on a pair
stays readable.  ``relation`` is sealed to ``held_on`` (``mods_cover``, confirmed 19 of 20 by the bill's own action
list) and ``noticed`` (``docs_house_br``, an agenda states intent); a ``BODY`` mention never becomes a row, and
``daily_digest_entry``, ``congress_related_items`` and ``front_matter_designator`` are named but not yet filled.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import Reference, Row, json_column, table_contract, text

HEARING_BILL_LINKS = table_contract(
    "hearing_bill_links",
    references=(
        Reference(("bill_id",), "congress_bills", ("bill_id",)),
        Reference(("committee_system_code",), "committees", ("system_code",)),
        Reference(("package_id",), "hearing_transcripts", ("package_id",)),
    ),
    grain=(
        "One row per bill one source states a hearing was held on or noticed for: the pair, the source that "
        "stated it, and the committee-and-date key the statement was checked against."
    ),
    identity=("package_id", "bill_id", "link_source"),
    version_column="link_rule_version",
    columns={
        "package_id": (
            "The CHRG package the hearing was printed as, spelled exactly as `hearing_transcripts.package_id` "
            "is, which is this table's document key."
        ),
        "congress": "The numbered Congress, from the package id's own grammar.",
        "chamber": (
            "The chamber, from the package id's document-type code rather than from its first letter, the "
            "same rule `hearing_transcripts.chamber` uses."
        ),
        "committee_system_code": (
            "The `authorityId` of the first `congCommittee` the package MODS names, already keyed the way "
            "`committees.system_code` is.  Half the join key a bill-side confirmation needs, and half the "
            "identity check an agenda row passed before it was written."
        ),
        "held_date": (
            "The day the hearing was held, where the package MODS states one distinct `heldDate`; NULL where it "
            "states none or several (a compiled volume, whose dates are held_dates_json).  Not the day its "
            "transcript was issued.  The other half of the confirmation join key."
        ),
        "event_id": (
            "The committee-meeting event id this link was reached through, so an agenda row joins "
            "`committee_meetings` and its own transcript row.  NULL on a cover row whose caller read no "
            "hearing detail: the MODS itself never states one."
        ),
        "bill_id": (
            "`congress_bills.bill_id` for the measure, in the publisher's own type and number.  Part of the identity."
        ),
        "link_source": (
            "Which rule in `interpretation/hearing_bill_links.py` stated this pair, from a sealed "
            "additions-only vocabulary: `mods_cover` (the package MODS's own cover list) and "
            "`docs_house_br` (the House Committee Repository's agenda) are implemented; "
            "`daily_digest_entry`, `congress_related_items` and `front_matter_designator` are measured, "
            "named and not yet filled.  Part of the identity, because two sources naming one pair is the "
            "evidence and collapsing them would delete it; additions-only because this value is published "
            "and a rename rewrites rows already out."
        ),
        "relation": (
            "What the row asserts, from the sealed vocabulary `held_on` and `noticed`.  `mods_cover` rows "
            "are `held_on`, confirmed 19 of 20 by the bill's own action list; `docs_house_br` rows are "
            "`noticed`, because an agenda states intent and an agenda-only bill is confirmed 1 of 18, "
            "contradicted 1 and unverifiable 16."
        ),
        "evidence_rule": (
            "Which statement inside that source settled the key, so a consumer can decline the weaker ones.  "
            "`mods_bill_context` for a cover row; `docs_house_bills_filename`, `docs_house_legis_num` or "
            "`docs_house_description` for an agenda row, in that order of preference -- the file name is the "
            "publisher's own machine-written form and the description is prose."
        ),
        "evidence_text": (
            "The exact string the rule read, so a wrong row is readable without the record in hand: the "
            "MODS `context` marker on a cover row, and the `BILLS-118HR188ih.pdf` file name, the "
            "`legis-num` or the `description` on an agenda row."
        ),
        "link_rule_version": (
            "A digest over every link rule's name, version, publisher, relation and reader, so these rows "
            "name the rules that produced them even when someone forgets to move a rule's own version; "
            "an equality token, never a freshness ordering. A successfully corrected generation supersedes "
            "its prior regardless of digest spelling. Derived the way `citations.py` derives "
            "`CITATION_RULE_SET_VERSION`, and blind for the same reason to a change inside a reader."
        ),
        # Appended last, the way a hosted table takes a new column (docs/tables.md).
        "held_dates_json": (
            "Every nonempty `heldDate` the package MODS states, as a JSON list in document order with "
            "repetitions kept; `[]` where it states none.  A compiled volume states several, and which bill "
            "was heard on which day is not stated, so no bill is paired with a date.  NULL on a row not "
            "re-read since the column was added (`mods_cover` 002)."
        ),
    },
)


def shape_hearing_bill_link(link: object) -> Row:
    """One ``hearing_bill_links`` row from one ``HearingBillLink`` finding, read by attribute so this module stays the
    stdlib-only leaf ``schemas`` is.
    """
    return {
        "package_id": text(link.package_id),
        "congress": text(link.congress),
        "chamber": text(link.chamber),
        "committee_system_code": text(link.committee_system_code),
        "held_date": text(link.held_date),
        "event_id": text(link.event_id),
        "bill_id": text(link.bill_id),
        "link_source": text(link.link_source),
        "relation": text(link.relation),
        "evidence_rule": text(link.evidence_rule),
        "evidence_text": text(link.evidence_text),
        "link_rule_version": text(link.rule_version),
        "held_dates_json": json_column(list(link.held_dates)),
    }


__all__ = ["HEARING_BILL_LINKS", "shape_hearing_bill_link"]
