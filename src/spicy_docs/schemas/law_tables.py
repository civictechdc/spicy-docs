"""The ``laws`` table (Congress.gov law list rows joined to their PLAW USLM citation), ``law_code_sections`` (OLRC
per-Congress classification lines) and ``table3_records`` (OLRC Table III records), closing gap A8.

``laws`` keys ``(congress, law_type, number)`` with ``law_type`` sealed to ``public``/``private`` so the list route, the
bulk folder and the USLM file share one key; ``law_code_sections`` keys on position because the same line can appear
twice on one page.  ``congress_bills.statutes_at_large_cite`` stays NULL on purpose: the citation lives in the PLAW USLM
the laws rollup acquires once per law, so the host joins ``laws`` on ``bill_id`` at merge time.

Both OLRC tables append ``usc_section_key``, the printed ``usc_section`` folded by ``tables.usc_section_key``, so a
key folded the same way (``31-5318a``) meets a row printed ``5318A``.  The citation side is not folded yet:
``document_citations``' ``usc_section`` rule 001 keeps the printed case, so a consumer folds it through the same helper
until B4's grammar, which lower-cases and adopts the helper, lands.  The key is last on
purpose: spicy-regs' ``merge_contract_table`` re-reads the contract, and its ``merge_table`` selects a column a prior
Parquet file lacks as ``CAST(NULL AS VARCHAR)`` (``test_merge_null_fills_columns_the_prior_table_lacks``), so rows
published before the column carry NULL until their scope is captured again.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from spicy_docs.schemas.tables import Row, TableContractError, natural_key, table_contract, text, usc_section_key

#: The Statutes at Large citation as the PLAW USLM ``citableAs`` spells it,
#: the rule the legislative data map's ``plaw→statute`` edge proved.
STAT_CITE = re.compile(r"(?P<volume>[0-9]+) Stat\. (?P<page>[0-9]+)")
_LAW_NUMBER = re.compile(r"(?P<congress>[1-9][0-9]{0,2})-(?P<number>[1-9][0-9]*)")
#: The PLAW bulkdata file grammar (``PLAW-119publ1.xml``), measured over every
#: file in the 119th's folders; the package id is the stem.
_PACKAGE_KINDS = {"public": "publ", "private": "pvtl"}
USLM_OUTCOMES = ("captured", "unavailable", "not_requested")

#: Both OLRC tables' appended join key, described once.
_USC_SECTION_KEY = (
    "usc_section as a join key: lower-cased, with every dash spelling an ASCII hyphen, as RefSpec's section oracle "
    "keys it. Fold the other side the same way (schemas.tables.usc_section_key): document_citations' usc_section rule "
    "001 keeps the printed case and dashes. NULL where usc_section is, and on rows published before the column existed."
)

LAWS = table_contract(
    "laws",
    grain="One row per enacted law the Congress.gov law list route states, with its PLAW USLM citation where captured.",
    identity=("congress", "law_type", "number"),
    version_column="update_date",
    columns={
        "law_id": "Natural key: congress, law_type and number joined with hyphens.",
        "congress": "The numbered Congress that enacted the law.",
        "law_type": (
            "`public` or `private`: the publisher's Public Law or Private Law folded onto the spelling the "
            "PLAW USLM publicPrivate field uses, so the list route, the bulk folder and the USLM file share one key."
        ),
        "number": "The law's number within its Congress and type, without the Congress prefix.",
        "law_number": "The publisher's own spelling of the number, Congress prefix included.",
        "publisher_law_type": "The publisher's laws[].type exactly as spelled (Public Law or Private Law).",
        "package_id": "The GovInfo PLAW package id by the measured bulk-file rule: `PLAW-` plus congress, publ or pvtl, and number.",
        "bill_id": "Natural key of the measure this law enacted, as congress_bills keys it.",
        "bill_type": "The enacted measure's type, lowercased as the bill tables spell it.",
        "bill_number": "The enacted measure's number.",
        "title": "The measure's title as the list route states it.",
        "origin_chamber": "The chamber the measure originated in, as the publisher states it.",
        "origin_chamber_code": "The publisher's one-letter origin chamber code.",
        "latest_action_date": "Date of the publisher's latestAction entry, which for a law is the became-law action.",
        "latest_action_text": "Text of that latestAction entry.",
        "update_date": "The publisher's updateDate on the list row; the merge prefers the larger value.",
        "update_date_including_text": "The publisher's updateDateIncludingText on the list row.",
        "url": "The publisher's own URL for the enacted measure.",
        "statutes_at_large_cite": (
            "The Statutes at Large citation the PLAW USLM meta states in citableAs, spelled NNN Stat. NNN; "
            "NULL exactly when uslm_outcome is not `captured` (the bulk folder lags the list route by several "
            "laws). A captured file whose citableAs names no such citation is refused, never published here as NULL."
        ),
        "statutes_at_large_volume": "The volume part of that citation.",
        "statutes_at_large_page": "The page part of that citation.",
        "approved_date": "The USLM meta's approvedDate, where the PLAW was captured.",
        "uslm_title": "The USLM meta's dc:title, where the PLAW was captured.",
        "uslm_processed_date": "The USLM meta's processedDate, where the PLAW was captured.",
        "uslm_sha256": "Digest of the captured PLAW USLM bytes, so the citation is traceable to one file.",
        "uslm_observed_at": "When the PLAW USLM was captured.",
        "uslm_outcome": (
            "`captured`, `unavailable` (the law's PLAW was absent from the bulkdata folder on the measured day: "
            "the bulk lag) or `not_requested`; a NULL citation is read through this column, never as absence."
        ),
    },
)

LAW_CODE_SECTIONS = table_contract(
    "law_code_sections",
    grain="One row per line of one OLRC per-Congress classification table: a Code place one public law section touched.",
    identity=("congress", "session", "seq"),
    version_column="observed_at",
    columns={
        "congress": "The Congress the table page states in its caption.",
        "session": "The session (1 or 2) the table page states in its caption.",
        "seq": "Zero-based position of this line in the page; part of the identity because one line can repeat.",
        "law_id": "Natural key of the law, as laws keys it.",
        "law_number": "The public law number as the table prints it, Congress prefix included.",
        "law_type": "Always `public`: the page is the publisher's table for public laws.",
        "number": "The law's number within its Congress.",
        "usc_title": "The U.S. Code title as printed; a trailing A means the title's appendix, per the page's legend.",
        "usc_section": "The U.S. Code section as printed.",
        "action": (
            "Column 3 verbatim (nt, new, nt new, nt [tbl], prec, fr, to, gen amd, omitted, repealed, ed chg); "
            "NULL where the page left it blank, which the page's legend reads as amended."
        ),
        "act_section": "The law's own section that did it, as printed; a quoted item after it names a new section.",
        "statutes_at_large_volume": "The volume the page's column header names.",
        "statutes_at_large_page": "The page as printed: one page, or a span such as two pages joined by a comma or a dash.",
        "link_volume": "The volume in the row's statviewer link, where the row carries one.",
        "link_page": "The page in the row's statviewer link, where the row carries one.",
        "table_order": "Which of the publisher's two orders the page is: `public-law` or `code`; both hold the same lines.",
        "stated_laws": "The law range the page's caption states it covers, verbatim.",
        "prepared_date": "The date the page states it was prepared.",
        "observed_at": "When the page was captured; the merge prefers the larger value.",
        "usc_section_key": _USC_SECTION_KEY,
    },
)

TABLE3_RECORDS = table_contract(
    "table3_records",
    grain="One row per classification record on one act's OLRC Table III page.",
    identity=("act_key", "seq"),
    version_column="observed_at",
    columns={
        "act_key": "The act key requested: a public law number, or a pre-1957 session-law chapter.",
        "stated_key": "The act key as the page itself states it, en dash and all.",
        "seq": "Zero-based position of this record on the page.",
        "congress": "The Congress the page states for the act.",
        "act_date": "The act's date as the page states it.",
        "statutes_at_large_volume": "The volume the page states for the act.",
        "release_point": "The currency the page states in its Table III Tool banner.",
        "act_section": "The act section this record classifies.",
        "record_volume": "The volume in this record's own statviewer link, where it carries one.",
        "record_page": "The Statutes at Large page for this record.",
        "usc_title": "The Code title the section went to; NULL where it went nowhere.",
        "usc_section": "The Code section the section went to; NULL where it went nowhere.",
        "status": "The page's status column for the record (repealed, omitted, and the like).",
        "observed_at": "When the page was captured; the merge prefers the larger value.",
        "usc_section_key": _USC_SECTION_KEY,
    },
)


def _law_type(publisher_type: object) -> str:
    if not isinstance(publisher_type, str):
        raise TableContractError("laws: a laws[] entry needs a string type")
    lowered = publisher_type.lower()
    if "private" in lowered:
        return "private"
    if "public" in lowered:
        return "public"
    raise TableContractError(f"laws: unknown law type {publisher_type!r}")


def law_id(congress: object, law_type: str, number: object) -> str:
    return natural_key(congress, law_type, number)


def _split_law_number(law_number: object, congress: object) -> str:
    match = _LAW_NUMBER.fullmatch(str(law_number))
    if match is None:
        raise TableContractError(f"laws: law number {law_number!r} is not congress-number")
    if match["congress"] != str(congress):
        raise TableContractError(f"laws: law number {law_number!r} names another Congress than {congress}")
    return match["number"]


def _stat_cite(citable_as: tuple[str, ...]) -> tuple[str, str, str]:
    """``(cite, volume, page)`` from the first ``NNN Stat. NNN`` in ``citableAs``; none is a refusal.

    ``captured`` promises a citation: a validated PLAW whose meta names none
    would otherwise publish a NULL that reads as the bulk lag. The pattern is
    the one the legislative data map proved on one law (119-1); it has not
    been surveyed across the 104 captured PLAWs of the 119th, so a refusal
    here in production is an assumption held, not a corruption found.
    """
    for citation in citable_as:
        match = STAT_CITE.fullmatch(citation.strip())
        if match is not None:
            return match[0], match["volume"], match["page"]
    raise TableContractError(f"laws: the USLM meta's citableAs {citable_as!r} names no Statutes at Large citation")


def shape_law(
    record: Mapping[str, Any],
    law: Mapping[str, Any],
    *,
    uslm: object | None = None,
    uslm_sha256: str | None = None,
    uslm_observed_at: str | None = None,
    uslm_outcome: str = "not_requested",
) -> Row:
    """One ``laws`` row from one law list record and one of its ``laws[]`` entries.

    ``uslm`` is given exactly when ``uslm_outcome`` is ``captured``; its own congress, kind and number must agree with
    the row or the join is refused, so a citation can never land on the wrong law.
    """
    if uslm_outcome not in USLM_OUTCOMES:
        raise TableContractError(f"laws: uslm_outcome must be one of {USLM_OUTCOMES}")
    if (uslm is not None) != (uslm_outcome == "captured"):
        raise TableContractError("laws: uslm is given exactly when uslm_outcome is captured")
    congress = record.get("congress")
    law_type = _law_type(law.get("type"))
    number = _split_law_number(law.get("number"), congress)
    latest = record.get("latestAction")
    latest = latest if isinstance(latest, Mapping) else {}
    bill_type = record.get("type")
    cite = volume = page = None
    if uslm is not None:
        stated = (str(uslm.congress), uslm.public_private, str(uslm.doc_number))
        if stated != (str(congress), law_type, number):
            raise TableContractError(f"laws: USLM meta states {stated}, not {(str(congress), law_type, number)}")
        cite, volume, page = _stat_cite(uslm.citable_as)
    return {
        "law_id": law_id(congress, law_type, number),
        "congress": text(congress),
        "law_type": law_type,
        "number": number,
        "law_number": text(law.get("number")),
        "publisher_law_type": text(law.get("type")),
        "package_id": f"PLAW-{congress}{_PACKAGE_KINDS[law_type]}{number}",
        "bill_id": natural_key(congress, bill_type, record.get("number")),
        "bill_type": None if bill_type is None else str(bill_type).lower(),
        "bill_number": text(record.get("number")),
        "title": text(record.get("title")),
        "origin_chamber": text(record.get("originChamber")),
        "origin_chamber_code": text(record.get("originChamberCode")),
        "latest_action_date": text(latest.get("actionDate")),
        "latest_action_text": text(latest.get("text")),
        "update_date": text(record.get("updateDate")),
        "update_date_including_text": text(record.get("updateDateIncludingText")),
        "url": text(record.get("url")),
        "statutes_at_large_cite": cite,
        "statutes_at_large_volume": volume,
        "statutes_at_large_page": page,
        "approved_date": None if uslm is None else text(uslm.approved_date),
        "uslm_title": None if uslm is None else text(uslm.title),
        "uslm_processed_date": None if uslm is None else text(uslm.processed_date),
        "uslm_sha256": text(uslm_sha256),
        "uslm_observed_at": text(uslm_observed_at),
        "uslm_outcome": uslm_outcome,
    }


def shape_law_code_section(record: object, *, table: object, observed_at: str) -> Row:
    """One ``law_code_sections`` row from one ``ClassificationRecord`` on its ``ClassificationTable``."""
    number = _split_law_number(record.law_number, table.congress)
    return {
        "congress": text(table.congress),
        "session": text(table.session),
        "seq": text(record.seq),
        "law_id": law_id(table.congress, "public", number),
        "law_number": text(record.law_number),
        "law_type": "public",
        "number": number,
        "usc_title": text(record.usc_title),
        "usc_section": text(record.usc_section),
        "action": text(record.description),
        "act_section": text(record.act_section),
        "statutes_at_large_volume": text(table.statutes_at_large_volume),
        "statutes_at_large_page": text(record.statutes_at_large_page),
        "link_volume": text(record.link_volume),
        "link_page": text(record.link_page),
        "table_order": text(table.order),
        "stated_laws": text(table.stated_laws),
        "prepared_date": text(table.prepared_date),
        "observed_at": text(observed_at),
        "usc_section_key": usc_section_key(record.usc_section),
    }


def shape_table3_record(record: object, *, page: object, seq: int, observed_at: str) -> Row:
    """One ``table3_records`` row from one ``Table3Record`` on its ``Table3Page``."""
    return {
        "act_key": text(page.key),
        "stated_key": text(page.stated_key),
        "seq": text(seq),
        "congress": text(page.congress),
        "act_date": text(page.act_date),
        "statutes_at_large_volume": text(page.statutes_at_large_volume),
        "release_point": text(page.release_point),
        "act_section": text(record.act_section),
        "record_volume": text(record.statutes_at_large_volume),
        "record_page": text(record.statutes_at_large_page),
        "usc_title": text(record.usc_title),
        "usc_section": text(record.usc_section),
        "status": text(record.status),
        "observed_at": text(observed_at),
        "usc_section_key": usc_section_key(record.usc_section),
    }


__all__ = [
    "LAWS",
    "LAW_CODE_SECTIONS",
    "STAT_CITE",
    "TABLE3_RECORDS",
    "USLM_OUTCOMES",
    "law_id",
    "shape_law",
    "shape_law_code_section",
    "shape_table3_record",
]
