"""One member, and one row per term that member served.

The placement study published a single ``members`` table.  The value inventory
(§6.7) found that every term but the last was discarded on the way in, and one
row cannot hold a chamber switch at all: a member who served in the House and
then the Senate had the House years erased.  ``Legislator.terms`` carries all of
them, so they are a table (C9).

``photo_url`` is not published.  BillTrax constructed it from a bioguide id
rather than fetching it, so the column asserted that an image exists at an
address nothing had checked.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import Row, json_column, table_contract, text

MEMBERS = table_contract(
    "members",
    grain="One row per legislator in one capture of the community crosswalk.",
    identity=("bioguide_id",),
    version_column="observed_at",
    columns={
        "bioguide_id": "The Biographical Directory id, which is this crosswalk's primary identifier.",
        "lis_id": "The Senate LIS id, which only senators carry.",
        "fec_ids_json": "Every FEC candidate id for this person, as a JSON array in the publisher's order.",
        "icpsr_id": "The ICPSR id used by roll-call research datasets.",
        "govtrack_id": "The GovTrack id.",
        "opensecrets_id": "The OpenSecrets id.",
        "wikidata_id": "The Wikidata item id.",
        "name_first": "The person's first name as the crosswalk spells it.",
        "name_last": "The person's last name as the crosswalk spells it.",
        "term_count": "How many terms the crosswalk lists; the member_terms row count for this person.",
        "first_term_start": "Start date of the earliest term listed.",
        "last_term_end": "End date of the latest term listed.",
        "current_term_type": "Chamber of the latest term: rep or sen.",
        "current_term_state": "State of the latest term.",
        "current_term_party": "Party of the latest term, as the crosswalk states it for that term.",
        "current_term_district": "District of the latest term; absent for a Senate term.",
        "roster": "Which file this record came from: current or historical.",
        "observed_at": "When the file was captured; the merge prefers the larger value.",
    },
)

MEMBER_TERMS = table_contract(
    "member_terms",
    grain="One row per term a legislator served, in the crosswalk's own order.",
    identity=("bioguide_id", "term_index"),
    version_column="observed_at",
    columns={
        "bioguide_id": "The legislator who served this term.",
        "term_index": "Zero-based position in the crosswalk's own terms list; part of the identity.",
        "term_type": "Chamber of this term: rep or sen.",
        "term_start": "Start date of this term.",
        "term_end": "End date of this term, where the crosswalk states one.",
        "term_state": "State this term was served for.",
        "term_party": "Party for this term.  One value per term, not a history: a mid-term switch collapses.",
        "term_district": "District for this term, spelled as the publisher does; absent for a Senate term.",
        "observed_at": (
            "The parent capture's instant, carried so a term list versions with the member row it came from."
        ),
    },
)


def shape_member(legislator: object, *, roster: str, observed_at: str) -> Row:
    """One ``members`` row, with the latest term's facts summarised onto it.

    ``current_term_*`` names the last term in the crosswalk's own order; the
    full history is ``member_terms``, so nothing about an earlier term is lost
    by summarising here.
    """
    terms = legislator.terms
    latest = terms[-1] if terms else None
    return {
        "bioguide_id": text(legislator.bioguide),
        "lis_id": text(legislator.lis),
        "fec_ids_json": json_column(list(legislator.fec)),
        "icpsr_id": text(legislator.icpsr),
        "govtrack_id": text(legislator.govtrack),
        "opensecrets_id": text(legislator.opensecrets),
        "wikidata_id": text(legislator.wikidata),
        "name_first": text(legislator.name_first),
        "name_last": text(legislator.name_last),
        "term_count": text(len(terms)),
        "first_term_start": text(terms[0].start if terms else None),
        "last_term_end": text(None if latest is None else latest.end),
        "current_term_type": text(None if latest is None else latest.type),
        "current_term_state": text(None if latest is None else latest.state),
        "current_term_party": text(None if latest is None else latest.party),
        "current_term_district": text(None if latest is None else latest.district),
        "roster": text(roster),
        "observed_at": text(observed_at),
    }


def shape_member_term(term: object, *, bioguide_id: str, term_index: int, observed_at: str) -> Row:
    """One ``member_terms`` row.

    ``observed_at`` is a column here even though the design's list omitted it:
    the design names ``observed_at`` as this table's version column, and a
    version column has to be one of the table's own columns for a merge to read
    it.  ``bill_sections`` carries its parent's ``version_date`` for exactly the
    same reason.
    """
    return {
        "bioguide_id": text(bioguide_id),
        "term_index": text(term_index),
        "term_type": text(term.type),
        "term_start": text(term.start),
        "term_end": text(term.end),
        "term_state": text(term.state),
        "term_party": text(term.party),
        "term_district": text(term.district),
        "observed_at": text(observed_at),
    }


__all__ = [
    "MEMBERS",
    "MEMBER_TERMS",
    "shape_member",
    "shape_member_term",
]
