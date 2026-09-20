"""The shared citation link table, and the House committee activity report it is built on.

Two tables, and the boundary between them is the owner's first rule: **data an
index already states is not recreated from the document.**

``house_activity_reports`` is the document row, and every field on it that
describes the report comes from a keyed GovInfo record and never from the
print -- the summary's title, Congress, session, issue date and *page count*,
and the MODS's authoring committee ``systemCode``, its ``<bill>`` list with
each bill's context and its ``<law>`` list.  What the PDF adds to that row is
counts, not facts: how many distinct bills and laws the print names, how many
of those the MODS does **not** already state, how many committees resolved to
a ``system_code`` and how many did not, and how far into the document the read
got.

``document_citations`` is the second rule: **nothing of value that only the
document holds may be left uncaptured.**  One row per occurrence of one cite,
carrying the exact text that matched and the character span it was read at, so
a consumer can re-read the print at that offset and see what the rule saw.
That span is the yield here, and it is worth stating why plainly, because the
bill and law keys themselves are not:

**Measured 2026-09-20 on both fixture packages: the package MODS already
states every bill and every law the print names.**  179 of 179 bills for
CRPT-118hrpt968 and 39 of 39 for CRPT-118hrpt965; 3 of 3 and 1 of 1 laws.  The
[rollup measurement](../../../docs/research/pdf-family-rollup-yield-2026-09-20.md)
reported 883 bills "beyond the index" because the index it compared against
was the ``published`` listing row -- seven fields, no bill -- and not the MODS
the body acquirer already fetches for every package it reads.  So a bill row
here is not a new join key; it is *where in a 282-page print that bill is
discussed*, which the MODS cannot say and which is why ``span_start`` is part
of this table's identity.  ``stated_by_index`` carries that per row rather
than leaving it to a research note.

What the print genuinely reaches that no GovInfo record states is the rest:
the committees other than the authoring one (16 House and 4 Senate
``system_code``s across the eight sampled prints, from 87 printed candidates),
the U.S. Code and CFR sections, the Federal Register cites, the GAO product
ids and the CRS report ids.

The rules are ``interpretation/citations.py``'s, which
``tools/analysis/pdf_family_rollup.py`` runs too, so the measurement and this
contract cannot disagree about what a bill number looks like.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from spicy_docs.schemas.tables import (
    Row,
    TableContractError,
    digest,
    flag,
    json_column,
    natural_key,
    table_contract,
    text,
)

#: The value ``document_kind`` takes for a GovInfo package read as a PDF print.
#: One vocabulary entry per family the link table serves, added as each family
#: is built; the column exists so one table serves all of them (build order
#: steps 1 to 3).
GOVINFO_PACKAGE = "govinfo_package"

DOCUMENT_CITATIONS = table_contract(
    "document_citations",
    grain=(
        "One row per occurrence of one cited key in one document's text: the key, the exact text that named it, "
        "and the character span it was read at."
    ),
    identity=("document_key", "cite_kind", "target_key", "span_start"),
    version_column="rule_version",
    columns={
        "document_key": (
            "The citing document's own natural key in its family's spelling: the GovInfo `packageId` for a "
            "package, and one value per family as the table takes each one."
        ),
        "document_kind": "Which family the citing document belongs to, so one table serves all of them.",
        "cite_kind": (
            "What kind of thing is cited: `bill_number`, `public_law`, `usc_section`, `cfr_section`, "
            "`federal_register_cite`, `gao_product_id`, `crs_report_id`, `case_docket_number` or `committee_name`."
        ),
        "target_key": (
            "The cited key in the hosted target's own spelling, which is part of this row's identity: "
            "`congress_bills.bill_id` for a bill, the joined `laws` identity for a law, a committee's "
            "`system_code`.  Where nothing settled it, the rule's canonical form of the printed text stands "
            "instead and `target_resolved` says so, because an unsettled key is still evidence and dropping it "
            "would lose what only the print holds."
        ),
        "span_start": (
            "Character offset of the match in the document's normalized text, counted from zero.  Part of the "
            "identity: one document naming one bill forty times is forty rows, and the offset is what tells "
            "them apart."
        ),
        "span_end": "Character offset just past the match, so `text[span_start:span_end]` is `matched_text`.",
        "evidence_page": (
            "The printed page the match starts on, one-based, where the rendition states page boundaries; NULL "
            "where it states none.  A match straddling a page break is attributed to the page it began on."
        ),
        "matched_text": (
            "The exact characters the rule matched, so a false positive is readable from the row without the "
            "document in hand."
        ),
        "target_table": "Which table or publisher addresses the target key, as the rule names it.",
        "target_resolved": (
            "Whether `target_key` is the hosted target's own spelling.  `false` means the rule found the cite "
            "but nothing settled the key: a bill with no stated Congress, or a committee name no supplied "
            "roster reaches."
        ),
        "stated_by_index": (
            "Whether a keyed index record for this document already states this target key -- the package "
            "MODS's own `<bill>` and `<law>` elements and its authoring committee.  NULL where no index "
            "record was supplied.  This is the owner's do-not-recreate rule, carried per row: where it is "
            "`true` the row's value is the evidence span, not the key."
        ),
        "rule_name": (
            "Which rule in `interpretation/citations.py` fired.  Equal to `cite_kind` today, and a separate "
            "column because one kind can gain a second rule -- `interpretation/bill_signals.py` already runs "
            "two patterns for one bill number -- and the row must then say which one read it."
        ),
        "rule_version": (
            "That rule's version, so a re-extraction under a corrected rule is attributable the way "
            "`prompt_version` is; the merge prefers the larger value.  Zero-padded decimal, because this "
            "column is compared as a string."
        ),
        "body_rendition": "Which rendition the text was derived from (pdf, htm, xml, txt).",
        "body_derivation": (
            "How that rendition became text (`pdf-extraction-gpo-normalized` for a print), which is what the "
            "offsets are offsets into."
        ),
        "text_sha256": (
            "Digest of that normalized text.  The span is meaningless without it: a re-extraction that moved "
            "one character moves every offset after it, and this column is what says whether two rows' offsets "
            "are comparable."
        ),
    },
)

HOUSE_ACTIVITY_REPORTS = table_contract(
    "house_activity_reports",
    grain="One row per end-of-Congress House committee activity report package, with what its print adds.",
    identity=("package_id",),
    version_column="last_modified",
    columns={
        "package_id": "The GovInfo package id, which is this row's identity.",
        "congress": "The numbered Congress, as the keyed summary states it.",
        "session": "The session of Congress the summary states.",
        "title": "The package title as the keyed summary states it.",
        "date_issued": "The date the package was issued.",
        "last_modified": "When the publisher last modified the package; the merge prefers the larger value.",
        "committee_system_code": (
            "The `authorityId` of the first `congCommittee` the MODS names: the committee whose activity this "
            "report is, already keyed the way `committees.system_code` is.  Never read off the printed cover, "
            "which the citation rules read for a different purpose."
        ),
        "committee_name": "That committee's `authority-standard` name, as the MODS spells it.",
        "committee_count": "How many committees the MODS names; every one is in committees_json.",
        "committees_json": (
            "Every `congCommittee` the MODS names, as a JSON array of objects carrying the authority id, "
            "chamber, name and the Congress the authority record itself states -- which is the roster's "
            "Congress and not necessarily this report's."
        ),
        "associated_bill_count": "How many bills the MODS names; every one is in associated_bills_json.",
        "associated_bills_json": (
            "Every root-level `<bill>` the MODS names, as a JSON array of objects carrying the bill's natural "
            "key and the publisher's own `context` marker, in document order.  The context is kept because "
            "document order is not priority order."
        ),
        "associated_law_count": "How many laws the MODS names; every one is in associated_laws_json.",
        "associated_laws_json": (
            "Every root-level `<law>` the MODS names, as a JSON array of joined `laws` identities, in document "
            "order.  Carried because it is what the beyond-index bill and law counts are measured against."
        ),
        "distinct_bills": "How many distinct bill keys the print names, by the shared citation rules.",
        "distinct_bills_beyond_index": (
            "How many of those the MODS does not already state.  Measured zero on both fixture packages: the "
            "MODS states every bill the print names, so a bill row's value is its evidence span."
        ),
        "distinct_laws": "How many distinct public laws the print names.",
        "distinct_laws_beyond_index": "How many of those the MODS does not already state.",
        "committees_resolved": (
            "How many distinct committee `system_code`s the printed committee names settled to against the "
            "rosters the caller supplied."
        ),
        "committees_unresolved": (
            "How many distinct printed committee candidates no supplied roster settled.  Not a defect count: "
            "the pinned Senate roster excerpt reaches only the committees its listed senators sit on, so this "
            "is a floor on what a full roster would settle."
        ),
        "citation_rows": "How many citation rows this document produced, across every kind.",
        "pages_read": (
            "How many pages the extraction actually read, which a capped read makes smaller than page_count."
        ),
        "page_count": (
            "How many pages the document has, as the keyed summary's own `pages` field states it -- not "
            "re-derived from the bytes."
        ),
        "pages_capped": "Whether the read stopped short of the document, so every count above is a floor.",
        "body_rendition": "Which rendition the text was derived from; `pdf` for this family.",
        "body_derivation": "How that rendition became text.",
        "text_sha256": "Digest of the normalized text the citation spans index into.",
        "rule_set_version": (
            "Digest over every citation rule's name, version and pattern, so these counts name the rules that "
            "produced them."
        ),
    },
)


@dataclass(frozen=True, slots=True)
class DocumentProvenance:
    """What every citation row of one document repeats, computed once.

    The digest is over the whole normalized text, so it is taken here rather
    than per row: a 282-page print with 267 bill mentions would otherwise hash
    140 KB 267 times, which is ``O(rows * characters)`` for a fact that does
    not change between rows.
    """

    document_key: str
    document_kind: str
    body_rendition: str
    body_derivation: str
    text_sha256: str | None


def document_provenance(body: object, *, document_key: str, document_kind: str) -> DocumentProvenance:
    """One document's provenance, from whatever ``extraction.body_text`` produced.

    ``body`` is read structurally -- ``rendition``, ``derivation`` and ``text``
    -- so this module stays the stdlib-only leaf ``schemas`` is and takes no
    import from ``extraction``.
    """
    for attribute in ("rendition", "derivation", "text"):
        if not hasattr(body, attribute):
            raise TableContractError(f"a body text must state {attribute}")
    return DocumentProvenance(
        document_key=document_key,
        document_kind=document_kind,
        body_rendition=str(body.rendition),
        body_derivation=str(body.derivation),
        text_sha256=digest(body.text),
    )


def index_stated_keys(mods: object) -> dict[str, frozenset[str]]:
    """The target keys a package MODS already states, in the citation rules' own spelling.

    This is what makes the owner's first rule checkable rather than assumed:
    both sides are reduced to one key before the comparison, so the print's
    ``H.R. 7806`` and the MODS's ``type="HR" number="7806"`` are one fact.
    ``mods`` is read structurally (``bills``, ``laws``, ``committees``), the
    shape ``sources.govinfo.bodies.PackageModsIdentity`` has.
    """
    bills = {
        natural_key(bill.congress, bill.normalized_bill_type or str(bill.bill_type).lower(), bill.number)
        for bill in getattr(mods, "bills", ())
    }
    laws = {natural_key(law.congress, law.law_type, law.number) for law in getattr(mods, "laws", ())}
    committees = {committee.authority_id for committee in getattr(mods, "committees", ())}
    return {
        "bill_number": frozenset(bills),
        "public_law": frozenset(laws),
        "committee_name": frozenset(committees),
    }


def shape_document_citation(
    finding: object,
    provenance: DocumentProvenance,
    *,
    stated_by_index: Mapping[str, frozenset[str]] | None = None,
) -> Row:
    """One ``document_citations`` row from one ``CitationFinding``.

    ``stated_by_index`` is :func:`index_stated_keys`'s output, or ``None`` when
    no index record was read for this document -- which lands as a NULL rather
    than as ``false``, because "not compared" and "the index does not state it"
    are different answers and the whole do-not-recreate rule turns on the
    difference.
    """
    stated: bool | None = None
    if stated_by_index is not None:
        stated = finding.target_key in stated_by_index.get(finding.kind, frozenset())
    return {
        "document_key": text(provenance.document_key),
        "document_kind": text(provenance.document_kind),
        "cite_kind": text(finding.kind),
        "target_key": text(finding.target_key),
        "span_start": text(finding.span_start),
        "span_end": text(finding.span_end),
        "evidence_page": text(finding.page),
        "matched_text": text(finding.matched_text),
        "target_table": text(finding.target_table),
        "target_resolved": flag(finding.target_resolved),
        "stated_by_index": flag(stated),
        "rule_name": text(finding.kind),
        "rule_version": text(finding.rule_version),
        "body_rendition": text(provenance.body_rendition),
        "body_derivation": text(provenance.body_derivation),
        "text_sha256": text(provenance.text_sha256),
    }


def _distinct(findings: Iterable[object], kind: str) -> set[str]:
    return {finding.target_key for finding in findings if finding.kind == kind}


def shape_activity_report(
    summary: object,
    mods: object,
    body: object,
    citations: Sequence[object],
    *,
    rule_set_version: str,
) -> Row:
    """One ``house_activity_reports`` row from the two keyed records, the text and its cites.

    ``summary`` and ``mods`` are what ``sources.govinfo.bodies`` validated for
    this package, ``body`` is its ``BodyText`` and ``citations`` the
    ``CitationFinding``s ``interpretation.citations.find_citations`` produced
    over ``body.text``.  All four are read structurally and nothing is fetched.

    Every descriptive field is the publisher's, including ``page_count``: the
    summary states the document's extent, so a capped read reports how far it
    got beside that rather than publishing its own count as the document's.
    """
    identity = summary.identity
    stated = index_stated_keys(mods)
    bills = _distinct(citations, "bill_number")
    laws = _distinct(citations, "public_law")
    committees = [finding for finding in citations if finding.kind == "committee_name"]
    pages = getattr(body, "pages", None)
    pages_read = None if pages is None else len(pages)
    page_count = summary.pages
    capped = None if pages_read is None or page_count is None else pages_read < int(page_count)
    return {
        "package_id": text(identity.package_id),
        "congress": text(identity.congress),
        "session": text(summary.session),
        "title": text(summary.title),
        "date_issued": text(summary.date_issued),
        "last_modified": text(summary.last_modified),
        "committee_system_code": text(next((c.authority_id for c in mods.committees), None)),
        "committee_name": text(next((c.name for c in mods.committees), None)),
        "committee_count": text(len(mods.committees)),
        "committees_json": json_column(
            [
                {
                    "system_code": committee.authority_id,
                    "name": committee.name,
                    "chamber": committee.chamber,
                    "congress": committee.congress,
                }
                for committee in mods.committees
            ]
        ),
        "associated_bill_count": text(len(mods.bills)),
        "associated_bills_json": json_column(
            [
                {
                    "bill_id": natural_key(
                        bill.congress, bill.normalized_bill_type or str(bill.bill_type).lower(), bill.number
                    ),
                    "context": bill.context,
                }
                for bill in mods.bills
            ]
        ),
        "associated_law_count": text(len(mods.laws)),
        "associated_laws_json": json_column([natural_key(law.congress, law.law_type, law.number) for law in mods.laws]),
        "distinct_bills": text(len(bills)),
        "distinct_bills_beyond_index": text(len(bills - stated["bill_number"])),
        "distinct_laws": text(len(laws)),
        "distinct_laws_beyond_index": text(len(laws - stated["public_law"])),
        "committees_resolved": text(len({f.target_key for f in committees if f.target_resolved})),
        "committees_unresolved": text(len({f.target_key for f in committees if not f.target_resolved})),
        "citation_rows": text(len(citations)),
        "pages_read": text(pages_read),
        "page_count": text(page_count),
        "pages_capped": flag(capped),
        "body_rendition": text(body.rendition),
        "body_derivation": text(body.derivation),
        "text_sha256": digest(body.text),
        "rule_set_version": text(rule_set_version),
    }


__all__ = [
    "DOCUMENT_CITATIONS",
    "GOVINFO_PACKAGE",
    "HOUSE_ACTIVITY_REPORTS",
    "DocumentProvenance",
    "document_provenance",
    "index_stated_keys",
    "shape_activity_report",
    "shape_document_citation",
]
