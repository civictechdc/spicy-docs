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
import bisect
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from spicy_docs.interpretation.bill_stage import infer_stage_from_text
from spicy_docs.interpretation.citations import CITATION_RULES_BY_NAME, find_citations

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


# --- the flattened matching text -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class FlatText:
    """The retained text with line-wrap hyphens closed, and the offsets back to it.

    ``flat[i]`` was read from ``retained[origin[i]]``; ``flat_index[j]`` is
    where ``retained[j]`` landed in ``flat`` (the character before it, for a
    character the flattening dropped). Both directions are needed: the citation
    rule matched in the retained text and the phrase rules match in the flat
    one.
    """

    retained: str
    flat: str
    origin: tuple[int, ...]
    flat_index: tuple[int, ...]

    def to_flat(self, offset: int) -> int:
        return self.flat_index[min(offset, len(self.flat_index) - 1)]

    def to_retained(self, offset: int) -> int:
        return self.origin[min(offset, len(self.origin) - 1)] if self.origin else 0


#: A hyphen at end of line is a print wrap in these documents; the character it
#: joins to is on the next line.  ``‐`` is the Unicode hyphen GPO's own
#: typesetting occasionally sets instead of the ASCII one.
_WRAP_HYPHENS = "-‐"


def flatten(text: str) -> FlatText:
    """Close line-wrap hyphens, space the newlines, and keep both offset maps."""
    out: list[str] = []
    origin: list[int] = []
    index = 0
    size = len(text)
    while index < size:
        character = text[index]
        if character in _WRAP_HYPHENS and index + 1 < size and text[index + 1] == "\n":
            index += 2
            continue
        out.append(" " if character == "\n" else character)
        origin.append(index)
        index += 1
    flat_index = [0] * (size + 1)
    for position, source in enumerate(origin):
        flat_index[source] = position
    for position in range(1, size + 1):
        if flat_index[position] == 0:
            flat_index[position] = flat_index[position - 1]
    return FlatText(text, "".join(out), tuple(origin), tuple(flat_index))


# --- sentences -----------------------------------------------------------------------

#: A sentence may close inside its own quotation marks or parentheses -- this
#: family sets a bill's short title as ``the "PHE Congressional Review Act of
#: 2023."`` and a disposition as ``(ordered favorably reported ... voice
#: vote.)``. A break rule that requires whitespace immediately after the stop
#: reads the whole of the next sentence as part of that title, which is how a
#: hearing held on a *discussion draft* came to be attached to the bill named
#: in the sentence after it.
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+")

#: Tokens that end in a period without ending a sentence. Measured, not
#: guessed: every one of these appears immediately before a would-be break in
#: these eight prints, and ``H.J.`` alone mis-split 20 mentions before it was
#: added -- a bill designator is the one abbreviation this corpus cannot afford
#: to split on, since the split would separate the bill from its own action.
ABBREVIATIONS: frozenset[str] = frozenset(
    {
        "h.r", "h.j", "s.j", "h.con", "s.con", "h.res", "s.res", "hr", "h", "s", "j", "con", "res", "conres",
        "jres", "no", "nos", "mr", "mrs", "ms", "dr", "jr", "sr", "rept", "repts", "rep", "sen", "u.s", "u.s.c",
        "p.l", "pub", "l", "cong", "st", "inc", "co", "corp", "ct", "stat", "doc", "ex", "fed", "reg", "c.f.r",
        "sec", "secs", "art", "vs", "v", "hon", "adm", "gen", "gov", "lt", "col", "maj", "capt", "ph", "d",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sept", "sep", "oct", "nov", "dec", "cal", "dist",
    }
)  # fmt: skip

_LAST_TOKEN = re.compile(r"[\s(\[“‘]")


#: A list number (``1.``), a lettered item (``c.``) or a roman numeral
#: (``II.``) only stands for an entry heading when it *opens* the sentence.
#: Measured, because the obvious version of this rule was wrong: reading any
#: short number as a list marker merged "the House passed H.R. 1121 by a vote
#: of 229 to 118." into the sentence after it, and a merged sentence is exactly
#: how an action gets attached to the wrong bill. Five characters is enough for
#: ``23. `` and ``iii. ``.
_LIST_MARKER = re.compile(r"\d{1,3}|[a-z]|[ivxl]+")
_LIST_MARKER_COLUMN = 5


def sentence_starts(flat: str) -> tuple[int, ...]:
    """Where each sentence begins in the flattened text.

    A break after an abbreviation is never a break -- ``H.J.`` and ``H. Rept.``
    are how this family spells a bill and a report -- and a break after an
    entry marker at the head of its own sentence is not one either.
    """
    starts = [0]
    for match in _SENTENCE_BREAK.finditer(flat):
        left = flat[max(0, match.start() - 14) : match.start() - 1]
        token = _LAST_TOKEN.split(left)[-1].lower() if left else ""
        opening = match.start() - len(token) - 1 - starts[-1] <= _LIST_MARKER_COLUMN
        if token in ABBREVIATIONS or (opening and _LIST_MARKER.fullmatch(token)):
            continue
        starts.append(match.end())
    return tuple(starts)


def sentence_at(starts: Sequence[int], flat: str, offset: int) -> tuple[int, int]:
    """``(begin, end)`` of the sentence that contains ``offset``."""
    index = bisect.bisect_right(starts, offset) - 1
    return starts[index], starts[index + 1] if index + 1 < len(starts) else len(flat)


# --- the print's own action phrasings ------------------------------------------------


@dataclass(frozen=True, slots=True)
class PrintAction:
    """One measured print phrasing, and why it is spelled the way it is.

    ``key`` names the phrasing, never the legislative event: this vocabulary
    describes *what the print wrote*, and the event it means is read off
    ``bill_stage`` by :func:`sealed_stage` or reported as unmapped. Inventing a
    parallel event vocabulary here is exactly what the interpretation package
    forbids.
    """

    key: str
    pattern: str
    note: str = ""

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.IGNORECASE)


#: The public-law spelling, imported rather than re-written: the citation rule
#: already reads all four forms these prints set, including the Bluebook one.
_PUBLIC_LAW = CITATION_RULES_BY_NAME["public_law"].pattern

#: Ordered by precedence, the way ``STAGE_RULES`` is, and for the same reason:
#: the first rule whose match covers a span owns it, so ``discharged from
#: further consideration`` is a discharge and not also a consideration, and
#: ``declined to mark up`` is a refusal and not a markup. Every pattern was
#: derived from the recurring phrasings in these eight prints; the count each
#: one reaches is published, including zero.
PRINT_ACTION_RULES: tuple[PrintAction, ...] = (
    PrintAction(
        "became_public_law",
        rf"became (?:a )?public law|signed into law|{_PUBLIC_LAW}|president \w+ signed|signed by the president",
        "the only phrasing a sealed matcher reaches through the law rung",
    ),
    PrintAction("vetoed", r"veto(?:ed|es)?\b", "no sealed matcher; the veto is not a rung of the ladder"),
    PrintAction(
        "presented_to_president",
        r"presented to the president|transmitted to the president",
        "here so the sealed `presented` rung is reachable from a print phrasing at all",
    ),
    PrintAction(
        "conference",
        r"conference report|appointed conferees|conferees|resolving differences",
        "here so the sealed `conference` rung is reachable; measured near zero in this family",
    ),
    PrintAction(
        "not_considered",
        r"was not considered|was not taken up|declined consideration|declined to (?:consider|take up)",
        "a negative statement: the print says an action did not happen, which no index states",
    ),
    PrintAction("declined_markup", r"declined to mark ?up", "before held_markup, which its text contains"),
    PrintAction("passed_senate", r"passed the senate|senate passed|senate agreed to"),
    PrintAction(
        "passed_house",
        r"passed the house|house passed|passed by the house|house agreed to",
        "the sealed matcher is 'passed house'; the print writes 'passed the House', one word apart",
    ),
    PrintAction("suspension", r"suspend the rules and pass\w*|under suspension of the rules|suspension of the rules"),
    PrintAction("agreed_to", r"was agreed to|agreed to the (?:motion|resolution|amendment)"),
    PrintAction("placed_on_calendar", r"placed on the (?:union|house|senate) calendar"),
    PrintAction("rule_for_consideration", r"providing for consideration of|rule provid\w+ for consideration"),
    PrintAction(
        "ordered_reported", r"ordered (?:to be )?(?:favorably )?reported|ordered [^.;]{0,80}?favorably reported"
    ),
    PrintAction("favorably_reported", r"favorably reported|reported favorably"),
    PrintAction(
        "favorably_forwarded",
        r"favorably forwarded|forwarded [^.;]{0,60}?to the full committee",
        "a subcommittee-to-full-committee step; no sealed matcher and no BILLSTATUS action text for it",
    ),
    PrintAction(
        "received_in_chamber",
        r"received in the (?:senate|house)",
        "before referred, which the same sentence usually also states of the receiving committee",
    ),
    PrintAction(
        "discharged",
        r"\bdischarged\b",
        "the bare verb: the print writes both 'was discharged from further consideration of' "
        "and 'the Committee ... discharged H.R. 2365', and a rule that reads only the first misses the second",
    ),
    PrintAction("report_filed", r"h(?:ouse)? ?rept?\.? ?\d{2,3}[-–]\d{1,4}|house report \d{2,3}[-–]\d{1,4}"),
    PrintAction(
        "reported",
        r"\breported\b",
        "past tense only: the plural noun in a bill's own title "
        "(`to require periodic reviews and updated reports`) is not a committee reporting it, "
        "and reading it as one produced 23 false rows against 162 real ones",
    ),
    PrintAction("held_markup", r"held a mark ?up|met in open mark ?up session|marked up|mark ?up of|\bmark ?up\b"),
    PrintAction("held_hearing", r"held a hearing|hearing on|hearing (?:entitled|titled)|\bhearing\b"),
    PrintAction("referred", r"\breferred\b"),
    PrintAction("introduced", r"\bintroduced\b"),
    PrintAction(
        "included_in",
        r"(?:were|was) included in|provisions of [^.;]{0,60}?included|incorporated into",
        "a bill-to-bill relationship, not a bill action; the commonest multi-bill sentence in the corpus",
    ),
    PrintAction(
        "considered",
        r"(?<!further )\bconsider(?:ed|s)\b|business meeting to consider",
        "the lookbehind keeps 'further consideration' with the discharge that states it",
    ),
)


def _rule_set_version(rules: Sequence[PrintAction]) -> str:
    """A digest over every phrasing's name and pattern, derived rather than written.

    The same device ``citations.CITATION_RULE_SET_VERSION`` uses: editing a
    pattern moves this, so a sidecar pinned against it cannot silently describe
    a different vocabulary from the one that produced it.
    """
    joined = "\n".join(f"{rule.key}|{rule.pattern}" for rule in rules)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


PRINT_ACTION_RULE_SET_VERSION = _rule_set_version(PRINT_ACTION_RULES)

_COMPILED_ACTIONS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (rule.key, rule.compiled()) for rule in PRINT_ACTION_RULES
)


def sealed_stage(phrase: str) -> tuple[str | None, str | None]:
    """``(stage, matcher)`` if ``bill_stage``'s sealed rules read this phrase, else ``(None, None)``.

    Derived, not declared. ``infer_stage_from_text`` returns the default rung
    with ``rule is None`` when nothing matched, and that -- not a rung of this
    module's choosing -- is what "the sealed vocabulary does not reach this
    phrasing" means here.
    """
    finding = infer_stage_from_text(phrase)
    return (None, None) if finding.rule is None else (finding.stage, finding.matcher)


# --- dates the print states ----------------------------------------------------------

_MONTHS: Mapping[str, str] = {
    name: f"{number:02d}"
    for number, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"),
        start=1,
    )
}  # fmt: skip
_PRINT_DATE = re.compile(
    r"\b(" + "|".join(_MONTHS) + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b|\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b",
    re.IGNORECASE,
)


def print_dates(sentence: str) -> tuple[str, ...]:
    """Every date the sentence states, in ISO form, in the order printed.

    Both spellings this family sets: ``On June 13, 2023,`` in prose and
    ``3/24/23`` in a markup-summary heading. A two-digit year is read as
    20xx, which is safe for a 118th-Congress print and stated rather than
    silently assumed.
    """
    found: list[str] = []
    for match in _PRINT_DATE.finditer(sentence):
        if match.group(1):
            found.append(f"{match.group(3)}-{_MONTHS[match.group(1).lower()]}-{int(match.group(2)):02d}")
        else:
            year = int(match.group(6))
            found.append(f"{2000 + year if year < 100 else year}-{int(match.group(4)):02d}-{int(match.group(5)):02d}")
    return tuple(found)


# --- one document's mentions and action rows -----------------------------------------


@dataclass(frozen=True, slots=True)
class ActionRow:
    """One action occurrence, attached to one bill mention.

    ``attachment`` is how the bill was chosen: ``sole`` when the sentence names
    one bill, ``nearest`` when it names several and this mention is the closest
    to the phrase. The two are kept apart because the multi-bill sentence is
    the failure mode this measurement exists to size.
    """

    package_id: str
    bill_id: str
    phrasing: str
    stage: str | None
    matcher: str | None
    attachment: str
    matched_text: str
    bills_in_sentence: int
    page: int | None
    sentence_start: int
    sentence_end: int
    mention_start: int
    mention_end: int
    dates: tuple[str, ...]


def _phrase_matches(sentence: str) -> list[tuple[str, int, int, str]]:
    """``(phrasing, start, end, matched)`` for each phrase this sentence states, precedence first."""
    taken: list[tuple[int, int]] = []
    found: list[tuple[str, int, int, str]] = []
    for key, pattern in _COMPILED_ACTIONS:
        for match in pattern.finditer(sentence):
            if any(match.start() < end and start < match.end() for start, end in taken):
                continue
            taken.append((match.start(), match.end()))
            found.append((key, match.start(), match.end(), match.group(0)))
    found.sort(key=lambda entry: entry[1])
    return found


def measure_document(package_id: str, pages: Sequence[str]) -> dict[str, Any]:
    """Every bill mention in one print, the sentence it sits in, and the actions attached.

    The attachment rule is **nearest mention in the same sentence**: an action
    phrase belongs to the bill whose printed designator is closest to it, ties
    going to the designator that follows the phrase, because the print's own
    grammar puts the measure after the verb (``ordered H.R. 1432 favorably
    reported``, ``held a hearing on H.R. 2691``). The alternative a reader
    might expect -- every bill in the sentence gets the action -- is measured
    beside it as ``sentence_scoped_rows``, because the difference between the
    two *is* the multi-bill exposure.
    """
    text = "\n".join(pages)
    flat = flatten(text)
    starts = sentence_starts(flat.flat)
    findings = find_citations(text, pages=pages, kinds=("bill_number",), congress=PACKAGE_CONGRESS)
    located = [(finding, flat.to_flat(finding.span_start)) for finding in findings]

    by_sentence: dict[tuple[int, int], list[tuple[Any, int]]] = {}
    for finding, position in located:
        by_sentence.setdefault(sentence_at(starts, flat.flat, position), []).append((finding, position))

    rows: list[ActionRow] = []
    phrasing_counts: Counter[str] = Counter()
    phrasing_bills: dict[str, set[str]] = {}
    orphan_phrasings: Counter[str] = Counter()
    sentence_scoped_rows = 0
    mentions_with_action = 0
    multi_bill_mentions = 0

    # Every phrase the print states in a sentence that names no bill at all.
    # This is the ceiling on what a sentence-scoped rule can never reach, and
    # it is not small: this family writes a bill's long title as its own
    # sentence and the disposition as the fragment after it ("...from January
    # 20, 2021 to February 24, 2023. (Ms. Greene) The measure was ordered
    # favorably reported to the House by a vote of 26Y to 20N."), and it writes
    # an en-bloc disposition as a sentence about "the measures". Reaching
    # either needs an *entry* grammar, and the entry is set differently by
    # every committee in the sample.
    for index, begin in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(flat.flat)
        if (begin, end) in by_sentence:
            continue
        for key, _start, _end, _matched in _phrase_matches(flat.flat[begin:end]):
            orphan_phrasings[key] += 1
    for (begin, end), mentions in by_sentence.items():
        sentence = flat.flat[begin:end]
        phrases = _phrase_matches(sentence)
        bills = {finding.target_key for finding, _ in mentions}
        dates = print_dates(sentence)
        if len(bills) > 1:
            multi_bill_mentions += len(mentions)
        sentence_scoped_rows += len(phrases) * len(bills)
        attached: set[int] = set()
        for key, phrase_start, _phrase_end, matched in phrases:
            absolute = begin + phrase_start
            finding, position = min(
                mentions,
                key=lambda entry, anchor=absolute: (abs(entry[1] - anchor), 0 if entry[1] >= anchor else 1),
            )
            stage, matcher = sealed_stage(matched)
            attached.add(id(finding))
            phrasing_counts[key] += 1
            phrasing_bills.setdefault(key, set()).add(finding.target_key)
            rows.append(
                ActionRow(
                    package_id=package_id,
                    bill_id=finding.target_key,
                    phrasing=key,
                    stage=stage,
                    matcher=matcher,
                    attachment="sole" if len(bills) == 1 else "nearest",
                    matched_text=matched,
                    bills_in_sentence=len(bills),
                    page=finding.page,
                    sentence_start=flat.to_retained(begin),
                    sentence_end=flat.to_retained(max(begin, end - 1)) + 1,
                    mention_start=finding.span_start,
                    mention_end=finding.span_end,
                    dates=dates,
                )
            )
        mentions_with_action += len(attached)
    return {
        "package_id": package_id,
        "pages": len(pages),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text_characters": len(text),
        "mentions": len(findings),
        "distinct_bills": len({finding.target_key for finding in findings}),
        "mentions_with_action": mentions_with_action,
        "mentions_in_multi_bill_sentence": multi_bill_mentions,
        "action_rows": len(rows),
        "sentence_scoped_rows": sentence_scoped_rows,
        "orphan_phrases": sum(orphan_phrasings.values()),
        "orphan_phrasings": dict(orphan_phrasings),
        "phrasings": dict(phrasing_counts),
        "phrasing_bills": {key: len(values) for key, values in phrasing_bills.items()},
        "rows": [asdict(row) for row in rows],
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

#: Every action-code row the publisher's own BILLSTATUS guide states for an
#: event one of these prints writes about, read from the retained fixture
#: ``tests/fixtures/billstatus_codes/guide-2026-08-03.md`` rather than asserted
#: here.  The mapping is from this module's phrasing key to the code the guide
#: lists; a phrasing with no entry is one the guide's tables do not name.
GUIDE_CODES: Mapping[str, tuple[str, ...]] = {
    "became_public_law": ("36000", "E40000", "49"),
    "passed_house": ("8000", "81"),
    "passed_senate": ("17000", "82"),
    "suspension": ("H37300",),
    "placed_on_calendar": ("H12410",),
    "rule_for_consideration": ("H1L210",),
    "ordered_reported": ("H12200", "5000"),
    "favorably_reported": ("H12200", "5000", "79"),
    "reported": ("H12200", "5000", "79"),
    "report_filed": ("H12100", "14900"),
    "discharged": ("H12300", "77", "78"),
    "received_in_chamber": ("H14000",),
    "presented_to_president": ("E20000", "28000"),
    "conference": ("H25200", "47", "48"),
    "agreed_to": ("8000", "17000"),
    "held_markup": ("74", "75", "13200"),
    "held_hearing": ("72", "73", "13100"),
    "referred": ("H11100", "2000", "11000"),
    "introduced": ("1000", "10000"),
    "considered": ("H30000",),
}


def guide_action_codes(guide: Path) -> frozenset[str]:
    """Every code the retained BILLSTATUS guide's two code tables list.

    Read from the fixture so :data:`GUIDE_CODES` is checkable against the
    publisher's own text rather than trusted.
    """
    if not guide.exists():
        raise RelationshipError(f"no retained BILLSTATUS guide at {guide}")
    return frozenset(re.findall(r"^\|\s*\*\*([A-Z0-9]{2,6})\*\*\s*\|", guide.read_text(), re.MULTILINE))


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
    unknown = {key: sorted(set(values) - codes) for key, values in GUIDE_CODES.items()}
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
    lines = ["package_id\tbill_id\tphrasing\tstage\tmatcher\tattachment\tbills_in_sentence\tpage\tmatched_text"]
    for document in documents:
        for row in document["rows"]:
            lines.append(
                "\t".join(
                    (
                        row["package_id"],
                        row["bill_id"],
                        row["phrasing"],
                        row["stage"] or "",
                        row["matcher"] or "",
                        row["attachment"],
                        str(row["bills_in_sentence"]),
                        str(row["page"] or ""),
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
            by_mention.setdefault((row["mention_start"], row["mention_end"]), []).append(row)
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
                    if row["bill_id"] == finding.target_key and begin <= row["mention_start"] < finish
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
    multi = [row for row in attached if row["bills_in_sentence"] and int(row["bills_in_sentence"]) > 1]
    sole = [row for row in attached if row["bills_in_sentence"] and int(row["bills_in_sentence"]) == 1]
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
            "sole_bill_sentence": {
                "judged": len(sole),
                "correct": sum(1 for row in sole if row["bill_correct"] == "yes"),
            },
            "multi_bill_sentence": {
                "judged": len(multi),
                "correct": sum(1 for row in multi if row["bill_correct"] == "yes"),
            },
        },
        "recall": {
            "per_stratum": per_stratum,
            "reader_actions": sum(int(row["reader_actions"]) for row in rows),
            "captured": sum(int(row["captured_actions"]) for row in rows),
            "recall": round(weighted_captured / weighted_reader, 4) if weighted_reader else None,
        },
    }


def report(receipt: Path, output: Path) -> None:
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
                "billstatus_codes": list(GUIDE_CODES.get(rule.key, ())),
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
                count for key, count in phrasings.items() if key not in GUIDE_CODES
            ),
        },
        "phrasings": table,
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
    lines.append("| Print phrasing | Rows | Orphan | Bills | `bill_stage` rung | Sealed matcher | BILLSTATUS code |")
    lines.append("| --- | ---: | ---: | ---: | --- | --- | --- |")
    for row in sorted(sidecar["phrasings"], key=lambda entry: (-entry["occurrences"], entry["phrasing"])):
        stage = f"`{row['sealed_stage']}`" if row["sealed_stage"] else "**none**"
        matcher = f"`{row['sealed_matcher']}`" if row["sealed_matcher"] else "—"
        codes = ", ".join(f"`{code}`" for code in row["billstatus_codes"]) or "**none**"
        lines.append(
            f"| `{row['phrasing']}` | {row['occurrences']:,} | {row['orphan_occurrences']:,} | "
            f"{row['distinct_bills']:,} | {stage} | {matcher} | {codes} |"
        )
    mapped = sum(row["occurrences"] for row in sidecar["phrasings"] if row["sealed_stage"])
    total = sum(row["occurrences"] for row in sidecar["phrasings"])
    uncoded = [row["phrasing"] for row in sidecar["phrasings"] if not row["billstatus_codes"]]
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
    lines.append("")
    lines.append(
        f"Only {len(uncoded)} of the {len(sidecar['phrasings'])} phrasings — "
        f"{', '.join(f'`{name}`' for name in uncoded)}, "
        f"**{totals['rows_whose_phrasing_billstatus_has_no_code_for']:,} rows** — name an event the "
        f"publisher's own BILLSTATUS guide states no action code for. Everything else the print says "
        f"about a bill, BILLSTATUS has a code for."
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
    lines.append(
        f"| — one-bill sentence | {attachment['sole_bill_sentence']['judged']} | "
        f"{attachment['sole_bill_sentence']['correct']} | {_rate(attachment['sole_bill_sentence'])} |"
    )
    lines.append(
        f"| — multi-bill sentence | {attachment['multi_bill_sentence']['judged']} | "
        f"{attachment['multi_bill_sentence']['correct']} | {_rate(attachment['multi_bill_sentence'])} |"
    )
    lines.append(
        f"| **A published row is right kind and right bill** | {classification['judged']} | "
        f"{attachment['correct']} | **{_percent(attachment['correct'] / classification['judged'])}** |"
    )
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
    lines.append("")
    lines.append("### Against what BILLSTATUS already states")
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
    for name in ("text", "measure", "sample", "report", "render"):
        phase = sub.add_parser(name)
        phase.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
        if name == "text":
            phase.add_argument("--source-receipt", type=Path, default=DEFAULT_SOURCE)
        if name == "measure":
            phase.add_argument("--mods-receipt", type=Path, default=DEFAULT_MODS)
            phase.add_argument("--export", type=Path, default=DEFAULT_EXPORT)
            phase.add_argument("--guide", type=Path, default=DEFAULT_GUIDE)
        if name == "report":
            phase.add_argument("--output", type=Path, required=True)
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
    elif args.phase == "report":
        report(receipt, args.output)
    elif args.phase == "render":
        render(args.sidecar, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
