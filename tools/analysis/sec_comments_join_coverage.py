#!/usr/bin/env python3
"""Measure the SEC comments join coverage over the retained releases, offline, through the join's own indexes.

Reads the retained regulations.gov SEC documents (campaign
``regs-documents-SEC``) and the retained Federal Register release
(``fr-full-1994-2026``) from their source-native manifests and verified
blobs, builds the join's ``MirrorSecIndex`` and ``FrDocumentIndex`` once, and
reports:

* how many SEC documents carry ``frCitation`` (the field is absent from the
  regulations.gov document schema), ``frDocNum``, and a ``docketId``, and
  whether any ``docketId`` spells an SEC file number;
* how many mirror documents ``FrDocumentIndex`` resolves to a volume/page
  citation, and how many resolve only to a non-SEC Federal Register record,
  which the SEC-agency index does not hold;
* link counts from ``link_rulemaking_to_mirror`` itself, fed each resolved
  record's citation with its own statements, then each ``Release No.`` and
  ``File No.`` statement the release's SEC records make -- with the S7-11-23
  chain as the worked example;
* a census of ``Release No(s).``/``File No(s).`` statements by a looser
  pattern than the join's grammar, with the shapes the join reads no number
  from, so a grammar gap shows as a count rather than as silence;
* the title+date last tier: the mirror documents the ``frDocNum`` tiers
  cannot reach, matched through ``match_sec_document_without_fr_doc_num``, and
  the title-pattern split of the resolved-but-weak links.

The unresolved ``frDocNum`` values are **not** Federal Register release
coverage gaps: re-derived live on 2026-09-24, the Federal Register API 404s
every one of them while serving era siblings (``00-22718``, ``E8-15000``
both answer 200). The Federal Register never served those numbers; see the
receipt, which is the record of every number and input pin.

The numbers and the input pins land in one receipt JSONL under
``--receipts``; the receipt, not the log, is the record of the run::

    uv run --frozen python tools/analysis/sec_comments_join_coverage.py
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import re
import sys
import time
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from spicy_docs.releases.format import ROLE_RECORDS
from spicy_docs.sources.sec_comments.join import (
    FrAgendaIndex,
    FrCollisionError,
    FrDocument,
    FrDocumentIndex,
    FrSecTitleIndex,
    MirrorSecDocument,
    MirrorSecIndex,
    SecCommentsJoinError,
    link_rulemaking_to_mirror,
    match_sec_document_without_fr_doc_num,
    normalize_fr_doc_num,
    record_is_sec_agency,
    stated_file_numbers,
    stated_release_numbers,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

MANIFEST: tuple[str, str] = ("manifests", "source-native.json")
SEC_DOCUMENT_RELEASE = Path("/Users/mikewolfd/Work/corpora/supply-2026-09-02/campaign/regs-documents-SEC")
FR_RELEASE = Path("/Users/mikewolfd/Work/corpora/supply-2026-09-02/releases/fr-full-1994-2026")
BLOB_STORE = Path("/Users/mikewolfd/Work/corpora/supply-2026-09-02/blobs")
RECEIPTS = Path("/Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/sec-comments-join-2026-09-24")

#: The SEC file-number spelling a docketId would have to carry to be usable for the comment join.
SEC_FILE_NUMBER = "S7-"

#: The S7-11-23 chain the fixtures pin: proposal, adoption, extension (real FR release records).
SAMPLE_FILE_NUMBER = "S7-11-23"

#: The title-pattern families the weak-link split reports; ``other`` is everything else.
#: The order is the precedence when a title names more than one family.
TITLE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("agenda", "agenda"),
    ("pra", "information collection"),
    ("sro", "self-regulatory organizations"),
)

#: Statement prefixes read looser than the join's grammar: any case, singular or plural.
_RAW_STATEMENTS = {"release": re.compile(r"(?i)\brelease\s+nos?\."), "file": re.compile(r"(?i)\bfile\s+nos?\.")}
_DIGITS = re.compile(r"[0-9]+")


def _title_pattern(title: str | None) -> str:
    """One mirror title's weak-link family: agenda, PRA, SRO, or other (casefolded containment)."""
    value = (title or "").casefold()
    for pattern, marker in TITLE_PATTERNS:
        if marker in value:
            return pattern
    return "other"


def _pin(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _rows(release: Path, store: LocalSourceNativeBlobStore) -> Iterator[dict]:
    """Every row of one release's record members, streamed from verified blobs."""
    members = json.loads(release.joinpath(*MANIFEST).read_text())["members"]
    for member in members:
        if member["role"] == ROLE_RECORDS:
            with store.open(member["blobRef"]) as handle:
                yield from map(json.loads, handle)


def _number_key(value: str | None) -> str | None:
    try:
        return normalize_fr_doc_num(value) if value else None
    except SecCommentsJoinError:
        return None


def _mirror_rows(rows: Iterable[dict], census: collections.Counter, unreadable: collections.Counter) -> Iterator[dict]:
    """Count the mirror fields the join reads while passing each row on to ``MirrorSecIndex``."""
    for row in rows:
        attributes = row["record"]["data"]["attributes"]
        census["records"] += 1
        census["frCitationNonNull"] += bool(attributes.get("frCitation"))
        fr_doc_num = attributes.get("frDocNum")
        if isinstance(fr_doc_num, str) and fr_doc_num:
            census["frDocNumNonNull"] += 1
            if _number_key(fr_doc_num) is None:
                unreadable[fr_doc_num.split("-", 1)[0]] += 1
        docket_id = attributes.get("docketId")
        if isinstance(docket_id, str) and docket_id:
            census["docketIdNonNull"] += 1
            census["docketIdSpellingAnSecFileNumber"] += SEC_FILE_NUMBER in docket_id
        yield row


def _fr_rows(rows: Iterable[dict], census: dict[str, Any], mirror_keys: set[str]) -> Iterator[dict]:
    """Census every Federal Register record, passing the SEC-agency ones on to ``FrDocumentIndex``.

    A non-SEC record whose number a mirror document names is recorded in
    ``outsideSec``. Each SEC record's statements are read twice: by the
    join's own extractors, collected for the link counts, and by the looser
    ``_RAW_STATEMENTS`` prefixes, so a statement the join reads nothing from is
    counted by its prefix spelling and shape.
    """
    for row in rows:
        record = row["record"]
        census["records"] += 1
        if not record_is_sec_agency(record):
            if (key := _number_key(record.get("document_number"))) in mirror_keys:
                census["outsideSec"].add(key)
            continue
        census["secAgencyRecords"] += 1
        docket_ids = [value for value in record.get("docket_ids") or () if isinstance(value, str)]
        read = {"release": set(stated_release_numbers(docket_ids)), "file": set(stated_file_numbers(docket_ids))}
        census["releaseNumbers"] |= read["release"]
        census["fileNumbers"] |= read["file"]
        for kind, pattern in _RAW_STATEMENTS.items():
            spellings = {" ".join(match[0].split()) for value in docket_ids for match in pattern.finditer(value)}
            for spelling in spellings:
                census["statements"][f"{kind}:{spelling}"] += 1
            if spellings and not read[kind]:
                census["unread"][f"{kind}:{_DIGITS.sub('N', json.dumps(docket_ids))}"] += 1
        yield row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sec-release", type=Path, default=SEC_DOCUMENT_RELEASE)
    parser.add_argument("--fr-release", type=Path, default=FR_RELEASE)
    parser.add_argument("--blob-store", type=Path, default=BLOB_STORE)
    parser.add_argument("--receipts", type=Path, default=RECEIPTS)
    args = parser.parse_args()
    started = datetime.datetime.now(datetime.UTC).isoformat()
    begun = time.monotonic()
    store = LocalSourceNativeBlobStore(args.blob_store, create=False)

    sec_census: collections.Counter = collections.Counter()
    unreadable: collections.Counter = collections.Counter()
    mirror_index = MirrorSecIndex.from_records(_mirror_rows(_rows(args.sec_release, store), sec_census, unreadable))
    mirror_keys = {key for document in mirror_index.documents if (key := _number_key(document.fr_doc_num))}
    fr_census: dict[str, Any] = {"records": 0, "secAgencyRecords": 0, "outsideSec": set()}
    fr_census.update(
        releaseNumbers=set(), fileNumbers=set(), statements=collections.Counter(), unread=collections.Counter()
    )
    fr_index = FrDocumentIndex.from_records(_fr_rows(_rows(args.fr_release, store), fr_census, mirror_keys))

    # Mirror document -> the SEC-agency FR record its frDocNum resolves to, when that record has a citation.
    resolved: dict[str, FrDocument] = {}
    for document in mirror_index.documents:
        if document.fr_doc_num is not None:
            cited = [fr for fr in fr_index.citation_for_fr_doc_num(document.fr_doc_num) if fr.citation is not None]
            if cited:
                resolved[document.document_id] = cited[0]
    unresolved = [d for d in mirror_index.documents if d.fr_doc_num is not None and d.document_id not in resolved]

    def linked(path: str | None = None, **statements: Any) -> set[str]:
        links = link_rulemaking_to_mirror(mirror_index=mirror_index, fr_index=fr_index, **statements)
        return {link.mirror_document.document_id for link in links if path is None or link.path == path}

    by_citation: set[str] = set()
    citation_collisions: list[dict[str, Any]] = []
    # Citations the join's own grammar (``89 FR 45894``, four- to six-digit page) cannot spell.
    unspellable: set[str] = set()
    for fr in {fr.document_number: fr for fr in resolved.values()}.values():
        files = sorted(stated_file_numbers(fr.docket_ids))
        try:
            by_citation |= linked(
                "fr_citation",
                file_number=files[0] if len(files) == 1 else None,
                release_numbers=tuple(stated_release_numbers(fr.docket_ids)),
                fr_citations=(fr.citation.spelled,),
            )
        except FrCollisionError as error:
            citation_collisions.append({"citation": fr.citation.normalized, "documentNumbers": error.document_numbers})
        except SecCommentsJoinError:
            unspellable.add(fr.citation.normalized)
    by_release = set().union(*(linked(file_number=None, release_numbers=(n,)) for n in fr_census["releaseNumbers"]))
    by_file = set().union(*(linked(file_number=n) for n in fr_census["fileNumbers"]))

    fr_agenda_index = FrAgendaIndex.from_fr_documents(fr_index.documents)
    fr_sec_index = FrSecTitleIndex.from_fr_documents(fr_index.documents)

    def fallback_entry(document: MirrorSecDocument) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "documentId": document.document_id,
            "frDocNum": document.fr_doc_num,
            "title": document.title,
            "documentType": document.document_type,
            "postedDate": document.posted_date,
        }
        try:
            match = match_sec_document_without_fr_doc_num(
                document.title, document.posted_date, fr_agenda_index, fr_sec_index
            )
        except FrCollisionError as error:
            entry["result"] = {
                "tier": "collision",
                "reason": str(error),
                "documentNumbers": list(error.document_numbers),
            }
            return entry
        result: dict[str, Any] = {
            "tier": match.tier,
            "statedTitle": match.stated_title,
            "postedDate": match.posted_date,
        }
        if match.tie_break is not None:
            result["tieBreak"] = match.tie_break
        if match.fr_document is not None:
            result["documentNumber"] = match.fr_document.document_number
            result["publicationDate"] = match.fr_document.publication_date
            result["citation"] = match.citation.normalized if match.citation is not None else None
        if match.reason is not None:
            result["reason"] = match.reason
        entry["result"] = result
        return entry

    def fallback_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
        by_tier = collections.Counter(entry["result"]["tier"] for entry in results)
        resolved_tiers = ("title-date-agenda", "title-date-sec")
        return {
            "total": len(results),
            "resolvedByTier": {
                tier: by_tier.get(tier, 0) for tier in (*resolved_tiers, "mirror-artifact", "collision")
            },
            "resolved": [entry for entry in results if entry["result"]["tier"] in resolved_tiers],
            "unresolvable": [entry for entry in results if entry["result"]["tier"] not in resolved_tiers],
        }

    no_fr_doc_num_summary = fallback_summary(
        [fallback_entry(document) for document in mirror_index.documents if document.fr_doc_num is None]
    )
    unresolved_summary = fallback_summary([fallback_entry(document) for document in unresolved])
    fallback_resolved = len(no_fr_doc_num_summary["resolved"]) + len(unresolved_summary["resolved"])

    no_file: collections.Counter[str] = collections.Counter()
    no_release: collections.Counter[str] = collections.Counter()
    titles = {document.document_id: document.title for document in mirror_index.documents}
    for document_id, fr in resolved.items():
        pattern = _title_pattern(titles[document_id])
        if not any(stated_file_numbers(fr.docket_ids)):
            no_file[pattern] += 1
        if not any(stated_release_numbers(fr.docket_ids)):
            no_release[pattern] += 1

    resolved_spellings = {d.fr_doc_num for d in mirror_index.documents if d.document_id in resolved}
    outside_only = [d for d in unresolved if _number_key(d.fr_doc_num) in fr_census["outsideSec"]]
    report = {
        "date": started[:10],
        "secDocuments": {
            **sec_census,
            "frDocNumUnreadable": sum(unreadable.values()),
            "frDocNumUnreadableByPrefix": dict(unreadable.most_common()),
        },
        "federalRegister": {
            "records": fr_census["records"],
            "secAgencyRecords": fr_census["secAgencyRecords"],
            "ambiguousNumbers": sorted(fr_index.ambiguous_numbers),
            "distinctReleaseNumbersStated": len(fr_census["releaseNumbers"]),
            "distinctFileNumbersStated": len(fr_census["fileNumbers"]),
            "statementSpellings": dict(fr_census["statements"].most_common()),
            "statementsTheJoinReadsNothingFrom": dict(fr_census["unread"].most_common(40)),
        },
        "coverage": {
            "frDocNumResolvedToCitation": len(resolved_spellings),
            "frDocNumResolvedFraction": (
                round(len(resolved) / sec_census["frDocNumNonNull"], 4) if sec_census["frDocNumNonNull"] else None
            ),
            "frDocNumUnresolved": sorted({document.fr_doc_num for document in unresolved}),
            "frDocNumResolvedOnlyOutsideSec": sorted({document.fr_doc_num for document in outside_only}),
            "resolvedStatingAFileNumber": len(resolved) - sum(no_file.values()),
            "resolvedStatingAReleaseNumber": len(resolved) - sum(no_release.values()),
            "joinableViaFrDocNumDocuments": len(resolved),
            "linkedByCitation": len(by_citation),
            "linkedByReleaseNumber": len(by_release),
            "linkedByFileNumber": len(by_file),
            "linkedByAnyStatement": len(by_citation | by_release | by_file),
            "citationCollisions": citation_collisions,
            "citationsOutsideTheJoinGrammar": len(unspellable),
            "citationsOutsideTheJoinGrammarExamples": sorted(unspellable)[:20],
            "fallbackResolvedDocuments": fallback_resolved,
            "totalJoinableDocuments": len(resolved) + fallback_resolved,
            "sampleChain": {
                SAMPLE_FILE_NUMBER: [
                    {
                        "documentNumber": fr.document_number,
                        "citation": fr.citation.normalized if fr.citation is not None else None,
                        "publicationDate": fr.publication_date,
                        "docketIds": list(fr.docket_ids),
                    }
                    for fr in fr_index.records_stating_file_number(SAMPLE_FILE_NUMBER)
                ],
                "links": [
                    {"path": link.path, "stated": link.stated, "mirrorDocumentId": link.mirror_document.document_id}
                    for link in link_rulemaking_to_mirror(
                        file_number=SAMPLE_FILE_NUMBER, mirror_index=mirror_index, fr_index=fr_index
                    )
                ],
            },
        },
        "fallbacks": {
            "noFrDocNumDocuments": no_fr_doc_num_summary,
            "unresolvedFrDocNumDocuments": unresolved_summary,
        },
        "weakLinks": {
            "resolvedWithoutFileNumber": {"total": sum(no_file.values()), "byTitlePattern": dict(no_file)},
            "resolvedWithoutReleaseNumber": {"total": sum(no_release.values()), "byTitlePattern": dict(no_release)},
        },
        "inputs": [_pin(args.sec_release.joinpath(*MANIFEST)), _pin(args.fr_release.joinpath(*MANIFEST))],
        "command": sys.argv,
        "startedAt": started,
        "finishedAt": datetime.datetime.now(datetime.UTC).isoformat(),
        "elapsedSeconds": round(time.monotonic() - begun, 1),
    }

    print(json.dumps({key: value for key, value in report.items() if key != "inputs"}, indent=1))
    args.receipts.mkdir(parents=True, exist_ok=True)
    receipt_path = args.receipts / "sec-comments-join-coverage-with-fallbacks.jsonl"
    with receipt_path.open("w") as handle:
        handle.write(json.dumps(report) + "\n")
    print(f"receipt: {receipt_path}")


if __name__ == "__main__":
    main()
