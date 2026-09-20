"""Reproduce the hearing-to-bill link measurement from its retained bytes, offline.

The [linkage note](../../docs/research/hearing-bill-linkage-2026-09-20.md) was
measured by scripts that live in its receipt and carry their own copies of the
rules. This runs the **product** rules -- ``interpretation/hearing_bill_links.py``
and ``sources/congress/house_committee_repository.py`` -- over the same retained
responses and compares what they produce against the receipt's own recomputes.
A rule that drifted from what was measured shows up here as a mismatch rather
than as a silently different hosted row.

    uv run --frozen python -m tools.analysis.hearing_bill_links_recompute \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/hearing-bill-linkage-2026-09-20 \\
        --output ~/Work/corpora/supply-2026-09-02/receipts/hearing-bill-links-build-2026-09-20/recompute.json

**Two comparisons, and what each one can and cannot see.**

*The cover sets.* For each retained CHRG MODS, the product ``cover_links`` rule
is run and its bill keys compared with ``cover-agreement.json``'s ``cover``
counts for the four packages that file names, and with
``probe1-recomputed.json``'s ``mods_cover`` **sets** for all twenty of probe 1's
hearings. The second comparison is the load-bearing one: it is per-bill and
two-directional, where the first is a count. Both are re-derived from the MODS
bytes, so neither can be satisfied by reading a number out of a summary file.

*The agenda resolution.* Every retained per-event meeting XML is parsed and its
``BR`` documents resolved, then compared with ``probe1-recomputed.json``'s
``docs_BR_keys`` per event and with the totals re-derived from that file's own per-document detail. The parent-committee
codes are compared too, because the identity check the product rules run is
built on them.

**What this cannot reproduce.** The 19-of-20 and 18-of-18 bill-side
confirmations need the 60 ``bill/{c}/{t}/{n}/actions`` responses' own *Hearings
Held* actions, which ``probe3.json`` holds as a scored summary rather than as
retained action lists for this rule to re-score. Those numbers stay the
receipt's, and this tool neither restates nor re-derives them.

**Complexity.** Linear in retained bytes: ``O(sum(M) + sum(X))`` over the MODS
and meeting files, one pass each, no re-parsing.

**Requests and credentials.** None, and none. Every byte read here is already
retained; nothing here opens a socket or reads a credential.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from spicy_docs.interpretation.hearing_bill_links import (
    HEARING_BILL_LINK_RULE_VERSION,
    agenda_links,
    check_meeting_identity,
    cover_links,
)
from spicy_docs.schemas.hearing_bill_link_tables import HEARING_BILL_LINKS, shape_hearing_bill_link
from spicy_docs.sources.congress.house_committee_repository import (
    HouseCommitteeRepositoryError,
    house_meeting_xml_locator,
    locator_from_meeting,
    parse_house_committee_meeting,
)
from spicy_docs.sources.govinfo.bodies import package_mods_locator, validate_package_mods

#: The receipt's own file names.  ``p1-`` is probe 1's twenty-hearing sample and
#: ``p2b-`` the five packages probe 2b fetched to compare ``relatedItems.bills``
#: against ``COVER``; both are package MODS and both are read the same way.
MODS_GLOB = "p*-mods-CHRG-*.xml"
MEETING_GLOB = "p1-meeting-*.xml"
MAX_MODS_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class Comparison:
    """One claim, what the receipt says, what the product code says."""

    claim: str
    expected: object
    observed: object

    @property
    def agrees(self) -> bool:
        return self.expected == self.observed


def _package_id(path: Path) -> str:
    """``p1-mods-CHRG-118hhrg56198.xml`` names the package it is a MODS of."""
    return path.stem.split("-mods-", 1)[1]


def cover_sets(receipt: Path) -> dict[str, list[str]]:
    """Every retained CHRG MODS's ``mods_cover`` bill keys, by package id."""
    sets: dict[str, list[str]] = {}
    for path in sorted((receipt / "responses").glob(MODS_GLOB)):
        package = _package_id(path)
        mods = validate_package_mods(
            path.read_bytes(),
            package=package,
            final_url=package_mods_locator(package),
            max_bytes=MAX_MODS_BYTES,
        )
        sets[package] = sorted(link.bill_id for link in cover_links(mods))
    return sets


def agenda_sets(receipt: Path) -> tuple[dict[str, dict[str, object]], int, int]:
    """Every retained meeting's resolved ``BR`` keys, plus the (documents, resolved) totals."""
    events: dict[str, dict[str, object]] = {}
    documents = resolved = 0
    for path in sorted((receipt / "responses").glob(MEETING_GLOB)):
        meeting = parse_house_committee_meeting(path.read_bytes())
        agenda = meeting.agenda_documents
        documents += len(agenda)
        resolved += sum(1 for document in agenda if document.bill_id)
        try:
            locator = house_meeting_xml_locator(locator_from_meeting(meeting))
        except HouseCommitteeRepositoryError as error:
            locator = f"unaddressable: {error}"
        events[meeting.event_id] = {
            "calendar_date": meeting.calendar_date,
            "parent_committee_codes": sorted(meeting.parent_committee_codes),
            "br_documents": len(agenda),
            "br_keys": sorted({document.bill_id for document in agenda if document.bill_id}),
            "br_refused": [document.refusal for document in agenda if document.bill_id is None],
            "locator": locator,
        }
    return events, documents, resolved


def compare(receipt: Path) -> tuple[list[Comparison], dict[str, object]]:
    """Every claim this tool can re-derive, with the receipt's own value beside it."""
    agreement = json.loads((receipt / "cover-agreement.json").read_text())
    recomputed = json.loads((receipt / "probe1-recomputed.json").read_text())
    covers = cover_sets(receipt)
    events, documents, resolved = agenda_sets(receipt)
    checks: list[Comparison] = []

    # 1. The six set-comparisons, by the count each row states.  A count, not a
    #    set: cover-agreement.json holds sizes and the cover_only/other_only
    #    lists that are empty, not the bills themselves.
    for row in agreement["rows"]:
        package = row["package_id"]
        checks.append(
            Comparison(
                f"cover-agreement {package} vs {row['against']}: {row['cover']} bills",
                row["cover"],
                len(covers.get(package, [])),
            )
        )
    checks.append(
        Comparison(
            "cover-agreement: bills over the agreeing comparisons",
            agreement["bills_in_agreeing_comparisons"],
            sum(len(covers.get(row["package_id"], [])) for row in agreement["rows"] if row["equal"]),
        )
    )

    # 2. The per-hearing COVER sets, two-directional and per bill.  This is
    #    what a count comparison cannot see.
    for row in recomputed["rows"]:
        package = row["package_id"]
        checks.append(Comparison(f"probe1 {package}: COVER set", sorted(row["mods_cover"]), covers.get(package, [])))

    # 3. The agenda resolution, per event and in total.
    for row in recomputed["rows"]:
        event = row["event_id"]
        if not event:
            continue
        observed = events.get(str(event), {})
        checks.append(
            Comparison(f"probe1 event {event}: BR keys", sorted(row["docs_BR_keys"]), observed.get("br_keys", []))
        )
        checks.append(
            Comparison(
                f"probe1 event {event}: parent committee codes",
                sorted(row["docs_parent_codes"]),
                observed.get("parent_committee_codes", []),
            )
        )
    # The totals are re-derived from the receipt's own per-document detail
    # rather than typed in, so the two sides of this comparison cannot both be
    # the same number somebody wrote twice.
    detail = [entry for row in recomputed["rows"] for entry in (row.get("docs_BR_detail") or [])]
    checks.append(Comparison("probe1: BR documents in all", len(detail), documents))
    checks.append(
        Comparison(
            "probe1: BR documents resolving to a bill key",
            sum(1 for entry in detail if entry.get("key")),
            resolved,
        )
    )

    report = {
        "receipt": receipt.name,
        "rule_version": HEARING_BILL_LINK_RULE_VERSION,
        "contract": {
            "name": HEARING_BILL_LINKS.name,
            "columns": len(HEARING_BILL_LINKS.columns),
            "identity": list(HEARING_BILL_LINKS.identity),
        },
        "requests": 0,
        "comparisons": len(checks),
        "agreeing": sum(check.agrees for check in checks),
        "cover_sets": covers,
        "events": events,
        "disagreements": [
            {"claim": check.claim, "receipt": check.expected, "product": check.observed}
            for check in checks
            if not check.agrees
        ],
    }
    return checks, report


def shaped_rows(receipt: Path, package: str, event: str) -> list[dict[str, str | None]]:
    """The hosted rows one hearing's two sources produce, proved against the contract.

    Included in the report so the measurement and the published shape are the
    same artifact: a reviewer can read the rows the numbers above describe.
    """
    mods = validate_package_mods(
        (receipt / "responses" / f"p1-mods-{package}.xml").read_bytes(),
        package=package,
        final_url=package_mods_locator(package),
        max_bytes=MAX_MODS_BYTES,
    )
    meeting = parse_house_committee_meeting((receipt / "responses" / f"p1-meeting-{event}.xml").read_bytes())
    check_meeting_identity(mods, meeting)
    links = (*cover_links(mods, event_id=meeting.event_id), *agenda_links(mods, meeting))
    return [HEARING_BILL_LINKS.checked(shape_hearing_bill_link(link)) for link in links]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--receipt", type=Path, required=True, help="the retained linkage receipt directory")
    parser.add_argument("--output", type=Path, help="where to write the JSON report; stdout when omitted")
    parser.add_argument("--rows-for", default="CHRG-118hhrg52385", help="the package whose hosted rows to include")
    parser.add_argument("--rows-event", default="115955", help="that package's docs.house.gov event id")
    args = parser.parse_args(argv)

    checks, report = compare(args.receipt)
    report["rows"] = shaped_rows(args.receipt, args.rows_for, args.rows_event)
    text = json.dumps(report, indent=1, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")
    for check in checks:
        if not check.agrees:
            print(f"DISAGREES {check.claim}: receipt {check.expected!r} product {check.observed!r}")
    print(f"{report['agreeing']} of {report['comparisons']} comparisons agree; 0 requests made")
    return 0 if report["agreeing"] == report["comparisons"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
