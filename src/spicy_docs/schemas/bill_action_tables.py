"""What a committee print says happened to a bill, hosted with its measured reliability.

One table. It exists because of a finding that ran the other way from the one
first reported, and the finding is the contract's whole justification, so it is
stated here before the columns.

**The publisher's action-code table has no House hearing or markup code.**
``tests/fixtures/billstatus_codes/guide-2026-08-03.md`` section 3, *Action Code
Element Possible Values*, is the ``<actionCode>`` vocabulary. Its only hearing
and markup entries are ``13100`` *Senate committee/subcommittee hearings* and
``13200`` *Senate committee/subcommittee markups*. There is no House
counterpart to either. So when a House committee's activity report says *"On
June 14, 2023, the Subcommittee on Health held a hearing on H.R. 2365"*, the
print's sentence is **the only structured statement of that event** -- and
hearings and markups are the two largest phrasings in the measured corpus, 420
and 219 rows of 4,456.

The first version of this measurement claimed the opposite, citing codes 72
*Hearing held in House* and 74 *Markup in House*. Those are **section 5**
values -- the mapping of LOC *summaries* version codes to ``<actionDesc>``
text, the ``<versionCode>`` child of ``<summaries>`` -- and not action codes at
all. The self-check that should have caught it scanned the whole guide and so
validated against a 123-code superset drawn from three tables; it could not
fail. ``interpretation/bill_actions.py`` carries the corrected mapping and
``tests/test_bill_actions.py`` scopes the check to section 3 and asserts the
section-5 codes are absent from it.

**What the rows are worth, measured, both directions.** From 60 hand-checked
mentions over the eight retained prints
(``docs/research/bill-action-relationship-2026-09-20.md``):

* **83.3%** of published rows in the single-bill class are both the right kind
  and the right bill (30 of 36). **50%** in the multi-bill class (2 of 4).
* **91.8%** of rows (4,089 of 4,456) are single-bill, so a consumer restricting
  to the trusted class gives up 8% of the volume.
* **Recall is a separate axis and is 59.6%** of what a reader sees stated in
  the entry. This table's precision figure is a statement about *what is
  published*, never about what the document contains. A consumer counting
  hearings from these rows is counting a floor.

``attachment_confidence`` is the filter that makes the first figure usable:
``WHERE attachment_confidence = 'single'`` is the hosted-quality subset, and
the multi-bill rows stay in the table as evidence to verify rather than being
dropped, because a dropped row is a fact nobody can check.

The rules are ``interpretation/bill_actions.py``'s, which
``tools/analysis/bill_action_relationship.py`` runs too, so the measurement and
this contract cannot disagree about what a markup looks like.
"""

from __future__ import annotations

from spicy_docs.schemas.tables import Row, joined, table_contract, text

#: The sealed rungs a print phrasing can resolve to are ``bill_stage``'s, and
#: ``sealed_stage`` is NULL for every phrasing none of its matchers reads --
#: 1,670 of 4,456 rows. That NULL is the print register, kept as a fact rather
#: than closed by widening ``STAGE_RULES``, which would make one sealed rule
#: set read two publishers' prose.
BILL_COMMITTEE_ACTIONS = table_contract(
    "bill_committee_actions",
    grain=(
        "One row per action phrase a committee print states about one bill it names in the same sentence: "
        "the print's own phrasing, what it maps to, and how reliable the pairing is."
    ),
    identity=("document_key", "text_sha256", "bill_id", "print_phrasing", "span_start"),
    version_column="rule_set_version",
    columns={
        "document_key": (
            "The stating document's own natural key in its family's spelling; the GovInfo `packageId` for a "
            "package.  Spelled exactly as `document_citations.document_key`, so the two tables join."
        ),
        "document_kind": "Which family the stating document belongs to, so one table serves all of them.",
        "bill_id": (
            "`congress_bills.bill_id` for the measure this action is attached to, in the citation rule's own "
            "spelling.  The Congress is the document's, because a print writes `H.R. 1093` and never a "
            "Congress; `house_activity_reports.bills_congress_mismatch` is what makes that assumption "
            "checkable, and it is measured zero on both fixture packages."
        ),
        "print_phrasing": (
            "What the print wrote, from the sealed additions-only vocabulary in "
            "`interpretation.bill_actions.PRINT_ACTION_RULES` -- `held_hearing`, `ordered_reported`, "
            "`favorably_forwarded`, `declined_markup` and 21 others.  It names the *phrasing*, never the "
            "legislative event: the event is `sealed_stage`, and a phrasing with no rung keeps its own name "
            "rather than being given an invented code.  Additions-only because this value is published: a "
            "renamed key rewrites rows that are already out."
        ),
        "span_start": (
            "Character offset of the **action phrase** in the document's normalized text, counted from zero, "
            "and part of the identity.  The phrase rather than the bill: one sentence states *signed by the "
            "President* and *became Public Law No: 118-83* about the same bill, which is two events' worth "
            "of evidence and two rows, and only the phrase offset tells them apart."
        ),
        "span_end": "Character offset just past the phrase, so `text[span_start:span_end]` is `matched_text`.",
        "matched_text": (
            "The exact characters the phrase rule matched, so a wrong row is readable without the document in "
            "hand.  The two measured classification failures both show up here: a `Pub. L.` cite naming the "
            "law a bill *amends*, and `reported to Congress` inside a bill's own subject matter."
        ),
        "mention_span_start": (
            "Character offset of the bill designator this phrase was attached to.  Equal to a "
            "`document_citations.span_start` for the same document and digest, which is how a consumer walks "
            "from an action to the citation row that found the bill."
        ),
        "mention_span_end": "Character offset just past that designator.",
        "sentence_start": (
            "Character offset the sentence this was read in begins at, so a consumer can re-read the whole "
            "clause and judge the row.  The sentence is the unit because the *entry* is not one: this family "
            "writes a bill's long title as its own sentence and the disposition as the fragment after it, and "
            "every committee sets an entry differently."
        ),
        "sentence_end": "Character offset just past that sentence.",
        "bills_in_sentence": (
            "How many distinct bills that sentence names.  **This is the reliability predicate**, published "
            "as the raw count so a consumer can set its own threshold rather than trusting a label: "
            "`attachment_confidence` is derived from it and nothing else."
        ),
        "attachment_confidence": (
            "`single` where the sentence names one bill and `multi` where it names several.  Measured joint "
            "precision -- right kind *and* right bill -- is **83.3% for `single`** (30 of 36 hand-checked) "
            "and **50% for `multi`** (2 of 4).  4,089 of 4,456 rows are `single`, so "
            "`WHERE attachment_confidence = 'single'` is the hosted-quality subset at an 8% cost in volume.  "
            "`multi` rows are kept rather than dropped because a coin-flip row a consumer can see and verify "
            "is worth more than a fact nobody can check."
        ),
        "sealed_stage": (
            "The rung of `interpretation.bill_stage`'s sealed seven-rung ladder this phrase resolves to, or "
            "NULL.  Derived by running the matched phrase through `infer_stage_from_text`, never asserted "
            "beside it.  NULL on 1,670 of 4,456 rows and that is a finding, not a gap: the print's register "
            "is not BILLSTATUS's.  `passed the House` is the sharpest case -- the sealed matcher is "
            "`passed house`, one word away -- and it is recorded NULL rather than closed by widening the "
            "sealed matcher list."
        ),
        "sealed_stage_matcher": (
            "The exact matcher string inside that rung's rule that fired, so the mapping is auditable rather "
            "than trusted; NULL wherever `sealed_stage` is."
        ),
        "billstatus_action_code": (
            "The `<actionCode>` values the publisher's own BILLSTATUS guide (section 3) gives for this "
            "phrasing in this row's chamber, joined; NULL where the publisher has none.  **NULL does not mean "
            "the print is unmapped.** For a House committee's hearing or markup it means the publisher has no "
            "code at all: section 3's only hearing and markup codes are `13100` and `13200`, both Senate, so "
            "for those two events -- 639 of 4,456 rows -- this print sentence is the only structured "
            "statement that exists.  NULL also on `favorably_forwarded`, `declined_markup`, `not_considered`, "
            "`included_in` and `vetoed`, 280 rows the guide's vocabulary has no entry for in either chamber."
        ),
        "chamber": (
            "Which chamber's vocabulary the codes were chosen from, read off the row and not off the "
            "document: a House committee's report states `the Senate passed H.R. 2365` and reports a Senate "
            "committee's action on a Senate bill, and both belong to the Senate side while sitting in a House "
            "print.  The phrase decides it where the phrase names a chamber, and the measure's own type "
            "otherwise."
        ),
        "stated_date": (
            "The first date the sentence states, ISO, or NULL.  **Unscored**: the dates are extracted and "
            "published, and whether this one belongs to *this* action rather than to a neighbouring clause "
            "was never hand-checked.  `stated_date_count` says when the sentence stated more than one, which "
            "is when the attribution is least safe."
        ),
        "stated_date_count": (
            "How many dates that sentence states.  Above one, `stated_date` is the first of several and a "
            "consumer wanting certainty re-reads the sentence at `sentence_start`."
        ),
        "evidence_page": (
            "The printed page the bill designator sits on, one-based, where the rendition states page "
            "boundaries; NULL where it states none."
        ),
        "rule_name": (
            "Which rule in `interpretation/bill_actions.py` fired.  Equal to `print_phrasing` today, and a "
            "separate column for the reason `document_citations.rule_name` is one: a phrasing can gain a "
            "second pattern and the row must then say which one read it."
        ),
        "rule_version": (
            "The phrasing vocabulary's own version, moved when a phrasing is appended.  Zero-padded decimal, "
            "because this column is compared as a string."
        ),
        "rule_set_version": (
            "Digest over every phrasing's name and pattern, so these rows name the rules that produced them "
            "even when someone forgets to move `rule_version`; the merge prefers the larger value."
        ),
        "citation_rule_version": (
            "The version of the `bill_number` citation rule that found the designator this row is attached "
            "to.  Two rule sets produced this row and a re-extraction can move either, so both are published."
        ),
        "body_rendition": "Which rendition the text was derived from (pdf, htm, xml, txt).",
        "body_derivation": (
            "How that rendition became text (`pdf-extraction-gpo-normalized` for a print), which is what the "
            "offsets are offsets into."
        ),
        "text_sha256": (
            "Digest of the normalized text every offset in this row indexes into, and part of the identity.  "
            "A span means nothing without it, and keying on it is what stops two extractions of one document "
            "from colliding on one identity and silently merging.  Append-only per digest, exactly as "
            "`document_citations` is."
        ),
    },
)


def shape_bill_committee_action(finding: object, provenance: object, *, citation_rule_version: str) -> Row:
    """One ``bill_committee_actions`` row from one ``BillActionFinding``.

    ``provenance`` is ``document_citation_tables.DocumentProvenance`` -- the
    same record the citation rows carry, so an action row and the citation row
    that found its bill agree on the document, the rendition and the digest by
    construction rather than by convention.  Both arguments are read by
    attribute, so this module stays the stdlib-only leaf ``schemas`` is.
    """
    dates = tuple(getattr(finding, "stated_dates", ()) or ())
    return {
        "document_key": text(provenance.document_key),
        "document_kind": text(provenance.document_kind),
        "bill_id": text(finding.bill_id),
        "print_phrasing": text(finding.phrasing),
        "span_start": text(finding.span_start),
        "span_end": text(finding.span_end),
        "matched_text": text(finding.matched_text),
        "mention_span_start": text(finding.mention_span_start),
        "mention_span_end": text(finding.mention_span_end),
        "sentence_start": text(finding.sentence_start),
        "sentence_end": text(finding.sentence_end),
        "bills_in_sentence": text(finding.bills_in_sentence),
        "attachment_confidence": text(finding.attachment),
        "sealed_stage": text(finding.stage),
        "sealed_stage_matcher": text(finding.stage_matcher),
        # Joined rather than a JSON array: the guide gives at most three codes
        # for one phrasing in one chamber and a consumer filters on membership,
        # which `joined` supports and a JSON string does not.
        "billstatus_action_code": joined(finding.billstatus_action_codes),
        "chamber": text(finding.chamber),
        "stated_date": text(dates[0] if dates else None),
        "stated_date_count": text(len(dates)),
        "evidence_page": text(finding.page),
        "rule_name": text(finding.phrasing),
        "rule_version": text(finding.rule_version),
        "rule_set_version": text(finding.rule_set_version),
        "citation_rule_version": text(citation_rule_version),
        "body_rendition": text(provenance.body_rendition),
        "body_derivation": text(provenance.body_derivation),
        "text_sha256": text(provenance.text_sha256),
    }


__all__ = ["BILL_COMMITTEE_ACTIONS", "shape_bill_committee_action"]
