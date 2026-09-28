"""CBO cost estimates from Congress.gov's bill record, for the bills CBO's own feed says it scored.

GovInfo's BILLSTATUS states no ``<cboCostEstimates>`` for the 112th and 113th Congresses: none in 12,299 and
10,637 documents of every bill type, where the 111th's state 2,156 items (2026-09-28). Congress.gov's bill record
lists them, one keyed request per bill, so CBO's keyless per-Congress feed names which bills to ask about
(``sources.cbo.cbo_feed_bills``): 813 and 988 bills rather than every bill, named by an item's ``Bill_Number`` or,
where that is empty, by the citation its title leads with. The record stays authoritative: a bill it lists no
estimate for yields no row, however the feed named it. Each record's ``cboCostEstimates``
reads into the same :class:`~spicy_docs.sources.congress.bill_status.CboCostEstimate` the BILLSTATUS route yields,
so both routes share the fold and the shaper and differ only in ``source``.

Requests go through :class:`~spicy_docs.sources.congress.listing.CongressListingReader` on the ``bill-detail``
route: the key travels as ``X-Api-Key`` and never in the URL, so every locator kept here is keyless; each request
is bounded and paced by the budget, a 429 or 5xx is retried with backoff inside it, and a 401/403 aborts the run.
The harvest appends one JSONL row per bill attempted and a resume skips only a recorded success
(``crs_summaries``' pattern), so an outage is retried rather than read as coverage.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spicy_docs.reading.json_input import load_decimal_json
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.cbo import CboAcquirer, CboBudget, CboFeedBill, CboFeedBills, cbo_feed_bills
from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError, CboCostEstimate
from spicy_docs.sources.congress.listing import LIST_ROUTES, CongressListingReader, list_route_url
from spicy_docs.transport.credentials import CredentialRefusedError, failure_reason, read_api_key
from spicy_docs.transport.source_acquirer import utc_now

if TYPE_CHECKING:
    import httpx

#: The four fields every measured ``cboCostEstimates`` item states, all strings; they are BILLSTATUS's
#: ``pubDate``/``title``/``url``/``description`` under the same names.
_ESTIMATE_FIELDS = frozenset({"pubDate", "title", "url", "description"})
#: A ``committeeReports`` item: the citation BILLSTATUS also states, and the API's own report resource.
_REPORT_FIELDS = frozenset({"citation", "url"})
#: 1,000 requests an hour is api.data.gov's published budget: 3.6 s exactly (``crs_summaries``).
DEFAULT_BUDGET = PagedJsonBudget(
    max_requests=4, max_page_bytes=4 * 1024 * 1024, timeout_seconds=60, min_request_interval_seconds=3.7
)
#: One keyless feed request, the largest measured feed (560,335 bytes) well inside the bound.
FEED_BUDGET = CboBudget(max_requests=3, max_bytes=4 * 1024 * 1024, timeout_seconds=60, min_request_interval_seconds=2)


class BillCboShapeError(BillSourceError):
    """A bill record's estimate or report list is outside the measured shape: refused by name, never dropped.

    The message names the shape, never source text, so a refusal row cannot
    copy an unexpected answer.
    """


@dataclass(frozen=True, slots=True)
class CongressBillEstimates:
    """One bill record's estimates and report citations, as the shaper takes them.

    ``outcome`` uses ``congress_bills.cbo_cost_estimates_outcome``'s words:
    ``populated``, ``requested-empty:absent`` (no ``cboCostEstimates`` key) or
    ``requested-empty:present-and-empty`` (``[]``). Neither empty answer says
    CBO never scored the bill.
    """

    identity: BillIdentity
    estimates: tuple[CboCostEstimate, ...]
    report_citations: tuple[str, ...]
    outcome: str


def _items(record: Mapping[str, Any], key: str, fields: frozenset[str]) -> list[Mapping[str, str]] | None:
    """The list at ``key`` if every item is an object of string fields drawn from ``fields``; ``None`` if absent."""
    value = record.get(key)
    if value is None and key not in record:
        return None
    if not isinstance(value, list):
        raise BillCboShapeError(f"bill record {key} is not a list")
    for item in value:
        if not isinstance(item, Mapping):
            raise BillCboShapeError(f"bill record {key} holds a non-object item")
        if not set(item) <= fields:
            raise BillCboShapeError(f"bill record {key} item carries an unknown field")
        if not all(isinstance(field, str) for field in item.values()):
            raise BillCboShapeError(f"bill record {key} item carries a non-string field")
        if not any(field.strip() for field in item.values()):
            raise BillCboShapeError(f"bill record {key} holds an empty item")
    return value


def read_bill_cbo_estimates(record: Mapping[str, Any], identity: BillIdentity) -> CongressBillEstimates:
    """Read one Congress.gov bill record's ``cboCostEstimates`` and ``committeeReports``, verbatim.

    The record must name ``identity``; strings keep the publisher's own
    whitespace, as the BILLSTATUS reader does (the API ends some descriptions
    in a newline). A missing field reads ``None``, as a missing BILLSTATUS
    element does, and the fold refuses an item it cannot key.
    """
    if not isinstance(record, Mapping):
        raise BillCboShapeError("bill record is not an object")
    stated = (record.get("congress"), record.get("type"), record.get("number"))
    if stated != (identity.congress, identity.bill_type.upper(), str(identity.number)):
        raise BillCboShapeError("bill record names another bill than the one requested")
    estimates = _items(record, "cboCostEstimates", _ESTIMATE_FIELDS)
    reports = _items(record, "committeeReports", _REPORT_FIELDS) or []
    if any("citation" not in report for report in reports):
        raise BillCboShapeError("bill record committeeReports item states no citation")
    outcome = (
        "requested-empty:absent"
        if estimates is None
        else "requested-empty:present-and-empty"
        if not estimates
        else "populated"
    )
    return CongressBillEstimates(
        identity,
        tuple(
            CboCostEstimate(
                pub_date=item.get("pubDate"),
                title=item.get("title"),
                url=item.get("url"),
                description=item.get("description"),
            )
            for item in estimates or ()
        ),
        tuple(report["citation"] for report in reports),
        outcome,
    )


def read_bill_detail(body: bytes, identity: BillIdentity) -> CongressBillEstimates:
    """Read retained ``bill-detail`` bytes, so a replay reads exactly what the harvest did."""
    value = load_decimal_json(body, source="Congress.gov bill record", error_type=BillCboShapeError)
    record = value.get("bill") if isinstance(value, Mapping) else None
    if not isinstance(record, Mapping):
        raise BillCboShapeError("Congress.gov bill-detail response has no bill object")
    return read_bill_cbo_estimates(record, identity)


def bill_detail_url(identity: BillIdentity) -> str:
    """The keyless locator of one bill record; the key is a request header, never part of it."""
    return list_route_url(
        LIST_ROUTES["bill-detail"], congress=identity.congress, bill_type=identity.bill_type, number=identity.number
    )


def _bill_id(identity: BillIdentity) -> str:
    return f"{identity.congress}-{identity.bill_type}-{identity.number}"


def _recorded(output: Path) -> dict[str, str]:
    """Each bill's latest recorded status in a harvest file; a later row supersedes an earlier one."""
    if not output.exists():
        return {}
    statuses: dict[str, str] = {}
    for line in output.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            statuses[row["bill_id"]] = row["status"]
    return statuses


def harvest_bill_cbo_estimates(
    bills: Iterable[CboFeedBill],
    output: Path,
    *,
    api_key: str,
    budget: PagedJsonBudget = DEFAULT_BUDGET,
    provenance: Mapping[str, object] | None = None,
    limit: int | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> Counter[str]:
    """Request each bill's record and append one row per bill asked; returns the statuses written this run.

    A resume skips only ``ok`` rows, so a ``failed`` (transport) or ``refused``
    (shape) row is asked again. An ``ok`` row keeps the exact response body,
    its SHA-256, keyless locator and observation time, the feed publications
    that named the bill and how (``found_by``), and ``provenance`` (the feed's
    own locator and digest);
    a ``refused`` row keeps the body it could not read. A 401/403 raises
    ``CredentialRefusedError`` and ends the run. ``budget.max_requests`` bounds
    one bill's attempts, retries included, and ``limit`` the bills asked.
    """
    done = _recorded(output)
    todo = [bill for bill in bills if done.get(_bill_id(bill.identity)) != "ok"]
    if limit is not None:
        todo = todo[:limit]
    written: Counter[str] = Counter()
    with (
        CongressListingReader(budget=budget, api_key=api_key, transport=transport, clock=clock) as reader,
        output.open("a") as sink,
    ):
        for bill in todo:
            url = bill_detail_url(bill.identity)
            row: dict[str, Any] = {
                "bill_id": _bill_id(bill.identity),
                "locator": url,
                "feed_publication_ids": list(bill.publication_ids),
                "found_by": bill.found_by,
                **dict(provenance or {}),
            }
            try:
                capture = reader.page(url, records_key="bill", single_record=True).capture
            except CredentialRefusedError:
                raise
            except Exception as error:  # noqa: BLE001 - recorded, then retried on resume
                row.update(status="failed", error=failure_reason(error, api_key))
            else:
                # The reader already decoded these bytes as UTF-8 JSON.
                row.update(observed_at=capture.observed_at, sha256=capture.sha256, body=capture.body.decode("utf-8"))
                try:
                    reading = read_bill_detail(capture.body, bill.identity)
                except BillCboShapeError as error:
                    row.update(status="refused", error=failure_reason(error, api_key))
                else:
                    row.update(status="ok", outcome=reading.outcome, estimate_count=len(reading.estimates))
            written[row["status"]] += 1
            sink.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            sink.flush()
    return written


def harvest_congress(
    congress: int,
    output: Path,
    *,
    api_key: str,
    limit: int | None = None,
    budget: PagedJsonBudget = DEFAULT_BUDGET,
    feed_transport: httpx.BaseTransport | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[CboFeedBills, Counter[str]]:
    """One Congress end to end: its feed, keyless, mapped to bills, then each bill's record, keyed.

    Every row carries the feed's own locator and digest, so the bill set it
    was asked from can be re-derived from the retained feed.
    """
    with CboAcquirer(budget=FEED_BUDGET, transport=feed_transport) as cbo:
        acquired = cbo.acquire_per_congress_feed(congress)
    named = cbo_feed_bills(acquired.feed, congress)
    provenance = {"feed_url": acquired.capture.requested_url, "feed_sha256": acquired.capture.sha256}
    written = harvest_bill_cbo_estimates(
        named.bills, output, api_key=api_key, budget=budget, provenance=provenance, limit=limit, transport=transport
    )
    return named, written


def main(argv: list[str] | None = None) -> int:
    """Harvest each named Congress into one JSONL file, reporting what its feed named and what was written."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--congress", type=int, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSONL, appended, resumable")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--env-var", default="API_GOV")
    parser.add_argument("--limit", type=int, default=None, help="bills asked this run, per Congress")
    args = parser.parse_args(argv)
    api_key = read_api_key(args.env_file, args.env_var)
    for congress in args.congress:
        named, written = harvest_congress(congress, args.output, api_key=api_key, limit=args.limit)
        found = Counter(bill.found_by for bill in named.bills)
        refused = Counter(f"{field}:{shape}" for _, field, shape in named.refused)
        print(
            f"{congress}th: {len(named.bills):,} bills named {dict(found)}, {named.unnamed:,} items name none, "
            f"refused {dict(refused)}; wrote {dict(written)}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
