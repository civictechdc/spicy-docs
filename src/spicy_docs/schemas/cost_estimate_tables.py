"""``cbo_cost_estimates``: CBO's cost-estimate index as a bill's record or CBO's own feed states it, because CBO's own
site is behind a bot wall ([routes](../../../docs/research/cbo-cost-estimate-routes-2026-09-20.md)).

Two routes state it, named in ``source``: the same BILLSTATUS document the bill family reads, and CBO's keyless
per-Congress feed (``interpretation.bill_family.build_cbo_feed_cost_estimates``), which a host reads for every Congress
and merges (``merge_cbo_cost_estimates``): all of the 112th-113th's rows, whose BILLSTATUS states none, and elsewhere the
estimates no BILLSTATUS record lists.  A bill absent here is never scored, not yet linked or named by neither route --
no count taken from this table is a CBO production rate -- and the sibling
``congress_bills.cbo_cost_estimates_outcome`` preserves the BILLSTATUS route's unread, populated and requested-empty
observations.  ``title_bill_id`` names the bill each estimate's own title leads with, which is how a wrong number shows.
The letter's text is not here: it is reprinted in the bill's committee report, and its span lands on
``committee_reports`` keyed by package because the report states no publication id at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from spicy_docs.schemas.tables import (
    Reference,
    Row,
    TableContractError,
    bill_id,
    json_column,
    table_contract,
    text,
)

#: The rule ``publication_id`` is produced by, recorded on every row the way
#: ``bill_committees.referral_rule`` records its lookup.
PUBLICATION_ID_RULE = "cbo_publication_url"

#: The ``url`` shapes measured: a bare ``/publication/{id}`` page on
#: ``www.cbo.gov``, never a PDF.  1,468 of 1,468 items in the 118th's ``hr``
#: and ``s`` bulk zips are on ``https``.  Every item of the 108th-111th (9,524 in
#: all 40 zips, 2026-09-28; the 112th states none) is one of a pair naming one
#: publication in one bill, once on ``http`` and once on ``https``: 4,762
#: pairs.  CBO's own sitemap lists 4,761 of those ids, every one on ``https``,
#: and its wall answers both schemes alike, so the ``http`` statement names
#: the same page and folds with its twin, which is the row.  Anchored, no query and no trailing
#: slash, because a locator this repository publishes as a key has to be the
#: one the publisher stated; a url outside these shapes is refused by name
#: rather than coerced into an id.  Receipt:
#: ``~/Work/corpora/fork-execution-2026-09-21/spicy-docs-0501/cbo-shape/``.
_PUBLICATION_URL = re.compile(r"(?P<scheme>https?)://www\.cbo\.gov/publication/(?P<id>[1-9][0-9]*)")

#: The rule ``report_citations_json``'s parsed parts are produced by.
REPORT_CITATION_RULE = "billstatus_committee_report_citation"

#: Every ``<committeeReports>`` citation shape measured over the two zips:
#: ``H. Rept. 118-53``, ``S. Rept. 118-201`` and the part form, which the
#: publisher writes **without a space after the comma** -- every one of the
#: thirteen measured is ``H. Rept. 118-167,Part 2``, and a pattern demanding
#: the space read all twelve occurrences as unparsed.  The space is allowed
#: anyway, because a publisher that writes one is spelling the same fact.  The
#: chamber letter maps to the GovInfo document-type code
#: ``committee_reports.report_type`` publishes; a part has no package id under
#: GovInfo's sealed CRPT grammar, so none is derived from one.
_REPORT_CITATION = re.compile(
    r"(?P<chamber>[HS])\. Rept\. (?P<congress>[1-9][0-9]*)-(?P<number>[1-9][0-9]*)"
    r"(?:,\s*Part\s+(?P<part>[1-9][0-9]*))?"
)
_REPORT_TYPE_BY_CHAMBER = {"H": "hrpt", "S": "srpt"}

#: Which route stated the element.  Sealed and additions-only: the value is
#: published.  ``billstatus_bulk`` is GovInfo's BILLSTATUS bulk zip, two
#: keyless requests per Congress and type.  ``congress_api`` was reserved for
#: Congress.gov's bill record and no route produces it: that record's
#: 112th-113th lists are CBO's feed regrouped by ``Bill_Number``, CBO's wrong
#: numbers included, so it states nothing the feed does not (independent
#: review, 2026-09-28).  ``cbo_feed`` is CBO's own keyless per-Congress feed,
#: read for every Congress: the only route for the 112th-113th, whose
#: BILLSTATUS states no estimate, and elsewhere the estimates BILLSTATUS omits.
ESTIMATE_SOURCES: tuple[str, ...] = ("billstatus_bulk", "congress_api", "cbo_feed")
BILLSTATUS_BULK = "billstatus_bulk"
CBO_FEED = "cbo_feed"
#: Which row a merge keeps when two routes state one ``(bill_id,
#: publication_id)``, best first: the bill's own BILLSTATUS record is the
#: publisher's statement about that bill, and the feed is CBO's list of its
#: work, so BILLSTATUS wins whatever either's ``pub_date`` says.
SOURCE_PRECEDENCE: tuple[str, ...] = (BILLSTATUS_BULK, "congress_api", CBO_FEED)
#: How the source linked an estimate to ``bill_id``, published as ``found_by``.  Sealed and additions-only:
#: ``billstatus`` on every ``billstatus_bulk`` row, and on a ``cbo_feed`` row the feed item's ``Bill_Number``, the
#: citation a blank item's title leads with, the law it leads with through the host's laws table, or a bare-number
#: ``Bill_Number`` whose type the title's leading citation of that number supplies (appended 2026-09-28).  The one
#: spelling of each: ``sources.cbo`` imports these.
FOUND_BY_BILLSTATUS, FOUND_BY_BILL_NUMBER, FOUND_BY_TITLE, FOUND_BY_TITLE_LAW, FOUND_BY_BILL_NUMBER_TITLE = (
    "billstatus",
    "bill_number",
    "title",
    "title_law",
    "bill_number_title",
)
FOUND_BY: tuple[str, ...] = (
    FOUND_BY_BILLSTATUS,
    FOUND_BY_BILL_NUMBER,
    FOUND_BY_TITLE,
    FOUND_BY_TITLE_LAW,
    FOUND_BY_BILL_NUMBER_TITLE,
)
#: The rule ``title_bill_id`` is read by, recorded on every row as ``publication_id_rule`` records its own: the
#: citation an estimate's title leads with (``sources.cbo.title_citation``), a public law through the host's laws
#: table.  Versioned because the grammar is ours and moves: a host tells rows read under an older one by this.
TITLE_BILL_ID_RULE = "cbo_title_citation/1"

CBO_COST_ESTIMATES = table_contract(
    "cbo_cost_estimates",
    references=(Reference(("bill_id",), "congress_bills", ("bill_id",)),),
    grain=(
        "One row per bill and CBO publication a source names as a cost estimate of it: the bill's own BILLSTATUS "
        "document or CBO's per-Congress feed, read for every Congress and merged, the bill's own record winning "
        "where both name one bill and publication."
    ),
    identity=("bill_id", "publication_id"),
    version_column="pub_date",
    columns={
        "bill_id": (
            "The bill the source attached this estimate to, as published, keyed the way congress_bills.bill_id is: "
            "the bill whose BILLSTATUS record lists it (`billstatus_bulk`), or the bill CBO's feed item names by "
            "Bill_Number, by a bare-number Bill_Number and the title's leading citation of that number, or, where "
            "Bill_Number is empty, by the citation its title leads with or by the bill the host's laws table says "
            "enacted the law it leads with (`cbo_feed`; found_by says which).  Where "
            "title_bill_id differs, this number is wrong and title_bill_id names the bill the estimate scores."
        ),
        "congress": "The numbered Congress the bill belongs to.",
        "bill_type": "Lowercase publisher bill or resolution type (hr, s, hjres...).",
        "bill_number": "The measure's number within its Congress and type.",
        "publication_id": (
            "CBO's own publication number, parsed from the stated url by the `cbo_publication_url` rule and "
            "part of this row's identity.  This is the key CBO's per-Congress feed also states, so that feed's "
            "own spelling of the measure, which no GovInfo route gives, joins here.  It is not unique alone: where "
            "the routes file one estimate under two bills, both rows publish -- CBO's feed files 22065, its "
            "estimate of P.L. 111-322, under the 112th's H.R. 3082 and the 111th's H.R. 3082 BILLSTATUS lists it "
            "-- and title_bill_id names the bill it scores."
        ),
        "pub_date": (
            "The publisher's pubDate for this estimate; the merge prefers the larger value.  It is when CBO "
            "published the estimate, not when the bill acted.  A `cbo_feed` row states the feed's Date as the "
            "same instant in UTC, spelled as BILLSTATUS spells pubDate."
        ),
        "title": "The estimate's title as the publisher states it, which is usually the bill's own title.",
        "description": (
            "CBO's own statement of which printing it scored (\"As ordered reported by the House Committee "
            'on Energy and Commerce on March 24, 2023").  The only field that distinguishes two estimates of '
            "one bill, and the field that states the stage: 826 of the 118th House's 1,062 rows begin \"As "
            'ordered reported by the House C", and the tail includes Rules Committee prints, which have no '
            "committee report at all.  A `cbo_feed` row's is the feed's Description with the surrounding "
            "whitespace this package's feed parser trims, a trailing newline on many."
        ),
        "url": "The publication page the publisher linked, exactly as stated; every measured one is walled.",
        "source": (
            "Which route stated the element: `billstatus_bulk` for GovInfo's keyless BILLSTATUS bulk zip, "
            "`cbo_feed` for CBO's keyless per-Congress feed; `congress_api` is reserved and no route produces "
            "it.  Sealed and additions-only.  The feed is read for every Congress.  BILLSTATUS states no estimate "
            "for the 112th-113th (none in 12,299 and 10,637 documents), so their rows are `cbo_feed`, and there a "
            "bill without a row is one no feed item names, never established as unscored.  Elsewhere a merge "
            "keeps `billstatus_bulk`, the bill's own record, where both routes state one bill and publication "
            "(merge_cbo_cost_estimates), so a `cbo_feed` row there is an estimate no BILLSTATUS record lists: 33 "
            "over the 108th-111th and 114th-119th (2026-09-28), among them the 111th's H.R. 1, H.R. 3200 and "
            "two of H.R. 3590, and the 110th's P.L. 110-50."
        ),
        "estimate_index": (
            "Zero-based position, in the list the row was read from, of the item this row states: the first one "
            "naming this publication on https, else the first one naming it.  A BILLSTATUS list keeps the "
            "publisher's order, which is a fact nothing here re-sorts.  A `cbo_feed` row's list is the feed items "
            "naming the bill, oldest first and then by publication id, because the feed runs newest first and "
            "its order within one Date changes between captures.  Each route's list is its own, so on a bill both "
            "routes give rows (8 over the 108th-119th, 2026-09-28) a `billstatus_bulk` and a `cbo_feed` row can "
            "share one index."
        ),
        "stated_count": (
            "How many items in this bill's list name this publication, which is one estimate stated that many "
            "times and not that many estimates.  The 108th-111th BILLSTATUS lists state every estimate twice, "
            "once on http and once on https, and the 112th-113th's state none.  Elsewhere it is usually 1: the "
            "118th states one twice on 37 of 1,468 measured rows.  A `cbo_feed` row's is 1, because the feed "
            "lists a publication once."
        ),
        "restatements_json": (
            "Every other item naming this publication whose fields differ from the row's, in list order, as a "
            "JSON array of objects carrying `estimate_index` and only the differing fields; `[]` when they "
            "agree or there is no other item.  In the 118th (measured 2026-09-20) 9 of the 37 restated rows "
            "differ, every one in `title` alone -- CBO re-spelling the bill's title ('Human rights' to 'Human "
            "Rights', one double-escaped ampersand).  In the 108th-111th every row carries its http twin, which "
            "differs in `url` and, on all but 11 of 4,762, in `description`, which it wraps in a p element.  "
            "The column exists so folding onto the identity drops nothing."
        ),
        "report_citation_count": (
            "How many committee reports this bill's own BILLSTATUS names, on a `cbo_feed` row too, where the "
            "host supplies that record; NULL on a `cbo_feed` row shaped without it. Zero means this document names "
            "no report citation; it does not establish that no CRPT package exists. 883 of the 1,368 scored bills of the "
            "118th are nonzero (64.5%), and the Senate shortfall is structural -- 155 of 395 scored Senate "
            "bills were reported without a written report."
        ),
        "report_citations_json": (
            "Every citation that bill's `<committeeReports>` states, as a JSON array in publisher order (NULL "
            "where report_citation_count is), each "
            "carrying the `citation` verbatim and its parsed `congress`, `report_type` and `number` -- the "
            "three columns `committee_reports` publishes -- plus `part` where the citation names one.  A part "
            "citation has no package id under GovInfo's sealed CRPT grammar, so none is invented; the parsed "
            "parts are NULL on any citation outside the measured shape."
        ),
        "publication_id_rule": "The rule that produced publication_id; a url shape, never a guess at an id.",
        "title_bill_id": (
            'The bill this estimate\'s own title leads with ("H.R. 3447, a bill to extend ..."), keyed as bill_id '
            'is and read by the feed\'s title rule; for a title leading with a public law ("P.L. 111-322, ..."), the '
            "bill the host's laws table says enacted it, where the host supplies that map.  NULL where the title "
            'leads with no citation, cites the bill only after its start ("Senate Amendment 1183 to S. 744"), is '
            "ambiguous, or names a law the host did not map.  Where it differs from bill_id the row is a numbering "
            "error and this is the bill the estimate scores: over the 108th-119th (2026-09-28), 5 BILLSTATUS rows "
            "and 5 feed rows by bill titles -- four of CBO's own wrong numbers on both, 112 H.R. 1707 for S. 1707 "
            "on the feed, and 114 H.R. 3347 on BILLSTATUS, whose record lists CBO's estimate of H.R. 3447 -- and, "
            "with a law map, 2 more on both (P.L. 119-21's estimates filed under H. Con. Res. 14) and 1 more on "
            "the feed (P.L. 111-322 filed under the 112th's H.R. 3082, its bill's number in the 111th).  A bill "
            "citation reads in the row's own Congress, so this cannot show a link to the same number in another "
            "Congress: 115 H.R. 1422's BILLSTATUS lists 52538, CBO's estimate of the 113th's H.R. 1422, and this "
            "reads 115-hr-1422; that pub_date, 2013-04-22, precedes the 115th.  On a `cbo_feed` row whose found_by "
            "is `title`, `title_law` or `bill_number_title` the title chose bill_id, so the two agree by "
            "construction and the agreement proves nothing: 237 of the 108th-119th's feed rows with the host's law "
            "map, 235 without (2026-09-28).  title_bill_id_rule names the rule."
        ),
        "found_by": (
            "How the source linked this estimate to bill_id: `billstatus` (the bill's own BILLSTATUS record lists "
            "it), or on a `cbo_feed` row `bill_number` (the item's Bill_Number), `title` (the citation a blank "
            "item's title leads with), `title_law` (the public law a blank item's title leads with, through the "
            "host's laws table: the 110th's P.L. 110-50 and the 112th's P.L. 112-8) or `bill_number_title` (a "
            "bare-number Bill_Number, whose type the title's leading citation of the same number supplies: the "
            "117th's 700 as H.R. 700, the 118th's 106 as S. 106).  Sealed and additions-only."
        ),
        "title_bill_id_rule": (
            "The rule that read title_bill_id, on every row, a NULL title_bill_id included (the rule ran and named "
            "no bill): `cbo_title_citation/1`, the bill or public law the estimate's title leads with, a law "
            "through the host's laws table.  The grammar is this package's and moves; the version says which one "
            "read the row."
        ),
    },
)


def publication_id(url: object) -> str | None:
    """CBO's publication number from a stated url, or ``None`` outside the measured shape.

    ``None`` rather than a raise: the caller owns the refusal, because it holds
    the identity to name it with and this module is a leaf that cannot log.
    """
    if not isinstance(url, str):
        return None
    match = _PUBLICATION_URL.fullmatch(url.strip())
    return None if match is None else match["id"]


def _on_https(url: object) -> bool:
    """Whether a url inside the measured shape is stated on ``https``."""
    match = _PUBLICATION_URL.fullmatch(url.strip()) if isinstance(url, str) else None
    return match is not None and match["scheme"] == "https"


def report_citation_parts(citation: object) -> dict[str, object]:
    """One ``<committeeReports>`` citation with the parts that address a CRPT package.

    The parsed parts are NULL where the citation is outside the measured
    shape, and the citation itself is always kept: an unparsed citation is
    still the publisher's statement that a report exists, and dropping it
    would understate the text route's reach.
    """
    value = citation if isinstance(citation, str) else None
    match = None if value is None else _REPORT_CITATION.fullmatch(value.strip())
    if match is None:
        return {"citation": value, "congress": None, "report_type": None, "number": None, "part": None}
    return {
        "citation": value,
        "congress": match["congress"],
        "report_type": _REPORT_TYPE_BY_CHAMBER[match["chamber"]],
        "number": match["number"],
        "part": match["part"],
    }


@dataclass(frozen=True, slots=True)
class FoldedEstimate:
    """One publication as one bill's list states it, with every restatement kept.

    ``estimate`` is the item the row states -- the first naming this
    publication on ``https``, else the first naming it -- read by attribute
    (``sources.congress.bill_status.CboCostEstimate`` is the shape) so this
    module stays the stdlib-only leaf ``schemas`` is.
    """

    publication_id: str
    estimate_index: int
    estimate: object
    stated_count: int
    restatements: tuple[dict[str, object], ...]


#: The fields folding compares and, where they differ, records.
_FOLDED_FIELDS: tuple[str, ...] = ("pub_date", "title", "url", "description")


def fold_cbo_cost_estimates(
    estimates: Sequence[object],
) -> tuple[tuple[FoldedEstimate, ...], tuple[tuple[int, object], ...]]:
    """Fold one bill's estimate items onto ``publication_id``, in first-stated order.

    Returns the folded rows and, separately, the ``(index, url)`` of every item outside the measured url shape, so the
    caller refuses those by name rather than publishing a row it could not key.  The fold exists because the publisher
    states one publication twice on some bills and ``(bill_id, publication_id)`` is one estimate; ``O(n)`` in the bill's
    own item count.

    The row states the first item naming the publication on ``https``, else the first naming it; every other item that
    differs from it is a restatement.  Preferring ``https`` is the 108th-111th's case: the ``http`` twin comes first in
    4,673 of 4,762 pairs, and it wraps the description in markup (and once misspells a title) where the ``https``
    statement, the page CBO's sitemap lists, is plain.  It also keeps the row the fork published before 0.50.1 read the
    ``http`` twin at all.
    """
    groups: dict[str, list[tuple[int, object]]] = {}
    refused: list[tuple[int, object]] = []
    for index, estimate in enumerate(estimates):
        key = publication_id(getattr(estimate, "url", None))
        if key is None:
            refused.append((index, getattr(estimate, "url", None)))
        else:
            groups.setdefault(key, []).append((index, estimate))
    folded: list[FoldedEstimate] = []
    for key, items in groups.items():
        row_index, row = next(((i, e) for i, e in items if _on_https(getattr(e, "url", None))), items[0])
        restatements: list[dict[str, object]] = []
        for index, estimate in items:
            if index == row_index:
                continue
            differences = {
                field: getattr(estimate, field, None)
                for field in _FOLDED_FIELDS
                if getattr(estimate, field, None) != getattr(row, field, None)
            }
            if differences:
                restatements.append({"estimate_index": index, **differences})
        folded.append(FoldedEstimate(key, row_index, row, len(items), tuple(restatements)))
    return tuple(folded), tuple(refused)


def shape_cbo_cost_estimate(
    identity: object,
    folded: FoldedEstimate,
    *,
    report_citations: Iterable[object] | None = (),
    source: str = BILLSTATUS_BULK,
    title_bill_id: str | None = None,
    found_by: str = FOUND_BY_BILLSTATUS,
) -> Row:
    """One ``cbo_cost_estimates`` row from one folded estimate of one bill.

    ``report_citations`` is the bill's own BILLSTATUS ``<committeeReports>``
    list, repeated on each of the bill's estimate rows: it is the text route's
    reachability, and a consumer asking "can I read this estimate's letter?"
    reads one row rather than joining to find out.  A bill carries at most a
    handful of estimates, so the repetition is bounded.  ``None`` means no
    BILLSTATUS record was read for the bill (a ``cbo_feed`` row a host shaped
    without one) and publishes NULL rather than a zero no document stated.
    ``title_bill_id`` is the bill the estimate's own title leads with, keyed
    as ``bill_id`` is, or ``None``; the caller reads it
    (``interpretation.bill_family``), from a public law through the host's
    laws table.
    """
    if source not in ESTIMATE_SOURCES:
        raise TableContractError(f"cbo_cost_estimates source must be one of {', '.join(ESTIMATE_SOURCES)}")
    if found_by not in FOUND_BY or (found_by == FOUND_BY_BILLSTATUS) != (source == BILLSTATUS_BULK):
        raise TableContractError(
            "cbo_cost_estimates found_by must be billstatus on a BILLSTATUS row and a feed way else"
        )
    estimate = folded.estimate
    citations = None if report_citations is None else [report_citation_parts(c) for c in report_citations]
    return {
        "bill_id": bill_id(identity),
        "congress": text(identity.congress),
        "bill_type": text(identity.bill_type),
        "bill_number": text(identity.number),
        "publication_id": text(folded.publication_id),
        "pub_date": text(estimate.pub_date),
        "title": text(estimate.title),
        "description": text(estimate.description),
        "url": text(estimate.url),
        "source": text(source),
        "estimate_index": text(folded.estimate_index),
        "stated_count": text(folded.stated_count),
        "restatements_json": json_column(list(folded.restatements)),
        "report_citation_count": None if citations is None else text(len(citations)),
        "report_citations_json": None if citations is None else json_column(citations),
        "publication_id_rule": PUBLICATION_ID_RULE,
        "title_bill_id": text(title_bill_id),
        "found_by": found_by,
        "title_bill_id_rule": TITLE_BILL_ID_RULE,
    }


def merge_cbo_cost_estimates(rows: Iterable[Row]) -> tuple[Row, ...]:
    """One row per ``(bill_id, publication_id)``, in first-seen order: the route ``SOURCE_PRECEDENCE`` ranks first, then
    the larger ``pub_date`` (the contract's version column), a missing one losing.

    What a host merge applies across routes; linear in the rows.  A source
    outside the vocabulary refuses rather than ranks last.
    """
    rank = {source: position for position, source in enumerate(SOURCE_PRECEDENCE)}
    kept: dict[tuple[str, ...], Row] = {}
    for row in rows:
        if row.get("source") not in rank:
            raise TableContractError(f"cbo_cost_estimates source must be one of {', '.join(ESTIMATE_SOURCES)}")
        key = CBO_COST_ESTIMATES.key(row)
        held = kept.get(key)
        if held is None:
            kept[key] = row
        elif rank[row["source"]] != rank[held["source"]]:
            if rank[row["source"]] < rank[held["source"]]:
                kept[key] = row
        elif (row.get("pub_date") or "") > (held.get("pub_date") or ""):
            kept[key] = row
    return tuple(kept.values())


__all__ = [
    "BILLSTATUS_BULK",
    "CBO_COST_ESTIMATES",
    "CBO_FEED",
    "ESTIMATE_SOURCES",
    "FOUND_BY",
    "FOUND_BY_BILLSTATUS",
    "FOUND_BY_BILL_NUMBER",
    "FOUND_BY_BILL_NUMBER_TITLE",
    "FOUND_BY_TITLE",
    "FOUND_BY_TITLE_LAW",
    "PUBLICATION_ID_RULE",
    "REPORT_CITATION_RULE",
    "SOURCE_PRECEDENCE",
    "TITLE_BILL_ID_RULE",
    "FoldedEstimate",
    "fold_cbo_cost_estimates",
    "merge_cbo_cost_estimates",
    "publication_id",
    "report_citation_parts",
    "shape_cbo_cost_estimate",
]
