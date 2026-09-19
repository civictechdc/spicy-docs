"""One frozen, versioned profile per target vocabulary, and the registry that holds them.

A profile is data, the way ``interpretation.bill_stage.STAGE_RULES`` is data:
its rules are a tuple of frozen records a reviewer reads as a ladder, and
every node the parser places names one of them. Three kinds of rule are kept
distinct on purpose, because they carry different authority when a real
document disagrees with them:

- ``schema`` -- the pinned DTD or XSD requires it; a violation is a schema
  finding, never something the parser works around.
- ``guide`` -- the publisher's user guide states it as convention; the guide
  and a real section can disagree, and when they do the section is evidence
  and the guide is convention (a ``guide`` rule cites the guide's section).
- ``heuristic`` -- this repository measured it on real renditions and it
  earns its place only by the benchmark; a ``heuristic`` rule cites the
  measurement.

The schema bundle is pinned by digest and stored under ``schemas/``; the guide
is pinned by the digest of the markdown fetched once from the publisher's
repository (``GuideReference``). Nothing here reads a file at import time:
``schema_path`` and ``check_schema_bundle`` are the only functions that touch
the package's own data, and a test runs the latter.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Literal

RuleKind = Literal["schema", "guide", "heuristic"]
RULE_KINDS: tuple[RuleKind, ...] = ("schema", "guide", "heuristic")


class ProfileError(ValueError):
    """A profile, or the bundle it pins, is not what the registry states."""


@dataclass(frozen=True, slots=True)
class Rule:
    """One named rule: what it decides, the authority it rests on, and where that is stated."""

    name: str
    kind: RuleKind
    statement: str
    source: str

    def __post_init__(self) -> None:
        if self.kind not in RULE_KINDS:
            raise ProfileError(f"rule {self.name!r} has kind {self.kind!r}; expected one of {', '.join(RULE_KINDS)}")


@dataclass(frozen=True, slots=True)
class SchemaFile:
    """One file of a pinned bundle: its name as the publisher spells it, its digest and its path under ``schemas/``."""

    name: str
    sha256: str
    path: str


@dataclass(frozen=True, slots=True)
class GuideReference:
    """The publisher's guide as fetched once: where, which revision, and the digest of the markdown."""

    url: str
    raw_url: str
    revision: str
    sha256: str
    fetched_on: str


@dataclass(frozen=True, slots=True)
class Applicability:
    """Which publisher collections and renditions a profile reconstructs, and the rule that says so."""

    collections: tuple[str, ...]
    renditions: tuple[str, ...]
    rule: str

    def applies(self, *, collection: str, rendition: str) -> bool:
        return collection in self.collections and rendition in self.renditions


@dataclass(frozen=True, slots=True)
class Profile:
    """The frozen record §3.2 of the proposal names; ``family`` and ``version`` identify it on every derivative."""

    family: str
    version: str
    applicability: Applicability
    schema_bundle: tuple[SchemaFile, ...]
    guide: GuideReference
    rules: tuple[Rule, ...]
    serializer: str
    validation_rules: tuple[str, ...]
    fixtures: tuple[str, ...]

    def __post_init__(self) -> None:
        names = [rule.name for rule in self.rules]
        if len(set(names)) != len(names):
            raise ProfileError(f"profile {self.family} repeats a rule name")
        if self.applicability.rule not in names:
            raise ProfileError(f"profile {self.family} applicability names an unknown rule")

    @property
    def identity(self) -> str:
        return f"{self.family}/{self.version}"

    def rule(self, name: str) -> Rule:
        for rule in self.rules:
            if rule.name == name:
                return rule
        raise ProfileError(f"profile {self.family} has no rule {name!r}")

    def rules_of_kind(self, kind: RuleKind) -> tuple[Rule, ...]:
        return tuple(rule for rule in self.rules if rule.kind == kind)


# --- the CFR profile ------------------------------------------------------------

CFR_GUIDE = GuideReference(
    url="https://github.com/usgpo/bulk-data/blob/main/CFR-XML_User-Guide.md",
    raw_url="https://raw.githubusercontent.com/usgpo/bulk-data/main/CFR-XML_User-Guide.md",
    revision="1.1 March 2015 (Markdown version of the December 2009 guide)",
    sha256="cdd2ead12d7f96a35514f888c9b9cd345c8b8adb2c672bb69a356aa0194ac41f",
    fetched_on="2026-09-19",
)

CFR_SCHEMA = SchemaFile(
    name="CFRMergedXML.xsd",
    sha256="1f400461602beda201e902268cdab4df4d4c5af88f47bbb760f74a3415ac6ae2",
    path="cfr/CFRMergedXML.xsd",
)

_XSD = "CFRMergedXML.xsd"
_GUIDE = "CFR-XML_User-Guide.md"
_FIXTURE_PDF = (
    "CFR-2025-title30-vol3-sec716-2.pdf (sha256 508548281c0ab7fc68b7d4a4765b3972cbbca9dc72043861fbe696f07ef08162)"
)

#: The CFR ladder. Order is the order the parser consults them in for one
#: block: furniture first, then structure, then what fills a section.
CFR_RULES: tuple[Rule, ...] = (
    Rule(
        "annual_cfr_section_rendition",
        "heuristic",
        "The profile reconstructs an annual CFR section from its PDF or text rendition; the XML rendition, "
        "where GovInfo serves it, is retrieved instead and reconstruction is a paired benchmark only",
        "closing-the-gaps-2026-09-19.md §3.1 (every edition GovInfo serves has XML)",
    ),
    # schema
    Rule("granule_root", "schema", "CFRGRANULE is the root of a section file and holds SECTION", f"{_XSD} line 6693"),
    Rule(
        "section_children",
        "schema",
        "SECTION holds SECTNO, SUBJECT, P, FP, HD, CITA, NOTE, EXTRACT, GPOTABLE, AUTH, PRTPAGE and the rest of "
        "the mixed choice the schema lists; nothing outside that list is emitted under it",
        f"{_XSD} line 4963",
    ),
    Rule("page_break_prtpage", "schema", "PRTPAGE with attribute P marks a printed page break", f"{_XSD} line 4272"),
    Rule("emphasis_e", "schema", "E with attribute T carries typographic emphasis inside text", f"{_XSD} line 1928"),
    # guide
    Rule(
        "section_number_then_subject",
        "guide",
        "A section always contains a section number, usually followed by its subject: SECTNO then SUBJECT",
        f"{_GUIDE} §2.5",
    ),
    Rule("paragraph_p", "guide", "A paragraph of section text is P", f"{_GUIDE} §2.5"),
    Rule("citation_cita", "guide", "A citation in a section is CITA", f"{_GUIDE} §2.5"),
    Rule(
        "table_gpotable",
        "guide",
        "A table is GPOTABLE with BOXHD, CHED, ROW and ENT; the print does not state cell boundaries, so a "
        "table region is left unresolved rather than serialized wrongly",
        f"{_GUIDE} §2.5",
    ),
    Rule("heading_hd", "guide", "Every heading level collapses to HD", f"{_GUIDE} §2.1 (HD, HD1..HD8, HED collapse)"),
    Rule("flush_paragraph_fp", "guide", "A flush paragraph is FP", f"{_GUIDE} §2.1 (FP variants collapse)"),
    # heuristic, each measured on the fixture PDF and then on the benchmark corpus
    Rule(
        "line_assembly",
        "heuristic",
        "Consecutive extractor lines in one vertical band that advance left to right are one printed line; "
        "justified setting splits a line into word fragments (5 at y=356 on page 1 of the fixture)",
        _FIXTURE_PDF,
    ),
    Rule(
        "page_number_furniture",
        "heuristic",
        "A digits-only line whose top sits below 0.9 of the page height is the printed page number",
        f"{_FIXTURE_PDF}: '89' at y0=718/792 on every page",
    ),
    Rule(
        "running_head_furniture",
        "heuristic",
        "Lines whose bottom sits above 0.215 of the page height are the running head (agency or chapter name and "
        "the section range) and carry no section text",
        f"{_FIXTURE_PDF}: AvantGarde-Demi 9 pt at y=159..168, body from y=177",
    ),
    Rule(
        "section_heading",
        "heuristic",
        "A bold line beginning with the section sign and a section number starts a section; the remainder of the "
        "line is the subject",
        f"{_FIXTURE_PDF}: NewCenturySchlbk-Bold 8 pt '§ 716.2' + 'Steep-slope mining.'",
    ),
    Rule(
        "section_heading_continuation",
        "heuristic",
        "A bold line directly after a section heading, without a section sign, continues the subject",
        "wrapped subjects in the benchmark corpus",
    ),
    Rule(
        "division_heading",
        "heuristic",
        "A line in the division-heading face is a part, subpart or subject-group heading: it ends the section "
        "above it and belongs to the part, never inside a section",
        "AvantGarde-Demi 10 pt in every measured edition; CFR-2024-title12-vol1-sec28-5 carries "
        "'Subpart B—Federal Branches and Agencies of Foreign Banks' inside the requested section's page range",
    ),
    Rule(
        "small_caps_restore",
        "heuristic",
        "GPO sets small capitals by size, not by case: a run at least 1 pt below its line's full size whose "
        "letters are all capitals is the reduced part of a small-capital word, and its case is restored",
        "CFR-2022-title40-vol1-sec23-2: MIonic 8.0 pt 'F' beside MIonic 6.5 pt 'EDERAL' for 'Federal Register'",
    ),
    Rule(
        "small_caps_continuation",
        "heuristic",
        "A line wholly in the reduced face that finishes a hyphen wrap out of a larger line is the rest of that "
        "word, not a note",
        "CFR-2022-title40-vol1-sec23-2: 'the FED-' then a line holding only 'ERAL'",
    ),
    Rule(
        "gpo_quote_pair",
        "heuristic",
        "GPO's doubled-backtick and doubled-apostrophe typewriter quotes collapse to one double quote, by the "
        "shared rule extraction.gpo_normalize.normalize_gpo_glyphs, so the PDF and the XML of one document "
        "spell a quotation the same way",
        "extraction/body_text.py RENDITION_CLEANUP_RULES; CFR-2023-title7-vol1-sec3-52 sets six quoted terms so",
    ),
    Rule(
        "part_heading",
        "heuristic",
        "A line beginning 'PART n' in the part heading face, before any section, is the part heading; a "
        "following line in the same face continues it",
        f"{_FIXTURE_PDF}: AvantGarde-Demi 10 pt 'PART 716—SPECIAL PERFORMANCE' / 'STANDARDS'",
    ),
    Rule(
        "contents_list",
        "heuristic",
        "Small-face lines from 'Sec.' until the first note or section are the part's contents list",
        f"{_FIXTURE_PDF}: MIonic 7 pt '716.1 General obligations.' ...",
    ),
    Rule(
        "authority_source_note",
        "heuristic",
        "A small-face line beginning 'AUTHORITY:' or 'SOURCE:' and its continuation lines are a part note",
        f"{_FIXTURE_PDF}: 'AUTHORITY: Secs. 201, 501, 527 and 529, Pub.' / 'L. 95–87, 91 Stat. 445'",
    ),
    Rule(
        "print_shop_footer",
        "heuristic",
        "A line matching extraction.gpo_normalize's verdate_footer or dsk_user rule is GPO's print-shop "
        "chrome, not content; reusing those rules rather than restating them keeps the corpus that measured "
        "them behind this one",
        "extraction/gpo_normalize.py METADATA_RULES; the footer reaches the extractor as a dozen fragments and "
        "would otherwise read as a table row on every page that carries one",
    ),
    Rule(
        "column_left_edge",
        "heuristic",
        "A page has two columns split at its horizontal middle; each column's left edge is the smallest left "
        "coordinate of a body line in that half",
        f"{_FIXTURE_PDF}: left edges 132 and 312 of 612",
    ),
    Rule(
        "first_line_indent",
        "heuristic",
        "A body line indented at least 4 pt from its column's left edge starts a paragraph",
        f"{_FIXTURE_PDF}: first lines at 140 and 320, continuations at 132 and 312",
    ),
    Rule(
        "paragraph_marker",
        "heuristic",
        "The parenthesized designations a paragraph opens with, such as '(e)(1)', are its marker",
        f"{_FIXTURE_PDF} and tests/fixtures/cfr/annual-title30-vol3-sec716-2.xml",
    ),
    Rule(
        "marker_hierarchy",
        "heuristic",
        "Designations nest as (a) then (1) then (i) then (A) then (1) then (i); a marker that continues the "
        "current run at some level closes the levels below it, and one that starts a run opens a level",
        "OFR Document Drafting Handbook ch. 1 paragraph designations, not the GPO guide; confirmed on § 716.2 "
        "(e)(1)(i)(A)",
    ),
    Rule(
        "wrap_hyphen_rejoin",
        "heuristic",
        "A line ending with a hyphen followed by a line beginning with a lowercase letter is a print wrap; "
        "the two join without the hyphen. A real compound split at the wrap is joined wrongly and the "
        "benchmark counts it",
        f"{_FIXTURE_PDF}: 'ini-' / 'tial', 'sep-' / 'arately'",
    ),
    Rule(
        "citation_line",
        "heuristic",
        "A small-face line beginning '[' inside a section, through the line that closes the bracket, is the "
        "section's source citation",
        f"{_FIXTURE_PDF}: '[42 FR 62691, Dec. 13, 1977, as amended at 45' / 'FR 83168, Dec. 17, 1980]'",
    ),
    Rule(
        "note_line",
        "heuristic",
        "A small-face line beginning with a note label (NOTE, EDITORIAL NOTE, EFFECTIVE DATE NOTE, "
        "CROSS REFERENCE) and its continuation lines are a note",
        "the benchmark corpus",
    ),
    Rule(
        "table_region",
        "heuristic",
        "A run of small-face lines assembled from three or more fragments, or a line of leader dots, is a "
        "table region and is left unresolved",
        "the benchmark corpus",
    ),
    Rule(
        "italic_emphasis",
        "heuristic",
        'An italic run inside a paragraph is E T="03"',
        "tests/fixtures/cfr/annual-title30-vol3-sec716-2.xml: run-in heading of § 716.2(e)",
    ),
    Rule(
        "page_break_in_paragraph",
        "heuristic",
        "A paragraph whose lines span two pages carries PRTPAGE with the second page's printed number at the break",
        'tests/fixtures/cfr/annual-title30-vol3-sec716-2.xml: PRTPAGE P="90" inside § 716.2(e)(3)(i)',
    ),
    Rule(
        "section_truncated",
        "heuristic",
        "A section that begins after the last heading on the last page, or ends the evidence without a "
        "citation, may continue beyond the rendition and is marked for review",
        "a section PDF is a page range and carries its neighbours (closing-the-gaps §3.1 boundary rule)",
    ),
    Rule(
        "unclassified_block",
        "heuristic",
        "A block no rule places is an unresolved region, listed by the coverage check",
        "closing-the-gaps-2026-09-19.md §3.2 (unresolved regions survive with an issue attached)",
    ),
)

CFR_PROFILE = Profile(
    family="cfr",
    version="1",
    applicability=Applicability(("CFR",), ("pdf", "txt", "htm"), "annual_cfr_section_rendition"),
    schema_bundle=(CFR_SCHEMA,),
    guide=CFR_GUIDE,
    rules=CFR_RULES,
    serializer="cfr-granule-xml",
    validation_rules=("schema_validity", "content_fidelity", "structural_fidelity", "coverage", "acceptance"),
    fixtures=(
        "tests/fixtures/reconstruction/cfr/README.md",
        "tests/fixtures/cfr/annual-title30-vol3-sec716-2.xml",
    ),
)

PROFILES: dict[str, Profile] = {CFR_PROFILE.family: CFR_PROFILE}


def profile(family: str) -> Profile:
    """The registered profile, or a refusal naming what is registered."""
    try:
        return PROFILES[family]
    except KeyError:
        raise ProfileError(f"no profile {family!r}; registered: {', '.join(sorted(PROFILES))}") from None


def select_profile(*, collection: str, rendition: str) -> Profile | None:
    """The one profile whose applicability rule admits this collection and rendition, or ``None``."""
    matches = [p for p in PROFILES.values() if p.applicability.applies(collection=collection, rendition=rendition)]
    if len(matches) > 1:
        raise ProfileError(
            f"{len(matches)} profiles apply to {collection}/{rendition}; applicability must be exclusive"
        )
    return matches[0] if matches else None


def schema_path(entry: SchemaFile) -> Traversable:
    """Where the pinned file lives in the installed package."""
    return files(__package__).joinpath("schemas").joinpath(entry.path)


def check_schema_bundle(profile: Profile) -> Iterator[SchemaFile]:
    """Yield each bundle file after proving its bytes carry the pinned digest; refuse otherwise."""
    for entry in profile.schema_bundle:
        path = schema_path(entry)
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            raise ProfileError(
                f"profile {profile.identity} pins {entry.name} at {entry.path}, which is missing"
            ) from None
        if digest != entry.sha256:
            raise ProfileError(
                f"profile {profile.identity}: {entry.name} has digest {digest}, not the pinned {entry.sha256}"
            )
        yield entry


__all__ = [
    "CFR_GUIDE",
    "CFR_PROFILE",
    "CFR_RULES",
    "CFR_SCHEMA",
    "PROFILES",
    "RULE_KINDS",
    "Applicability",
    "GuideReference",
    "Profile",
    "ProfileError",
    "Rule",
    "RuleKind",
    "SchemaFile",
    "check_schema_bundle",
    "profile",
    "schema_path",
    "select_profile",
]
