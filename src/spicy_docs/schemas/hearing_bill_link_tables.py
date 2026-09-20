"""The hearing-to-bill link table: one row per (hearing, bill, source).

A link table and not a column, because the relationship is one-to-many:
``CHRG-118hhrg56198`` was held on **twelve** bills, so a scalar
``hearing_transcripts.bill_id`` forces an arbitrary pick. That column stays
NULL, and the reason it stays NULL changed -- from "no source states it" to
"a scalar column is the wrong shape"
([the measurement](../../../docs/research/hearing-bill-linkage-2026-09-20.md)).

**The source is part of the identity.** Two publishers naming the same pair is
the strongest evidence this measurement found -- where the MODS cover and the
House agenda agree, the bill's own action list confirms **18 of 18** -- so a
row per source keeps that agreement readable and a row per pair would delete
it. The identity is ``(package_id, bill_id, link_source)``.

**What each source earns, measured on the 118th Congress and nowhere else.**

``mods_cover`` -- the hearing's own printed cover list, free on every body this
repository already acquires:

* **Precision 19 of 20.** The bill's own action list carries a *Hearings Held*
  action by that committee on that date for 19 of 20 pairs; the one exception
  (``118-hr-8529``) has three actions in total, so the bill side is silent
  rather than contradicting.
* **6 of 6 set-comparisons** against a list produced by a different process
  (the Congress.gov hearing title three times, the Daily Digest committee
  entry, ``relatedItems.bills``, the transcript's front page) are set-equal
  over **55 bills** -- no bill either way in any of them.
* **Recall is unmeasured.** 2 of 20 sampled House hearings carry a ``COVER``
  bill at all, and no probe classified hearing type, so that is a floor over
  all hearings and not a rate over legislative ones. 0 of 3 sampled **Senate**
  hearings carry one, and those three MODS state no bill in any context: a row
  absent for a Senate hearing is indistinguishable from a row absent for an
  oversight hearing, and nothing in this table says which.

``docs_house_br`` -- the House Committee Repository's agenda, one keyless GET
per event:

* **36 of 46** retained ``BR`` documents resolve to a bill key. The 10 that do
  not are the ``BILLS-118Xih.pdf`` discussion drafts, which name a measure with
  no number at all; whether those drafts later acquire a number that could be
  joined back was not investigated.
* **The rows are ``noticed``, never ``held_on``.** Where the agenda and the
  cover agree the bill side confirms 18 of 18; where the agenda alone states a
  bill it confirms 1 of 18, **contradicts 1** (``118-hr-2997``, noticed for
  2023-05-23 and heard 2023-06-22) and is silent on 16. The agenda states
  intent, and a bill noticed and dropped stays on it.
* **Reach is bounded by Congress.gov, not by this publisher.** Only 9 of 20
  sampled hearings state an ``eventId`` at all; all 9 that do resolve, and all
  9 pass the per-row committee-and-date identity check.

**Three more sources are measured and not implemented**, and
``interpretation.hearing_bill_links`` names all three in the sealed vocabulary
so taking one later is an addition and not a rename: ``daily_digest_entry``
(both chambers back to 1994, and the only route that could close the Senate
gap), ``congress_related_items`` (the only Senate source measured, promotable
only behind the reverse jacket edge) and ``front_matter_designator`` (the
transcript's own title page).

**A ``BODY`` mention never becomes a row.** 0 of 23 ``BODY``-only mentions
carry a confirming action. They are what the transcript cites, not what it was
held on; ``document_citations`` is where a mention with its span belongs.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import Row, table_contract, text

HEARING_BILL_LINKS = table_contract(
    "hearing_bill_links",
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
            "The `heldDate` the package MODS states: the day the hearing was held, which is not the day its "
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
            "name the rules that produced them even when someone forgets to move a rule's own version; the "
            "merge prefers the larger value.  Derived the way `citations.py` derives "
            "`CITATION_RULE_SET_VERSION`, and blind for the same reason to a change inside a reader."
        ),
    },
)


def shape_hearing_bill_link(link: object) -> Row:
    """One ``hearing_bill_links`` row from one ``HearingBillLink`` finding.

    ``link`` is read by attribute, so this module stays the stdlib-only leaf
    ``schemas`` is and takes no import from ``interpretation`` or ``sources``.
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
    }


__all__ = ["HEARING_BILL_LINKS", "shape_hearing_bill_link"]
