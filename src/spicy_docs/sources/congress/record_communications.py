"""Read the House executive communications one Congressional Record issue printed.

The Record prints, on every House sitting day, a section titled
``EXECUTIVE COMMUNICATIONS, ETC.`` -- a ``granuleClass: HOUSE`` CREC granule
with an HTML rendition back to 1994. Each numbered entry in it is one sentence,
and Congress.gov's ``house-communication/{congress}/EC/{number}`` detail record
is a **decomposition of that same sentence**: its ``abstract`` equals the
printed entry under the four normalizations :func:`publisher_normalized` names,
and ``submittingOfficial``, ``submittingAgency``, ``reportNature``,
``legalAuthority`` and the committee referral are spans of it. The publisher
decomposes only from the 114th Congress forward, so this module exists to read
the un-decomposed ones.

What this module is **not**: it does not interpret. The RIN stays
``interpretation/communication_rin.py``'s rule over
:attr:`~RecordCommunicationEntry.report_nature`, and committee names stay whole
names -- splitting the referral tail shatters *Education and the Workforce* and
*Ways and Means* -- so a system code must be resolved against the committee
roster this repository already hosts, never parsed out of the sentence. That
resolver does not exist yet, so ``house_communications.referral_system_code``
is NULL on every reconstructed row.

Four measured failure modes shape the rules here, each with its reason beside
the code: GPO's inline ``[[Page Hnnnn]]`` marker, an issue that prints the
section twice (:func:`executive_communication_granules` takes every match),
committee names that cannot be tokenized, and an official/agency split point
punctuation cannot find (:func:`split_from_clause`, which refuses rather than
guesses). The rules were measured on 216 entries across seven issues and then
scored against the publisher's own decomposition on the overlap era, which
found a fourth publisher normalization (``Pub. L.``), a print dash the Record
spells with four hyphens, and GPO's hyphenated line wrap -- each fixed here
with its reason beside it.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

#: The granule title the House section carries, exactly as GovInfo spells it.
SECTION_TITLE = "EXECUTIVE COMMUNICATIONS, ETC."

#: The GovInfo granule class the House section carries.
SECTION_GRANULE_CLASS = "HOUSE"

#: Every numbered entry in this section is an executive communication, spelled
#: the way ``house_communications.communication_type`` spells it. The section's
#: "ETC." covers the introductory clause, not other communication types: the
#: Record prints memorials and presidential messages under their own headings.
SECTION_COMMUNICATION_TYPE = "ec"

#: A granule title naming this section. Matched loosely on purpose -- the
#: comparison is against the publisher's own title string, whose punctuation
#: and pluralisation are its to change, and a stricter match would silently
#: drop an issue rather than report one.
_SECTION_TITLE_RE = re.compile(r"executive\s+communication", re.IGNORECASE)

#: One printed entry: its number, then everything up to the next numbered
#: entry. Lookahead rather than a line-bounded match, because the Record wraps
#: one entry over many lines and the sentence has to arrive whole.
#:
#: The ``EC-`` prefix is optional because the Record changed its own spelling:
#: every issue sampled from 1996 through 2020 numbers an entry ``1205.`` and
#: every issue from 2021 on numbers it ``EC-1205.``. The overlap measurement
#: found this by reading **zero** entries out of the 117th and 118th sections
#: it had just fetched -- a recall failure a field-by-field score could never
#: have reported, because a section that yields no entries yields nothing to
#: disagree about.
_ENTRY = re.compile(
    r"^\s{0,12}(?:EC-)?(\d{1,5})\.\s+(A\s+letter\s+from\s+.*?)"
    r"(?=^\s{0,12}(?:EC-)?\d{1,5}\.\s+A\s+letter\s+from|\Z)",
    re.MULTILINE | re.DOTALL | re.IGNORECASE,
)
_OPENING = re.compile(r"^A\s+letter\s+from\s+the\s+", re.IGNORECASE)
_TRANSMITTING = re.compile(r",\s+transmitting\s+", re.IGNORECASE)
_PURSUANT = re.compile(r",?\s+pursuant\s+to\s+", re.IGNORECASE)
_REFERRAL = re.compile(
    r";\s*(?P<joint>jointly,?\s*)?to\s+the\s+Committees?\s+on\s+(?P<names>.*?)\.\s*$",
    re.IGNORECASE,
)
#: GPO prints a page-break marker inside the running text. 2 of the 216
#: measured entries carried one and both lost their referral tail to it;
#: stripping it took referral recovery from 214/216 to 216/216. Gated on the
#: marker's own evidence -- the substitution finds nothing when GPO printed
#: none -- the way ``extraction/gpo_normalize.py`` gates its PDF rules.
_PAGE_MARKER = re.compile(r"\s*\[\[Page\s+[^\]]*\]\]\s*")
#: The rule of an underscore rule line that closes a Record section.
_TRAILER = re.compile(r"\s*_{4,}\s*$")
#: A line-final hyphen inside a token, with the rest of that token on the next
#: line: GPO wraps `[Docket No.: FDA-2013-C-1008]` after `FDA-2013-`, and the
#: publisher's own abstract has no space there. See :func:`rejoin_print_wraps`.
_HYPHEN_WRAP = re.compile(r"(?<=[A-Za-z0-9])-\n(?=[A-Za-z0-9])")

#: The three substitutions the publisher's own abstract makes to the print.
#: Named constants rather than inline literals so :func:`_rule_version` can
#: digest them: a published ``abstract`` column is their output, so editing one
#: changes what every reconstructed row states.
_PRINT_DASH = re.compile(r"\s*-{2,}\s*")
_SECTION_ABBREVIATION = re.compile(r"\bSec\.\s*")
_PUBLIC_LAW_ABBREVIATION = re.compile(r"\bPub\.\s*L\.\s*")

#: The comma-group head nouns that begin the agency side of a from-clause.
#:
#: Closed and evidence-backed, not a guess at English. A group is agency-side
#: when its **first or last** word is one of these -- the Record spells an
#: agency either way (*Department of Transportation*, *Agricultural Marketing
#: Service*) and a rule that read only one end would miss 133 of the 216
#: measured entries.
#:
#: ``Office``, ``Division``, ``Directorate``, ``Branch``, ``Center`` and
#: ``Corps`` are deliberately **absent**, each for its own measured reason:
#: the publisher keeps *Directorate of Cooperative and State Programs* and
#: *Regulatory Management Division* on the official's side, and ``Office`` is
#: genuinely ambiguous in the same corpus -- *Office of Regulatory Management
#: and Information* is an office inside EPA while *Office of Personnel
#: Management* is an agency, and no rule over the sentence separates them. A
#: from-clause naming only an excluded word stays unresolved rather than being
#: split at the wrong comma.
AGENCY_HEAD_WORDS: frozenset[str] = frozenset(
    {
        "Administration",
        "Agency",
        "Authority",
        "Board",
        "Bureau",
        "Commission",
        "Corporation",
        "Department",
        "Foundation",
        "Institute",
        "Institution",
        "Service",
        "System",
    }
)


#: Moved by hand when :func:`split_from_clause`'s *reader* changes without its
#: vocabulary changing. A digest over patterns and word lists cannot see a
#: change inside a function -- ``interpretation/citations.py`` says so of its
#: own -- and this rule has already been through one such change: matching a
#: group's last word only took the split from 83 of 216 entries to 203 while
#: every pattern stayed byte-identical.
SPLIT_POLICY_VERSION = "002"


def _rule_version() -> str:
    """A digest over every pattern and vocabulary that decides what a row says.

    Derived, not written: editing a pattern moves this even when someone
    forgets to move a version by hand, and the pinned test then names both.
    The agency head words and the section's own communication type are in the
    input because both change what every affected row publishes.
    """
    parts = [
        f"entry|{_ENTRY.pattern}",
        f"opening|{_OPENING.pattern}",
        f"transmitting|{_TRANSMITTING.pattern}",
        f"pursuant|{_PURSUANT.pattern}",
        f"referral|{_REFERRAL.pattern}",
        f"page-marker|{_PAGE_MARKER.pattern}",
        f"trailer|{_TRAILER.pattern}",
        f"hyphen-wrap|{_HYPHEN_WRAP.pattern}",
        f"print-dash|{_PRINT_DASH.pattern}",
        f"section-abbreviation|{_SECTION_ABBREVIATION.pattern}",
        f"public-law-abbreviation|{_PUBLIC_LAW_ABBREVIATION.pattern}",
        f"communication-type|{SECTION_COMMUNICATION_TYPE}",
        f"split-policy|{SPLIT_POLICY_VERSION}",
        "agency-head-words|" + ",".join(sorted(AGENCY_HEAD_WORDS)),
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


#: The identity of the whole reconstruction rule, for a row that states which
#: rule produced it. ``record-communication`` names the rule; the digest moves
#: when any pattern or vocabulary above does.
RECORD_COMMUNICATION_RULE_VERSION = f"record-communication-{_rule_version()}"


class RecordCommunicationError(ValueError):
    """A granule body this module cannot read as the executive-communications section."""


# --- the publisher normalizations -----------------------------------------------------
#
# Each is one edit the publisher's own `abstract` makes to the sentence the
# Record printed. Named separately because the first byte-for-byte comparison
# said "not equal", which is what a measurement that encodes its own assumption
# looks like: relaxed with these named and nothing else, the abstract *equals*
# the printed entry.
#
# The research named three (§2). The overlap measurement, run on 166 rows the
# rule was not fitted to, named a fourth -- `Pub. L.` -- and widened the print
# dash from `-{2,3}` to `-{2,}`, because the Record prints `----` where the
# publisher prints one dash. Both were found by disagreement with the
# publisher, which is what two ground-truth rows could not have shown.


def fold_print_dash(value: str) -> str:
    """A run of GPO's print dashes folded to the publisher's single `` - ``.

    ``-{2,}`` and not ``-{2,3}``: 114th EC 1773 prints ``Criterion ---- First``
    where the publisher's abstract has one dash, and the narrower rule left the
    remainder standing as a second dash.
    """
    return _PRINT_DASH.sub(" - ", value)


def expand_section_abbreviation(value: str) -> str:
    """The Record's ``Sec.`` expanded to the publisher's ``section``."""
    return _SECTION_ABBREVIATION.sub("section ", value)


def expand_public_law_abbreviation(value: str) -> str:
    """The Record's ``Pub. L.`` expanded to the publisher's ``Public Law``.

    The same kind of edit as ``Sec.``, found the same way -- by the overlap
    measurement, on rows citing the Inspector General Act and the Arms Export
    Control Act, where the two publishers' strings differ in nothing else.
    """
    return _PUBLIC_LAW_ABBREVIATION.sub("Public Law ", value)


def fold_en_dash(value: str) -> str:
    """The en dash the publisher prints in Public Law numbers (``104–121``) folded to the Record's hyphen."""
    return value.replace("–", "-")


def publisher_normalized(value: str) -> str:
    """All four normalizations, in the one order the comparison uses.

    En dash first: folding it to a hyphen before :func:`fold_print_dash` runs
    means a publisher's ``104–121`` and a Record's ``104-121`` reach that rule
    as the same string, and neither is then mistaken for a print dash.
    """
    return fold_print_dash(expand_public_law_abbreviation(expand_section_abbreviation(fold_en_dash(value))))


def rejoin_print_wraps(text: str) -> str:
    """Rejoin a token GPO broke across two printed lines at its own hyphen.

    The Record wraps ``[Docket No.: FDA-2013-C-1008]`` as ``FDA-2013-`` then a
    new line, and collapsing the layout naively leaves ``FDA-2013- C-1008``
    where the publisher has no space; GPO wraps after a digit as readily as
    after a letter. Gated by its own evidence on both sides: the character
    before the hyphen must be alphanumeric -- which keeps a line-final ``--``
    print dash out of it -- and the next line must start with one.
    """
    return _HYPHEN_WRAP.sub("-", text)


def normalized_entry_text(value: str) -> str:
    """One printed entry reduced to a single line, with GPO's print artifacts gone.

    Unicode-normalized (the Record's typographic quotes and dashes), page
    markers stripped, wrapped tokens rejoined, the section's closing rule line
    removed, and runs of whitespace collapsed -- the Record wraps one sentence
    over a dozen indented lines, and the sentence is the fact, not its column
    width. A page marker becomes a line break rather than a space, so a token
    the marker lands inside still meets :func:`rejoin_print_wraps` as a wrap.
    """
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("–", "-").replace("—", "--").replace("’", "'")
    text = _PAGE_MARKER.sub("\n", text)
    # One newline per line break, with the print's indentation gone, so the
    # wrap rule sees `-\n` wherever GPO broke a token.
    text = re.sub(r"[ \t]*\n\s*", "\n", text)
    return _TRAILER.sub("", " ".join(rejoin_print_wraps(text).split()))


# --- one entry ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecordCommunicationEntry:
    """One executive communication, as one Record issue printed it.

    ``entry_text`` is the whole printed sentence, kept beside every derived
    field the way ``house_communications.rin_matched_text`` is kept beside
    ``rin``: a bad parse stays readable from the row, and a field this rule
    could not resolve is a NULL next to the evidence rather than a guess.
    """

    number: int
    communication_type: str
    entry_text: str
    from_clause: str | None
    submitting_official: str | None
    submitting_agency: str | None
    report_nature: str | None
    legal_authority: str | None
    committee_names: tuple[str, ...]
    joint_referral: bool
    rule_version: str
    record_package_id: str | None = None
    record_granule_id: str | None = None

    @property
    def split_resolved(self) -> bool:
        """Whether :func:`split_from_clause` found the official/agency boundary."""
        return self.submitting_official is not None and self.submitting_agency is not None

    @property
    def publisher_abstract(self) -> str:
        """The printed sentence under the publisher's own four normalizations.

        This, not :attr:`entry_text`, is what Congress.gov's ``abstract``
        states for the same communication -- equal on 97.9% of held-out rows.
        The two are kept apart on purpose: a published ``abstract`` column
        should carry the value the publisher would have carried, while
        ``record_entry_text`` stays the print exactly as GPO set it, so a
        disagreement is diagnosable from the row rather than from a re-fetch.
        """
        return publisher_normalized(self.entry_text)


def split_from_clause(from_clause: str) -> tuple[str | None, str | None]:
    """The transmitting official and the agency, or ``(None, None)`` when unresolved.

    The boundary is **not** derivable from punctuation; what is derivable is
    which comma group the agency *starts* at -- the first one whose head noun
    is in :data:`AGENCY_HEAD_WORDS` -- and that reproduced the publisher's own
    split on both ground-truth rows. A from-clause naming no such group
    (``Secretary of Defense``, one group and all role) returns ``(None, None)``,
    and so does one whose *first* group is already the agency: an official has
    to be named before the boundary, or there is no boundary to find. Both are
    the rule refusing, not the row being empty -- the caller keeps the whole
    from-clause beside it, because a guessed split is an invented fact and a
    NULL beside the printed sentence is not.
    """
    groups = [group.strip() for group in from_clause.split(",")]
    for index, group in enumerate(groups):
        if index and _is_agency_group(group):
            return ", ".join(groups[:index]), ", ".join(groups[index:])
    return None, None


def _is_agency_group(group: str) -> bool:
    words = [word.strip(".") for word in group.split()]
    return bool(words) and (words[0] in AGENCY_HEAD_WORDS or words[-1] in AGENCY_HEAD_WORDS)


def _parse_entry(
    number: int,
    entry_text: str,
    package_id: str | None,
    granule_id: str | None,
) -> RecordCommunicationEntry:
    body = _OPENING.sub("", entry_text)
    from_clause: str | None = None
    report_nature: str | None = None
    legal_authority: str | None = None
    committee_names: tuple[str, ...] = ()
    joint = False
    official = agency = None
    parts = _TRANSMITTING.split(body, maxsplit=1)
    if len(parts) == 2:
        from_clause, rest = parts
        official, agency = split_from_clause(from_clause)
        referral = _REFERRAL.search(rest)
        if referral is not None:
            # One name per "Committee(s) on ..." tail, never tokenized: §3.3
            # measured that splitting on "and"/"," shatters *Education and the
            # Workforce* and *Ways and Means*. A joint referral names several,
            # and resolving them to system codes is the roster's job.
            committee_names = _referral_names(referral.group("names"))
            joint = bool(referral.group("joint"))
            rest = rest[: referral.start()]
        # Six of the 216 measured entries cite no authority at all; that is a
        # real absence and a correct NULL, not a rule that failed.
        subject, authority = _split_authority(rest)
        report_nature = subject.rstrip(", ").strip() or None
        legal_authority = None if authority is None else authority.rstrip("; ").strip() or None
    return RecordCommunicationEntry(
        number=number,
        communication_type=SECTION_COMMUNICATION_TYPE,
        entry_text=entry_text,
        from_clause=from_clause,
        submitting_official=official,
        submitting_agency=agency,
        report_nature=report_nature,
        legal_authority=legal_authority,
        committee_names=committee_names,
        joint_referral=joint,
        rule_version=RECORD_COMMUNICATION_RULE_VERSION,
        record_package_id=package_id,
        record_granule_id=granule_id,
    )


def _split_authority(rest: str) -> tuple[str, str | None]:
    """The subject and the cited authority, or the subject alone."""
    parts = _PURSUANT.split(rest, maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], None)


def _referral_names(names: str) -> tuple[str, ...]:
    """The referral tail's committee names, whole.

    A joint referral prints them as a list -- *Appropriations, Transportation
    and Infrastructure, and Ways and Means* -- and the only separator that does
    not also sit inside a name is the comma; ``and`` is never a separator here,
    since it is inside two of those three names. The serial ``and`` that
    introduces the last item is dropped at the front of that one name, which is
    the only place it is not part of a name.
    """
    return tuple(
        stripped for name in names.split(",") if (stripped := re.sub(r"^and\s+", "", name.strip(), flags=re.IGNORECASE))
    )


def parse_record_communications(
    text: str,
    *,
    package_id: str | None = None,
    granule_id: str | None = None,
) -> tuple[RecordCommunicationEntry, ...]:
    """One record per entry the section's text prints, in printed order.

    ``text`` is the granule's derived text -- what ``extraction/body_text``
    returns for the HTML rendition ``GovInfoBodyAcquirer.acquire_granule``
    fetches. ``package_id`` and ``granule_id`` are carried onto every entry so
    a row states the granule that printed it.
    """
    if not isinstance(text, str):
        raise RecordCommunicationError("section text must be a string")
    return tuple(
        _parse_entry(int(number), normalized_entry_text(body), package_id, granule_id)
        for number, body in _ENTRY.findall(text)
    )


def parse_granule_body(body: object) -> tuple[RecordCommunicationEntry, ...]:
    """The entries one acquired CREC granule body printed.

    Takes what ``GovInfoBodyAcquirer.acquire_granule`` returns -- a
    ``GovInfoGranuleBody``, whose ``identity`` is a ``GranuleIdentity`` -- and
    reads the rendition through ``extraction.body_text``, so the derivation is
    the repository's own and the bytes are the ones the acquirer proved.
    """
    from spicy_docs.extraction.body_text import body_text

    # Read directly, never through `getattr(..., None)`: the provenance columns
    # are the row's only locator, and a silent NULL from an upstream rename is
    # worse than an AttributeError naming the attribute that moved.
    identity = body.identity
    return parse_record_communications(
        body_text(body).text,
        package_id=identity.package.package_id,
        granule_id=identity.granule_id,
    )


# --- choosing the granules, and the completeness witness ------------------------------


def executive_communication_granules(records: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    """Every House executive-communications granule id one issue's granule page lists.

    **Every** match, not the first: ``CREC-2004-06-16`` carries two
    (``pt1-PgH4278`` and ``pt2-PgH4285``), and a backfill that took the first
    would silently drop a whole block of numbers (§3.2).
    """
    return tuple(
        str(record["granuleId"])
        for record in records
        if str(record.get("granuleClass") or "") == SECTION_GRANULE_CLASS
        and _SECTION_TITLE_RE.search(str(record.get("title") or ""))
        and record.get("granuleId")
    )


@dataclass(frozen=True, slots=True)
class ContiguityWitness:
    """What one issue's block of EC numbers says about its own completeness.

    Each sampled day's section printed a contiguous, strictly increasing block
    (7 of 7 issues, §6), and EC numbering runs continuously through a Congress.
    So a hole inside one day's block names an entry this rule failed to read,
    and concatenating a Congress's blocks must yield ``1..N``. The check needs
    no external authority, runs over the parsed entries alone, and can fail --
    which is what makes it a witness rather than a restatement.
    """

    first: int | None
    last: int | None
    count: int
    holes: tuple[int, ...]
    strictly_increasing: bool

    @property
    def contiguous(self) -> bool:
        return not self.holes and self.strictly_increasing


def contiguity_witness(entries: Sequence[RecordCommunicationEntry]) -> ContiguityWitness:
    """The block's first and last number, and any hole between them."""
    numbers = [entry.number for entry in entries]
    if not numbers:
        return ContiguityWitness(first=None, last=None, count=0, holes=(), strictly_increasing=True)
    seen = set(numbers)
    return ContiguityWitness(
        first=numbers[0],
        last=numbers[-1],
        count=len(numbers),
        holes=tuple(n for n in range(min(numbers), max(numbers) + 1) if n not in seen),
        strictly_increasing=all(a < b for a, b in pairwise(numbers)),
    )


__all__ = [
    "AGENCY_HEAD_WORDS",
    "RECORD_COMMUNICATION_RULE_VERSION",
    "SECTION_COMMUNICATION_TYPE",
    "SECTION_GRANULE_CLASS",
    "SECTION_TITLE",
    "SPLIT_POLICY_VERSION",
    "ContiguityWitness",
    "RecordCommunicationEntry",
    "RecordCommunicationError",
    "contiguity_witness",
    "executive_communication_granules",
    "expand_public_law_abbreviation",
    "expand_section_abbreviation",
    "fold_en_dash",
    "fold_print_dash",
    "normalized_entry_text",
    "parse_granule_body",
    "parse_record_communications",
    "publisher_normalized",
    "rejoin_print_wraps",
    "split_from_clause",
]
