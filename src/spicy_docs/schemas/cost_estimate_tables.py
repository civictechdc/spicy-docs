"""``cbo_cost_estimates``: the CBO cost-estimate index read out of the same BILLSTATUS document the bill family reads,
because CBO's own site is behind a bot wall ([routes](../../../docs/research/cbo-cost-estimate-routes-2026-09-20.md)).

The element is never emitted empty, so a bill absent here is either never scored or not yet linked -- no count taken
from this table is a CBO production rate -- and the sibling ``congress_bills.cbo_cost_estimates_outcome`` preserves the
unread, populated and requested-empty observations.  The letter's text is not here: it is reprinted in the bill's
committee report, and its span lands on ``committee_reports`` keyed by package because the report states no publication
id at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from spicy_docs.schemas.tables import (
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

#: The only ``url`` shape measured: 1,468 of 1,468 items in the 118th's ``hr``
#: and ``s`` bulk zips are a bare ``/publication/{id}`` page and **none** is a
#: PDF.  Anchored, no query and no trailing slash, because a locator this
#: repository publishes as a key has to be the one the publisher stated; a url
#: outside this shape is refused by name rather than coerced into an id.
_PUBLICATION_URL = re.compile(r"https://www\.cbo\.gov/publication/(?P<id>[1-9][0-9]*)")

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
#: published.  ``billstatus_bulk`` is the recommended harvest (two keyless
#: requests per Congress and type); ``congress_api`` is the same four fields
#: from ``api.congress.gov``, one keyed request per bill, kept as the spot
#: check and the disagreement detector rather than as a harvest.
ESTIMATE_SOURCES: tuple[str, ...] = ("billstatus_bulk", "congress_api")
BILLSTATUS_BULK = "billstatus_bulk"

CBO_COST_ESTIMATES = table_contract(
    "cbo_cost_estimates",
    grain="One row per bill and CBO publication the bill's BILLSTATUS document names as a cost estimate of it.",
    identity=("bill_id", "publication_id"),
    version_column="pub_date",
    columns={
        "bill_id": "The bill this estimate scores, keyed the way congress_bills.bill_id is.",
        "congress": "The numbered Congress the bill belongs to.",
        "bill_type": "Lowercase publisher bill or resolution type (hr, s, hjres...).",
        "bill_number": "The measure's number within its Congress and type.",
        "publication_id": (
            "CBO's own publication number, parsed from the stated url by the `cbo_publication_url` rule and "
            "part of this row's identity.  This is the key CBO's per-Congress feed also states, so that feed's "
            "own spelling of the measure, which no GovInfo route gives, joins here."
        ),
        "pub_date": (
            "The publisher's pubDate for this estimate; the merge prefers the larger value.  It is when CBO "
            "published the estimate, not when the bill acted."
        ),
        "title": "The estimate's title as the publisher states it, which is usually the bill's own title.",
        "description": (
            "CBO's own statement of which printing it scored (\"As ordered reported by the House Committee "
            'on Energy and Commerce on March 24, 2023").  The only field that distinguishes two estimates of '
            "one bill, and the field that states the stage: 826 of the 118th House's 1,062 rows begin \"As "
            'ordered reported by the House C", and the tail includes Rules Committee prints, which have no '
            "committee report at all."
        ),
        "url": "The publication page the publisher linked, exactly as stated; every measured one is walled.",
        "source": (
            "Which route stated the element: `billstatus_bulk` for the keyless bulk zip, `congress_api` for "
            "the keyed per-bill route.  Sealed and additions-only."
        ),
        "estimate_index": (
            "Zero-based position, in the publisher's own list, of the first item naming this publication.  "
            "Document order is kept because the publisher's order is a fact and nothing here re-sorts it."
        ),
        "stated_count": (
            "How many items in this bill's list name this publication.  Usually 1; the publisher states one "
            "twice on 37 of 1,468 measured rows, which is one estimate stated twice and not two estimates."
        ),
        "restatements_json": (
            "Every later item naming this publication whose fields differ from the first, as a JSON array of "
            "objects carrying `estimate_index` and only the differing fields; `[]` when they agree or there is "
            "no later item.  Measured 2026-09-20: 9 of the 37 restated rows differ, every one in `title` "
            "alone -- CBO re-spelling the bill's title ('Human rights' to 'Human Rights', one double-escaped "
            "ampersand).  The column exists so folding onto the identity drops nothing."
        ),
        "report_citation_count": (
            "How many committee reports this bill's own BILLSTATUS names. Zero means this document names "
            "no report citation; it does not establish that no CRPT package exists. 883 of the 1,368 scored bills of the "
            "118th are nonzero (64.5%), and the Senate shortfall is structural -- 155 of 395 scored Senate "
            "bills were reported without a written report."
        ),
        "report_citations_json": (
            "Every citation that bill's `<committeeReports>` states, as a JSON array in publisher order, each "
            "carrying the `citation` verbatim and its parsed `congress`, `report_type` and `number` -- the "
            "three columns `committee_reports` publishes -- plus `part` where the citation names one.  A part "
            "citation has no package id under GovInfo's sealed CRPT grammar, so none is invented; the parsed "
            "parts are NULL on any citation outside the measured shape."
        ),
        "publication_id_rule": "The rule that produced publication_id; a url shape, never a guess at an id.",
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

    ``estimate`` is the first item naming this publication, read by attribute
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
        first_index, first = items[0]
        restatements: list[dict[str, object]] = []
        for index, estimate in items[1:]:
            differences = {
                field: getattr(estimate, field, None)
                for field in _FOLDED_FIELDS
                if getattr(estimate, field, None) != getattr(first, field, None)
            }
            if differences:
                restatements.append({"estimate_index": index, **differences})
        folded.append(FoldedEstimate(key, first_index, first, len(items), tuple(restatements)))
    return tuple(folded), tuple(refused)


def shape_cbo_cost_estimate(
    identity: object,
    folded: FoldedEstimate,
    *,
    report_citations: Iterable[object] = (),
    source: str = BILLSTATUS_BULK,
) -> Row:
    """One ``cbo_cost_estimates`` row from one folded estimate of one bill.

    ``report_citations`` is that same BILLSTATUS document's
    ``<committeeReports>`` list, repeated on each of the bill's estimate rows:
    it is the text route's reachability, and a consumer asking "can I read this
    estimate's letter?" reads one row rather than joining to find out.  A bill
    carries at most a handful of estimates, so the repetition is bounded.
    """
    if source not in ESTIMATE_SOURCES:
        raise TableContractError(f"cbo_cost_estimates source must be one of {', '.join(ESTIMATE_SOURCES)}")
    estimate = folded.estimate
    citations = [report_citation_parts(citation) for citation in report_citations]
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
        "report_citation_count": text(len(citations)),
        "report_citations_json": json_column(citations),
        "publication_id_rule": PUBLICATION_ID_RULE,
    }


__all__ = [
    "BILLSTATUS_BULK",
    "CBO_COST_ESTIMATES",
    "ESTIMATE_SOURCES",
    "PUBLICATION_ID_RULE",
    "REPORT_CITATION_RULE",
    "FoldedEstimate",
    "fold_cbo_cost_estimates",
    "publication_id",
    "report_citation_parts",
    "shape_cbo_cost_estimate",
]
