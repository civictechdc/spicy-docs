"""The sealed bill-version-code vocabulary, format choice and PDF package ids.

Ported from BillTrax (read-only, `/Users/mikewolfd/Work/spicy-stack/BillTrax`):
`src/lib/govinfo-pdf-fetch.ts:26-58` (`VERSION_CODE_TO_GOVINFO_SLUG`, the
canonical copy), `scripts/validate-pdf-xml-concordance.ts:44-64` (a private,
drifted second copy missing `pch`, `rds`, `rfh`, `hds`), and the three
duplicated `slugify`/`chooseFormat`/`pickVersionUrls` implementations named in
`docs/research/billtrax-value-inventory-2026-09-19.md` §1a/§2.1.

**The sealed contract.** BillTrax's SQL keys on `bill_versions.version_code`
(`migrations/016_version_kind.ts`, `020_version_uniqueness_includes_source.ts`),
so every slug string BillTrax ever emitted stays in `VERSION_CODES` unchanged;
this module only adds entries, never renames or removes one.

**What the 119th measurement changed.** `docs/research/billtrax-raw-data-2026-09-19.md`
§1 counted every BILLS version code the 119th Congress actually produced (24
distinct GovInfo package-id suffixes across 21,947 XML files) and found three
things BillTrax's name-derived map cannot fix by better naming:

1. BillTrax's map reaches 12 of the 24 codes correctly, has no entry for 12
   more (1,027 files, `rfs` alone 568), and resolves the same suffix "rfh" from
   two different long slugs -- one of them wrong. `returned-to-the-house-by-
   unanimous-consent` mapped to `rfh` (colliding with `referred-to-house`);
   the measured 119th suffix for that version type is `rhuc`, which the
   publisher never once spells `rfh`. Outcome over rules: the publisher wins.
   The slug `returned-to-the-house-by-unanimous-consent` is unchanged (sealed);
   its `govinfo_suffix` is corrected to `rhuc`, and `rhuc` is added as its own
   passthrough entry.
2. Congress.gov's `type` string is **not unique per version**: "Engrossed
   Amendment Senate" names both `eas` and its numbered reprint `eas2`,
   "Engrossed in House" names both `eh` and `eh1s`, and "Referred in Senate"
   names both `rfs` and `rfs2`. No name-derived slug can tell those apart --
   `version_slug()` produces the same string for both. `version_slug_reprints`
   exposes this rather than hiding it; see below.
3. **The map itself is demoted, not deleted.** `bill_version_package_id` (the
   port of `buildGovinfoPdfUrl`) and `version_slug` (the port of `slugify`
   applied to a version-type name, as BillTrax's ingest path does) remain --
   BillTrax's SQL already holds rows keyed on these slugs with no stored
   package id, and some acquisition paths still only have a type name -- but
   they are the *fallback*, not the derivation `acquire_bill_pdf` prefers.
   The publisher's own package id, read from a stated format URL via
   `sources.congress.bill_status.bill_package_id_from_url`, is preferred
   whenever a caller has one; see `bill_pdf.acquire_bill_pdf`.

**Cross-checked against DeltaTrack upstream.** DeltaTrack's own
`tools/fetch_govinfo.py::VERSION_CODES`/`resolve_code()`
(https://github.com/civictechdc/DeltaTrack, a separate BillTrax-adjacent
project this port does not otherwise draw on) carries govinfo's full
authoritative 53-code list (govinfo.gov/help/bills) with its own display
names and a documented `eas2 -> eas` prefix-fallback for numbered reprints.
All 24 codes this port measured in the 119th resolve there, with two cosmetic
spelling differences recorded on the affected entries below (`rs`: "Reported
to Senate" measured vs. "Reported in Senate" upstream's canonical wording;
`as`: parenthesized "(Senate)" measured vs. unparenthesized upstream -- both
slugify identically). The 30 codes upstream carries that neither BillTrax nor
this port's own 119th measurement produced are added below, `measured_119th`
False, so a real govinfo code is not silently missing for want of a 119th
sighting; DeltaTrack's own `version_stems.py` is unrelated (on-disk filename
ordinals for a locally cached bill folder, not this vocabulary) and is not a
source here.

`VERSION_CODES` therefore carries, per slug, every spelling this port found
evidence for: the `version_types` Congress.gov or DeltaTrack upstream states
(measured for the 24 codes seen in the 119th BILLS corpus; cited to upstream
otherwise), the `stage_value` the document's own root attribute states
(measured for 10 of them, from a 40-file structural sample --
`docs/research/billtrax-raw-data-2026-09-19.json`
`sources.billXmlStructure.doctypeAndStage`), and the `govinfo_suffix` the
fallback path builds a package id from. `measured_119th` records whether that
suffix appeared at all in the 119th BILLS package-id census.

Format choice ports `congress-api.ts chooseFormat`/`chooseXmlFormat` and
`sync-govinfo.ts pickVersionUrls`, including the URL fallback `pickVersionUrls`
added at `sync-govinfo.ts:262` for a format item with no stated `type` -- see
`choose_format`'s own docstring for which producer actually needs it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

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
    ``version_types`` are the publisher version-type strings measured (or, for
    a code neither BillTrax nor the 119th measurement named, cited to
    DeltaTrack upstream) to name this suffix; `version_slug` resolves any of
    them back to this slug even when it does not literally equal
    ``slugify(version_type)`` (empty when the slug is a short code addressed
    directly, never derived by name). ``stage_value`` is the document's own
    ``@bill-stage``/``@resolution-stage`` attribute spelling for this suffix,
    where measured -- a third, independent publisher spelling `bill_text.py`
    already reads for three of these. ``measured_119th`` is True when this
    exact suffix appeared in the 119th Congress BILLS package-id census (24
    distinct suffixes, 21,947 files).
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
    """BillTrax's slugifier, ported byte-for-byte.

    Three identical copies existed (`congress-api.ts:130-132`,
    `sync-govinfo.ts:40-42`, inline at `version-kind.ts:103`); this is the one.
    """
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return _SLUG_COLLAPSE.sub("-", value.lower()).strip("-")


def version_slug(version_type: str) -> str:
    """The `version_code` BillTrax stores for one publisher version-type string.

    BillTrax itself computes this as plain `slugify(version_type)`
    (`congress-api.ts:291`, `sync-govinfo.ts` version_code derivation) with no
    separate type-to-slug dictionary. This function keeps that as the
    fallback but checks first whether some sealed slug in `VERSION_CODES`
    already claims this exact measured type name under a *different*
    spelling -- `slugify("Received in Senate")` is `received-in-senate`, but
    the sealed slug for that document is `referred-to-senate` (BillTrax's own
    name), so composing `bill_version_package_id(identity, version_slug(...))`
    must land on the sealed slug, not a slug nothing in the vocabulary defines.

    This is still the *name-derived* fallback, and still cannot recover a
    numbered reprint's own suffix: "Engrossed Amendment Senate" claims both
    `eas` and its reprint `eas2`, and whichever was declared first in
    `VERSION_CODES` wins (the earliest printing). `version_slug_reprints`
    exposes when that happened, rather than resolving silently. Prefer a
    stated package id when one exists; see `bill_pdf.acquire_bill_pdf`.
    """
    if not isinstance(version_type, str) or not version_type:
        raise VersionCodeError("version_type must be a nonempty string")
    key = slugify(version_type)
    return _SLUG_BY_TYPE_NAME.get(key, key)


def version_slug_reprints(version_type: str) -> tuple[str, ...]:
    """Other sealed slugs naming a *different* document under this exact name.

    Non-empty means the name is ambiguous: Congress.gov gives a numbered
    reprint the identical `type` string as its original (measured 2026-09-19:
    `eas`/`eas2`, `eh`/`eh1s`, `rfs`/`rfs2`). `version_slug` still resolves --
    always to the earliest-declared, i.e. earliest-printed, slug -- but only a
    stated package id tells the documents apart. Empty when the name is
    unambiguous, claimed by no sealed slug, or claimed only by another slug
    for the *same* suffix (a long-slug/short-code pair like
    `returned-to-the-house-by-unanimous-consent`/`rhuc` names one document
    twice, which is aliasing, not ambiguity).
    """
    key = slugify(version_type)
    resolved = version_slug(version_type)
    resolved_suffix = govinfo_suffix(resolved)
    claimants = tuple(entry.slug for entry in VERSION_CODES if key in {slugify(t) for t in entry.version_types})
    return tuple(
        slug for slug in claimants if slug != resolved and VERSION_CODES_BY_SLUG[slug].govinfo_suffix != resolved_suffix
    )


def govinfo_suffix(slug: str) -> str:
    """The GovInfo BILLS package-id suffix this sealed slug names.

    Raises for a slug this module has no entry for, matching
    `buildGovinfoPdfUrl`'s `null` return for an unknown `version_code`.
    """
    entry = VERSION_CODES_BY_SLUG.get(slug)
    if entry is None:
        raise VersionCodeError(f"version_code slug is not in the sealed vocabulary: {slug!r}")
    return entry.govinfo_suffix


def bill_version_package_id(identity: BillIdentity, slug: str) -> str:
    """The GovInfo BILLS package id for one bill version's sealed slug.

    Fallback path: name-derived, cannot distinguish a numbered reprint from
    its original (see module docstring). Prefer a stated package id when the
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
#: producer. USLM (`United States Legislative Markup`) is recognized by name
#: here but is **not yet acquirable**: `GovInfoBodyAcquirer`'s
#: `PACKAGE_BODY_FORMATS` supports only htm/xml/txt/pdf, and
#: `sources.govinfo.uslm` reads the separate PLAW/COMPS collections, not a
#: BILLS package's own `uslm/{id}.xml` rendition.
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
#: `tests/test_congress_bill_versions.py` pins them equal. USLM stays out of
#: the default: it is recognized by name and by folder but is not acquirable
#: (see `FORMAT_TYPE_NAMES`).
DEFAULT_FORMAT_PREFERENCE: tuple[str, ...] = ("xml", "html", "txt", "pdf")


def choose_format(
    formats: Sequence[BillTextFormat], prefer: Sequence[str] = DEFAULT_FORMAT_PREFERENCE
) -> BillTextFormat | None:
    """The first offered format matching `prefer` in order, or None.

    The default is the sealed body preference (`DEFAULT_FORMAT_PREFERENCE`),
    which keeps BillTrax's `congress-api.ts chooseFormat` order -- XML, then
    text, then PDF -- and adds HTML between XML and text, where the sealed
    order puts it. PDF stays the last default rather than being excluded:
    bill PDFs measured small (median 246 KB; see "The PDF path" in
    `docs/sources/congress-bill-versions.md`), so a version a publisher
    offers only as PDF is chosen here rather than refused.

    Also ports `sync-govinfo.ts pickVersionUrls`'s fallback for a format item
    with no stated `type`. `prefer` takes this module's short format names
    (`FORMAT_TYPE_NAMES`'s values plus `uslm`), not Congress.gov's `type`
    strings.
    """
    if isinstance(prefer, str) or not isinstance(prefer, Sequence):
        raise TypeError("prefer must be a sequence of format names, not one name")
    named = [(item, format_name(item)) for item in formats if item.url]
    for name in prefer:
        for item, item_name in named:
            if item_name == name:
                return item
    return None


__all__ = [
    "DEFAULT_FORMAT_PREFERENCE",
    "FORMAT_TYPE_NAMES",
    "VERSION_CODES",
    "VERSION_CODES_BY_SLUG",
    "VersionCode",
    "VersionCodeError",
    "bill_version_package_id",
    "choose_format",
    "format_name",
    "govinfo_suffix",
    "slugify",
    "version_slug",
    "version_slug_reprints",
]
