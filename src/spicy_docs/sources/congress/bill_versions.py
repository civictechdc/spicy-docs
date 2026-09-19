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

**What the measurement changed.** `docs/research/billtrax-raw-data-2026-09-19.md`
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
   Amendment Senate" names both `eas` and its numbered reprint `eas2`, and
   "Engrossed in House" names both `eh` and `eh1s`. No name-derived slug can
   tell those apart -- `version_slug()`/`slugify()` produce the same string
   for both. Only the GovInfo package id itself (or, per the doctype sample,
   the document's own `@bill-stage`/`@resolution-stage` attribute, a *third*
   spelling: `rs`'s API `type` is "Reported to Senate" but its XML root states
   `resolution-stage="Reported-in-Senate"`) carries the real identity.
3. **The map itself is demoted, not deleted.** `bill_version_package_id` (the
   port of `buildGovinfoPdfUrl`) and `version_slug` (the port of `slugify`
   applied to a version-type name, as BillTrax's ingest path does) remain --
   BillTrax's SQL already holds rows keyed on these slugs with no stored
   package id, and some acquisition paths still only have a type name -- but
   they are the *fallback*, not the derivation `acquire_bill_pdf` prefers.
   The publisher's own package id, read from a stated format URL via
   `sources.congress.bill_status.bill_package_id_from_url`, is preferred
   whenever a caller has one; see `bill_pdf.acquire_bill_pdf`.

`VERSION_CODES` therefore carries, per slug, every spelling this port found
evidence for: the `version_types` Congress.gov states (measured for the 24
codes seen in the 119th BILLS corpus), the `stage_value` the document's own
root attribute states (measured for 10 of them, from a 40-file structural
sample -- `docs/research/billtrax-raw-data-2026-09-19.json`
`sources.billXmlStructure.doctypeAndStage`), and the `govinfo_suffix` the
fallback path builds a package id from. `measured_119th` records whether that
suffix appeared at all in the 119th BILLS package-id census; two of
BillTrax's own passthrough entries (`pch`, `hds`) did not.

Format choice ports `congress-api.ts chooseFormat`/`chooseXmlFormat` and
`sync-govinfo.ts pickVersionUrls`, including the URL-suffix fallback
`pickVersionUrls` added at `sync-govinfo.ts:262` for a format item with no
stated `type`. Measured 2026-09-19: every one of 240 sampled format entries
across 24 bills carried a `type`, so the fallback is kept as a tolerance, not
a live path. A fourth format, `United States Legislative Markup` (USLM, 10 of
240 sampled entries, offered on enrolled bills), is in `choose_format`'s known
vocabulary -- BillTrax never read it, but `sources.govinfo.uslm` already does.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from spicy_docs.sources.congress.bill_status import BillIdentity, BillTextFormat

_SLUG_COLLAPSE = re.compile(r"[^a-z0-9]+")


class VersionCodeError(ValueError):
    """A version-code slug cannot be resolved to a GovInfo package-id suffix."""


@dataclass(frozen=True, slots=True)
class VersionCode:
    """One entry in the sealed `version_code` vocabulary.

    ``slug`` is what BillTrax stores in ``bill_versions.version_code`` and is
    never renamed. ``govinfo_suffix`` is the BILLS package-id suffix the
    fallback path (``bill_version_package_id``) builds from this slug.
    ``version_types`` are the Congress.gov ``textVersions[].type`` strings
    measured to produce this slug via ``version_slug`` (empty when the slug
    is a short code addressed directly, never derived by name).
    ``stage_value`` is the document's own ``@bill-stage``/``@resolution-stage``
    attribute spelling for this suffix, where measured -- a third, independent
    publisher spelling `bill_text.py` already reads for three of these.
    ``measured_119th`` is True when this exact suffix appeared in the 119th
    Congress BILLS package-id census (24 distinct suffixes, 21,947 files).
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
        note="BillTrax knew this suffix; the 119th BILLS corpus never produced it.",
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
        ("Held at the Desk Senate",),
        note="BillTrax knew this suffix; the 119th BILLS corpus never produced it.",
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
        ("Reported to Senate",),
        "Reported-in-Senate",
        True,
        note="A third spelling: API type says 'to Senate', the XML root's resolution-stage says 'in-Senate'.",
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
        note="568 files (2.6% of the 119th BILLS corpus) -- the single largest gap in BillTrax's map.",
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
    VersionCode("as", "as", ("Amendment Ordered to be Printed (Senate)",), measured_119th=True),
    VersionCode("cdh", "cdh", ("Committee Discharged House",), measured_119th=True),
    VersionCode(
        "eas2",
        "eas2",
        ("Engrossed Amendment Senate",),
        measured_119th=True,
        note=(
            "A numbered reprint of 'eas'; Congress.gov's type string is "
            "identical to eas's, so version_slug() cannot recover this suffix "
            "from a name -- only a stated package id (or this passthrough "
            "entry, when the suffix is already known) can address it."
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
)

VERSION_CODES_BY_SLUG: dict[str, VersionCode] = {entry.slug: entry for entry in VERSION_CODES}
if len(VERSION_CODES_BY_SLUG) != len(VERSION_CODES):
    raise AssertionError("VERSION_CODES has a duplicate slug")


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

    This is exactly `slugify(version_type)` (`congress-api.ts:291`,
    `sync-govinfo.ts` version_code derivation): BillTrax has no separate
    type-to-slug dictionary, so every type string produces a slug this way
    with no refusal case -- slugify's general rule is the whole mapping and
    its own fallback.

    This is the *name-derived* fallback. A numbered reprint (`eas2`, `eh1s`)
    slugifies identically to its original (`eas`, `eh`) because Congress.gov
    gives both the same `type` string, so this function cannot recover a
    reprint's real suffix. Prefer a stated package id when one exists; see
    `bill_pdf.acquire_bill_pdf`.
    """
    if not isinstance(version_type, str) or not version_type:
        raise VersionCodeError("version_type must be a nonempty string")
    return slugify(version_type)


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
# pickVersionUrls (the URL-suffix fallback at sync-govinfo.ts:262).
# ---------------------------------------------------------------------------

#: Congress.gov `textVersions[].formats[].type` strings this module recognizes,
#: to the short format name `choose_format` matches against `prefer`. A fourth
#: format BillTrax never read: USLM, offered on enrolled bills (10 of 240
#: format entries sampled 2026-09-19); `sources.govinfo.uslm` already reads it.
FORMAT_TYPE_NAMES: dict[str, str] = {
    "Formatted Text": "txt",
    "Formatted XML": "xml",
    "PDF": "pdf",
    "HTML": "html",
    "United States Legislative Markup": "uslm",
}
#: The fallback `pickVersionUrls` (`sync-govinfo.ts:255-268`) applies to a
#: format item whose `type` is absent: name it from its URL's extension.
#: Measured 2026-09-19: 0 of 240 sampled format entries had no `type`, so
#: this is a tolerance, not a live path (docs/research/billtrax-raw-data-2026-09-19.md §7).
_FORMAT_URL_SUFFIXES: tuple[tuple[str, str], ...] = (
    (".xml", "xml"),
    (".htm", "html"),
    (".html", "html"),
    (".txt", "txt"),
    (".pdf", "pdf"),
)


def _format_name(item: BillTextFormat) -> str | None:
    if item.type is not None:
        return FORMAT_TYPE_NAMES.get(item.type)
    for suffix, name in _FORMAT_URL_SUFFIXES:
        if item.url.endswith(suffix):
            return name
    return None


def choose_format(
    formats: Sequence[BillTextFormat], prefer: Sequence[str] = ("xml", "html", "txt")
) -> BillTextFormat | None:
    """The first offered format matching `prefer` in order, or None.

    Ports `congress-api.ts chooseFormat`/`chooseXmlFormat` (XML then text
    then PDF preference) and `sync-govinfo.ts pickVersionUrls` (its
    URL-suffix fallback for a format item with no stated `type`) as one
    function. `prefer` takes this module's short format names
    (`FORMAT_TYPE_NAMES`'s values), not Congress.gov's `type` strings.
    """
    if isinstance(prefer, str) or not isinstance(prefer, Sequence):
        raise TypeError("prefer must be a sequence of format names, not one name")
    named = [(item, _format_name(item)) for item in formats if item.url]
    for name in prefer:
        for item, item_name in named:
            if item_name == name:
                return item
    return None


__all__ = [
    "FORMAT_TYPE_NAMES",
    "VERSION_CODES",
    "VERSION_CODES_BY_SLUG",
    "VersionCode",
    "VersionCodeError",
    "bill_version_package_id",
    "choose_format",
    "govinfo_suffix",
    "slugify",
    "version_slug",
]
