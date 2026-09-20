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

**What the print actually adds, measured.** The
[MODS re-check](../../../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
read all eight sampled activity reports at full page depth -- 1,249 pages, not
the rollup's capped 476 -- and compared every key against each package's own
MODS:

===========================  ==========================================
Kind                         Print-only, eight reports, every page
===========================  ==========================================
``bill_number``              **0 of 1,406**
``public_law``               **0 of 174** (the one apparent survivor, ``188-11``, is the print's misprint)
``usc_section``              **0 of 37**
``statutes_at_large``        **0 of 7**
``committee_name``           **27 resolved codes**, 71 of 79 rows
``rin``                      **87**
``docket_number``            **38**
``gao_product_id``           5
``cfr_section``              1 of 1
``federal_register_cite``    1
``us_reports_cite``          2
===========================  ==========================================

So for bills, laws, Code sections and Statutes pages the MODS is the
**authoritative** source and the print is a floor bounded by how far the read
got; what the print adds for those kinds is the *evidence span* -- where in a
282-page print a measure is discussed -- which no GovInfo record states.  What
the print adds outright is the committees beyond the one that submitted the
report, the RINs, the agency dockets and the GAO ids: **no sampled MODS in any
collection states a Federal Register cite, a GAO product id, a CRS report id,
an agency docket, a case docket, a U.S. Reports cite or a dollar figure.**

``stated_by_index`` carries that per row, and
``WHERE stated_by_index IS NOT TRUE`` is the consumer's predicate for the kinds
that are genuinely new.  It is NULL rather than ``false`` for a kind the MODS
vocabulary has no element for at all, because "compared and absent" and "no
comparison was possible" are different answers.

The rollup measured "beyond the index" against the ``published`` listing row --
seven fields, no citation among them -- and so reported 883 bills of yield for
this family.  That was the wrong index record: ``GovInfoBodyAcquirer`` fetches
the package MODS for every body it reads.

**The aggregate shape is derivable from this one; the reverse is not.**  A
consumer wanting one row per (document, key) takes ``GROUP BY document_key,
cite_kind, target_key`` with ``COUNT(*)`` and ``MIN(span_start)``.  Storing
that aggregate instead would make the table a lossy copy of the MODS, which is
exactly what it must not be.

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
    identity=("document_key", "text_sha256", "cite_kind", "target_key", "span_start"),
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
        "target_rule": (
            "How the key was reached.  The rule's own name for every kind but `committee_name`, where it is "
            "the resolution route: `exact` and `roster_prefix` are lookups in the roster vocabulary, while "
            "`name_prefix` and `sibling_prefix` are inferences from the printed text of this one document.  A "
            "consumer wanting only roster lookups filters on this column rather than on `target_resolved`."
        ),
        "stated_by_index": (
            "Whether a keyed index record for this document already states this target key -- the package "
            "MODS's own `<bill>`, `<law>` and `<USCode>` section elements and its authoring committee.  NULL "
            "where no index record was supplied.  This is the owner's do-not-recreate rule, carried per row: "
            "where it is `true` the row's value is the evidence span, not the key, and "
            "`WHERE stated_by_index IS NOT TRUE` selects the kinds that are genuinely new."
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
            "Digest of the normalized text the offsets index into, and part of the identity.  A span means "
            "nothing without it -- a re-extraction that moved one character moves every offset after it -- and "
            "keying on it is what stops two extractions of the same document from colliding on one identity "
            "and silently merging.  The table is append-only per digest: a superseded extraction's rows are "
            "not retired, and a consumer filters to the digest `house_activity_reports.text_sha256` states for "
            "that document."
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
        "submitted_by_bioguide_id": (
            'The `bioGuideId` of the member the MODS names with `role="SUBMITTEDBY"`.  The one bioguide id '
            "any of these documents states -- the citation rules measured zero *printed* ones across ten "
            "families -- and NULL where the publisher states the member without an id, which CRPT-118hrpt965 "
            "does."
        ),
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
        "associated_usc_section_count": (
            "How many U.S. Code sections the MODS names; every one is in associated_usc_sections_json."
        ),
        "associated_usc_sections_json": (
            "Every `<USCode>` *section* the MODS names, as a JSON array of objects carrying the `{title}-{section}` "
            "key and the publisher's own subsection detail, in document order.  A chapter-only `<USCode>` block "
            "contributes nothing: a chapter is not a section and has no hosted key."
        ),
        "related_report_count": "How many sibling reports the MODS names; every one is in related_reports_json.",
        "related_reports_json": (
            "Every `<congReport>` the MODS names, as a JSON array of CRPT package ids, in document order: the "
            "report-to-report edge, stated by the publisher rather than read off the print."
        ),
        "distinct_bills": (
            "How many distinct bill keys the print names, by the shared citation rules.  A floor, not a total: "
            "it counts what pages_read reached, and the MODS is the authoritative list.  Every key carries the "
            "Congress the summary states for this document, because a print writes `H.R. 7806` and never a "
            "Congress; bills_congress_mismatch is what makes that assumption checkable."
        ),
        "distinct_bills_beyond_index": (
            "How many of those the MODS does not already state, which is a measured floor and not a discovery "
            "rate: 0 of 1,406 across all eight sampled reports at full page depth.  The per-row "
            "`document_citations.stated_by_index` carries the same comparison exactly; this column is its "
            "summary for one document."
        ),
        "bills_congress_mismatch": (
            "How many printed bills the MODS states under a *different* Congress than the one stamped on them: "
            "the same comparison run a second time on `(bill_type, number)` alone.  Nonzero means the document "
            "names a measure from another Congress and its published `bill_id` is wrong for that row, which no "
            "amount of reading the print can settle.  Measured zero on both fixture packages."
        ),
        "distinct_laws": "How many distinct public laws the print names; a floor bounded by pages_read.",
        "distinct_laws_beyond_index": (
            "How many of those the MODS does not already state: 0 of 174 across all eight sampled reports at "
            "full page depth.  A floor with `stated_by_index` semantics, not a yield estimate."
        ),
        "distinct_usc_sections": "How many distinct U.S. Code sections the print names; a floor bounded by pages_read.",
        "distinct_usc_sections_beyond_index": (
            "How many of those the MODS does not already state: 0 of 37 across all eight sampled reports at "
            "full page depth.  This is the correction that removed U.S. Code sections from the family's claimed "
            "new yield; the kinds that survive are committees, RINs, agency dockets and GAO ids."
        ),
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
        "stated_page_count": (
            "How many pages the document has, as the keyed summary's own `pages` field states it -- not "
            "re-derived from the bytes.  Named apart from `committee_reports.page_count`, which is a package-"
            "keyed column holding how many pages *that* extraction read: the two would otherwise collide on "
            "one `package_id` with opposite meanings (282 against 60 on CRPT-118hrpt965)."
        ),
        "pages_capped": "Whether the read stopped short of the document, so every count above is a floor.",
        "body_rendition": (
            "Which rendition the text was derived from.  `pdf` here because the acquirer is asked for "
            "`sources.govinfo.bodies.PRINT_BODY_PREFERENCE` -- the sealed order with PDF first -- and **not** "
            "because it is all an activity report offers: these packages state `htm` too, and under the sealed "
            "default 10 of 41 refused on HTML nesting depth while the 31 that were read stated no page at all, "
            "which is what the four page-stating columns here need."
        ),
        "body_derivation": "How that rendition became text.",
        "text_sha256": "Digest of the normalized text the citation spans index into.",
        "rule_set_version": (
            "Digest over every citation rule's name, version, pattern and rejects, so these counts name the "
            "rules that produced them."
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


def bill_key(bill: object) -> str:
    """One ``ModsBill`` as ``congress_bills.bill_id`` spells it.

    Shared by every family whose document row publishes the MODS's own
    ``<bill>`` list, so one reading of the publisher's ``type``/``number``
    reaches every table.
    """
    return natural_key(bill.congress, bill.normalized_bill_type or str(bill.bill_type).lower(), bill.number)


def distinct_targets(findings: Iterable[object], kind: str) -> set[str]:
    """Every distinct ``target_key`` of one kind among one document's findings.

    Shared because a document row's ``distinct_*`` columns are this count in
    every family, and a second spelling of it would be a second definition of
    what "distinct" means.
    """
    return {finding.target_key for finding in findings if finding.kind == kind}


def read_depth(body: object, summary: object) -> tuple[int | None, str | None, bool | None]:
    """``(pages_read, stated_page_count, pages_capped)`` for one document.

    The publisher states the extent and the extraction states how far it got,
    and the two are never re-derived from each other: a capped read reports
    both rather than publishing its own count as the document's.
    ``pages_capped`` is NULL when the rendition states no page split, and also
    when the publisher ever states a non-numeric extent -- which must not crash
    the row or, worse, be read as uncapped.

    Shared by every family that reads a paginated body, so the cap rule is
    stated once (measured 2026-09-20: CRPT-118hrpt965 states 282 pages and a
    60-page read saw 60).
    """
    pages = getattr(body, "pages", None)
    pages_read = None if pages is None else len(pages)
    page_count = summary.pages
    numeric_pages = page_count is not None and str(page_count).isdecimal()
    capped = None if pages_read is None or not numeric_pages else pages_read < int(page_count)
    return pages_read, page_count, capped


def index_stated_keys(mods: object) -> dict[str, frozenset[str]]:
    """The target keys a package MODS already states, in the citation rules' own spelling.

    This is what makes the owner's first rule checkable rather than assumed:
    both sides are reduced to one key before the comparison, so the print's
    ``H.R. 7806`` and the MODS's ``type="HR" number="7806"`` are one fact.
    ``mods`` is read structurally, the shape
    ``sources.govinfo.bodies.PackageModsIdentity`` has.

    **A kind is in the returned mapping when the MODS vocabulary can state it
    at all**, with an empty set where this record states none.  The
    distinction is the point: ``frozenset()`` means "compared, and the index
    does not state this" and a missing kind means "this index has no element
    of that shape", which lands as NULL rather than ``false``.  No sampled
    MODS in any collection states a Federal Register cite, a GAO product id, a
    CRS report id, an agency docket, a case docket, a U.S. Reports cite or a
    dollar figure, so those kinds are absent here by measurement, not by
    oversight (the
    [MODS re-check](../../../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
    censuses every root-level ``extension`` child of 24 records).
    """
    laws = {natural_key(law.congress, law.law_type, law.number) for law in getattr(mods, "laws", ())}
    return {
        "bill_number": frozenset(bill_key(bill) for bill in getattr(mods, "bills", ())),
        "public_law": frozenset(laws),
        "statutes_at_large": frozenset(
            f"{statute.volume}-{statute.pages}" for statute in getattr(mods, "statutes", ())
        ),
        "usc_section": frozenset(f"{section.title}-{section.number}" for section in getattr(mods, "usc_sections", ())),
        "cfr_section": frozenset(f"{part.title}-{part.part}" for part in getattr(mods, "cfr_parts", ())),
        "rin": frozenset(getattr(mods, "rins", ())),
        "committee_name": frozenset(committee.authority_id for committee in getattr(mods, "committees", ())),
    }


def index_stated_bill_pairs(mods: object) -> frozenset[str]:
    """The MODS's bills as ``{type}-{number}``, with the Congress dropped.

    The secondary comparison behind ``bills_congress_mismatch``: the citation
    rules stamp the document's own Congress on every bare designator, so a
    printed measure from an earlier Congress produces a ``bill_id`` the
    publisher disagrees with.  Comparing without the Congress is the only way
    to see that, since the print states nothing that would settle it.
    """
    return frozenset(
        f"{bill.normalized_bill_type or str(bill.bill_type).lower()}-{bill.number}"
        for bill in getattr(mods, "bills", ())
    )


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
    # A kind the index vocabulary cannot state at all stays NULL: "compared,
    # and absent" and "no element of this shape exists" are different answers,
    # and reporting the second as `false` would claim a comparison that never
    # happened.
    if stated_by_index is not None and finding.kind in stated_by_index:
        stated = finding.target_key in stated_by_index[finding.kind]
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
        "target_rule": text(finding.target_rule),
        "stated_by_index": flag(stated),
        "rule_name": text(finding.kind),
        "rule_version": text(finding.rule_version),
        "body_rendition": text(provenance.body_rendition),
        "body_derivation": text(provenance.body_derivation),
        "text_sha256": text(provenance.text_sha256),
    }


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

    Every descriptive field is the publisher's, including
    ``stated_page_count``: the summary states the document's extent, so a
    capped read reports how far it got beside that rather than publishing its
    own count as the document's.

    **The Congress on every printed bill key is this document's**, from the
    summary, because no print states one.  ``bills_congress_mismatch`` runs
    the index comparison a second time with the Congress dropped, so a measure
    the document discusses from another Congress shows up as a discrepancy
    rather than as a confidently wrong ``bill_id``.
    """
    identity = summary.identity
    provenance = document_provenance(body, document_key=identity.package_id, document_kind=GOVINFO_PACKAGE)
    stated = index_stated_keys(mods)
    bills = distinct_targets(citations, "bill_number")
    laws = distinct_targets(citations, "public_law")
    sections = distinct_targets(citations, "usc_section")
    committees = [finding for finding in citations if finding.kind == "committee_name"]
    # A bill the index states only under another Congress: it misses the
    # strict key and matches the Congress-free one.
    loose = index_stated_bill_pairs(mods)
    mismatched = {key for key in bills - stated["bill_number"] if "-".join(key.split("-")[1:]) in loose}
    pages_read, page_count, capped = read_depth(body, summary)
    submitter = getattr(mods, "submitted_by", None)
    return {
        "package_id": text(identity.package_id),
        "congress": text(identity.congress),
        "session": text(summary.session),
        "title": text(summary.title),
        "date_issued": text(summary.date_issued),
        "last_modified": text(summary.last_modified),
        "committee_system_code": text(next((c.authority_id for c in mods.committees), None)),
        "committee_name": text(next((c.name for c in mods.committees), None)),
        "submitted_by_bioguide_id": text(None if submitter is None else submitter.bioguide_id),
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
            [{"bill_id": bill_key(bill), "context": bill.context} for bill in mods.bills]
        ),
        "associated_law_count": text(len(mods.laws)),
        "associated_laws_json": json_column([natural_key(law.congress, law.law_type, law.number) for law in mods.laws]),
        "associated_usc_section_count": text(len(mods.usc_sections)),
        "associated_usc_sections_json": json_column(
            [
                {"usc_key": f"{section.title}-{section.number}", "detail": section.detail}
                for section in mods.usc_sections
            ]
        ),
        "related_report_count": text(len(mods.reports)),
        "related_reports_json": json_column([report.package_id for report in mods.reports]),
        "distinct_bills": text(len(bills)),
        "distinct_bills_beyond_index": text(len(bills - stated["bill_number"])),
        "bills_congress_mismatch": text(len(mismatched)),
        "distinct_laws": text(len(laws)),
        "distinct_laws_beyond_index": text(len(laws - stated["public_law"])),
        "distinct_usc_sections": text(len(sections)),
        "distinct_usc_sections_beyond_index": text(len(sections - stated["usc_section"])),
        "committees_resolved": text(len({f.target_key for f in committees if f.target_resolved})),
        "committees_unresolved": text(len({f.target_key for f in committees if not f.target_resolved})),
        "citation_rows": text(len(citations)),
        "pages_read": text(pages_read),
        "stated_page_count": text(page_count),
        "pages_capped": flag(capped),
        "body_rendition": text(provenance.body_rendition),
        "body_derivation": text(provenance.body_derivation),
        "text_sha256": text(provenance.text_sha256),
        "rule_set_version": text(rule_set_version),
    }


__all__ = [
    "DOCUMENT_CITATIONS",
    "GOVINFO_PACKAGE",
    "HOUSE_ACTIVITY_REPORTS",
    "DocumentProvenance",
    "bill_key",
    "distinct_targets",
    "document_provenance",
    "index_stated_bill_pairs",
    "index_stated_keys",
    "read_depth",
    "shape_activity_report",
    "shape_document_citation",
]
