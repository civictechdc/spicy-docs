"""The sealed version-code vocabulary, format choice, package ids and version kind.

BillTrax originals: `src/lib/version-kind.ts`/`version-kind.test.ts` (32 cases,
ported below verbatim), `src/lib/govinfo-pdf-fetch.ts:26-58` (canonical slug
map) and `scripts/validate-pdf-xml-concordance.ts:44-64` (its drifted, private
copy) -- both read-only from `/Users/mikewolfd/Work/spicy-stack/BillTrax`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spicy_docs.interpretation.version_kind import version_kind
from spicy_docs.sources.congress.bill_status import BillIdentity, BillTextFormat
from spicy_docs.sources.congress.bill_versions import (
    VERSION_CODES,
    VERSION_CODES_BY_SLUG,
    VersionCodeError,
    bill_version_package_id,
    choose_format,
    govinfo_suffix,
    slugify,
    version_slug,
)
from spicy_docs.sources.govinfo.bodies import parse_package_id

# ---------------------------------------------------------------------------
# The two BillTrax copies, transcribed verbatim as evidence, not imported --
# BillTrax is a sibling repo this project does not depend on. Every key here
# came from reading the file directly (govinfo-pdf-fetch.ts:26-58,
# validate-pdf-xml-concordance.ts:44-64) on 2026-09-19.
# ---------------------------------------------------------------------------

_GOVINFO_PDF_FETCH_KEYS = frozenset(
    {
        # 16 name-derived long slugs
        "introduced-in-house",
        "introduced-in-senate",
        "engrossed-in-house",
        "engrossed-in-senate",
        "enrolled-bill",
        "public-law",
        "placed-on-calendar-senate",
        "placed-on-calendar-house",
        "referred-to-senate",
        "referred-to-house",
        "held-at-desk-senate",
        "returned-to-the-house-by-unanimous-consent",
        "engrossed-amendment-senate",
        "engrossed-amendment-house",
        "reported-in-house",
        "reported-in-senate",
        # 14 passthrough short codes
        "ih",
        "is",
        "eh",
        "es",
        "enr",
        "pcs",
        "pch",
        "rds",
        "rfh",
        "hds",
        "eas",
        "eah",
        "rh",
        "rs",
    }
)
assert len(_GOVINFO_PDF_FETCH_KEYS) == 30

_DRIFTED_CONCORDANCE_KEYS = frozenset(
    {
        # Same 16 long slugs
        "introduced-in-house",
        "introduced-in-senate",
        "engrossed-in-house",
        "engrossed-in-senate",
        "enrolled-bill",
        "public-law",
        "placed-on-calendar-senate",
        "placed-on-calendar-house",
        "referred-to-senate",
        "referred-to-house",
        "held-at-desk-senate",
        "returned-to-the-house-by-unanimous-consent",
        "engrossed-amendment-senate",
        "engrossed-amendment-house",
        "reported-in-house",
        "reported-in-senate",
        # Only 10 passthrough short codes -- missing pch, rds, rfh, hds
        "ih",
        "is",
        "eh",
        "es",
        "enr",
        "pcs",
        "eas",
        "eah",
        "rh",
        "rs",
    }
)
assert len(_DRIFTED_CONCORDANCE_KEYS) == 26
assert _DRIFTED_CONCORDANCE_KEYS < _GOVINFO_PDF_FETCH_KEYS  # the drift, measured: a strict subset

# The 24 GovInfo BILLS package-id suffixes the 119th Congress actually used
# (docs/research/billtrax-raw-data-2026-09-19.md §1, 21,947 files, all 19
# `bulkdata/json/BILLS/119/{session}/{type}` listings).
_MEASURED_119TH_CODES = frozenset(
    {
        "ih", "is", "eh", "rh", "rfs", "rs", "ats", "es", "pcs", "enr", "rds", "cps",
        "eas", "eah", "rfh", "rcs", "rhuc", "as", "cdh", "eas2", "eh1s", "lth", "rfs2", "ris",
    }
)  # fmt: skip
assert len(_MEASURED_119TH_CODES) == 24


def test_vocabulary_is_the_union_of_both_billtrax_copies() -> None:
    """The drift is closed, not perpetuated: no key either copy held is missing here."""
    slugs = set(VERSION_CODES_BY_SLUG)
    missing_from_canonical = _GOVINFO_PDF_FETCH_KEYS - slugs
    missing_from_drifted = _DRIFTED_CONCORDANCE_KEYS - slugs
    assert not missing_from_canonical, f"lost canonical slugs: {sorted(missing_from_canonical)}"
    assert not missing_from_drifted, f"lost drifted-copy slugs: {sorted(missing_from_drifted)}"
    # Bidirectional, per the inventory's own complaint about the BillTrax test
    # this replaces: a check that only confirms a subset agrees would not have
    # caught the drift. Every slug this module additionally carries is either
    # a passthrough for the corrected returned-to-the-house-by-unanimous-consent
    # target, or a measured 119th addition -- never a silent rename.
    additions = slugs - _GOVINFO_PDF_FETCH_KEYS
    assert additions == (_MEASURED_119TH_CODES - _GOVINFO_PDF_FETCH_KEYS)


def test_every_slug_but_one_keeps_billtraxs_original_govinfo_suffix() -> None:
    """The one deliberate correction (outcome over rules) is isolated and documented."""
    original_targets = {
        "introduced-in-house": "ih",
        "introduced-in-senate": "is",
        "engrossed-in-house": "eh",
        "engrossed-in-senate": "es",
        "enrolled-bill": "enr",
        "public-law": "enr",
        "placed-on-calendar-senate": "pcs",
        "placed-on-calendar-house": "pch",
        "referred-to-senate": "rds",
        "referred-to-house": "rfh",
        "held-at-desk-senate": "hds",
        "returned-to-the-house-by-unanimous-consent": "rfh",  # BillTrax's original (measured wrong)
        "engrossed-amendment-senate": "eas",
        "engrossed-amendment-house": "eah",
        "reported-in-house": "rh",
        "reported-in-senate": "rs",
    }
    corrected = {"returned-to-the-house-by-unanimous-consent"}
    for slug, original_suffix in original_targets.items():
        if slug in corrected:
            assert govinfo_suffix(slug) == "rhuc", "the measured 119th suffix, not BillTrax's 'rfh'"
        else:
            assert govinfo_suffix(slug) == original_suffix


@pytest.mark.parametrize("code", sorted(_MEASURED_119TH_CODES))
def test_every_code_measured_in_the_119th_maps_to_a_slug(code: str) -> None:
    assert code in {entry.govinfo_suffix for entry in VERSION_CODES}


def test_billtraxs_own_unused_passthroughs_are_marked_unmeasured() -> None:
    """BillTrax carries pch and hds; the 119th BILLS corpus never produced either."""
    assert VERSION_CODES_BY_SLUG["pch"].measured_119th is False
    assert VERSION_CODES_BY_SLUG["hds"].measured_119th is False
    for code in _MEASURED_119TH_CODES:
        matches = [entry for entry in VERSION_CODES if entry.slug == code]
        if matches:
            assert matches[0].measured_119th is True


# ---------------------------------------------------------------------------
# slugify / version_slug
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("Engrossed Amendment Senate", "engrossed-amendment-senate"),
        ("Introduced in House", "introduced-in-house"),
        ("  Reported to Senate!!  ", "reported-to-senate"),
        ("A.B.--C", "a-b-c"),
        ("already-a-slug", "already-a-slug"),
    ],
)
def test_slugify_matches_billtrax(value: str, expected: str) -> None:
    assert slugify(value) == expected


def test_version_slug_is_slugify_with_no_refusal_case() -> None:
    assert version_slug("Engrossed Amendment Senate") == "engrossed-amendment-senate"
    with pytest.raises(VersionCodeError):
        version_slug("")


def test_version_slug_cannot_distinguish_a_numbered_reprint() -> None:
    """Congress.gov gives eas and eas2 the identical type string; slugify can't tell them apart."""
    assert version_slug("Engrossed Amendment Senate") == version_slug("Engrossed Amendment Senate")
    assert VERSION_CODES_BY_SLUG["eas2"].govinfo_suffix == "eas2"
    assert VERSION_CODES_BY_SLUG["eas"].govinfo_suffix == "eas"


# ---------------------------------------------------------------------------
# bill_version_package_id / govinfo_suffix and its round trip through the
# BILLS grammar govinfo/bodies.py already parses.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "congress,bill_type,number,slug,expected",
    [
        (119, "hr", 7148, "introduced-in-house", "BILLS-119hr7148ih"),
        (118, "s", 4366, "enrolled-bill", "BILLS-118s4366enr"),
        (119, "hjres", 77, "introduced-in-house", "BILLS-119hjres77ih"),
        (119, "hr", 1, "ih", "BILLS-119hr1ih"),
        (119, "hr", 6644, "eas2", "BILLS-119hr6644eas2"),
    ],
)
def test_bill_version_package_id_matches_billtraxs_url_stem(
    congress: int, bill_type: str, number: int, slug: str, expected: str
) -> None:
    identity = BillIdentity(congress, bill_type, number)
    assert bill_version_package_id(identity, slug) == expected


def test_bill_version_package_id_refuses_an_unmapped_slug() -> None:
    with pytest.raises(VersionCodeError, match="not in the sealed vocabulary"):
        bill_version_package_id(BillIdentity(119, "hr", 1), "some-unknown-code")


@pytest.mark.parametrize("slug", ["introduced-in-house", "eas2", "rhuc", "returned-to-the-house-by-unanimous-consent"])
def test_bill_version_package_id_round_trips_through_parse_package_id(slug: str) -> None:
    identity = BillIdentity(119, "hr", 7148)
    package_id = bill_version_package_id(identity, slug)
    parsed = parse_package_id(package_id)
    assert parsed.collection == "BILLS"
    assert parsed.congress == identity.congress
    assert parsed.document_type == identity.bill_type
    assert parsed.number == str(identity.number)
    assert parsed.version == govinfo_suffix(slug)


# ---------------------------------------------------------------------------
# choose_format: congress-api.ts chooseFormat/chooseXmlFormat + sync-govinfo.ts
# pickVersionUrls's URL-suffix fallback.
# ---------------------------------------------------------------------------


def _fmt(url: str, type_: str | None) -> BillTextFormat:
    return BillTextFormat(url=url, type=type_, package_id=None)


def test_choose_format_prefers_xml_then_html_then_text() -> None:
    formats = [
        _fmt("https://example.invalid/a.htm", "HTML"),
        _fmt("https://example.invalid/a.xml", "Formatted XML"),
        _fmt("https://example.invalid/a.txt", "Formatted Text"),
    ]
    assert choose_format(formats).url.endswith(".xml")
    assert choose_format(formats, prefer=("txt",)).url.endswith(".txt")
    assert choose_format(formats, prefer=("pdf",)) is None


def test_choose_format_never_picks_pdf_unless_asked() -> None:
    formats = [_fmt("https://example.invalid/a.pdf", "PDF")]
    assert choose_format(formats) is None
    assert choose_format(formats, prefer=("pdf",)) is formats[0]


def test_choose_format_recognizes_uslm() -> None:
    formats = [_fmt("https://example.invalid/a.xml", "United States Legislative Markup")]
    assert choose_format(formats, prefer=("uslm",)) is formats[0]
    # Not in the default preference (BillTrax never read it, matching its port contract).
    assert choose_format(formats) is None


def test_choose_format_falls_back_to_the_url_suffix_when_type_is_missing() -> None:
    """sync-govinfo.ts:262's fallback: measured to fire 0/240 times, kept as a tolerance."""
    formats = [_fmt("https://example.invalid/a.xml", None)]
    assert choose_format(formats, prefer=("xml",)) is formats[0]
    assert choose_format([_fmt("https://example.invalid/a.pdf", None)], prefer=("pdf",)) is not None
    assert choose_format([_fmt("https://example.invalid/a.unknown", None)], prefer=("xml", "html", "txt")) is None


def test_choose_format_skips_items_with_no_url() -> None:
    assert choose_format([_fmt("", "Formatted XML")]) is None


def test_choose_format_rejects_a_single_name_for_prefer() -> None:
    with pytest.raises(TypeError):
        choose_format([_fmt("https://example.invalid/a.xml", "Formatted XML")], prefer="xml")


# ---------------------------------------------------------------------------
# version_kind: the 32 cases from version-kind.test.ts, ported verbatim.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version_code,section_count,body_bytes,expected",
    [
        # Full-text slugs
        ("introduced-in-house", None, 50_000, "full_text"),
        ("introduced-in-senate", None, 50_000, "full_text"),
        ("engrossed-in-house", None, 50_000, "full_text"),
        ("enrolled-bill", None, 50_000, "full_text"),
        ("public-law", None, 50_000, "full_text"),
        ("reported-in-house", None, 50_000, "full_text"),
        ("reported-to-senate", None, 50_000, "full_text"),
        ("placed-on-calendar-senate", None, 50_000, "full_text"),
        ("reference-change-senate", None, 50_000, "full_text"),
        ("returned-to-the-house-by-unanimous-consent", None, 50_000, "full_text"),
        # Procedural amendments slugs
        ("engrossed-amendment-senate", None, None, "procedural_amendments"),
        ("engrossed-amendment-house", None, None, "procedural_amendments"),
        ("amendment-senate", None, None, "procedural_amendments"),
        ("amendment-house", None, None, "procedural_amendments"),
        ("failed-amendment-senate", None, None, "procedural_amendments"),
        # Procedural summary slugs
        ("statement-of-substance", None, None, "procedural_summary"),
        ("held-at-desk-senate", None, None, "procedural_summary"),
        # Size-heuristic override
        ("engrossed-in-house", None, 5_000, "kind_uncertain"),
        ("introduced-in-house", 3, 50_000, "kind_uncertain"),
        ("engrossed-in-house", None, 10_000, "full_text"),
        ("engrossed-in-house", 20, 50_000, "full_text"),
        ("engrossed-in-house", None, None, "full_text"),
        ("engrossed-amendment-senate", None, 50_000, "procedural_amendments"),
        # Unknown slug heuristics
        ("some-new-amendment-type", None, None, "procedural_amendments"),
        ("some-new-version-type", None, 50_000, "full_text"),
        ("some-new-version-type", None, 2_000, "unknown"),
        ("some-new-version-type", None, None, "unknown"),
        (None, None, None, "unknown"),
        ("", None, None, "unknown"),
        # Slug normalization
        ("Engrossed-Amendment-Senate", None, None, "procedural_amendments"),
        ("Engrossed Amendment Senate", None, None, "procedural_amendments"),
        ("Introduced in House", None, 50_000, "full_text"),
    ],
)
def test_version_kind_matches_version_kind_ts(
    version_code: str | None, section_count: int | None, body_bytes: int | None, expected: str
) -> None:
    assert version_kind(version_code, section_count=section_count, body_bytes=body_bytes) == expected


# ---------------------------------------------------------------------------
# Live PDF acquisition, mirroring test_govinfo_package_body_acquisition.py's
# read_api_key(...) pattern -- credentials header-only, never in a fixture.
# ---------------------------------------------------------------------------

ENV_FILE = Path("/Users/mikewolfd/Work/spicy-stack/spicy-docs/.env")


@pytest.mark.integration
def test_live_bill_pdf_is_acquired_and_proved() -> None:
    from spicy_docs.sources.congress.bill_pdf import acquire_bill_pdf
    from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
    from spicy_docs.transport.credentials import read_api_key

    if not ENV_FILE.exists():
        pytest.skip(f"no credential file at {ENV_FILE}")
    # BILLS-119hconres11eh: the smallest bill PDF sampled 2026-09-19
    # (112,378 bytes, docs/research/billtrax-raw-data-2026-09-19.md §3).
    identity = BillIdentity(119, "hconres", 11)
    budget = GovInfoBodyBudget(
        max_requests=6,
        max_body_bytes=8 * 1024 * 1024,
        max_metadata_bytes=8 * 1024 * 1024,
        timeout_seconds=60.0,
        min_request_interval_seconds=0.5,
    )
    key = read_api_key(ENV_FILE, "API_GOV")
    with GovInfoBodyAcquirer(budget=budget, api_key=key) as client:
        result = acquire_bill_pdf(identity, "engrossed-in-house", acquirer=client)

    assert result.identity.package_id == "BILLS-119hconres11eh"
    assert result.format == "pdf"
    assert result.body_capture.body.startswith(b"%PDF-")
    assert result.body_capture.byte_size > 10_000
    assert key.encode() not in result.body_capture.body
