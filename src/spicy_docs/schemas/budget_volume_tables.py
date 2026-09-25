"""``budget_volumes``: one row per published volume of the President's budget, carrying what its print adds to its own
MODS index.

This is the only GovInfo family measured whose print substantially outruns its index -- 504 of 518 public laws
print-only across eight volumes read at full page depth -- so it leads the revised build order;
``pages_read``/``pages_capped`` say how far a read actually got.  A budget volume states no Congress, so printed bills
cannot be compared strictly: ``bill_number`` is dropped from the index comparison and the congress-blind
``{type}-{number}`` pair is published as a count, never a join key.  Citation rows are shared ``document_citations``
rows with ``document_kind`` ``budget_volume``, carrying the same ``stated_by_index`` semantics, not a link table of this
family's own.
"""

from __future__ import annotations

from collections.abc import Sequence

from spicy_docs.schemas.document_citation_tables import (
    bill_key,
    distinct_targets,
    document_provenance,
    index_stated_bill_pairs,
    index_stated_keys,
    read_depth,
)
from spicy_docs.schemas.tables import VALUE_KEY, Row, flag, json_column, natural_key, table_contract, text

#: The value ``document_citations.document_kind`` takes for a budget volume,
#: beside ``document_citation_tables.GOVINFO_PACKAGE``.  snake_case, like every
#: other enum value this column family publishes: the vocabulary is a public
#: contract, and one spelling settled before anything consumes it costs nothing
#: where moving it afterwards would need a behavior change to justify it.
BUDGET_VOLUME = "budget_volume"

BUDGET_VOLUMES = table_contract(
    "budget_volumes",
    grain="One row per published volume of the President's budget, with what its print adds to its own index.",
    identity=("package_id",),
    version_column="last_modified",
    key_spelling=VALUE_KEY,
    columns={
        "package_id": "The GovInfo package id, which is this row's identity.",
        "fiscal_year": (
            "The fiscal year this volume is the budget for, as the MODS states it in "
            '`field name="Fiscal Year"`, falling back to the year the package id itself carries where the '
            "MODS states none.  Not the year it was issued: BUDGET-2026-MSR was issued 2025-09-05."
        ),
        "part": (
            "Which part of the budget this volume is, in the publisher's own id spelling (`APP` for the "
            "Appendix, `MSR` for the Mid-Session Review).  The sealed vocabulary is in "
            "`sources/govinfo/bodies.py`'s package-id grammar, so a part no measurement has seen is a "
            "refusal rather than a row."
        ),
        "title": "The volume's title as the keyed summary states it.",
        "date_issued": "The date the package was issued, as the summary states it.",
        "last_modified": "When the publisher last modified the package; the merge prefers the larger value.",
        "stated_page_count": (
            "How many pages the volume has, as the keyed summary's own `pages` field states it -- never "
            "re-derived from the bytes, so a capped read reports how far it got beside the document's own "
            "extent rather than publishing its own count as the volume's."
        ),
        "associated_bill_count": "How many bills the MODS names; every one is in associated_bills_json.",
        "associated_bills_json": (
            "Every root-level `<bill>` the MODS names, as a JSON array of objects carrying the bill's "
            "natural key and the publisher's own `context` marker, in document order.  Published whole "
            "because it is the only statement of this edge that carries a Congress: a budget volume's print "
            "names a bill without one, so a printed key can be compared with these only congress-blind and "
            "can join `congress_bills` not at all."
        ),
        "associated_law_count": "How many laws the MODS names; every one is in associated_laws_json.",
        "associated_laws_json": (
            "Every root-level `<law>` the MODS names, as a JSON array of joined `laws` identities, in "
            "document order.  This is what distinct_laws_beyond_index is measured against."
        ),
        "associated_usc_section_count": (
            "How many U.S. Code sections the MODS names; every one is in associated_usc_sections_json."
        ),
        "associated_usc_sections_json": (
            "Every `<USCode>` *section* the MODS names, as a JSON array of objects carrying the "
            "`{title}-{section}` key and the publisher's own subsection detail, in document order.  A "
            "chapter-only or appendix-only block contributes nothing: neither is a section and neither has "
            "a hosted key."
        ),
        "associated_cfr_part_count": "How many CFR parts the MODS names; every one is in associated_cfr_parts_json.",
        "associated_cfr_parts_json": (
            "Every `<cfr>` part the MODS names, as a JSON array of `{title}-{part}` keys, in document "
            "order.  Budget volumes are the only sampled collection whose MODS states one at all."
        ),
        "associated_statute_count": (
            "How many Statutes at Large pages the MODS names; every one is in associated_statutes_json."
        ),
        "associated_statutes_json": (
            "Every `<statuteAtLarge>` page the MODS names, as a JSON array of `{volume}-{pages}` keys, in "
            "document order."
        ),
        "distinct_bills": (
            "How many distinct bills the print names, by the shared citation rules.  A floor bounded by "
            "pages_read, and **not a join key**: a budget volume states no Congress, so the rule leaves each "
            "one as the congress-free `HR7806` and `congress_bills.bill_id` cannot be built from it.  The "
            "MODS's own bill list, which does carry a Congress, is in associated_bills_json."
        ),
        "distinct_bills_beyond_index_congress_blind": (
            "How many of those the MODS does not state **with the Congress dropped from both sides** -- the "
            "only comparison this family supports, and the one the re-check made when it reported 6 "
            "print-only of 8 distinct across the eight sampled volumes at full page depth.  Named for what "
            "it is: a count, never a key, and weaker than every other `*_beyond_index` column here, because "
            "two measures numbered alike in different Congresses are one value.  The per-row "
            "`document_citations.stated_by_index` stays NULL for bills, because the strict comparison a row "
            "would have to claim still cannot be made."
        ),
        "distinct_laws": (
            "How many distinct public laws the print names, by the shared citation rules.  A floor, not a "
            "total: it counts what pages_read reached."
        ),
        "distinct_laws_beyond_index": (
            "How many of those the MODS does not already state.  This is the family's headline: 504 of 518 "
            "across the eight sampled volumes at full page depth, against 43 of 69 at the rollup's 60-page "
            "cap.  The per-row `document_citations.stated_by_index` carries the same comparison exactly; "
            "this column is its summary for one volume."
        ),
        "distinct_usc_sections": "How many distinct U.S. Code sections the print names; a floor bounded by pages_read.",
        "distinct_usc_sections_beyond_index": (
            "How many of those the MODS does not already state: 97 of 922 across the eight sampled volumes "
            "at full page depth.  The MODS states far more than the print here, which is the do-not-recreate "
            "rule working in the other direction."
        ),
        "distinct_cfr_parts": "How many distinct CFR parts the print names; a floor bounded by pages_read.",
        "distinct_cfr_parts_beyond_index": (
            "How many of those the MODS does not already state: 13 of 18 across the eight sampled volumes at "
            "full page depth."
        ),
        "distinct_statutes": (
            "How many distinct Statutes at Large pages the print names; a floor bounded by pages_read."
        ),
        "distinct_statutes_beyond_index": (
            "How many of those the MODS does not already state: 1 of 81 across the eight sampled volumes at "
            "full page depth, which is why this kind carries no contract of its own."
        ),
        "citation_rows": "How many citation rows this volume produced, across every kind.",
        "pages_read": (
            "How many pages the extraction actually read, which a capped read makes smaller than stated_page_count."
        ),
        "pages_capped": (
            "Whether the read stopped short of the volume, so every count above is a floor.  NULL where "
            "the read states no page split or the publisher states no numeric extent."
        ),
        "body_rendition": (
            "Which rendition the text was derived from.  `pdf` here because the acquirer is asked for "
            "`sources.govinfo.bodies.PRINT_BODY_PREFERENCE` -- the sealed order with PDF first, for the "
            "families whose contracts publish a page -- and **not** because PDF is all a budget volume "
            "offers.  A package-root format refusal on this family is the publisher's answer, not a missing "
            "volume: 4 of the 13 measured parts state no PDF at the package root (one id per part, measured "
            "2026-09-20).  `TAB`, `DB` and `CLIMATE` state theirs inside a constituent record at a *granule* "
            "stem (`pdf/BUDGET-2027-TAB-1.pdf`), which `acquire_granule` reaches and the package locator does "
            "not derive; `LRB` states one XLS and no body rendition at all.  A `published/BUDGET` walk that "
            "meets `GovInfoFormatNotOfferedError` on one of those has found that shape."
        ),
        "body_derivation": "How that rendition became text.",
        "text_sha256": "Digest of the normalized text the citation spans index into.",
        "rule_set_version": (
            "Digest over every citation rule's name, version, pattern and rejects, so these counts name the "
            "rules that produced them."
        ),
    },
)


def budget_index_stated_keys(mods: object) -> dict[str, frozenset[str]]:
    """The MODS keys a budget volume's print can actually be compared against.

    :func:`~spicy_docs.schemas.document_citation_tables.index_stated_keys` minus ``bill_number``: that mapping's
    contract is that a kind is present when the comparison can be made and absent when it cannot, so the dropped kind
    lands NULL rather than ``false`` instead of claiming a comparison that never ran.
    """
    stated = dict(index_stated_keys(mods))
    del stated["bill_number"]
    return stated


def congress_blind_bill_keys(mods: object) -> frozenset[str]:
    """The MODS's bills reduced to the Congress-less spelling the print side produces, so ``hr-7806`` meets ``HR7806``.

    The index side is reduced rather than the print re-parsed, because this module is a stdlib-only leaf and must not
    learn the bill-type vocabulary a second time; it is the same reduction the re-check compared on.
    """
    return frozenset(pair.replace("-", "").upper() for pair in index_stated_bill_pairs(mods))


def shape_budget_volume(
    summary: object,
    mods: object,
    body: object,
    citations: Sequence[object],
    *,
    rule_set_version: str,
) -> Row:
    """One ``budget_volumes`` row from the keyed summary and MODS, the body text and its citation findings, all read
    structurally and nothing fetched.

    The fiscal year is the MODS's own labelled statement where it makes one and the package id's otherwise (the two
    agreed on every volume measured, and a test holds them equal on both fixtures rather than trusting one).
    """
    identity = summary.identity
    provenance = document_provenance(body, document_key=identity.package_id, document_kind=BUDGET_VOLUME)
    stated = budget_index_stated_keys(mods)
    bills = distinct_targets(citations, "bill_number")
    laws = distinct_targets(citations, "public_law")
    sections = distinct_targets(citations, "usc_section")
    parts = distinct_targets(citations, "cfr_section")
    statutes = distinct_targets(citations, "statutes_at_large")
    pages_read, page_count, capped = read_depth(body, summary)
    return {
        "package_id": text(identity.package_id),
        "fiscal_year": text(getattr(mods, "fiscal_year", None) or identity.fiscal_year),
        "part": text(identity.document_type),
        "title": text(summary.title),
        "date_issued": text(summary.date_issued),
        "last_modified": text(summary.last_modified),
        "stated_page_count": text(page_count),
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
        "associated_cfr_part_count": text(len(mods.cfr_parts)),
        "associated_cfr_parts_json": json_column([f"{part.title}-{part.part}" for part in mods.cfr_parts]),
        "associated_statute_count": text(len(mods.statutes)),
        "associated_statutes_json": json_column([f"{s.volume}-{s.pages}" for s in mods.statutes]),
        "distinct_bills": text(len(bills)),
        "distinct_bills_beyond_index_congress_blind": text(len(bills - congress_blind_bill_keys(mods))),
        "distinct_laws": text(len(laws)),
        "distinct_laws_beyond_index": text(len(laws - stated["public_law"])),
        "distinct_usc_sections": text(len(sections)),
        "distinct_usc_sections_beyond_index": text(len(sections - stated["usc_section"])),
        "distinct_cfr_parts": text(len(parts)),
        "distinct_cfr_parts_beyond_index": text(len(parts - stated["cfr_section"])),
        "distinct_statutes": text(len(statutes)),
        "distinct_statutes_beyond_index": text(len(statutes - stated["statutes_at_large"])),
        "citation_rows": text(len(citations)),
        "pages_read": text(pages_read),
        "pages_capped": flag(capped),
        "body_rendition": text(provenance.body_rendition),
        "body_derivation": text(provenance.body_derivation),
        "text_sha256": text(provenance.text_sha256),
        "rule_set_version": text(rule_set_version),
    }


__all__ = [
    "BUDGET_VOLUME",
    "BUDGET_VOLUMES",
    "budget_index_stated_keys",
    "congress_blind_bill_keys",
    "shape_budget_volume",
]
