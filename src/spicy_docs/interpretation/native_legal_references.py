"""Read the legal targets a native U.S. Code or eCFR observation names, and complete its published row.

A native href is typed only when it is an exact U.S. Code section, Statutes at Large page or numbered public law
(57th Congress on) in a USLM ``ref`` or XHTML ``a``; fragments, subsection tails, ranges, historical act locators and
unfamiliar namespaces stay literal and yield nothing. A source credit or note is read with the shared citation rules
for its kinds, and each finding is a partial reading beside the complete text, never a replacement for it. Whether a
typed target is held anywhere is the host's lookup in the tables it selected, supplied to
:func:`interpret_native_references` as ``resolve``; nothing here reads a table.

Moved from spicy-regs' ``transforms/native_legal_references.py`` (``_interpret``, read at its ``fork/main``
``63a18d7``), where it ran under the same ``native-legal-reference/002`` rule, so every value it publishes is the one
already published.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass

from spicy_docs.interpretation.citations import find_citations
from spicy_docs.schemas.native_reference_rows import NATIVE_LEGAL_REFERENCE_RULE, NATIVE_LEGAL_REFERENCES
from spicy_docs.schemas.tables import Row, TableContractError, digest, json_column, usc_section_key

#: The rule an exact native href is typed under, named in each candidate it yields.
NATIVE_HREF_RULE = "native-legal-exact-href/002"

#: The citation kinds a source credit or note is read for.
TEXT_CITATION_KINDS = ("usc_section", "cfr_section", "public_law", "statutes_at_large", "federal_register_cite")

#: The elements whose href is a legal reference: USLM ``ref``, in the USLM namespace or none, and XHTML ``a``.
_REFERENCE_TAGS = frozenset({"ref", "{http://xml.house.gov/schemas/uslm/1.0}ref", "{http://www.w3.org/1999/xhtml}a"})
_USC_SECTION_HREF = re.compile(r"/us/usc/t([1-9][0-9]*[aA]?)/s([0-9]+[A-Za-z0-9–—-]*)")
_STATUTE_HREF = re.compile(r"/us/stat/([1-9][0-9]*[A-Za-z]?)/([1-9][0-9]*)")
_PUBLIC_LAW_HREF = re.compile(r"/us/pl/([1-9][0-9]*)/([1-9][0-9]*)")
#: The first Congress whose public laws are numbered; an earlier ``/us/pl/`` href is not typed.
_FIRST_NUMBERED_PUBLIC_LAW_CONGRESS = 57
#: A ``cfr_section`` key that names a part, not a section: title and part only.
_CFR_PART_KEY = re.compile(r"[0-9]+-[0-9]+")

#: The host's lookup: a copy of every candidate of a run, in order, and each read text's digest by
#: ``(document_kind, document_key)``, to one outcome per candidate in the same order, each the candidate with every
#: field unchanged plus what the lookup found (spicy-regs ``citation_resolution.resolve_citations``' ``occurrences``).
TargetLookup = Callable[[list[dict[str, object]], dict[tuple[str, str], str]], Iterable[Mapping[str, object]]]


@dataclass(frozen=True, slots=True)
class NativeReferenceReading:
    """What one observation's reading found: its ``interpretation_status``, the typed targets in reading order, and
    the digest of the text it read (``None`` for an href, which reads no text)."""

    status: str
    candidates: tuple[dict[str, object], ...]
    text_sha256: str | None = None


def _document_key(row: Mapping[str, str | None]) -> str:
    """The observation's key in a candidate: its scope and ordinal, which together name it within the table."""
    return f"{row['scope_id']}:{row['occurrence_index']}"


def _href_target(href: str) -> tuple[str, str, str] | None:
    """``(cite_kind, target_key, status)`` for an exact native href, or ``None`` when its shape is not typed."""
    if section := _USC_SECTION_HREF.fullmatch(href):
        return "usc_section", f"{section[1].upper()}-{usc_section_key(section[2])}", "native_section_href"
    if statute := _STATUTE_HREF.fullmatch(href):
        return "statutes_at_large", f"{statute[1].upper()}-{statute[2]}", "native_statute_href"
    if (law := _PUBLIC_LAW_HREF.fullmatch(href)) and int(law[1]) >= _FIRST_NUMBERED_PUBLIC_LAW_CONGRESS:
        return "public_law", f"{law[1]}-public-{law[2]}", "native_public_law_href"
    return None


def interpret_native_reference(row: Mapping[str, str | None]) -> NativeReferenceReading:
    """Read one shaped ``native_legal_references`` row: an href's exact target, or the citations in a note's text.

    An href yields at most one candidate, keyed ``<document key>:href``; text yields one per finding, keyed by its
    position, with its span, the text's digest and the citation rule that found it. A ``cfr_section`` finding that
    names only a part is ``cfr_part``, so no lookup treats it as a section.
    """
    common: dict[str, object] = {
        "document_kind": row["source_family"],
        "document_key": _document_key(row),
        "source_record_key": row["source_record_key"],
    }
    if row["observation_kind"] == "native_reference":
        href = row["href"] or ""
        target = _href_target(href) if row["element_tag"] in _REFERENCE_TAGS else None
        if target is None:
            return NativeReferenceReading("unsupported_href", ())
        kind, key, status = target
        candidate = {
            **common,
            "occurrence_key": f"{common['document_key']}:href",
            "cite_kind": kind,
            "target_key": key,
            "matched_text": href,
            "target_resolved": True,
            "derivation_rule": NATIVE_HREF_RULE,
        }
        return NativeReferenceReading(status, (candidate,))
    note = row["text"] or ""
    text_sha256 = digest(note)
    candidates = tuple(
        {
            **common,
            "occurrence_key": f"{common['document_key']}:{index}",
            "cite_kind": (
                "cfr_part"
                if finding.kind == "cfr_section" and _CFR_PART_KEY.fullmatch(finding.target_key)
                else finding.kind
            ),
            "target_key": finding.target_key,
            "target_resolved": finding.target_resolved,
            "matched_text": finding.matched_text,
            "span_start": finding.span_start,
            "span_end": finding.span_end,
            "text_sha256": text_sha256,
            "derivation_rule": finding.target_rule,
            "derivation_version": finding.rule_version,
        }
        for index, finding in enumerate(find_citations(note, kinds=TEXT_CITATION_KINDS))
    )
    status = "partial_text_findings" if candidates else "no_qualified_text_findings"
    return NativeReferenceReading(status, candidates, text_sha256)


def interpret_native_references(rows: Sequence[Row], *, resolve: TargetLookup) -> list[Row]:
    """Complete shaped observation rows: read each, look every candidate up in one ``resolve`` call, spell the rest.

    One lookup for the whole run, so a distinct target key is read once however many observations name it, and the
    host's bounds apply to the run as they did before the reading moved here. ``resolve`` receives a deep copy of the
    candidates, so it cannot change what they are checked against, and must return one outcome per candidate, in order,
    each keeping every field of its candidate; anything else refuses. Two rows naming one observation (one
    ``scope_id`` and ``occurrence_index``) refuse before the lookup, since their candidates would share their keys.
    ``target_candidates_json`` is :func:`json_column`'s spelling, and each completed row is checked against the
    contract.
    """
    documents: set[str] = set()
    for row in rows:
        document = _document_key(row)
        if document in documents:
            raise TableContractError(f"two rows name observation {document}; a run reads each once")
        documents.add(document)
    readings = [interpret_native_reference(row) for row in rows]
    candidates = [candidate for reading in readings for candidate in reading.candidates]
    texts = {
        (str(row["source_family"]), _document_key(row)): reading.text_sha256
        for row, reading in zip(rows, readings, strict=True)
        if reading.text_sha256 is not None
    }
    outcomes = list(resolve(copy.deepcopy(candidates), texts))
    if len(outcomes) != len(candidates) or any(
        any(field not in outcome or outcome[field] != value for field, value in candidate.items())
        for outcome, candidate in zip(outcomes, candidates, strict=True)
    ):
        raise TableContractError(
            "the target lookup must return one outcome per candidate, in candidate order, each keeping every field of "
            "its candidate"
        )
    completed: list[Row] = []
    start = 0
    for row, reading in zip(rows, readings, strict=True):
        end = start + len(reading.candidates)
        filled = {
            **row,
            "interpretation_status": reading.status,
            "target_candidates_json": json_column([dict(outcome) for outcome in outcomes[start:end]]),
            "rule_version": NATIVE_LEGAL_REFERENCE_RULE,
        }
        completed.append(NATIVE_LEGAL_REFERENCES.checked(filled))
        start = end
    return completed


__all__ = [
    "NATIVE_HREF_RULE",
    "TEXT_CITATION_KINDS",
    "NativeReferenceReading",
    "TargetLookup",
    "interpret_native_reference",
    "interpret_native_references",
]
