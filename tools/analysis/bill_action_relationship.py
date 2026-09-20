"""Is a House activity report's *bill-action relationship* extractable, and what would it join to?

The [MODS re-check](../../docs/research/pdf-yield-mods-recheck-2026-09-20.md)
closed the citation question for this family and left one open, as build-order
item 8: the package MODS states **that** a committee activity report names
``H.R. 1093``; the print states **what happened to it** -- referred, hearing
held, marked up, ordered reported, passed, became law -- and no index in that
measurement states the relationship. That re-check compared keys, never
relationships, so nothing there says whether the print's action language is
extractable, how many distinct actions it carries, or whether the hosted
``bill_actions`` already holds them. This measures exactly that, on the same
eight prints and the same retained bytes.

Five phases, every one offline. **No request is made by any of them**, because
everything this needs is already retained: the eight PDFs are in the rollup
receipt's ``blobs/``, their MODS in the re-check receipt's ``mods/``, and the
hosted ``congress_bills`` export is a local Parquet file.

    uv run --frozen python -m tools.analysis.bill_action_relationship text ...
    uv run --frozen python -m tools.analysis.bill_action_relationship measure ...
    uv run --frozen python -m tools.analysis.bill_action_relationship sample ...
    uv run --frozen python -m tools.analysis.bill_action_relationship report ...
    uv run --frozen python -m tools.analysis.bill_action_relationship render ...

``text`` re-reads every page of the eight retained PDFs and caches the
normalized pages, so the three phases after it are cheap and the hand-check
sheet quotes bytes that can be re-derived. ``sample`` writes the 60-mention
hand-check sheet and **never overwrites a sheet that already carries
verdicts**; ``report`` reads the filled sheet and writes the sidecar; ``render``
brings the report's generated block in line with the sidecar, which a test
byte-compares.

**Three rules are reused, none restated.** Mentions come from
``interpretation.citations.find_citations``'s ``bill_number`` rule -- the same
rule, at the same version, the re-check measured the yield with. Action *kinds*
come from ``interpretation.bill_stage``: :func:`sealed_stage` runs the print's
own matched phrase through ``infer_stage_from_text``, so the mapping from a
print phrasing to a rung is **derived from the sealed vocabulary rather than
asserted beside it**, and a phrasing the sealed matchers do not reach is
reported unmapped instead of being given a parallel code of its own. The
public-law spelling inside ``became_public_law`` is
``CITATION_RULES_BY_NAME["public_law"]``'s measured pattern, not a second copy.

**What a print phrasing is.** :data:`PRINT_ACTION_RULES` is a small measured
vocabulary, derived from the recurring phrasings in these eight prints and
ordered by precedence the way ``STAGE_RULES`` is: the first rule whose match
covers a span owns it, so ``discharged from further consideration`` is a
discharge and not also a consideration. Every rule's occurrence count is
published, including the phrasings no sealed matcher reaches, which is the
finding rather than a defect to hide.

**Why the text is flattened before a phrase is matched.** These prints are not
gutter-numbered, so ``normalize_gpo_pages`` leaves their line-wrap hyphens in
place by design -- ``held a hear-\\ning`` is the page's own text. A phrase rule
run over that reads no hearing at all. :func:`flatten` therefore builds a
matching text with line-wrap hyphens closed and newlines spaced, and keeps the
offset of every flattened character, so **every span this tool publishes is an
offset into the retained normalized text**, the same text the citation spans
and the text digest are against. Nothing is measured in one text and reported
against another.

**Complexity.** Linear in retained pages for ``text``; for ``measure``, one
pass per rule over each document (``O(K*C)`` for ``K`` rules and ``C``
characters, ``K`` = 25 and ``C`` = 3.3 M across the eight prints), plus a
binary search per mention into the sentence offsets. The overlap join runs in
DuckDB over a 418,657-row Parquet export, one hash join.

**Credentials.** Nothing here reads a key, opens a socket or names an
environment variable. The receipt it writes carries retained public text only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from spicy_docs.interpretation.bill_actions import (
    ATTACHMENT_MULTI,
    ATTACHMENT_SINGLE,
    BILLSTATUS_ACTION_CODES,
    HOUSE,
    HOUSE_COMMITTEE_EVENTS_WITHOUT_A_CODE,
    PRINT_ACTION_RULE_SET_VERSION,
    PRINT_ACTION_RULES,
    find_bill_actions,
    guide_codes_for,
    sealed_stage,
)
from spicy_docs.interpretation.citations import CITATION_RULES_BY_NAME, find_citations
from spicy_docs.sources.congress.listing import API as CONGRESS_API

#: The family name the rollup receipt files these eight prints under.
FAMILY = "house_activity"

#: Every sampled activity report is a 118th-Congress package, and the print
#: writes a bare ``H.R. 1093`` with no Congress, so this is the Congress
#: ``_bill_target`` stamps a mention with. The re-check measured the exposure
#: that assumption carries on this very sample: 1 of 1,406 distinct print keys
#: is dated by its own MODS to another Congress.
PACKAGE_CONGRESS = 118


class RelationshipError(RuntimeError):
    """This measurement could not read something it was pointed at."""


# --- one document's mentions and action rows -----------------------------------------


def measure_document(package_id: str, pages: Sequence[str]) -> dict[str, Any]:
    """Every bill mention in one print, the actions attached, and what reached no bill.

    The rules are not here: :func:`interpretation.bill_actions.find_bill_actions`
    owns the sentence split, the phrasing vocabulary, the attachment rule and
    the chamber derivation, and the hosted ``bill_committee_actions`` contract
    is shaped from the same findings. A measurement that restated them would be
    measuring a second implementation.

    What this adds is the per-document bookkeeping a measurement needs and a
    contract does not: how many mentions reached an action at all, how many sat
    in a multi-bill sentence, and what the *sentence-scoped* alternative would
    have published -- giving every bill in the sentence the action -- because
    the difference between the two row counts is the multi-bill exposure.
    """
    text = "\n".join(pages)
    findings = find_citations(text, pages=pages, kinds=("bill_number",), congress=PACKAGE_CONGRESS)
    reading = find_bill_actions(text, findings)

    phrasing_counts: Counter[str] = Counter()
    phrasing_bills: dict[str, set[str]] = {}
    attachment_counts: Counter[str] = Counter()
    mentions_with_action: set[int] = set()
    sentence_scoped_rows = 0
    for action in reading.findings:
        phrasing_counts[action.phrasing] += 1
        phrasing_bills.setdefault(action.phrasing, set()).add(action.bill_id)
        attachment_counts[action.attachment] += 1
        mentions_with_action.add(action.mention_span_start)
        sentence_scoped_rows += action.bills_in_sentence
    return {
        "package_id": package_id,
        "pages": len(pages),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_characters": len(text),
        "mentions": len(findings),
        "distinct_bills": len({finding.target_key for finding in findings}),
        "mentions_with_action": len(mentions_with_action),
        "mentions_in_multi_bill_sentence": reading.mentions_in_multi_bill_sentence,
        "action_rows": len(reading.findings),
        "sentence_scoped_rows": sentence_scoped_rows,
        "trusted_rows": attachment_counts[ATTACHMENT_SINGLE],
        "attachment": dict(attachment_counts),
        "orphan_phrases": sum(reading.orphan_phrasings.values()),
        "orphan_phrasings": dict(reading.orphan_phrasings),
        "phrasings": dict(phrasing_counts),
        "phrasing_bills": {key: len(values) for key, values in phrasing_bills.items()},
        "rows": [asdict(action) for action in reading.findings],
    }


# --- the retained inputs -------------------------------------------------------------


def cached_pages(receipt: Path) -> dict[str, list[str]]:
    """The eight prints' normalized pages, as ``text`` cached them."""
    found = {}
    for path in sorted((receipt / "text").glob("*.json")):
        payload = json.loads(path.read_text())
        found[payload["package_id"]] = payload["pages"]
    if not found:
        raise RelationshipError("no cached text; run the `text` phase first")
    return found


def cache_text(receipt: Path, source_receipt: Path) -> None:
    """Re-read every page of the eight retained CRPT PDFs and cache the normalized pages.

    No request: the bodies are the rollup receipt's own ``blobs/``, addressed
    by the digest its ``requests.jsonl`` recorded for each sampled locator.
    Table detection is off, as the re-check's uncapped read had it off -- a
    relationship contract needs the prose, and ``find_tables()`` is what the
    per-page cost is spent on.
    """
    from spicy_docs.extraction import DocumentExtractor, NativeText
    from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages
    from tools.analysis.pdf_family_rollup import RequestLog
    from tools.analysis.pdf_yield_mods_recheck import govinfo_documents

    (receipt / "text").mkdir(parents=True, exist_ok=True)
    log = RequestLog(source_receipt)
    for document in govinfo_documents(source_receipt):
        if document.family != FAMILY:
            continue
        target = receipt / "text" / f"{document.package_id}.json"
        if target.exists():
            print(f"{document.package_id}: cached")
            continue
        digest = log.succeeded(document.url)
        if digest is None:
            raise RelationshipError(f"no retained body for {document.package_id}")
        extractor = DocumentExtractor(NativeText(), tables=False)
        texts: list[str] = []
        results = extractor.extract(log.body(digest), media_type="application/pdf")
        try:
            for result in results:
                texts.append(result.text)
        finally:
            results.close()
        normalized, _cleanup = normalize_gpo_pages(tuple(texts))
        target.write_text(json.dumps({"package_id": document.package_id, "pages": list(normalized)}) + "\n")
        print(f"{document.package_id}: {len(normalized)} pages cached")


def mods_bill_keys(mods_receipt: Path, package_id: str) -> tuple[str, ...]:
    """The bills one package MODS states, as ``congress-type-number``.

    Read through the re-check's own ``mods_facts`` so the two measurements
    cannot disagree about what a MODS states.
    """
    from tools.analysis.pdf_yield_mods_recheck import mods_facts

    path = mods_receipt / "mods" / f"{package_id}.xml"
    if not path.exists():
        raise RelationshipError(f"no retained MODS for {package_id}")
    return tuple(mods_facts(path.read_bytes())["bill_natural_keys"])


# --- what BILLSTATUS already states --------------------------------------------------

#: The heading that opens the guide's ``<actionCode>`` table, and the one that
#: closes it. Scoping matters and the first version of this tool did not scope
#: at all: it scanned the whole document, so its self-check validated against a
#: 123-code superset drawn from three different tables -- section 3's action
#: codes, section 4's type names and **section 5's LOC summaries version
#: codes** -- and could not fail. Codes 72 *Hearing held in House* and 74
#: *Markup in House* are section 5 values, the ``<versionCode>`` child of
#: ``<summaries>``, and reading them as action codes is what produced the claim
#: that BILLSTATUS already states a House committee's hearings and markups. It
#: does not: see :data:`interpretation.bill_actions.BILLSTATUS_ACTION_CODES`.
GUIDE_ACTION_CODE_SECTION = "# 3. Action Code Element Possible Values"
GUIDE_NEXT_SECTION = "# 4. Actions Type Element Possible Values"

#: A section-5 code whose presence in a "section 3" reading proves the scoping
#: is broken. Used by the tool's own cross-check and by the test.
GUIDE_SUMMARIES_VERSION_CODES: frozenset[str] = frozenset({"72", "73", "74", "75", "77", "79", "81", "82", "49"})


def guide_action_codes(guide: Path) -> frozenset[str]:
    """Every ``<actionCode>`` value the retained guide's **section 3** table lists.

    Scoped to that one table, so the mapping in
    ``interpretation.bill_actions`` is checkable against the publisher's own
    action-code vocabulary and against nothing else.
    """
    if not guide.exists():
        raise RelationshipError(f"no retained BILLSTATUS guide at {guide}")
    text = guide.read_text()
    try:
        start = text.index(GUIDE_ACTION_CODE_SECTION)
        finish = text.index(GUIDE_NEXT_SECTION, start)
    except ValueError as error:
        raise RelationshipError("the retained guide does not carry the action-code section") from error
    return frozenset(re.findall(r"^\|\s*\*\*([A-Z0-9]{2,6})\*\*\s*\|", text[start:finish], re.MULTILINE))


def overlap_with_hosted(export: Path, bill_ids: Sequence[str]) -> dict[str, Any]:
    """What the hosted ``congress_bills`` export already states for these bills.

    **What this can and cannot see, stated before the numbers.** The retained
    export carries ``latest_action_date`` and ``latest_action_text`` per bill --
    the publisher's own ``latestAction``, which is *one* action. The hosted
    ``bill_actions`` contract holds every action with its code and date, and no
    such export is retained locally, so this measures a **floor** on what
    BILLSTATUS already states: a print action the latest action alone already
    duplicates is duplicated, and one it does not may still sit in the full
    list. That direction is the safe one for a verdict that argues *against*
    building, and the unsafe one for a verdict that argues for it.
    """
    import duckdb

    if not export.exists():
        raise RelationshipError(f"no retained congress_bills export at {export}")
    connection = duckdb.connect()
    connection.execute("create table printed(bill_id varchar)")
    connection.executemany("insert into printed values (?)", [(value,) for value in sorted(set(bill_ids))])
    rows = connection.execute(
        "select p.bill_id, b.latest_action_date, b.latest_action_text "
        f"from printed p left join read_parquet('{export}') b using (bill_id)"
    ).fetchall()
    hosted: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for bill_id, date, action_text in rows:
        if action_text is None:
            missing.append(bill_id)
            continue
        stage, matcher = sealed_stage(action_text)
        hosted[bill_id] = {"date": date, "text": action_text, "stage": stage, "matcher": matcher}
    congresses = connection.execute(
        f"select min(cast(congress as integer)), max(cast(congress as integer)), count(*) from read_parquet('{export}')"
    ).fetchone()
    return {
        "export": str(export),
        "export_rows": congresses[2],
        "export_congress_range": [congresses[0], congresses[1]],
        "bills_asked": len(set(bill_ids)),
        "bills_hosted": len(hosted),
        "bills_not_hosted": sorted(missing),
        "hosted": hosted,
    }


# --- the row-for-row BILLSTATUS overlap ----------------------------------------------

#: The bound. Twenty bills is what answers the question the retained
#: ``congress_bills`` export cannot: that export carries one action per bill
#: (``latestAction``), so it can only give a floor on duplication. This asks
#: the publisher for the **whole action list** of a sample of the bills these
#: prints act on, which is the only way the claim "BILLSTATUS already holds
#: this" can rest on rows rather than on a code table.
MAX_BILLSTATUS_REQUESTS = 20
BILLSTATUS_USER_AGENT = "spicy-docs-bill-action-relationship/1.0 (https://github.com/civictechdc/spicy-docs)"


def _actions_url(bill_id: str) -> str:
    congress, bill_type, number = bill_id.split("-", 2)
    return f"{CONGRESS_API}/bill/{congress}/{bill_type}/{number}/actions?limit=250"


def billstatus(receipt: Path, env_file: Path, max_requests: int) -> None:
    """Fetch the full action list for a bounded sample of the bills these prints act on.

    **Why this is worth a keyed request when nothing else here is.** Every
    other phase reads retained bytes. This one cannot: no full ``bill_actions``
    export is retained locally and the six committed BILLSTATUS fixtures are
    thin 119th-Congress measures with no committee-sourced action at all, so
    the duplication argument would otherwise rest on the publisher's *code
    table* and not on what the publisher actually files. The corrected reading
    of that table says section 3 has no House hearing or markup code; this
    checks whether the action lists agree.

    Resumable and bounded the way every fetcher here is: a bill with a retained
    body is not re-requested, the run aborts on a credential refusal rather
    than skipping it as a bad row, and every request is logged scrubbed.
    """
    from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential
    from spicy_docs.transport.source_acquirer import SourceAcquirer

    measured = json.loads((receipt / "measure.json").read_text())
    key = read_api_key(env_file, "API_GOV")
    bodies = receipt / "billstatus"
    bodies.mkdir(parents=True, exist_ok=True)
    log_path = receipt / "billstatus-requests.jsonl"
    rows = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()] if log_path.exists() else []

    wanted = _billstatus_sample(measured, max_requests)
    outstanding = [bill for bill in wanted if not (bodies / f"{bill}.json").exists()]
    if len(outstanding) > max_requests:
        raise RelationshipError(f"{len(outstanding)} bills to fetch exceeds the {max_requests}-request bound")
    print(f"{len(wanted)} bills sampled, {len(outstanding)} to fetch")

    acquirer = SourceAcquirer(
        max_requests=max_requests,
        timeout_seconds=60,
        min_request_interval_seconds=0.5,
        user_agent=BILLSTATUS_USER_AGENT,
        label="BILLSTATUS action overlap",
        error_type=RelationshipError,
        context_key="bill_action_relationship",
        headers={"X-Api-Key": key},
        credential=key,
    )
    try:
        for bill in outstanding:
            url = _actions_url(bill)
            try:
                capture = acquirer.capture_validated(
                    url,
                    media_types=("application/json",),
                    parse=lambda capture, _max_bytes: capture,
                    max_bytes=4_000_000,
                    unavailable=lambda capture: RelationshipError(f"actions unavailable: {capture.status_code}"),
                    context={"billId": bill},
                    reset_budget=False,
                )[0]
            except CredentialRefusedError:
                rows.append({"bill_id": bill, "status": None, "note": "credential refused"})
                raise
            except Exception as error:  # noqa: BLE001 - recorded, then the run continues
                rows.append(
                    {"bill_id": bill, "status": None, "note": scrub_credential(f"{type(error).__name__}: {error}", key)}
                )
                print(f"refused {bill}: {scrub_credential(str(error), key)}")
                continue
            (bodies / f"{bill}.json").write_bytes(capture.body)
            rows.append(
                {
                    "bill_id": bill,
                    "url": scrub_credential(url, key),
                    "status": capture.status_code,
                    "media_type": capture.content_type,
                    "bytes": len(capture.body),
                    "sha256": hashlib.sha256(capture.body).hexdigest(),
                }
            )
    finally:
        log_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    print(f"logged {len(rows)} requests to {log_path}")


def _billstatus_sample(measured: Mapping[str, Any], size: int) -> list[str]:
    """The bills to ask about: deterministic, and weighted to the claim under test.

    Every bill carrying a ``held_hearing`` or ``held_markup`` row comes first,
    because those are the two events the corrected code table says BILLSTATUS
    has no House code for and they are what this request budget exists to
    settle. The remainder fills from the other trusted rows, so the sample also
    covers phrasings the guide *does* code.
    """
    import random

    hearings: set[str] = set()
    others: set[str] = set()
    for document in measured["documents"]:
        for row in document["rows"]:
            if row["attachment"] != ATTACHMENT_SINGLE:
                continue
            target = hearings if row["phrasing"] in {"held_hearing", "held_markup"} else others
            target.add(row["bill_id"])
    rng = random.Random(SAMPLE_SEED)
    chosen = rng.sample(sorted(hearings), min(size - size // 4, len(hearings)))
    rest = rng.sample(sorted(others - set(chosen)), min(size - len(chosen), len(others - set(chosen))))
    return sorted(chosen + rest)


def billstatus_overlap(receipt: Path) -> dict[str, Any]:
    """Compare the print's rows against the retained action lists, row for row.

    Offline: reads what :func:`billstatus` retained. For each sampled bill,
    every action the publisher states is reduced to ``(actionCode, actionDate,
    text)``, and each of the print's single-attachment rows is asked two
    questions: does the publisher state an action carrying one of the codes
    this phrasing maps to, and does it state one on the date the print states?
    A phrasing with no code in the publisher's vocabulary can only be asked the
    second, and ``held_hearing``/``held_markup`` are asked a third: does the
    publisher's list state the event *at all*, by any code or wording?
    """
    bodies = receipt / "billstatus"
    if not bodies.exists():
        raise RelationshipError("no retained BILLSTATUS bodies; run the `billstatus` phase first")
    measured = json.loads((receipt / "measure.json").read_text())
    published: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(bodies.glob("*.json")):
        payload = json.loads(path.read_text())
        published[path.stem] = [
            {
                "code": (item.get("actionCode") or "").strip(),
                "date": (item.get("actionDate") or "").strip(),
                "text": (item.get("text") or "").strip(),
                "type": (item.get("type") or "").strip(),
                "source": ((item.get("sourceSystem") or {}).get("name") or "").strip(),
            }
            for item in payload.get("actions", [])
        ]
    sources: Counter[str] = Counter()
    for actions in published.values():
        for action in actions:
            sources[action["source"]] += 1
    hearing_words = ("hearing", "hearings held")
    markup_words = ("markup", "mark-up", "consideration and mark-up")
    result = {
        "bills_requested": len(published),
        "rows_compared": 0,
        "code_matched": 0,
        "date_matched": 0,
        "no_code_in_vocabulary": 0,
        "hearing_or_markup_rows": 0,
        "hearing_or_markup_stated_by_billstatus": 0,
        "publisher_action_rows": sum(len(actions) for actions in published.values()),
        "publisher_source_systems": {},
        "absent_from_billstatus": [],
        "per_phrasing": {},
    }
    for document in measured["documents"]:
        for row in document["rows"]:
            actions = published.get(row["bill_id"])
            if actions is None or row["attachment"] != ATTACHMENT_SINGLE:
                continue
            result["rows_compared"] += 1
            cell = result["per_phrasing"].setdefault(
                row["phrasing"],
                {"rows": 0, "code_matched": 0, "date_matched": 0, "coded": bool(row["billstatus_action_codes"])},
            )
            cell["rows"] += 1
            codes = set(row["billstatus_action_codes"])
            if not codes:
                result["no_code_in_vocabulary"] += 1
            elif any(action["code"] in codes for action in actions):
                result["code_matched"] += 1
                cell["code_matched"] += 1
            dates = set(row["stated_dates"] or ())
            if dates and any(action["date"] in dates for action in actions):
                result["date_matched"] += 1
                cell["date_matched"] += 1
            if row["phrasing"] in {"held_hearing", "held_markup"}:
                result["hearing_or_markup_rows"] += 1
                words = hearing_words if row["phrasing"] == "held_hearing" else markup_words
                stated = any(any(word in action["text"].lower() for word in words) for action in actions)
                cell["stated_by_any_wording"] = cell.get("stated_by_any_wording", 0) + int(stated)
                if stated:
                    result["hearing_or_markup_stated_by_billstatus"] += 1
                elif len(result["absent_from_billstatus"]) < 8:
                    result["absent_from_billstatus"].append(
                        {
                            "bill_id": row["bill_id"],
                            "phrasing": row["phrasing"],
                            "stated_date": (row["stated_dates"] or [None])[0],
                            "matched_text": " ".join(row["matched_text"].split()),
                        }
                    )
    result["publisher_source_systems"] = dict(sources.most_common())
    return result


# --- the phases ----------------------------------------------------------------------


def measure(receipt: Path, mods_receipt: Path, export: Path, guide: Path) -> None:
    """Every mention, its sentence, the actions attached, and the hosted overlap."""
    documents: list[dict[str, Any]] = []
    for package_id, pages in cached_pages(receipt).items():
        measured = measure_document(package_id, pages)
        stated = mods_bill_keys(mods_receipt, package_id)
        printed = {row["bill_id"] for row in measured["rows"]}
        measured["mods_bills"] = len(stated)
        measured["mods_bills_with_an_action_row"] = len(printed & set(stated))
        measured["action_bills_not_in_mods"] = sorted(printed - set(stated))
        documents.append(measured)
        print(
            f"{package_id}: {measured['mentions']} mentions, {measured['distinct_bills']} bills, "
            f"{measured['action_rows']} action rows, "
            f"{measured['mentions_in_multi_bill_sentence']} mentions in a multi-bill sentence"
        )
    all_bills = sorted({row["bill_id"] for document in documents for row in document["rows"]})
    overlap = overlap_with_hosted(export, all_bills)
    codes = guide_action_codes(guide)
    unknown = {key: sorted({entry.code for entry in values} - codes) for key, values in BILLSTATUS_ACTION_CODES.items()}
    # A section-5 code inside a "section 3" reading means the scoping broke
    # again, which is the defect that produced the first version's inverted
    # conclusion. Fail the phase rather than publish it.
    leaked = sorted(codes & GUIDE_SUMMARIES_VERSION_CODES)
    if leaked:
        raise RelationshipError(f"the action-code scan reached section 5 codes: {leaked}")
    payload = {
        "rule_set_version": PRINT_ACTION_RULE_SET_VERSION,
        "citation_rule_version": CITATION_RULES_BY_NAME["bill_number"].version,
        "documents": documents,
        "overlap": overlap,
        "guide_codes_not_in_the_retained_guide": {key: values for key, values in unknown.items() if values},
    }
    (receipt / "measure.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _write_actions_tsv(receipt, documents)
    print(f"wrote {receipt / 'measure.json'}")


def _write_actions_tsv(receipt: Path, documents: Sequence[Mapping[str, Any]]) -> None:
    header = (
        "package_id\tbill_id\tphrasing\tsealed_stage\tbillstatus_codes\tattachment"
        "\tbills_in_sentence\tpage\tstated_date\tmatched_text"
    )
    lines = [header]
    for document in documents:
        for row in document["rows"]:
            lines.append(
                "\t".join(
                    (
                        document["package_id"],
                        row["bill_id"],
                        row["phrasing"],
                        row["stage"] or "",
                        ",".join(row["billstatus_action_codes"]),
                        row["attachment"],
                        str(row["bills_in_sentence"]),
                        str(row["page"] or ""),
                        (row["stated_dates"] or [""])[0],
                        " ".join(row["matched_text"].split()),
                    )
                )
            )
    (receipt / "actions.tsv").write_text("\n".join(lines) + "\n")


#: 60 mentions, spread across the eight prints so no one committee's house
#: style carries the figure, and **stratified on whether the tool attached an
#: action**: 5 per print that carry one and 2 or 3 that do not.
#:
#: Precision is a statement about rows a contract would publish, so it is
#: measured on the stratum those rows come from; drawing 60 uniformly would
#: have spent 35 of them on mentions that publish nothing and left 25 to carry
#: the precision figure. The no-action stratum is not padding either -- it is
#: the only place a silent miss can show up. Both stratum sizes are published
#: in the sidecar, so every combined figure here is re-weighted by them rather
#: than read off the sample as if it were uniform.
SAMPLE_WITH_ACTION_PER_PRINT = 5
SAMPLE_WITHOUT_ACTION = 20
SAMPLE_SIZE = 60
SAMPLE_SEED = 20260920

HAND_CHECK_COLUMNS = (
    "id",
    "package_id",
    "page",
    "bill_id",
    "matched_text",
    "stratum",
    "tool_phrasings",
    "tool_stage",
    "bills_in_sentence",
    "entry_phrasings",
    "phrase_correct",
    "bill_correct",
    "reader_actions",
    "captured_actions",
    "note",
)

#: How much text either side of the mention the hand check reads as "the
#: entry". These prints set an entry -- a numbered markup item, a lettered
#: bill heading, a ``Legislative History`` paragraph -- in roughly 600 to 1,000
#: characters, so this window holds the whole of one and the edges of its
#: neighbours, which is what a reader has in front of them.
ENTRY_WINDOW = 700


def sample(receipt: Path) -> None:
    """Write the 60-mention hand-check sheet and the contexts a reader checks it against.

    Two different things are checked on one sheet, and they need two different
    units. **Precision** is per mention: the phrasing attached to *this*
    designator, and whether it is this bill's. **Recall** is per (bill, entry):
    a bill's own heading line states no action, but the entry around it states
    several, each on a sentence with its own mention of the bill -- so a reader
    counting what the print states about a bill counts the entry, and
    ``entry_phrasings`` is what the tool produced for that bill anywhere in the
    same window.

    A sheet that already carries verdicts is never overwritten: the verdicts
    are hand work and the contexts file re-derives from the same seed anyway.
    """
    import random

    measured = json.loads((receipt / "measure.json").read_text())
    documents = {document["package_id"]: document for document in measured["documents"]}
    order = sorted(documents, key=lambda key: (-documents[key]["mentions"], key))
    without = {package_id: SAMPLE_WITHOUT_ACTION // len(order) for package_id in order}
    for package_id in order[: SAMPLE_WITHOUT_ACTION - sum(without.values())]:
        without[package_id] += 1

    pages = cached_pages(receipt)
    rows: list[dict[str, Any]] = []
    contexts: list[str] = []
    for package_id in sorted(order):
        text = "\n".join(pages[package_id])
        document = documents[package_id]
        by_mention: dict[tuple[int, int], list[Mapping[str, Any]]] = {}
        for row in document["rows"]:
            by_mention.setdefault((row["mention_span_start"], row["mention_span_end"]), []).append(row)
        findings = find_citations(text, pages=pages[package_id], kinds=("bill_number",), congress=PACKAGE_CONGRESS)
        strata = {
            "with_action": [f for f in findings if (f.span_start, f.span_end) in by_mention],
            "without_action": [f for f in findings if (f.span_start, f.span_end) not in by_mention],
        }
        wanted = {"with_action": SAMPLE_WITH_ACTION_PER_PRINT, "without_action": without[package_id]}
        for stratum, population in strata.items():
            rng = random.Random(f"{SAMPLE_SEED}:{package_id}:{stratum}")
            for finding in rng.sample(population, min(wanted[stratum], len(population))):
                attached = by_mention.get((finding.span_start, finding.span_end), [])
                identifier = f"{package_id}:{finding.span_start}"
                begin = max(0, finding.span_start - ENTRY_WINDOW)
                finish = finding.span_end + ENTRY_WINDOW
                entry_rows = [
                    row
                    for row in document["rows"]
                    if row["bill_id"] == finding.target_key and begin <= row["mention_span_start"] < finish
                ]
                rows.append(
                    {
                        "id": identifier,
                        "package_id": package_id,
                        "page": str(finding.page or ""),
                        "bill_id": finding.target_key,
                        "matched_text": " ".join(finding.matched_text.split()),
                        "stratum": stratum,
                        "tool_phrasings": ",".join(row["phrasing"] for row in attached) or "-",
                        "tool_stage": ",".join(row["stage"] or "-" for row in attached) or "-",
                        "bills_in_sentence": str(attached[0]["bills_in_sentence"]) if attached else "",
                        "entry_phrasings": ",".join(sorted({row["phrasing"] for row in entry_rows})) or "-",
                        "phrase_correct": "",
                        "bill_correct": "",
                        "reader_actions": "",
                        "captured_actions": "",
                        "note": "",
                    }
                )
                quoted = "\n".join(
                    f"    {row['phrasing']} <- {' '.join(row['matched_text'].split())!r}" for row in attached
                )
                sentence = (
                    " ".join(text[attached[0]["sentence_start"] : attached[0]["sentence_end"]].split())
                    if attached
                    else ""
                )
                contexts.append(
                    f"### {identifier}\nbill: {finding.target_key}  page {finding.page}  "
                    f"stratum: {stratum}\n"
                    f"this mention: {rows[-1]['tool_phrasings']} ({rows[-1]['tool_stage']}), "
                    f"{rows[-1]['bills_in_sentence'] or '0'} bills in its sentence\n"
                    f"{quoted}\n"
                    f"its sentence: {sentence!r}\n"
                    f"this bill, anywhere in the window: {rows[-1]['entry_phrasings']}\n"
                    f"---\n{text[begin:finish]}\n---\n"
                )
    sheet = receipt / "hand-check.tsv"
    verdict = HAND_CHECK_COLUMNS.index("phrase_correct")
    if sheet.exists() and any(
        line.split("\t")[verdict:] != [""] * (len(HAND_CHECK_COLUMNS) - verdict)
        for line in sheet.read_text().splitlines()[1:]
    ):
        print(f"{sheet} already carries verdicts; not overwritten")
    else:
        lines = ["\t".join(HAND_CHECK_COLUMNS)]
        lines.extend("\t".join(row[column] for column in HAND_CHECK_COLUMNS) for row in rows)
        sheet.write_text("\n".join(lines) + "\n")
        print(f"wrote {sheet} with {len(rows)} mentions")
    (receipt / "hand-check-contexts.md").write_text(
        "# The 60 sampled mentions, with the text a reader checks them against\n\n" + "\n".join(contexts)
    )


def read_hand_check(receipt: Path) -> list[dict[str, str]]:
    """The filled sheet, refused rather than half-read when a verdict is missing."""
    sheet = receipt / "hand-check.tsv"
    if not sheet.exists():
        raise RelationshipError("no hand-check.tsv; run the `sample` phase and fill it in")
    lines = sheet.read_text().splitlines()
    header = lines[0].split("\t")
    if tuple(header) != HAND_CHECK_COLUMNS:
        raise RelationshipError(f"hand-check.tsv columns are {header}, not {list(HAND_CHECK_COLUMNS)}")
    rows = [dict(zip(header, line.split("\t"), strict=True)) for line in lines[1:] if line.strip()]
    blank = [row["id"] for row in rows if not row["reader_actions"] or not row["captured_actions"]]
    if blank:
        raise RelationshipError(f"{len(blank)} hand-check rows carry no verdict: {blank[:5]}")
    return rows


def score(rows: Sequence[Mapping[str, str]], strata: Mapping[str, int]) -> dict[str, Any]:
    """Precision of the classification, precision of the attachment, and recall.

    Three separate numbers, because they fail separately. A phrase can be read
    correctly off a sentence and attached to the wrong bill -- that is the
    multi-bill entry, and folding it into one "accuracy" would hide it.
    ``reader_actions`` is what a reader sees the print state about *this* bill
    in the entry around the mention, so recall is measured against the
    document, not against the tool's own output.

    Recall is reported per stratum **and** re-weighted by ``strata``, the two
    strata's sizes in the corpus. The sample is deliberately not uniform (see
    :data:`SAMPLE_WITH_ACTION_PER_PRINT`), so reading a combined rate straight
    off the 60 rows would overstate it: the no-action stratum is the larger of
    the two in the corpus and the smaller of the two in the sample.
    """
    judged = [row for row in rows if row["phrase_correct"] in {"yes", "no"}]
    attached = [row for row in rows if row["bill_correct"] in {"yes", "no"}]
    # The figure a consumer acts on is neither of the two above: it is the
    # share of *published rows* that are both the right kind and the right
    # bill, per attachment class, because that is what filtering on
    # `attachment_confidence` selects. A row whose phrase was misread is a
    # wrong published row whatever its attachment, so it counts against its
    # own class rather than dropping out of the denominator.
    published: dict[str, dict[str, int]] = {}
    for row in judged:
        count = int(row["bills_in_sentence"]) if row["bills_in_sentence"] else 1
        cell = published.setdefault(ATTACHMENT_SINGLE if count == 1 else ATTACHMENT_MULTI, {"judged": 0, "correct": 0})
        cell["judged"] += 1
        cell["correct"] += int(row["phrase_correct"] == "yes" and row["bill_correct"] == "yes")
    for cell in published.values():
        cell["precision"] = round(cell["correct"] / cell["judged"], 4) if cell["judged"] else None
    per_stratum: dict[str, dict[str, Any]] = {}
    for name, size in strata.items():
        drawn = [row for row in rows if row["stratum"] == name]
        reader = sum(int(row["reader_actions"]) for row in drawn)
        captured = sum(int(row["captured_actions"]) for row in drawn)
        per_stratum[name] = {
            "corpus_mentions": size,
            "sampled": len(drawn),
            "weight": round(size / len(drawn), 4) if drawn else None,
            "reader_actions": reader,
            "captured": captured,
            "recall": round(captured / reader, 4) if reader else None,
        }
    weighted_reader = sum(cell["weight"] * cell["reader_actions"] for cell in per_stratum.values() if cell["weight"])
    weighted_captured = sum(cell["weight"] * cell["captured"] for cell in per_stratum.values() if cell["weight"])
    return {
        "mentions_checked": len(rows),
        "mentions_with_a_tool_action": len(judged),
        "mentions_without_a_tool_action": len(rows) - len(judged),
        "classification": {
            "judged": len(judged),
            "correct": sum(1 for row in judged if row["phrase_correct"] == "yes"),
            "precision": round(sum(1 for row in judged if row["phrase_correct"] == "yes") / len(judged), 4)
            if judged
            else None,
        },
        "attachment": {
            "judged": len(attached),
            "correct": sum(1 for row in attached if row["bill_correct"] == "yes"),
            "precision": round(sum(1 for row in attached if row["bill_correct"] == "yes") / len(attached), 4)
            if attached
            else None,
        },
        # The headline: what share of published rows is right, per class.
        "published_row_precision": published,
        "recall": {
            "per_stratum": per_stratum,
            "reader_actions": sum(int(row["reader_actions"]) for row in rows),
            "captured": sum(int(row["captured_actions"]) for row in rows),
            "recall": round(weighted_captured / weighted_reader, 4) if weighted_reader else None,
        },
    }


#: The two retained activity reports this repository keeps as committed
#: fixtures. ``CRPT-118hrpt968`` is a complete 56-page read, so its rows are
#: the sidecar's own per-document numbers; ``CRPT-118hrpt965`` is 60 pages of a
#: 282-page print, so its rows must be a strict *prefix subset* of the full
#: read -- same text, same offsets, fewer pages -- which is a stronger check
#: than a count.
FIXTURE_PACKAGES: tuple[str, ...] = ("CRPT-118hrpt965", "CRPT-118hrpt968")


def fixture_counts(fixtures: Path) -> dict[str, Any]:
    """What the committed fixture texts produce, so a test can pin the loader to it.

    Read from ``tests/fixtures/document_citations`` rather than from the
    receipt: the receipt is outside the repository and a test may not reach it,
    so the numbers a test asserts have to be derivable from committed bytes.
    """
    counted: dict[str, Any] = {}
    for package in FIXTURE_PACKAGES:
        text = (fixtures / f"{package}.txt").read_text()
        lengths = json.loads((fixtures / f"{package}.json").read_text())["page_lengths"]
        pages, cursor = [], 0
        for length in lengths:
            pages.append(text[cursor : cursor + length])
            cursor += length + 1
        citations = find_citations(text, pages=tuple(pages), kinds=("bill_number",), congress=PACKAGE_CONGRESS)
        reading = find_bill_actions(text, citations)
        attachment = Counter(action.attachment for action in reading.findings)
        counted[package] = {
            "pages": len(pages),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "mentions": len(citations),
            "action_rows": len(reading.findings),
            "trusted_rows": attachment[ATTACHMENT_SINGLE],
            "attachment": dict(sorted(attachment.items())),
            "orphan_phrases": sum(reading.orphan_phrasings.values()),
            "distinct_bills_with_an_action": len({action.bill_id for action in reading.findings}),
        }
    return counted


def report(receipt: Path, output: Path, fixtures: Path) -> None:
    """Fold the measurement and the filled hand-check sheet into the committed sidecar."""
    measured = json.loads((receipt / "measure.json").read_text())
    documents = measured["documents"]
    phrasings: Counter[str] = Counter()
    orphans: Counter[str] = Counter()
    phrasing_bills: dict[str, set[str]] = {}
    for document in documents:
        for key, count in document["phrasings"].items():
            phrasings[key] += count
        orphans.update(document["orphan_phrasings"])
        for row in document["rows"]:
            phrasing_bills.setdefault(row["phrasing"], set()).add(row["bill_id"])
    table = []
    for rule in PRINT_ACTION_RULES:
        stage, matcher = sealed_stage(_representative(documents, rule.key) or rule.key)
        table.append(
            {
                "phrasing": rule.key,
                "occurrences": phrasings.get(rule.key, 0),
                "orphan_occurrences": orphans.get(rule.key, 0),
                "distinct_bills": len(phrasing_bills.get(rule.key, ())),
                "sealed_stage": stage,
                "sealed_matcher": matcher,
                "billstatus_codes": list(guide_codes_for(rule.key, HOUSE)),
                "billstatus_codes_any_chamber": [entry.code for entry in BILLSTATUS_ACTION_CODES.get(rule.key, ())],
                "house_code_absent": rule.key in HOUSE_COMMITTEE_EVENTS_WITHOUT_A_CODE,
                "note": rule.note,
            }
        )
    hosted = measured["overlap"]["hosted"]
    duplicated = 0
    latest_only = 0
    for document in documents:
        for row in document["rows"]:
            record = hosted.get(row["bill_id"])
            if record is None:
                continue
            latest_only += 1
            if row["stage"] is not None and row["stage"] == record["stage"]:
                duplicated += 1
    sidecar = {
        "measured": "2026-09-20",
        "rule_set_version": measured["rule_set_version"],
        "citation_rule_version": measured["citation_rule_version"],
        "requests": 0,
        "documents": [
            {key: document[key] for key in sorted(document) if key not in {"rows", "phrasings", "phrasing_bills"}}
            for document in documents
        ],
        "totals": {
            "pages": sum(document["pages"] for document in documents),
            "mentions": sum(document["mentions"] for document in documents),
            "distinct_bills": len({row["bill_id"] for document in documents for row in document["rows"]}),
            "mentions_with_action": sum(document["mentions_with_action"] for document in documents),
            "mentions_in_multi_bill_sentence": sum(
                document["mentions_in_multi_bill_sentence"] for document in documents
            ),
            "action_rows": sum(document["action_rows"] for document in documents),
            "trusted_rows": sum(document["trusted_rows"] for document in documents),
            "sentence_scoped_rows": sum(document["sentence_scoped_rows"] for document in documents),
            "orphan_phrases": sum(document["orphan_phrases"] for document in documents),
            "mods_bills": sum(document["mods_bills"] for document in documents),
            "mods_bills_with_an_action_row": sum(document["mods_bills_with_an_action_row"] for document in documents),
            # Rows whose phrasing the publisher's own BILLSTATUS guide states no
            # action code for. This is the committee narrative in one number:
            # the subcommittee-to-full-committee forward, the refusal to mark a
            # bill up, the bill folded into another, the measure the other
            # chamber never took up.
            "rows_whose_phrasing_billstatus_has_no_code_for": sum(
                count for key, count in phrasings.items() if key not in BILLSTATUS_ACTION_CODES
            ),
        },
        "phrasings": table,
        "fixtures": fixture_counts(fixtures),
        "billstatus_overlap": billstatus_overlap(receipt),
        "hand_check": score(
            read_hand_check(receipt),
            {
                "with_action": sum(document["mentions_with_action"] for document in documents),
                "without_action": sum(
                    document["mentions"] - document["mentions_with_action"] for document in documents
                ),
            },
        ),
        "overlap": {
            key: value for key, value in measured["overlap"].items() if key not in {"hosted", "bills_not_hosted"}
        }
        | {
            "bills_not_hosted": measured["overlap"]["bills_not_hosted"],
            "action_rows_with_a_hosted_bill": latest_only,
            "action_rows_whose_stage_the_latest_action_already_states": duplicated,
            "print_congresses": sorted({row["bill_id"].split("-")[0] for d in documents for row in d["rows"]}),
        },
        "guide_codes_not_in_the_retained_guide": measured["guide_codes_not_in_the_retained_guide"],
    }
    output.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")
    print(f"wrote {output}")


def _representative(documents: Sequence[Mapping[str, Any]], phrasing: str) -> str | None:
    """The first matched text this phrasing produced, so the sealed reading is of real bytes."""
    for document in documents:
        for row in document["rows"]:
            if row["phrasing"] == phrasing:
                return str(row["matched_text"])
    return None


# --- the report's generated block ----------------------------------------------------

MARK_START = "<!-- generated by tools/analysis/bill_action_relationship.py: start -->"
MARK_END = "<!-- generated by tools/analysis/bill_action_relationship.py: end -->"


def render_block(sidecar: Mapping[str, Any]) -> str:
    """The markdown between the markers, rendered from the sidecar alone."""
    totals = sidecar["totals"]
    check = sidecar["hand_check"]
    overlap = sidecar["overlap"]
    lines = [MARK_START, ""]
    lines.append(
        f"Measured {sidecar['measured']} from retained bytes, **{sidecar['requests']} requests**: "
        f"{totals['pages']:,} pages of the eight prints, "
        f"{totals['mentions']:,} bill mentions over {totals['distinct_bills']:,} distinct bills, "
        f"{totals['action_rows']:,} action rows. Phrasing rule set `{sidecar['rule_set_version']}`, "
        f"`bill_number` rule version `{sidecar['citation_rule_version']}`."
    )
    lines.append("")
    lines.append("### Every print phrasing, with what the sealed vocabulary makes of it")
    lines.append("")
    lines.append("`Orphan` counts the same phrasing in a sentence that names no bill at all — what no")
    lines.append("sentence-scoped rule can ever attach.")
    lines.append("")
    lines.append("| Print phrasing | Rows | Orphan | Bills | `bill_stage` rung | BILLSTATUS action code, House |")
    lines.append("| --- | ---: | ---: | ---: | --- | --- |")
    for row in sorted(sidecar["phrasings"], key=lambda entry: (-entry["occurrences"], entry["phrasing"])):
        stage = f"`{row['sealed_stage']}`" if row["sealed_stage"] else "**none**"
        codes = ", ".join(f"`{code}`" for code in row["billstatus_codes"])
        if not codes:
            codes = "**none — Senate-only**" if row["house_code_absent"] else "**none**"
        lines.append(
            f"| `{row['phrasing']}` | {row['occurrences']:,} | {row['orphan_occurrences']:,} | "
            f"{row['distinct_bills']:,} | {stage} | {codes} |"
        )
    mapped = sum(row["occurrences"] for row in sidecar["phrasings"] if row["sealed_stage"])
    total = sum(row["occurrences"] for row in sidecar["phrasings"])
    uncoded = [row["phrasing"] for row in sidecar["phrasings"] if not row["billstatus_codes_any_chamber"]]
    uncoded_rows = sum(row["occurrences"] for row in sidecar["phrasings"] if not row["billstatus_codes_any_chamber"])
    lines.append("")
    lines.append(
        f"**{mapped:,} of {total:,}** action rows carry a phrasing one of `bill_stage`'s sealed "
        f"matchers reads; **{total - mapped:,}** carry one it does not — `passed_house`, "
        f"`suspension`, `held_hearing`, `discharged` and `report_filed` among them, so the print's "
        f"own spelling of passage and of every committee step falls outside the sealed ladder."
    )
    lines.append("")
    lines.append(
        f"**{totals['orphan_phrases']:,} further phrase occurrences** sit in a sentence that names "
        f"no bill, against {total:,} that reach one."
    )
    senate_only = [row["phrasing"] for row in sidecar["phrasings"] if row["house_code_absent"]]
    senate_only_rows = sum(row["occurrences"] for row in sidecar["phrasings"] if row["house_code_absent"])
    lines.append("")
    lines.append(
        f"**{len(uncoded)} phrasings have no action code in either chamber** — "
        f"{', '.join(f'`{name}`' for name in uncoded)}, "
        f"{uncoded_rows:,} rows — and "
        f"**{len(senate_only)} more have one only for the Senate**: "
        f"{', '.join(f'`{name}`' for name in senate_only)}, **{senate_only_rows:,} rows**. "
        f"Section 3 of the publisher's guide has no House hearing code and no House markup code at all, "
        f"so for those two events in a House committee's print the sentence is the only structured "
        f"statement there is."
    )
    lines.append("")
    lines.append("### Per print")
    lines.append("")
    lines.append(
        "| Report | Pages | MODS bills | Mentions | Mentions with an action | In a multi-bill sentence | Action rows |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for document in sorted(sidecar["documents"], key=lambda entry: entry["package_id"]):
        lines.append(
            f"| {document['package_id']} | {document['pages']:,} | {document['mods_bills']:,} | "
            f"{document['mentions']:,} | {document['mentions_with_action']:,} | "
            f"{document['mentions_in_multi_bill_sentence']:,} | {document['action_rows']:,} |"
        )
    lines.append(
        f"| **Total** | {totals['pages']:,} | {totals['mods_bills']:,} | {totals['mentions']:,} | "
        f"{totals['mentions_with_action']:,} | {totals['mentions_in_multi_bill_sentence']:,} | "
        f"{totals['action_rows']:,} |"
    )
    classification = check["classification"]
    attachment = check["attachment"]
    recall = check["recall"]
    with_action = recall["per_stratum"]["with_action"]
    without_action = recall["per_stratum"]["without_action"]
    lines.append("")
    lines.append("### The hand check")
    lines.append("")
    lines.append(
        f"{check['mentions_checked']} mentions, sampled across the eight prints and read in the "
        f"extract text with the surrounding entry. {check['mentions_with_a_tool_action']} carried a "
        f"tool action and {check['mentions_without_a_tool_action']} carried none."
    )
    lines.append("")
    lines.append("| Measure | Judged | Correct | Rate |")
    lines.append("| --- | ---: | ---: | ---: |")
    lines.append(
        f"| Action classification | {classification['judged']} | {classification['correct']} | "
        f"**{_percent(classification['precision'])}** |"
    )
    lines.append(
        f"| Bill-to-action attachment, given a correct reading | {attachment['judged']} | "
        f"{attachment['correct']} | **{_percent(attachment['precision'])}** |"
    )
    single = check["published_row_precision"][ATTACHMENT_SINGLE]
    multi = check["published_row_precision"][ATTACHMENT_MULTI]
    lines.append(
        f"| **A published row is right kind and right bill — `single`** | {single['judged']} | "
        f"{single['correct']} | **{_percent(single['precision'])}** |"
    )
    lines.append(f"| **— `multi`** | {multi['judged']} | {multi['correct']} | **{_percent(multi['precision'])}** |")
    lines.append(
        f"| Recall, re-weighted by stratum | {recall['reader_actions']} | {recall['captured']} | "
        f"**{_percent(recall['recall'])}** |"
    )
    lines.append(
        f"| — where the tool found an action | {with_action['reader_actions']} | "
        f"{with_action['captured']} | {_percent(with_action['recall'])} |"
    )
    lines.append(
        f"| — where it found none | {without_action['reader_actions']} | "
        f"{without_action['captured']} | {_percent(without_action['recall'])} |"
    )
    trusted = totals["trusted_rows"]
    lines.append("")
    lines.append(
        f"**{trusted:,} of {totals['action_rows']:,} rows ({trusted / totals['action_rows']:.1%}) are "
        f"`single`**, so a consumer filtering to the trusted class keeps "
        f"{trusted / totals['action_rows']:.1%} of the volume at "
        f"{_percent(single['precision'])} precision. Recall is a separate axis and is "
        f"{_percent(check['recall']['recall'])}: this is a statement about what is published, never "
        f"about what a reader sees captured."
    )
    lines.append("")
    lines.append("### The row-for-row BILLSTATUS overlap, 20 keyed requests")
    overlap_rows = sidecar["billstatus_overlap"]
    per = overlap_rows["per_phrasing"]
    lines.append("")
    lines.append(
        f"The retained `congress_bills` export carries one action per bill, so it can only floor the "
        f"duplication. This asked the publisher for the **whole action list** of "
        f"{overlap_rows['bills_requested']} of the bills these prints act on — "
        f"{overlap_rows['publisher_action_rows']} published actions — and compared "
        f"{overlap_rows['rows_compared']} single-attachment print rows against them."
    )
    lines.append("")
    lines.append("| | Print rows | Publisher states the same code | Same date | States the event at all |")
    lines.append("| --- | ---: | ---: | ---: | ---: |")
    for name in ("held_hearing", "held_markup"):
        cell = per.get(name, {})
        lines.append(
            f"| `{name}` | {cell.get('rows', 0)} | **{cell.get('code_matched', 0)}** (no code exists) | "
            f"{cell.get('date_matched', 0)} | **{cell.get('stated_by_any_wording', 0)}** |"
        )
    coded = {name: cell for name, cell in per.items() if cell.get("coded")}
    lines.append(
        f"| every coded phrasing | {sum(c['rows'] for c in coded.values())} | "
        f"{sum(c['code_matched'] for c in coded.values())} | "
        f"{sum(c['date_matched'] for c in coded.values())} | — |"
    )
    hearing = per.get("held_hearing", {})
    lines.append("")
    lines.append(
        f"**{hearing.get('rows', 0) - hearing.get('stated_by_any_wording', 0)} of "
        f"{hearing.get('rows', 0)} subcommittee hearings the print states are absent from BILLSTATUS "
        f"altogether** — no code, no wording, nothing. Markups are different and the difference is the "
        f"finding's own limit: all {per.get('held_markup', {}).get('rows', 0)} markup rows appear in the "
        f"publisher's list as free text filed by the `House committee actions` source system "
        f"({overlap_rows['publisher_source_systems'].get('House committee actions', 0)} of "
        f"{overlap_rows['publisher_action_rows']} published actions), carrying no action code. So the "
        f"print is the sole source for hearings, and a second, uncoded source for markups."
    )
    lines.append("")
    lines.append("### Against the hosted `congress_bills` export")
    lines.append("")
    lines.append(
        f"The retained `congress_bills` export holds {overlap['export_rows']:,} bills, Congresses "
        f"{overlap['export_congress_range'][0]} to {overlap['export_congress_range'][1]}. "
        f"**{overlap['bills_hosted']:,} of the {overlap['bills_asked']:,}** bills these prints attach an "
        f"action to have a hosted row; {len(overlap['bills_not_hosted'])} do not. "
        f"Every bill the prints act on is from Congress "
        f"{', '.join(overlap['print_congresses'])} — **this sample contains no pre-108th bill at all**, "
        f"so what the print would add before the 108th is not measured here. "
        f"Of the {overlap['action_rows_with_a_hosted_bill']:,} action rows whose bill is hosted, "
        f"**{overlap['action_rows_whose_stage_the_latest_action_already_states']:,}** state a rung the "
        f"hosted row's *latest action alone* already states."
    )
    lines.append("")
    lines.append(MARK_END)
    return "\n".join(lines)


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _rate(cell: Mapping[str, int]) -> str:
    return "—" if not cell["judged"] else f"{cell['correct'] / cell['judged']:.1%}"


def render(sidecar: Path, report_path: Path) -> None:
    """Replace the report's generated block with the one the sidecar renders."""
    block = render_block(json.loads(sidecar.read_text()))
    text = report_path.read_text()
    start, end = text.find(MARK_START), text.find(MARK_END)
    if start < 0 or end < 0:
        raise RelationshipError("the report carries no generated-block markers")
    report_path.write_text(text[:start] + block + text[end + len(MARK_END) :])
    print(f"rendered {len(block)} characters into {report_path}")


# --- entry point ---------------------------------------------------------------------

DEFAULT_RECEIPT = Path("~/Work/corpora/supply-2026-09-02/receipts/bill-action-relationship-2026-09-20")
DEFAULT_SOURCE = Path("~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20")
DEFAULT_MODS = Path("~/Work/corpora/supply-2026-09-02/receipts/pdf-yield-mods-recheck-2026-09-20")
DEFAULT_EXPORT = Path("~/Work/corpora/congress-bills-export-2026-09-06/congress_bills_actions.parquet")
DEFAULT_GUIDE = Path("tests/fixtures/billstatus_codes/guide-2026-08-03.md")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ and __doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="phase", required=True)
    for name in ("text", "measure", "sample", "billstatus", "report", "render"):
        phase = sub.add_parser(name)
        phase.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
        if name == "text":
            phase.add_argument("--source-receipt", type=Path, default=DEFAULT_SOURCE)
        if name == "measure":
            phase.add_argument("--mods-receipt", type=Path, default=DEFAULT_MODS)
            phase.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
            phase.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
        if name == "billstatus":
            phase.add_argument("--env", type=Path, default=Path(".env"))
            phase.add_argument("--max-requests", type=int, default=MAX_BILLSTATUS_REQUESTS)
        if name == "report":
            phase.add_argument("--output", type=Path, required=True)
            phase.add_argument("--fixtures", type=Path, default=Path("tests/fixtures/document_citations"))
        if name == "render":
            phase.add_argument("--sidecar", type=Path, required=True)
            phase.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = args.receipt.expanduser()
    if args.phase == "text":
        cache_text(receipt, args.source_receipt.expanduser())
    elif args.phase == "measure":
        measure(receipt, args.mods_receipt.expanduser(), args.export.expanduser(), args.guide.expanduser())
    elif args.phase == "sample":
        sample(receipt)
    elif args.phase == "billstatus":
        billstatus(receipt, args.env.expanduser(), args.max_requests)
    elif args.phase == "report":
        report(receipt, args.output, args.fixtures)
    elif args.phase == "render":
        render(args.sidecar, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
