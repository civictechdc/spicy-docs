"""The SEC comments join: rulemakings, retained regulations.gov SEC documents, and SEC comment files.

Three corpora, three identity namespaces, joined on statements each side
retains on disk:

* **SEC rulemakings** (``pages.py``) name a file number (``S7-11-23``, the
  comment docket key), release numbers (``34-103320``) and Federal Register
  citations (``89 FR 45894``). The index row states the file number and
  release numbers; the rule page states release numbers, the file number and
  the FR citations.
* **Retained regulations.gov SEC documents** (the Mirrulations mirror's
  ``regs-documents-SEC`` release) carry ``frDocNum`` (``05-18766``,
  ``2024-31178`` -- zero-padded where the Federal Register release is not)
  and almost never a ``docketId``. They carry no FR citation field; the
  citation is derived, not stated.
* **SEC comment files** (``reader.py``) live under a docket directory named
  by the file number, lowercased.

The bridge that makes the FR-citation join provable is the retained Federal
Register release (``fr-full-1994-2026``), whose records state ``volume`` and
``start_page`` per ``document_number`` and whose ``docket_ids`` state
``File No. S7-11-23`` and ``Release No. 34-103320`` for SEC documents. Only
SEC-agency records are indexed, and a number key two distinct Federal Register
numbers normalize to is refused rather than chosen between. A
mirror ``frDocNum`` becomes a citation through it:

    frDocNum ``2024-31178`` --normalize--> ``2024-31178`` (document_number)
        --> volume 90, start_page 2790 --> ``90 FR 2790``.

So the primary link matches an SEC-stated citation against a mirror document's
*derived* citation, and every hop carries its provenance.

The ``frDocNum``-only fallback is accepted only when a release-number ->
``frDocNum`` map is provable: an SEC-stated release number matched against the
Federal Register release's own ``docket_ids`` statements (``Release No.
34-103320``) names the FR document, and its ``document_number`` names the
mirror's ``frDocNum``. The file-number statement is provable the same way
(``File No. S7-11-23``) and is the last tier. Neither fallback ever matches a
mirror ``frDocNum`` directly against an SEC statement -- that map does not
exist on disk.

Every statement is tried, tier by tier -- FR citations, release numbers, the
file number -- and each FR record links once, under the first tier that reached
it. Every link records the tier (``path``), the SEC-side statement, its
normalized form, the bridging FR document and the matched mirror field
(always ``frDocNum`` today; the mirror's ``docketId`` is a regulations.gov
docket id, not an SEC file number, and never joins here). A citation several
SEC records share is narrowed to the records stating this rulemaking's own
release or file number, and refused when none does.

Mirror documents the ``frDocNum`` tiers cannot reach -- no ``frDocNum`` at
all, or one the Federal Register never served under that number (measured on
2026-09-24: the live FR API 404s every unresolved mirror number while serving
era siblings) -- fall back to title + posted date, the last tier. Two
families, both matched against FR *SEC-agency* records only:

* **title-date-agenda**: titles naming the agenda family (the marker, e.g.
  ``Semiannual Regulatory Agenda - Spring 2010``, ``Semi-annual agenda``)
  match the FR SEC-agency agenda records by publication_date within a small
  window; the agenda publishes roughly twice a year. A season can hold more
  than one SEC-agency record (the joint NRC/SEC unified-agenda header beside
  the SEC regulatory-flexibility agenda), and the tier resolves such a
  collision with a documented tie-break ladder -- posted-date equality, then
  a single-SEC-agency record over a composite, then the mirror title's
  season word -- naming the rung that chose, and refuses when no rung can
  (never a silent pick).
* **title-date-sec**: everything else matches FR SEC-agency records by
  normalized title (casefold, curly quotes folded to ASCII, whitespace
  collapsed -- nothing fuzzier) within a tighter date window.

Either tier accepts exactly one candidate and refuses a collision with a
named error; no candidate is a ``mirror-artifact`` result naming the reason.
See :func:`match_sec_document_without_fr_doc_num`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from spicy_docs.interpretation.identifier_shapes import fr_doc_num_release_spelling
from spicy_docs.sources.sec_comments.pages import (
    FR_CITATION_PATTERN,
    NAMED_RELEASE_PATTERN,
    RELEASE_NUMBER_PATTERN,
    SecCommentFile,
    SecRulemaking,
    SecRulePage,
    named_release_number,
)

#: ``89 FR 45894``: one FR citation, volume then page, in the grammar the pages read; the only spelling accepted.
_CITATION = re.compile(rf"\s*{FR_CITATION_PATTERN}\s*")
#: ``frDocNum``/``document_number`` grammar as both releases spell it: a year or series
#: prefix, an optional year segment the C/R series carry (``C1-2010-12986``), and a sequence.
_DOC_NUM = re.compile(r"^(\d{2,4}|[A-Z]{1,2}\d{0,2})(-\d{4})?-(\d{1,6})$")
#: ``Release No. 34-103320`` or ``Release Nos. 33-11275, 34-99679 and IA-6546`` as the FR release's
#: ``docket_ids`` state them; the release splits a list across elements, so it is read over the joined list.
_LIST_SEPARATOR = r"\s*(?:[,;/&]\s*(?:and\s+)?|and\s+)"
_STATED_RELEASES = re.compile(
    rf"(?i:Release\s+Nos?\.)\s*((?:{RELEASE_NUMBER_PATTERN})(?:{_LIST_SEPARATOR}(?:{RELEASE_NUMBER_PATTERN}))*)"
)
_RELEASE_NUMBER = re.compile(RELEASE_NUMBER_PATTERN)
_STATED_NAMED_RELEASE = re.compile(NAMED_RELEASE_PATTERN)
#: A dashed file number as the FR release spells it: ``S7-11-23``, and ``SR- NASDAQ-2021-007`` or
#: ``SR– FINRA–2023–016`` with one space beside a hyphen or en dash; `` - `` never joins two words.
_FILE_NUMBER = r"[a-z0-9]+(?:(?:[-\u2013]\s?|\s[-\u2013])[a-z0-9]+)+"
#: ``File No. S7-11-23`` reads one number; a dash-less one (``File No. 9823633``) keeps its reading, so
#: nothing the one-token grammar read is lost. ``File Nos. SR-DTC-2018-009, SR-FICC-2018-010`` reads the
#: list, continuations dashed only (receipt ``sec-file-number-grammar-2026-09-25``).
_STATED_FILE_NUMBERS = re.compile(
    rf"File\s+No\.\s*({_FILE_NUMBER}|[a-z0-9]+)"
    rf"|File\s+Nos\.\s*((?:{_FILE_NUMBER}|[a-z0-9]+)(?:{_LIST_SEPARATOR}{_FILE_NUMBER})*)",
    re.IGNORECASE,
)
_FILE_DASH = re.compile(r"\s?[-\u2013]\s?")
#: The correct ``raw_name`` spellings that make a Federal Register record an SEC record.
SEC_AGENCY_RAW_NAMES = ("SEC", "SECURITIES AND EXCHANGE COMMISSION")
#: The Federal Register's own normalized agency identity; it names the SEC where ``raw_name`` is
#: misspelled (``SECURITIES AND EXCHANGE COMMISISON``, ``SECURITES ...``, measured 2026-09-25).
SEC_AGENCY_SLUG = "securities-and-exchange-commission"
#: The title marker that puts a mirror document in the agenda family (``Semi-annual agenda``,
#: ``Semiannual Regulatory Agenda - Spring 2010``); searched casefolded.
AGENDA_TITLE_MARKER = "agenda"
#: postedDate window, days, the title-date-agenda tier accepts (the agenda publishes ~twice a year).
AGENDA_DATE_WINDOW_DAYS = 15
#: postedDate window, days, the title-date-sec tier accepts (postedDate is UTC).
TITLE_DATE_WINDOW_DAYS = 2
#: Unicode quotation marks folded to their ASCII spellings before titles compare: the FR release
#: spells curly quotes (``"As/of"``) where the mirror spells straight ones (``"As/of"``),
#: measured on the C1-2018-08 pair.
_TITLE_QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


class SecCommentsJoinError(ValueError):
    """A join input cannot establish its identity: a locator, a statement, or a record it names."""


@dataclass(frozen=True, slots=True)
class FrCitation:
    """One Federal Register citation: the volume and start page both sides normalize to.

    ``spelled`` is the statement as it was read (``89 FR 45894``);
    ``normalized`` is the canonical form the join compares
    (``89 FR 45894`` -- equal spellings, equal citations).
    """

    volume: int
    page: int
    spelled: str

    @property
    def normalized(self) -> str:
        return f"{self.volume} FR {self.page}"


def normalize_fr_citation(spelled: str) -> FrCitation:
    """The one citation grammar both sides must meet: ``89 FR 45894``.

    Anything else -- ``89FR45894``, ``89 F.R. 45894``, a page range -- refuses
    rather than guessing, so a join is always between spellings the sources
    themselves stated.
    """
    match = _CITATION.fullmatch(spelled) if isinstance(spelled, str) else None
    if match is None:
        raise SecCommentsJoinError(
            "FR citation must be the publisher's spelling, e.g. 89 FR 45894; a different spelling refuses"
        )
    return FrCitation(int(match[1]), int(match[2]), " ".join(spelled.split()))


def normalize_fr_doc_num(fr_doc_num: str) -> str:
    """One ``frDocNum``/``document_number`` in the Federal Register release's spelling.

    The mirror pads the sequence to five digits (``2010-00239``) where the
    Federal Register release does not (``2010-239``), one mirror value uses an
    en dash (``E8–27139``), and the C/R series names a year segment the plain
    series does not (``C1-2010-12986``, ``C1-2013-00201``); both sides
    normalize to the release's spelling, the one form the two corpora were
    measured to agree in.

    The spelling mechanics live once in
    :func:`spicy_docs.interpretation.identifier_shapes.fr_doc_num_release_spelling`
    -- the en-dash fold, the zero-padding rule and the measured C7 -> Z7 mirror
    series (regulations.gov's ``C7-14563``/``C7-15181`` for the Register's
    ``Z7-14563``/``Z7-15181``, the 2007 PRA notices, never C -> Z in general) --
    while this function keeps its own grammar, :data:`_DOC_NUM`, and its own
    refusal. A mirror ``frDocNum`` that is a readable spelling the Register
    never served -- the five truncated ``C1-2017-11``-shaped values -- still
    normalizes; the title + date fallback tier is what reaches it.
    """
    value = fr_doc_num.replace("\u2013", "-").strip() if isinstance(fr_doc_num, str) else ""
    match = _DOC_NUM.fullmatch(value)
    if match is None:
        raise SecCommentsJoinError(f"FR document number is not a readable {_DOC_NUM.pattern} spelling: {fr_doc_num!r}")
    return fr_doc_num_release_spelling(value)


@dataclass(frozen=True, slots=True)
class FrDocument:
    """One Federal Register release record's join-relevant fields.

    ``citation`` is derived from the record's own ``volume`` and
    ``start_page``; ``docket_ids`` are the statements the release retained
    (``Release No. 34-103320``, ``File No. S7-11-23``); ``agencies`` are the
    record's ``raw_name`` statements, the witness the agenda tie-break reads
    to tell a single-agency record from a composite.
    """

    document_number: str
    volume: int | None
    start_page: int | None
    end_page: int | None
    publication_date: str | None
    docket_ids: tuple[str, ...]
    title: str | None
    agencies: tuple[str, ...] = ()

    @property
    def citation(self) -> FrCitation | None:
        if self.volume is None or self.start_page is None:
            return None
        return FrCitation(self.volume, self.start_page, f"{self.volume} FR {self.start_page}")


def stated_file_numbers(docket_ids: Iterable[str]) -> Iterable[str]:
    """Every file number an FR record's ``File No.``/``File Nos.`` statements carry, hyphenated and lowercased."""
    joined = ", ".join(docket_id for docket_id in docket_ids if isinstance(docket_id, str))
    for statement in _STATED_FILE_NUMBERS.finditer(joined):
        for number in re.split(_LIST_SEPARATOR, statement[1] or statement[2]):
            yield _FILE_DASH.sub("-", number).lower()


def stated_release_numbers(docket_ids: Iterable[str]) -> Iterable[str]:
    """Every release number an FR record's statements carry, in text order: ``Release No(s).`` lists and act-named releases."""
    joined = ", ".join(docket_id for docket_id in docket_ids if isinstance(docket_id, str))
    found = (*_STATED_RELEASES.finditer(joined), *_STATED_NAMED_RELEASE.finditer(joined))
    for statement in sorted(found, key=lambda match: match.start()):
        if statement.re is _STATED_NAMED_RELEASE:
            yield named_release_number(statement[1], statement[2])
        else:
            yield from (match[0] for match in _RELEASE_NUMBER.finditer(statement[1]))


def record_is_sec_agency(record: dict) -> bool:
    """Whether one Federal Register record lists the SEC, by its ``raw_name`` spelling or the release's agency slug."""
    return any(
        agency.get("raw_name") in SEC_AGENCY_RAW_NAMES or agency.get("slug") == SEC_AGENCY_SLUG
        for agency in record.get("agencies") or ()
        if isinstance(agency, dict)
    )


def fr_document_from_record(record: dict) -> tuple[str, FrDocument] | None:
    """One Federal Register record's normalized number key and join-relevant fields; None without a readable number."""
    number = record.get("document_number")
    if not isinstance(number, str) or not number:
        return None
    try:
        key = normalize_fr_doc_num(number)
    except SecCommentsJoinError:
        return None
    return key, FrDocument(
        document_number=number,
        volume=record.get("volume"),
        start_page=record.get("start_page"),
        end_page=record.get("end_page"),
        publication_date=record.get("publication_date"),
        docket_ids=tuple(value for value in record.get("docket_ids") or () if isinstance(value, str)),
        title=record.get("title"),
        agencies=tuple(
            agency.get("raw_name")
            for agency in record.get("agencies") or ()
            if isinstance(agency, dict) and isinstance(agency.get("raw_name"), str)
        ),
    )


def normalize_sec_title(title: str | None) -> str:
    """The one title spelling both sides compare in: casefolded, curly quotes folded to ASCII, whitespace collapsed.

    After normalization the titles must be exactly equal, so a title+date link
    is always between spellings the sources themselves stated; nothing fuzzier
    is accepted. The quote fold exists because the two releases were measured
    to disagree on quote characters alone (FR ``"As/of"`` vs mirror
    ``"As/of"``), and the collapse because FR titles carry trailing newlines.
    """
    if not isinstance(title, str) or not title:
        return ""
    return " ".join(title.translate(_TITLE_QUOTES).casefold().split())


def _iso_date(value: str | None) -> date | None:
    """The date part of a mirror ``postedDate`` or an FR ``publication_date``; None when absent or unreadable.

    Mirror values carry a UTC time (``2010-04-26T04:00:00Z``); the Federal
    Register states dates alone, so the join compares days only.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


@dataclass
class FrDocumentIndex:
    """The Federal Register release's SEC-agency join keys, built once from its records.

    ``documents`` are every SEC-agency record read. ``_by_number`` keys on
    :func:`normalize_fr_doc_num`; a key two distinct numbers reach (``94-190``
    and ``94-0190``) is listed in ``ambiguous_numbers`` and indexed nowhere, as
    ``unpadded_federal_register_document_number`` refuses one. ``_by_citation``
    keys on ``(volume, start_page)``; ``_by_file_number`` and
    ``_by_release_number`` on the statements in each record's own ``docket_ids``.
    """

    documents: tuple[FrDocument, ...] = ()
    ambiguous_numbers: frozenset[str] = frozenset()
    _by_number: dict[str, tuple[FrDocument, ...]] = field(default_factory=dict)
    _by_citation: dict[tuple[int, int], tuple[FrDocument, ...]] = field(default_factory=dict)
    _by_file_number: dict[str, tuple[FrDocument, ...]] = field(default_factory=dict)
    _by_release_number: dict[str, tuple[FrDocument, ...]] = field(default_factory=dict)

    @classmethod
    def from_records(cls, records: Iterable[dict]) -> FrDocumentIndex:
        """Index the SEC-agency release records: O(N), each number normalized once, then O(1) lookups."""
        by_number: dict[str, list[FrDocument]] = defaultdict(list)
        for row in records:
            record = row.get("record", row)
            if record_is_sec_agency(record) and (read := fr_document_from_record(record)) is not None:
                by_number[read[0]].append(read[1])
        ambiguous = frozenset(key for key, found in by_number.items() if len({d.document_number for d in found}) > 1)
        by_citation: dict[tuple[int, int], list[FrDocument]] = defaultdict(list)
        # Keyed by document number, so a record stating one number twice is indexed once.
        by_file: dict[str, dict[str, FrDocument]] = defaultdict(dict)
        by_release: dict[str, dict[str, FrDocument]] = defaultdict(dict)
        for key, documents in by_number.items():
            if key in ambiguous:
                continue
            for document in documents:
                if (citation := document.citation) is not None:
                    by_citation[(citation.volume, citation.page)].append(document)
                for file_number in stated_file_numbers(document.docket_ids):
                    by_file[file_number][document.document_number] = document
                for release_number in stated_release_numbers(document.docket_ids):
                    by_release[release_number][document.document_number] = document
        return cls(
            documents=tuple(document for documents in by_number.values() for document in documents),
            ambiguous_numbers=ambiguous,
            _by_number={key: tuple(values) for key, values in by_number.items() if key not in ambiguous},
            _by_citation={key: tuple(values) for key, values in by_citation.items()},
            _by_file_number={key: tuple(values.values()) for key, values in by_file.items()},
            _by_release_number={key: tuple(values.values()) for key, values in by_release.items()},
        )

    def citation_for_fr_doc_num(self, fr_doc_num: str) -> tuple[FrDocument, ...]:
        """The FR records one ``frDocNum`` names, in its normalized spelling."""
        try:
            return self._by_number.get(normalize_fr_doc_num(fr_doc_num), ())
        except SecCommentsJoinError:
            return ()

    def documents_at_citation(self, citation: FrCitation) -> tuple[FrDocument, ...]:
        return self._by_citation.get((citation.volume, citation.page), ())

    def records_stating_file_number(self, file_number: str) -> tuple[FrDocument, ...]:
        return self._by_file_number.get(file_number.lower(), ())

    def records_stating_release_number(self, release_number: str) -> tuple[FrDocument, ...]:
        return self._by_release_number.get(release_number, ())


@dataclass(frozen=True, slots=True)
class MirrorSecDocument:
    """One retained regulations.gov SEC document's join-relevant fields, in the release's spellings."""

    document_id: str
    fr_doc_num: str | None
    docket_id: str | None
    title: str | None
    document_type: str | None
    posted_date: str | None


def mirror_document_from_record(row: dict) -> MirrorSecDocument:
    """Read one retained regulations.gov document envelope (``record.data.attributes`` shape)."""
    record = row.get("record", row)
    data = record.get("data", record)
    attributes = data.get("attributes", {}) if isinstance(data, dict) else {}
    document_id = data.get("id") if isinstance(data, dict) else None
    if not isinstance(document_id, str) or not document_id:
        raise SecCommentsJoinError("regulations.gov document record states no id")
    fr_doc_num = attributes.get("frDocNum")
    return MirrorSecDocument(
        document_id=document_id,
        fr_doc_num=fr_doc_num if isinstance(fr_doc_num, str) and fr_doc_num else None,
        docket_id=attributes.get("docketId"),
        title=attributes.get("title"),
        document_type=attributes.get("documentType"),
        posted_date=attributes.get("postedDate"),
    )


@dataclass
class MirrorSecIndex:
    """The retained SEC documents, indexed by their join keys."""

    documents: tuple[MirrorSecDocument, ...]
    _by_fr_doc_num: dict[str, tuple[MirrorSecDocument, ...]] = field(default_factory=dict)
    _by_docket_id: dict[str, tuple[MirrorSecDocument, ...]] = field(default_factory=dict)

    @classmethod
    def from_records(cls, records: Iterable[dict]) -> MirrorSecIndex:
        documents = tuple(mirror_document_from_record(row) for row in records)
        by_fr_doc_num: dict[str, list[MirrorSecDocument]] = defaultdict(list)
        by_docket_id: dict[str, list[MirrorSecDocument]] = defaultdict(list)
        for document in documents:
            if document.fr_doc_num is not None:
                try:
                    by_fr_doc_num[normalize_fr_doc_num(document.fr_doc_num)].append(document)
                except SecCommentsJoinError:
                    continue
            if isinstance(document.docket_id, str) and document.docket_id:
                by_docket_id[document.docket_id].append(document)
        return cls(
            documents=documents,
            _by_fr_doc_num={key: tuple(values) for key, values in by_fr_doc_num.items()},
            _by_docket_id={key: tuple(values) for key, values in by_docket_id.items()},
        )

    def documents_for_fr_doc_num(self, fr_doc_num: str) -> tuple[MirrorSecDocument, ...]:
        try:
            return self._by_fr_doc_num.get(normalize_fr_doc_num(fr_doc_num), ())
        except SecCommentsJoinError:
            return ()

    def documents_for_docket_id(self, docket_id: str) -> tuple[MirrorSecDocument, ...]:
        return self._by_docket_id.get(docket_id, ())


@dataclass
class FrAgendaIndex:
    """The FR SEC-agency agenda records, keyed by publication_date, for the title-date-agenda tier.

    A season can carry more than one SEC-agency record (the joint NRC/SEC
    unified-agenda header beside the SEC regulatory-flexibility agenda); the
    matcher resolves that collision with the documented tie-break ladder and
    refuses when no rung can choose -- it never picks one silently.
    """

    _by_date: dict[date, tuple[FrDocument, ...]] = field(default_factory=dict)

    @classmethod
    def from_fr_documents(cls, documents: Iterable[FrDocument]) -> FrAgendaIndex:
        """Index the SEC-agency agenda records: O(N) in documents, then O(dates) lookups."""
        by_date: dict[date, list[FrDocument]] = defaultdict(list)
        for document in documents:
            published = _iso_date(document.publication_date)
            if published is None or AGENDA_TITLE_MARKER not in normalize_sec_title(document.title):
                continue
            by_date[published].append(document)
        return cls(_by_date={key: tuple(values) for key, values in by_date.items()})

    def candidates_near(self, posted: date, *, days: int = AGENDA_DATE_WINDOW_DAYS) -> tuple[FrDocument, ...]:
        """Every agenda record whose publication_date lies within ``days`` of ``posted``."""
        matched: list[FrDocument] = []
        for published, documents in self._by_date.items():
            if abs((posted - published).days) <= days:
                matched.extend(documents)
        return tuple(matched)


@dataclass
class FrSecTitleIndex:
    """The FR SEC-agency records, keyed by normalized title, for the title-date-sec tier."""

    _by_title: dict[str, tuple[FrDocument, ...]] = field(default_factory=dict)

    @classmethod
    def from_fr_documents(cls, documents: Iterable[FrDocument]) -> FrSecTitleIndex:
        """Index the SEC-agency records by :func:`normalize_sec_title`: O(N) in documents, then O(1) lookups."""
        by_title: dict[str, list[FrDocument]] = defaultdict(list)
        for document in documents:
            key = normalize_sec_title(document.title)
            if key:
                by_title[key].append(document)
        return cls(_by_title={key: tuple(values) for key, values in by_title.items()})

    def candidates_for(self, title: str, posted: date, *, days: int = TITLE_DATE_WINDOW_DAYS) -> tuple[FrDocument, ...]:
        """Every SEC record whose normalized title equals ``title`` and whose publication_date lies within ``days`` of ``posted``."""
        matched: list[FrDocument] = []
        for document in self._by_title.get(normalize_sec_title(title), ()):
            published = _iso_date(document.publication_date)
            if published is not None and abs((posted - published).days) <= days:
                matched.append(document)
        return tuple(matched)


@dataclass(frozen=True, slots=True)
class MatchResult:
    """One title+date fallback outcome for a mirror document the ``frDocNum`` tiers cannot reach.

    ``tier`` is ``title-date-agenda``, ``title-date-sec``, or
    ``mirror-artifact`` -- never resolved by title+date either, with
    ``reason`` naming the failed check. ``stated_title`` and ``posted_date``
    are the mirror's own spellings: the provenance of the link.
    ``tie_break`` names the agenda tie-break rung that chose one of several
    candidates (``posted-date equality``, ``single SEC agency``,
    ``title season word``); it is None whenever no collision was resolved.
    """

    tier: str
    fr_document: FrDocument | None
    reason: str | None = None
    stated_title: str | None = None
    posted_date: str | None = None
    tie_break: str | None = None

    @property
    def citation(self) -> FrCitation | None:
        return self.fr_document.citation if self.fr_document is not None else None


class FrCollisionError(SecCommentsJoinError):
    """A join tier met more than one FR record it cannot choose between; no link is emitted rather than a guess."""

    def __init__(self, tier: str, stated: str, document_numbers: Iterable[str]) -> None:
        self.tier = tier
        self.document_numbers = tuple(document_numbers)
        super().__init__(f"{tier} for {stated} collides on FR records {', '.join(self.document_numbers)}")


#: A season word with its year, as the mirror's agenda titles state it (``Spring 2011``); the
#: FR agenda records' own titles carry no season word (measured), so this rung exists for
#: season-worded FR titles and is exercised synthetically, not by the retained corpus.
_SEASON_PHRASE = re.compile(r"\b(spring|summer|fall|winter)\s+\d{4}\b", re.IGNORECASE)


def _single_sec_agency(document: FrDocument) -> bool:
    """Whether a record names only the SEC among its agencies (a composite like the joint NRC/SEC
    unified-agenda header names more; an empty agency list is unknown, never single)."""
    return bool(document.agencies) and all(name in SEC_AGENCY_RAW_NAMES for name in document.agencies)


def _resolve_agenda_collision(
    candidates: tuple[FrDocument, ...], posted: date, stated_title: str
) -> tuple[FrDocument, str] | None:
    """One agenda candidate when the tie-break ladder can choose, naming the rung that chose; None refuses.

    Ladder, each rung keeping the survivors of the previous one -- falling back
    to that previous set when it would empty, because a rung that eliminates
    everyone did not discriminate:

    1. **posted-date equality**: the record published on the mirror's posted date;
    2. **single SEC agency**: a record naming only the SEC, over a multi-agency composite
       (the mirror document is the SEC's own posted copy, so the joint NRC/SEC
       unified-agenda header is the wrong record -- measured on both retained collisions);
    3. **title season word**: the mirror title's season phrase (``spring 2011``) in the
       record's normalized title.

    Exactly one survivor after a rung is the resolution, named by that rung's field;
    several survivors -- or a ladder that never narrows to one -- refuses (None), so
    a resolution always says which field chose and a refusal never silently picks.
    """
    survivors = list(candidates)
    exact = [document for document in survivors if _iso_date(document.publication_date) == posted]
    if len(exact) == 1:
        return exact[0], "posted-date equality"
    if exact:
        survivors = exact
    single = [document for document in survivors if _single_sec_agency(document)]
    if len(single) == 1:
        return single[0], "single SEC agency"
    if single:
        survivors = single
    season = _SEASON_PHRASE.search(stated_title or "")
    if season is not None:
        phrase = " ".join(season[0].split()).casefold()
        worded = [document for document in survivors if phrase in normalize_sec_title(document.title)]
        if len(worded) == 1:
            return worded[0], "title season word"
        if worded:
            survivors = worded
    return None


def match_sec_document_without_fr_doc_num(
    title: str | None,
    posted_date: str | None,
    fr_agenda_index: FrAgendaIndex,
    fr_sec_index: FrSecTitleIndex,
) -> MatchResult:
    """The last join tier: match a mirror document the ``frDocNum`` tiers cannot reach by title + posted date.

    Two families, per the mirror's stored title:

    * agenda family (title contains the marker, casefolded) ->
      ``title-date-agenda``: the FR SEC-agency agenda records whose
      publication_date lies within :data:`AGENDA_DATE_WINDOW_DAYS` of the
      mirror's ``postedDate`` (the agenda publishes ~twice a year, so one
      season is the only sensible candidate set). Several candidates are
      resolved by the :func:`_resolve_agenda_collision` ladder, whose result
      names the rung that chose; a ladder that cannot choose refuses.
    * everything else -> ``title-date-sec``: the FR SEC-agency records whose
      :func:`normalize_sec_title` title equals the mirror's and whose
      publication_date lies within :data:`TITLE_DATE_WINDOW_DAYS`
      (``postedDate`` is UTC; the FR states days only, so days are compared).

    One candidate wins and the result carries the matched FR document, its
    citation and the tier; several candidates refuse with
    :class:`FrCollisionError` rather than guessing; none is a
    ``mirror-artifact`` result whose ``reason`` names the failed check.
    """
    if not isinstance(title, str) or not title:
        return MatchResult("mirror-artifact", None, "no title", title, posted_date)
    posted = _iso_date(posted_date)
    if posted is None:
        return MatchResult("mirror-artifact", None, "no readable posted date", title, posted_date)
    if AGENDA_TITLE_MARKER in normalize_sec_title(title):
        candidates = fr_agenda_index.candidates_near(posted)
        if not candidates:
            return MatchResult(
                "mirror-artifact",
                None,
                f"no SEC agency agenda FR record within +/-{AGENDA_DATE_WINDOW_DAYS} days",
                title,
                posted_date,
            )
        if len(candidates) == 1:
            return MatchResult("title-date-agenda", candidates[0], None, title, posted_date)
        resolved = _resolve_agenda_collision(candidates, posted, title)
        if resolved is None:
            raise FrCollisionError(
                "title-date-agenda", f"{title!r} @ {posted_date}", (document.document_number for document in candidates)
            )
        document, tie_break = resolved
        return MatchResult("title-date-agenda", document, None, title, posted_date, tie_break)
    candidates = fr_sec_index.candidates_for(title, posted)
    if len(candidates) > 1:
        raise FrCollisionError(
            "title-date-sec", f"{title!r} @ {posted_date}", (document.document_number for document in candidates)
        )
    if candidates:
        return MatchResult("title-date-sec", candidates[0], None, title, posted_date)
    return MatchResult(
        "mirror-artifact",
        None,
        f"title matches no SEC agency FR record within +/-{TITLE_DATE_WINDOW_DAYS} days",
        title,
        posted_date,
    )


@dataclass(frozen=True, slots=True)
class SecMirrorLink:
    """One rulemaking -> mirror-document link, with the statement and bridge that proved it.

    ``path`` is the tier that produced it: ``fr_citation`` (the SEC side
    stated the citation the mirror's FR record derives to), ``release_number``
    (an SEC-stated release number named the FR record through its own
    ``docket_ids``, the provable release -> frDocNum map), or ``file_number``
    (the SEC file number named the FR record through ``File No.``). A
    ``frDocNum`` is only ever matched through one of these bridges, never
    directly against an SEC statement. ``matched_field`` is the mirror field
    that closed the link -- ``frDocNum`` today.
    """

    path: str
    matched_field: str
    mirror_document: MirrorSecDocument
    stated: str
    citation: FrCitation | None
    fr_document: FrDocument | None


@dataclass(frozen=True, slots=True)
class SecCommentLink:
    """One rulemaking -> comment-file link: the file number the docket directory spells."""

    matched_field: str
    sec_file_number: str
    docket: str
    comment: SecCommentFile


def _documents_at_citation(
    citation: FrCitation, fr_index: FrDocumentIndex, release_numbers: tuple[str, ...], file_number: str | None
) -> tuple[FrDocument, ...]:
    """The FR records at one citation; several are narrowed to those stating this rulemaking's own numbers.

    Several SEC records can start on one page (``89 FR 19292`` holds three
    corrections). Each record's own ``docket_ids`` release and file numbers
    choose; when no record states the rulemaking's, the citation refuses with
    :class:`FrCollisionError`, as the title-date tiers do, never a silent pick.
    """
    candidates = fr_index.documents_at_citation(citation)
    if len(candidates) < 2:
        return candidates
    docket = file_number.lower() if file_number is not None else None
    chosen = tuple(
        document
        for document in candidates
        if any(number in release_numbers for number in stated_release_numbers(document.docket_ids))
        or docket in set(stated_file_numbers(document.docket_ids))
    )
    if not chosen:
        raise FrCollisionError("fr_citation", citation.spelled, (document.document_number for document in candidates))
    return chosen


def link_rulemaking_to_mirror(
    *,
    file_number: str | None,
    release_numbers: Iterable[str] = (),
    fr_citations: Iterable[str] = (),
    mirror_index: MirrorSecIndex,
    fr_index: FrDocumentIndex,
) -> tuple[SecMirrorLink, ...]:
    """Link one rulemaking to its retained mirror documents through every statement it makes.

    Tiers run in order: (1) every FR citation the rule page stated, matched
    against mirror documents whose ``frDocNum`` the Federal Register release
    derives to the same citation; (2) every release number, through the FR
    release's own ``Release No.`` statements -- the provable release ->
    ``frDocNum`` map; (3) the file number, through its ``File No.``
    statements. Each FR record links once, under the first tier that reached
    it, so a link's ``path`` names its strongest proof. A statement that names
    no FR record yields no link, never a guessed one.
    """
    release_numbers = tuple(release_numbers)
    tiers = [
        ("fr_citation", citation.spelled, _documents_at_citation(citation, fr_index, release_numbers, file_number))
        for citation in map(normalize_fr_citation, fr_citations)
    ]
    tiers += [("release_number", number, fr_index.records_stating_release_number(number)) for number in release_numbers]
    if file_number is not None:
        tiers.append(("file_number", file_number, fr_index.records_stating_file_number(file_number)))
    reached: set[str] = set()
    links: list[SecMirrorLink] = []
    for path, stated, fr_documents in tiers:
        for fr_document in fr_documents:
            if fr_document.document_number in reached:
                continue
            reached.add(fr_document.document_number)
            links.extend(
                SecMirrorLink(path, "frDocNum", mirror_document, stated, fr_document.citation, fr_document)
                for mirror_document in mirror_index.documents_for_fr_doc_num(fr_document.document_number)
            )
    return tuple(links)


def comments_by_docket(comments: Iterable[SecCommentFile]) -> dict[str, tuple[SecCommentFile, ...]]:
    """Group comment files by docket in one pass, so a batch join hands each rulemaking only its own: O(N) overall."""
    groups: dict[str, list[SecCommentFile]] = defaultdict(list)
    for comment in comments:
        groups[comment.docket].append(comment)
    return {docket: tuple(files) for docket, files in groups.items()}


def link_file_number_to_comments(file_number: str, comments: Iterable[SecCommentFile]) -> tuple[SecCommentLink, ...]:
    """Link one rulemaking to the comment files of its own docket.

    The docket directory is the file number lowercased (``S7-11-23`` ->
    ``s7-11-23``), the publisher's own spelling, and the comment's ``docket``
    must be exactly it; comments of any other docket are the caller's mismatch
    to observe, never linked by guess.
    """
    docket = file_number.lower()
    return tuple(
        SecCommentLink(matched_field="file_number", sec_file_number=file_number, docket=docket, comment=comment)
        for comment in comments
        if comment.docket == docket
    )


def _citation_provenance(link: SecMirrorLink) -> dict:
    return {
        "path": link.path,
        "matched_field": link.matched_field,
        "stated": link.stated,
        "fr_document_number": link.fr_document.document_number if link.fr_document is not None else None,
        "fr_docket_ids": list(link.fr_document.docket_ids) if link.fr_document is not None else None,
        "mirror_document_id": link.mirror_document.document_id,
    }


def emit_docket_record(
    *,
    file_number: str,
    title: str,
    rule_url: str | None,
    comment_index_url: str | None,
    fr_citations: Iterable[FrCitation],
    release_numbers: Iterable[str],
    links: Iterable[SecMirrorLink],
) -> dict:
    """One docket record: the SEC statements, the derived FR citations, and the linked mirror documents.

    ``fr_citations`` lists the citations the SEC side stated, each with the
    provenance of every link that closed on it, then the citations derived
    through the fallback bridges that the SEC side did not state. Provenance
    keeps the tier, the SEC statement, the bridging FR document number and
    ``docket_ids``, and the matched mirror document id at every hop.
    """
    links = tuple(links)

    def entry(citation: FrCitation) -> dict:
        return {
            "spelled": citation.spelled,
            "normalized": citation.normalized,
            "volume": citation.volume,
            "page": citation.page,
            "provenance": [],
        }

    # Stated citations first, in their order; a link's citation joins its entry or opens a derived one.
    citations = {citation.normalized: entry(citation) for citation in fr_citations}
    for link in links:
        if link.citation is not None:
            citations.setdefault(link.citation.normalized, entry(link.citation))["provenance"].append(
                _citation_provenance(link)
            )
    return {
        "kind": "sec-comments-docket",
        "file_number": file_number,
        "docket": file_number.lower(),
        "title": title,
        "rule_url": rule_url,
        "comment_index_url": comment_index_url,
        "release_numbers": list(release_numbers),
        "fr_citations": list(citations.values()),
        "mirror_documents": [
            {
                "document_id": link.mirror_document.document_id,
                "frDocNum": link.mirror_document.fr_doc_num,
                "docketId": link.mirror_document.docket_id,
                "title": link.mirror_document.title,
                "documentType": link.mirror_document.document_type,
                "postedDate": link.mirror_document.posted_date,
                "links": [_citation_provenance(link)],
            }
            for link in links
        ],
        "comment_count": 0,
    }


def emit_comment_record(link: SecCommentLink) -> dict:
    """One comment record linked to its docket, in the comment file's own spellings."""
    comment = link.comment
    return {
        "kind": "sec-comment",
        "docket": comment.docket,
        "file_number": link.sec_file_number,
        "url": comment.url,
        "file_name": comment.file_name,
        "format": comment.format,
        "link_text": comment.link_text,
        "letter_type": comment.letter_type,
        "date": comment.date,
        "link": {
            "matched_field": link.matched_field,
            "sec_file_number": link.sec_file_number,
            "docket": link.docket,
        },
    }


def join_sec_comments(
    rulemaking: SecRulemaking,
    comments: Iterable[SecCommentFile],
    *,
    mirror_index: MirrorSecIndex,
    fr_index: FrDocumentIndex,
    rule_page: SecRulePage | None = None,
) -> dict:
    """The combined emission: one docket record and every linked comment record.

    ``rulemaking`` is a :class:`SecRulemaking` index row; ``rule_page`` the
    per-rule page that states its FR citations (the index does not state
    them). Release numbers are the union of both statements; a rule page that
    states a different file number refuses, because the two pages would not be
    one rulemaking. Comments whose docket is not this file number are reported
    as mismatches and never linked; a batch caller passes each rulemaking its
    own :func:`comments_by_docket` group.
    """
    file_number = rulemaking.file_number
    if file_number is None:
        raise SecCommentsJoinError("rulemaking states no file number; a comment docket cannot be derived")
    docket = file_number.lower()
    if rule_page is not None and rule_page.file_number is not None and rule_page.file_number != docket:
        raise SecCommentsJoinError(f"rule page states file number {rule_page.file_number!r}, not the row's {docket!r}")
    release_numbers = list(
        dict.fromkeys((*rulemaking.release_numbers, *(rule_page.release_numbers if rule_page else ())))
    )
    citations = list(dict.fromkeys(rule_page.fr_citations if rule_page else ()))
    links = link_rulemaking_to_mirror(
        file_number=file_number,
        release_numbers=release_numbers,
        fr_citations=citations,
        mirror_index=mirror_index,
        fr_index=fr_index,
    )
    comments = tuple(comments)
    comment_links = link_file_number_to_comments(file_number, comments)
    record = emit_docket_record(
        file_number=file_number,
        title=rulemaking.title,
        rule_url=rulemaking.rule_url,
        comment_index_url=rulemaking.comment_index_url,
        fr_citations=tuple(normalize_fr_citation(citation) for citation in citations),
        release_numbers=release_numbers,
        links=links,
    )
    record["comment_count"] = len(comment_links)
    record["mismatched_comment_dockets"] = sorted({comment.docket for comment in comments} - {docket})
    return {
        "docket": record,
        "comments": [emit_comment_record(link) for link in comment_links],
    }
