"""The sealed bill-version-code vocabulary, printing order, format choice and PDF package ids.

Ported from BillTrax's `VERSION_CODE_TO_GOVINFO_SLUG` and its duplicated
format-choice helpers; `VERSION_CODES` slugs are never renamed or removed (its
SQL keys on them), only added, with one suffix corrected to `rhuc` because the
publisher never spells that version `rfh`. Congress.gov's `type` string is not
unique per printing (it names both `eas` and its numbered reprint `eas2`), so a
name-derived slug cannot tell them apart: prefer a publisher-stated package id
from `bill_status.bill_package_id_from_url`, and treat `version_slug` /
`bill_version_package_id` as the fallback, with `version_slug_reprints`
exposing the ambiguity. `choose_format`/`format_name` pick an offered
rendition, including a type-less format item named from its GovInfo URL folder.
`printing_order`/`consecutive_pairs` order a bill's printings by publisher date,
placing a dateless enrolled printing by its stage.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from spicy_docs.sources.congress.bill_status import BillIdentity, BillTextFormat

_SLUG_COLLAPSE = re.compile(r"[^a-z0-9]+")

#: Shared note text for a slug carried only because DeltaTrack upstream's
#: authoritative govinfo list names it; not observed in this port's own
#: 119th BILLS measurement.
_UPSTREAM_ONLY_NOTE = (
    "Not observed in the 119th BILLS census this port measured; carried from "
    "DeltaTrack upstream's authoritative govinfo code list "
    "(tools/fetch_govinfo.py::VERSION_CODES, civictechdc/DeltaTrack) so a real "
    "govinfo code is not silently missing for want of a 119th sighting."
)


class VersionCodeError(ValueError):
    """A version-code slug cannot be resolved to a GovInfo package-id suffix."""


@dataclass(frozen=True, slots=True)
class VersionCode:
    """One entry in the sealed `version_code` vocabulary.

    ``slug`` is what BillTrax stores in ``bill_versions.version_code`` and is
    never renamed. ``govinfo_suffix`` is the BILLS package-id suffix the
    fallback path (``bill_version_package_id``) builds from this slug.
    ``version_types`` are the publisher version-type strings that resolve here,
    measured or cited to upstream, and need not literally equal
    ``slugify(slug)`` (empty when the slug is a short code addressed directly).
    ``stage_value`` is the document's own stage-attribute spelling where
    measured. ``measured_119th`` is whether this exact suffix appeared in the
    119th BILLS census (24 distinct suffixes); a code carried only from
    upstream's authoritative govinfo list says so in ``note``.
    """

    slug: str
    govinfo_suffix: str
    version_types: tuple[str, ...] = ()
    stage_value: str | None = None
    measured_119th: bool = False
    note: str | None = None


VERSION_CODES: tuple[VersionCode, ...] = (
    # --- BillTrax's canonical long slugs, name-derived (govinfo-pdf-fetch.ts:26-42) ---
    VersionCode("introduced-in-house", "ih", ("Introduced in House",), "Introduced-in-House", True),
    VersionCode("introduced-in-senate", "is", ("Introduced in Senate",), "Introduced-in-Senate", True),
    VersionCode("engrossed-in-house", "eh", ("Engrossed in House",), "Engrossed-in-House", True),
    VersionCode("engrossed-in-senate", "es", ("Engrossed in Senate",), "Engrossed-in-Senate", True),
    VersionCode("enrolled-bill", "enr", ("Enrolled Bill",), "Enrolled-Bill", True),
    VersionCode(
        "public-law",
        "enr",
        ("Public Law",),
        measured_119th=False,
        note=(
            "Deliberately collides with enrolled-bill on 'enr' (BillTrax's own "
            "choice). The 119th census read the API type for every 'enr' file "
            "sampled as 'Enrolled Bill', never 'Public Law'; this entry is kept "
            "(BillTrax may see 'Public Law' once a law number posts) but is "
            "unconfirmed by this measurement."
        ),
    ),
    VersionCode("placed-on-calendar-senate", "pcs", ("Placed on Calendar Senate",), "Placed-on-Calendar-Senate", True),
    VersionCode(
        "placed-on-calendar-house",
        "pch",
        ("Placed on Calendar House",),
        note=(
            "BillTrax knew this suffix; the 119th BILLS corpus never produced "
            "it. Name confirmed (not just guessed) against DeltaTrack "
            "upstream's authoritative list, which states the same wording."
        ),
    ),
    VersionCode(
        "referred-to-senate",
        "rds",
        ("Received in Senate",),
        measured_119th=True,
        note="BillTrax's slug says 'referred'; the measured API type is 'Received in Senate'. Slug unchanged (sealed).",
    ),
    VersionCode("referred-to-house", "rfh", ("Referred in House",), measured_119th=True),
    VersionCode(
        "held-at-desk-senate",
        "hds",
        ("Held at Desk Senate",),
        note=(
            "BillTrax knew this suffix; the 119th BILLS corpus never produced "
            "it. Name is DeltaTrack upstream's authoritative wording (no "
            "119th measurement exists to confirm it independently)."
        ),
    ),
    VersionCode(
        "returned-to-the-house-by-unanimous-consent",
        "rhuc",
        ("Returned to the House by Unanimous Consent",),
        measured_119th=True,
        note=(
            "BillTrax mapped this slug to 'rfh', deliberately colliding with "
            "referred-to-house. Measured 2026-09-19 (119th BILLS census): the "
            "publisher's real suffix is 'rhuc', which a 'Referred in House' "
            "document never uses. The publisher wins; the target suffix is "
            "corrected here. The slug string itself is unchanged (sealed)."
        ),
    ),
    VersionCode("engrossed-amendment-senate", "eas", ("Engrossed Amendment Senate",), None, True),
    VersionCode("engrossed-amendment-house", "eah", ("Engrossed Amendment House",), measured_119th=True),
    VersionCode("reported-in-house", "rh", ("Reported in House",), "Reported-in-House", True),
    VersionCode(
        "reported-in-senate",
        "rs",
        # Two publisher-adjacent spellings for one document: BILLSTATUS/
        # Congress.gov's own <type> (measured) says "to Senate"; DeltaTrack
        # upstream's canonical GPO wording (matching this slug's own
        # spelling) says "in Senate". version_slug resolves both.
        ("Reported to Senate", "Reported in Senate"),
        "Reported-in-Senate",
        True,
        note="A third spelling too: the XML root's own resolution-stage attribute says 'Reported-in-Senate'.",
    ),
    # --- BillTrax's passthrough short codes (both copies key these to themselves) ---
    VersionCode("ih", "ih", measured_119th=True),
    VersionCode("is", "is", measured_119th=True),
    VersionCode("eh", "eh", measured_119th=True),
    VersionCode("es", "es", measured_119th=True),
    VersionCode("enr", "enr", measured_119th=True),
    VersionCode("pcs", "pcs", measured_119th=True),
    VersionCode("pch", "pch", note="Canonical-only passthrough; unused in the 119th BILLS corpus."),
    VersionCode("rds", "rds", measured_119th=True),
    VersionCode("rfh", "rfh", measured_119th=True),
    VersionCode("hds", "hds", note="Canonical-only passthrough; unused in the 119th BILLS corpus."),
    VersionCode("eas", "eas", measured_119th=True),
    VersionCode("eah", "eah", measured_119th=True),
    VersionCode("rh", "rh", measured_119th=True),
    VersionCode("rs", "rs", measured_119th=True),
    # --- Additions: measured in the 119th BILLS census, absent from both BillTrax copies ---
    VersionCode(
        "rfs",
        "rfs",
        ("Referred in Senate",),
        measured_119th=True,
        note=(
            "568 files (2.6% of the 119th BILLS corpus) -- the single largest "
            "gap in BillTrax's map. 'Referred in Senate' also names rfs2's "
            "reprint; declared here first, so version_slug resolves it to rfs "
            "(the earliest printing) -- see version_slug_reprints."
        ),
    ),
    VersionCode("ats", "ats", ("Agreed to Senate",), "Agreed-to-Senate", True),
    VersionCode("cps", "cps", ("Considered and Passed Senate",), measured_119th=True),
    VersionCode("rcs", "rcs", ("Reference Change Senate",), measured_119th=True),
    VersionCode(
        "rhuc",
        "rhuc",
        ("Returned to the House by Unanimous Consent",),
        measured_119th=True,
        note="The correct suffix for this version type; see the note on returned-to-the-house-by-unanimous-consent.",
    ),
    VersionCode(
        "as",
        "as",
        # Measured (parenthesized "(Senate)") and DeltaTrack upstream's
        # authoritative wording (no parens) -- cosmetic: both slugify identically.
        ("Amendment Ordered to be Printed (Senate)", "Amendment Ordered to be Printed Senate"),
        measured_119th=True,
    ),
    VersionCode("cdh", "cdh", ("Committee Discharged House",), measured_119th=True),
    VersionCode(
        "eas2",
        "eas2",
        ("Engrossed Amendment Senate",),
        measured_119th=True,
        note=(
            "A numbered reprint of 'eas'; Congress.gov's type string is "
            "identical to eas's, so version_slug resolves that shared name to "
            "eas (the earliest printing), not here -- see version_slug_reprints. "
            "Only a stated package id (or this passthrough entry, when the "
            "suffix is already known) can address eas2 by name."
        ),
    ),
    VersionCode(
        "eh1s",
        "eh1s",
        ("Engrossed in House",),
        measured_119th=True,
        note="A numbered reprint of 'eh'; same name-collision limitation as eas2.",
    ),
    VersionCode("lth", "lth", ("Laid on Table in House",), measured_119th=True),
    VersionCode(
        "rfs2",
        "rfs2",
        ("Referred in Senate",),
        measured_119th=True,
        note="A numbered reprint of 'rfs'; same name-collision limitation as eas2.",
    ),
    VersionCode("ris", "ris", ("Referral Instructions Senate",), measured_119th=True),
    # --- Additions: DeltaTrack upstream's authoritative govinfo code list,
    # unmeasured in the 119th BILLS census (tools/fetch_govinfo.py::VERSION_CODES,
    # civictechdc/DeltaTrack). Grouped by upstream's own legislative-stage tiers
    # for the same reason upstream groups them: purely for a reader's orientation,
    # load-bearing nowhere in this module. ---
    # tier 1: introduced / sponsorship administration
    VersionCode("ash", "ash", ("Additional Sponsors House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("sas", "sas", ("Additional Sponsors Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("sc", "sc", ("Sponsor Change",), note=_UPSTREAM_ONLY_NOTE),
    # tier 2: referral / receipt / reference / held at desk
    VersionCode("rdh", "rdh", ("Received in House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("rch", "rch", ("Reference Change House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("rth", "rth", ("Referred to Committee House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("rts", "rts", ("Referred to Committee Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("rih", "rih", ("Referral Instructions House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("rah", "rah", ("Referred with Amendments House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("ras", "ras", ("Referred with Amendments Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("hdh", "hdh", ("Held at Desk House",), note=_UPSTREAM_ONLY_NOTE),
    # tier 3: reported / calendar / committee discharged / print
    VersionCode("cds", "cds", ("Committee Discharged Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("oph", "oph", ("Ordered to be Printed House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("ops", "ops", ("Ordered to be Printed Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("pp", "pp", ("Public Print",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("pav", "pav", ("Previous Action Vitiated",), note=_UPSTREAM_ONLY_NOTE),
    # tier 4: engrossed / passed / agreed / amended / floor disposition
    VersionCode("reah", "reah", ("Re-engrossed Amendment House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("res", "res", ("Re-engrossed Amendment Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("eph", "eph", ("Engrossed and Deemed Passed by House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("cph", "cph", ("Considered and Passed House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("ath", "ath", ("Agreed to House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("fah", "fah", ("Failed Amendment House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("fph", "fph", ("Failed Passage House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("fps", "fps", ("Failed Passage Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("iph", "iph", ("Indefinitely Postponed House",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("ips", "ips", ("Indefinitely Postponed Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("lts", "lts", ("Laid on Table in Senate",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("pwah", "pwah", ("Ordered to be Printed with House Amendment",), note=_UPSTREAM_ONLY_NOTE),
    # tier 5: enrolled / printed as passed
    VersionCode("renr", "renr", ("Re-enrolled Bill",), note=_UPSTREAM_ONLY_NOTE),
    VersionCode("pap", "pap", ("Printed as Passed",), note=_UPSTREAM_ONLY_NOTE),
)

VERSION_CODES_BY_SLUG: dict[str, VersionCode] = {entry.slug: entry for entry in VERSION_CODES}
if len(VERSION_CODES_BY_SLUG) != len(VERSION_CODES):
    raise AssertionError("VERSION_CODES has a duplicate slug")

#: `slugify(a measured/cited version type)` -> the slug that claims it, first
#: entry declared wins (VERSION_CODES's own order -- always earliest printing
#: first for a shared name; see version_slug and version_slug_reprints).
_SLUG_BY_TYPE_NAME: dict[str, str] = {}
for _entry in VERSION_CODES:
    for _type_name in _entry.version_types:
        _SLUG_BY_TYPE_NAME.setdefault(_SLUG_COLLAPSE.sub("-", _type_name.lower()).strip("-"), _entry.slug)
del _entry, _type_name


def slugify(value: str) -> str:
    """BillTrax's slugifier, ported byte-for-byte from its three identical copies."""
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return _SLUG_COLLAPSE.sub("-", value.lower()).strip("-")


def version_slug(version_type: str) -> str:
    """The `version_code` BillTrax stores for one publisher version-type string.

    BillTrax computes this as plain `slugify(version_type)`, kept here as the
    fallback; first it checks whether a sealed slug already claims this exact
    measured type name under a *different* spelling (``received-in-senate`` ->
    ``referred-to-senate``), so a composed package id lands on the sealed slug.

    This is still name-derived and cannot recover a numbered reprint's own
    suffix -- the earliest-declared slug wins -- `version_slug_reprints`
    exposes when that happened; prefer a stated package id when one exists.
    """
    if not isinstance(version_type, str) or not version_type:
        raise VersionCodeError("version_type must be a nonempty string")
    key = slugify(version_type)
    return _SLUG_BY_TYPE_NAME.get(key, key)


def version_slug_reprints(version_type: str) -> tuple[str, ...]:
    """Other sealed slugs naming a *different* document under this exact name.

    Non-empty means the name is ambiguous (``eas``/``eas2``, ``eh``/``eh1s``,
    ``rfs``/``rfs2``): Congress.gov gives a numbered reprint the identical
    `type` string as its original, and `version_slug` always resolves to the
    earliest-declared printing -- only a stated package id tells the documents
    apart. Empty when the name is unambiguous, claimed by no sealed slug, or
    claimed only by another slug for the *same* suffix (a long-slug/short-code
    pair naming one document twice is aliasing, not ambiguity).
    """
    key = slugify(version_type)
    resolved = version_slug(version_type)
    resolved_suffix = govinfo_suffix(resolved)
    claimants = tuple(entry.slug for entry in VERSION_CODES if key in {slugify(t) for t in entry.version_types})
    return tuple(
        slug for slug in claimants if slug != resolved and VERSION_CODES_BY_SLUG[slug].govinfo_suffix != resolved_suffix
    )


def govinfo_suffix(slug: str) -> str:
    """The GovInfo BILLS package-id suffix this sealed slug names; an unknown slug raises."""
    entry = VERSION_CODES_BY_SLUG.get(slug)
    if entry is None:
        raise VersionCodeError(f"version_code slug is not in the sealed vocabulary: {slug!r}")
    return entry.govinfo_suffix


def bill_version_package_id(identity: BillIdentity, slug: str) -> str:
    """The GovInfo BILLS package id for one bill version's sealed slug.

    Fallback path: name-derived, cannot distinguish a numbered reprint from its
    original (see module docstring), so prefer a stated package id when the
    caller has one -- `bill_pdf.acquire_bill_pdf` does. The BILLS grammar in
    `sources.govinfo.bodies` parses exactly this stem, so
    `parse_package_id(bill_version_package_id(identity, slug))` round-trips
    identity's own congress, bill_type and number.
    """
    if not isinstance(identity, BillIdentity):
        raise TypeError("identity must be a BillIdentity")
    suffix = govinfo_suffix(slug)
    return f"BILLS-{identity.congress}{identity.bill_type}{identity.number}{suffix}"


# ---------------------------------------------------------------------------
# Format choice: congress-api.ts chooseFormat/chooseXmlFormat, sync-govinfo.ts
# pickVersionUrls (the fallback at sync-govinfo.ts:262).
# ---------------------------------------------------------------------------

#: Congress.gov REST `/bill/.../text` `textVersions[].formats[].type` strings,
#: to the short format name `choose_format` matches against `prefer`. This
#: table is for a REST-sourced producer this repository does not build yet --
#: see `choose_format`'s docstring for why it is dead against today's one
#: producer. USLM (`United States Legislative Markup`) is acquirable:
#: `GovInfoBodyAcquirer`'s `PACKAGE_BODY_FORMATS` reads a BILLS package's own
#: `uslm/{id}.xml` rendition directly (§B7); `sources.govinfo.uslm` is a
#: separate module for the PLAW/COMPS collections and is not involved.
FORMAT_TYPE_NAMES: dict[str, str] = {
    "Formatted Text": "txt",
    "Formatted XML": "xml",
    "PDF": "pdf",
    "HTML": "html",
    "United States Legislative Markup": "uslm",
}
#: `pickVersionUrls`'s fallback (`sync-govinfo.ts:255-268`), adapted: name a
#: format item with no stated `type` from the GovInfo rendition *folder* in
#: its URL path (`sources.govinfo.bodies.PACKAGE_BODY_FORMATS`'s own folder
#: names), not the file extension -- BILLS states its USLM rendition at
#: `uslm/{id}.xml`, which no extension check can tell apart from `xml/{id}.xml`.
#: This is the *only* live path today: `bill_status.py`'s `_text_version`
#: (the one place a `BillTextFormat` is built on `main`) reads BILLSTATUS
#: `<formats><item>`, which carries `<url>` only -- never `<type>` -- on
#: every fixture in `tests/fixtures/govinfo_bills`. The 240-format-entry,
#: "every one carried a type" measurement (§7,
#: docs/research/billtrax-raw-data-2026-09-19.md) was of the Congress.gov
#: REST route, not BILLSTATUS; it says nothing about whether this fallback
#: fires against the data this repository actually parses today.
_FORMAT_URL_FOLDERS: tuple[tuple[str, str], ...] = (
    ("/xml/", "xml"),
    ("/html/", "html"),
    ("/text/", "txt"),
    ("/pdf/", "pdf"),
    ("/uslm/", "uslm"),
)


def format_name(item: BillTextFormat) -> str | None:
    """This module's short name for one offered format link, or None for an unknown one.

    The publisher's own ``type`` string wins where it states one; otherwise the
    name comes from the GovInfo rendition *folder* in the URL path, never the
    file extension -- BILLS states its USLM rendition at ``uslm/{id}.xml``,
    which no extension check can tell apart from ``xml/{id}.xml``.

    Public because ``choose_format`` is not the only caller any more: a
    published ``bill_versions`` row states which rendition was read, and naming
    it a second way is how the row and the choice would drift apart.
    """
    if item.type is not None:
        return FORMAT_TYPE_NAMES.get(item.type)
    for folder, name in _FORMAT_URL_FOLDERS:
        if folder in item.url:
            return name
    return None


#: `sources.govinfo.bodies.BODY_PREFERENCE` spelled in this module's own
#: format names: the GovInfo rendition `htm` is `html` here, because that is
#: what Congress.gov's `type` string ("HTML") and this module's folder
#: fallback already call it. The two orders are the same order and must stay
#: so -- a version chosen in one spelling is fetched in the other, and
#: `tests/test_congress_bill_versions.py` pins them equal.
DEFAULT_FORMAT_PREFERENCE: tuple[str, ...] = ("xml", "uslm", "html", "txt", "pdf")


def choose_format(
    formats: Sequence[BillTextFormat], prefer: Sequence[str] = DEFAULT_FORMAT_PREFERENCE
) -> BillTextFormat | None:
    """The first offered format matching `prefer` in order, or None.

    The default is the sealed body preference (`DEFAULT_FORMAT_PREFERENCE`),
    which keeps BillTrax's `chooseFormat` order -- XML, then text, then PDF --
    and adds HTML between XML and text, where the sealed order puts it, and
    USLM right after XML; PDF stays the last default rather than being
    excluded, since bill PDFs measured small. Also ports `pickVersionUrls`'s
    fallback for a format item with no stated `type`. `prefer` takes this
    module's short format names (`FORMAT_TYPE_NAMES`'s values), not
    Congress.gov's `type` strings, and must be a sequence, never one string.
    """
    if isinstance(prefer, str) or not isinstance(prefer, Sequence):
        raise TypeError("prefer must be a sequence of format names, not one name")
    named = [(item, format_name(item)) for item in formats if item.url]
    for name in prefer:
        for item, item_name in named:
            if item_name == name:
                return item
    return None


# ---------------------------------------------------------------------------
# Printing order: which printing of a bill precedes which, for pairing diffs.
# ---------------------------------------------------------------------------

#: The printing GPO defines as the last one a bill has: "Enrolled Bill — final
#: official copy of the bill or joint resolution which both the House and the
#: Senate have passed in identical form" (govinfo.gov/help/bills). BILLSTATUS
#: states no date for it: ``<date/>`` is empty, and so is the printing's own
#: ``<dc:date>``, on every enrolled printing measured -- all 469 enrolled-bill
#: rows spicy-regs published at 2026-09-25, and all 9 enrolled items among 213
#: BILLSTATUS files, each listed first in the publisher's newest-first item
#: order (receipt ``fork-execution-2026-09-21/drift-qualification-2026-09-26/
#: bills-citations/`` under ``~/Work/corpora``).
ENROLLED_SLUGS = frozenset({"enrolled-bill", "enr"})

#: The printings that by definition follow enrollment: a re-enrolment, and the
#: law the enrolled bill became. BILLSTATUS dates the law item with the
#: enactment date and lists it after every printing.
AFTER_ENROLLMENT_SLUGS = frozenset({"renr", "public-law", "private-law"})


def _placed(printing: tuple[str, str | None]) -> bool:
    """Whether a publisher date or the slug's stage establishes where the printing falls."""
    slug, date = printing
    return bool(date) or slug in ENROLLED_SLUGS


def printing_order(printings: Sequence[tuple[str, str | None]]) -> list[int]:
    """Indices of ``(version_code, date)`` printings, earliest first.

    Dated printings sort by the publisher's date, ties broken by
    `VERSION_CODES`' declaration order (earliest printing first for a shared
    name) and then by input order. A dateless printing is placed by the stage
    its slug states, never by an invented date: an enrolled printing
    (`ENROLLED_SLUGS`) after every dated printing that precedes enrollment and
    before the first dated one that follows it (`AFTER_ENROLLMENT_SLUGS`). A
    dateless printing whose slug states no stage (none measured) sorts first,
    where an empty date always sorted, and `consecutive_pairs` pairs it with
    nothing. Idempotent: ordering an ordered list returns ``range(len(...))``.
    """
    rank = {entry.slug: index for index, entry in enumerate(VERSION_CODES)}

    def declared(index: int) -> int:
        return rank.get(printings[index][0], len(rank))

    dated = sorted((i for i, (_, date) in enumerate(printings) if date), key=lambda i: (printings[i][1], declared(i)))
    dateless = sorted((i for i, (_, date) in enumerate(printings) if not date), key=declared)
    ordered = [i for i in dateless if printings[i][0] not in ENROLLED_SLUGS] + dated
    for index in (i for i in dateless if printings[i][0] in ENROLLED_SLUGS):
        later = [at for at, i in enumerate(ordered) if printings[i][1] and printings[i][0] in AFTER_ENROLLMENT_SLUGS]
        ordered.insert(later[0] if later else len(ordered), index)
    return ordered


def consecutive_pairs(printings: Sequence[tuple[str, str | None]]) -> list[tuple[int, int]]:
    """``(earlier, later)`` index pairs of printings that neighbour in `printing_order` and whose order is established.

    These are the only pairs a bill's diff compares: consecutive, never every
    pair, and never a pair one of whose printings neither a date nor a stage
    places. Indices are into ``printings`` as given.
    """
    ordered = printing_order(printings)
    return [
        (older, newer) for older, newer in pairwise(ordered) if _placed(printings[older]) and _placed(printings[newer])
    ]


__all__ = [
    "AFTER_ENROLLMENT_SLUGS",
    "DEFAULT_FORMAT_PREFERENCE",
    "ENROLLED_SLUGS",
    "FORMAT_TYPE_NAMES",
    "VERSION_CODES",
    "VERSION_CODES_BY_SLUG",
    "VersionCode",
    "VersionCodeError",
    "bill_version_package_id",
    "choose_format",
    "consecutive_pairs",
    "format_name",
    "govinfo_suffix",
    "printing_order",
    "slugify",
    "version_slug",
    "version_slug_reprints",
]
