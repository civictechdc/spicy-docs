"""The sealed version-code vocabulary, format choice, package ids and version kind.

BillTrax originals: `src/lib/version-kind.ts`/`version-kind.test.ts` (32 cases,
ported below verbatim), `src/lib/govinfo-pdf-fetch.ts:26-58` (canonical slug
map) and `scripts/validate-pdf-xml-concordance.ts:44-64` (its drifted, private
copy) -- both read-only from `/Users/mikewolfd/Work/spicy-stack/BillTrax`.
DeltaTrack upstream's `tools/fetch_govinfo.py::VERSION_CODES` (read-only at
`/private/tmp/claude-501/-Users-mikewolfd-Work-spicy-docs/8a5a1a5d-bd44-4a09-a525-c269c5837b3d/scratchpad/DeltaTrack-upstream`,
canonical repo `https://github.com/civictechdc/DeltaTrack`) is the source for
the cross-check tests near the bottom of the vocabulary section.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from spicy_docs.interpretation.version_kind import VersionKindFinding, version_kind, version_kind_finding
from spicy_docs.sources.congress.bill_status import BillIdentity, BillTextFormat, parse_bill_status
from spicy_docs.sources.congress.bill_versions import (
    DEFAULT_FORMAT_PREFERENCE,
    VERSION_CODES,
    VERSION_CODES_BY_SLUG,
    VersionCodeError,
    bill_version_package_id,
    choose_format,
    govinfo_suffix,
    slugify,
    version_slug,
    version_slug_reprints,
)
from spicy_docs.sources.govinfo.bodies import BODY_PREFERENCE, parse_package_id

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"

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

# DeltaTrack upstream's full authoritative govinfo code list (govinfo.gov/help/bills,
# 53 codes), transcribed from tools/fetch_govinfo.py::VERSION_CODES.
_DELTATRACK_UPSTREAM_CODES = frozenset(
    {
        "ih", "is", "ash", "sas", "sc", "rfh", "rfs", "rdh", "rds", "rch", "rcs", "rth", "rts",
        "rih", "ris", "rah", "ras", "hdh", "hds", "rh", "rs", "pch", "pcs", "cdh", "cds", "oph",
        "ops", "pp", "pav", "eh", "es", "eah", "eas", "reah", "res", "eph", "cph", "cps", "ath",
        "ats", "as", "fah", "fph", "fps", "iph", "ips", "lth", "lts", "pwah", "rhuc", "enr",
        "renr", "pap",
    }
)  # fmt: skip
assert len(_DELTATRACK_UPSTREAM_CODES) == 53
# Every 119th code "resolves" upstream in the sense the coordinator measured:
# either a direct base-table entry, or -- for the three numbered reprints --
# via upstream's own resolve_code() longest-known-prefix fallback (eas2 ->
# eas, eh1s -> eh, rfs2 -> rfs), the same earliest-printing rule this module's
# version_slug_reprints exposes rather than resolves silently.
_MEASURED_119TH_REPRINTS = frozenset({"eas2", "eh1s", "rfs2"})
assert (_MEASURED_119TH_CODES - _MEASURED_119TH_REPRINTS) <= _DELTATRACK_UPSTREAM_CODES

# The 30 upstream codes neither BillTrax nor this port's own 119th
# measurement produced, added as unmeasured passthrough entries.
_UPSTREAM_ONLY_CODES = frozenset(
    {
        "ash", "sas", "sc", "rdh", "rch", "rth", "rts", "rih", "rah", "ras", "hdh",
        "cds", "oph", "ops", "pp", "pav", "reah", "res", "eph", "cph", "ath",
        "fah", "fph", "fps", "iph", "ips", "lts", "pwah", "renr", "pap",
    }
)  # fmt: skip
assert len(_UPSTREAM_ONLY_CODES) == 30
assert _UPSTREAM_ONLY_CODES == _DELTATRACK_UPSTREAM_CODES - _GOVINFO_PDF_FETCH_KEYS - _MEASURED_119TH_CODES


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
    # target, a measured 119th addition, or an unmeasured DeltaTrack-upstream
    # addition -- never a silent rename.
    additions = slugs - _GOVINFO_PDF_FETCH_KEYS
    assert additions == (_MEASURED_119TH_CODES - _GOVINFO_PDF_FETCH_KEYS) | _UPSTREAM_ONLY_CODES


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
# Cross-checked against DeltaTrack upstream's authoritative govinfo list.
# ---------------------------------------------------------------------------


def test_every_deltatrack_upstream_code_resolves() -> None:
    """All 53 govinfo codes DeltaTrack's authoritative list names are addressable here."""
    known_suffixes = {entry.govinfo_suffix for entry in VERSION_CODES} | set(VERSION_CODES_BY_SLUG)
    missing = _DELTATRACK_UPSTREAM_CODES - known_suffixes
    assert not missing, f"upstream codes with no entry: {sorted(missing)}"


def test_upstream_only_codes_are_added_unmeasured_not_silently_dropped() -> None:
    for code in _UPSTREAM_ONLY_CODES:
        entry = VERSION_CODES_BY_SLUG[code]
        assert entry.measured_119th is False
        assert entry.version_types, f"{code} has no recorded name"
        assert entry.note is not None and "DeltaTrack" in entry.note


def test_two_cosmetic_spelling_differences_against_upstream_are_recorded() -> None:
    """rs and as: the measured Congress.gov spelling differs from upstream's canonical one."""
    assert "Reported to Senate" in VERSION_CODES_BY_SLUG["reported-in-senate"].version_types  # measured
    assert "Reported in Senate" in VERSION_CODES_BY_SLUG["reported-in-senate"].version_types  # upstream
    assert "Amendment Ordered to be Printed (Senate)" in VERSION_CODES_BY_SLUG["as"].version_types  # measured
    assert "Amendment Ordered to be Printed Senate" in VERSION_CODES_BY_SLUG["as"].version_types  # upstream


# ---------------------------------------------------------------------------
# slugify / version_slug / version_slug_reprints
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


def test_version_slug_redirects_to_the_sealed_slug_a_measured_name_actually_claims() -> None:
    """slugify("Received in Senate") alone is not a vocabulary entry; the sealed slug is."""
    assert version_slug("Received in Senate") == "referred-to-senate"  # BillTrax's own name
    assert govinfo_suffix(version_slug("Received in Senate")) == "rds"
    assert version_slug("Referred in Senate") == "rfs"  # a pure addition, not name-derived
    assert govinfo_suffix(version_slug("Referred in Senate")) == "rfs"


def test_version_slug_reprints_exposes_the_ambiguity_it_resolves_through() -> None:
    """Congress.gov gives eas/eas2, eh/eh1s and rfs/rfs2 the identical type string."""
    assert version_slug("Engrossed Amendment Senate") == "engrossed-amendment-senate"
    assert govinfo_suffix(version_slug("Engrossed Amendment Senate")) == "eas"  # earliest printing, silently
    assert version_slug_reprints("Engrossed Amendment Senate") == ("eas2",)  # exposed, not hidden
    assert version_slug_reprints("Engrossed in House") == ("eh1s",)
    assert version_slug_reprints("Referred in Senate") == ("rfs2",)
    # An unambiguous name, and a long-slug/short-code alias for one document
    # (not two different documents), both expose nothing.
    assert version_slug_reprints("Introduced in House") == ()
    assert version_slug_reprints("Returned to the House by Unanimous Consent") == ()


@pytest.mark.parametrize("entry", [entry for entry in VERSION_CODES if entry.version_types], ids=lambda e: e.slug)
def test_name_derived_composition_resolves_or_is_flagged_ambiguous(entry) -> None:
    """Every measured or cited type name composes to a working package id -- ambiguous or not."""
    identity = BillIdentity(119, "hr", 1)
    for measured_type in entry.version_types:
        derived_slug = version_slug(measured_type)
        resolved_suffix = govinfo_suffix(derived_slug)  # must not raise
        package_id = bill_version_package_id(identity, derived_slug)
        assert package_id.endswith(resolved_suffix)
        reprints = version_slug_reprints(measured_type)
        if reprints:
            # Ambiguous: this entry's own slug is one of the named claimants
            # of the shared type name, even when version_slug resolved this
            # particular measured_type to a different (earlier-printed) one.
            assert entry.slug in (derived_slug, *reprints)
        else:
            # Unambiguous: the resolved suffix is this document's, whether
            # reached through this entry's own slug or an alias for the same
            # suffix declared first (long-slug/short-code pairs like
            # returned-to-the-house-by-unanimous-consent/rhuc).
            assert resolved_suffix == entry.govinfo_suffix


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
# pickVersionUrls's fallback, now folder- not extension-based (Fix 2).
# ---------------------------------------------------------------------------


def _fmt(url: str, type_: str | None) -> BillTextFormat:
    return BillTextFormat(url=url, type=type_, package_id=None)


def test_choose_format_default_is_the_sealed_body_preference() -> None:
    """One order, two spellings: `htm` on the GovInfo side is `html` here."""
    assert DEFAULT_FORMAT_PREFERENCE == tuple("html" if name == "htm" else name for name in BODY_PREFERENCE)
    formats = [
        _fmt("https://example.invalid/content/pkg/BILLS-119hr1ih/pdf/BILLS-119hr1ih.pdf", "PDF"),
        _fmt("https://example.invalid/content/pkg/BILLS-119hr1ih/xml/BILLS-119hr1ih.xml", "Formatted XML"),
        _fmt("https://example.invalid/content/pkg/BILLS-119hr1ih/text/BILLS-119hr1ih.txt", "Formatted Text"),
    ]
    assert choose_format(formats).url.endswith(".xml")
    assert choose_format(formats, prefer=("txt",)).url.endswith(".txt")
    # A version offered only as PDF is chosen, not refused -- the whole point
    # of keeping PDF last rather than leaving it out.
    assert choose_format([formats[0]]).url.endswith(".pdf")


def test_choose_format_prefers_html_over_formatted_text() -> None:
    """The sealed order puts htm/html between xml and txt; this is the one pair that moved."""
    html = _fmt("https://example.invalid/content/pkg/BILLS-119hr1ih/html/BILLS-119hr1ih.htm", "HTML")
    txt = _fmt("https://example.invalid/content/pkg/BILLS-119hr1ih/text/BILLS-119hr1ih.txt", "Formatted Text")
    assert choose_format([txt, html]) is html
    assert choose_format([txt]) is txt


def test_choose_format_recognizes_uslm_by_type_but_not_by_default() -> None:
    formats = [
        _fmt(
            "https://example.invalid/content/pkg/BILLS-119s1071enr/uslm/BILLS-119s1071enr.xml",
            "United States Legislative Markup",
        )
    ]
    assert choose_format(formats, prefer=("uslm",)) is formats[0]
    assert choose_format(formats) is None  # not in the default preference, matching BillTrax's own order


def test_choose_format_falls_back_to_the_url_folder_when_type_is_missing() -> None:
    """The only live path against BILLSTATUS-sourced data: bill_status.py never sets .type."""
    xml = _fmt("https://www.govinfo.gov/content/pkg/BILLS-119hr1ih/xml/BILLS-119hr1ih.xml", None)
    pdf = _fmt("https://www.govinfo.gov/content/pkg/BILLS-119hr1ih/pdf/BILLS-119hr1ih.pdf", None)
    txt = _fmt("https://www.govinfo.gov/content/pkg/BILLS-119hr1ih/text/BILLS-119hr1ih.txt", None)
    uslm = _fmt("https://www.govinfo.gov/content/pkg/BILLS-119s1071enr/uslm/BILLS-119s1071enr.xml", None)
    assert choose_format([xml], prefer=("xml",)) is xml
    assert choose_format([pdf], prefer=("pdf",)) is pdf
    assert choose_format([txt], prefer=("txt",)) is txt
    assert choose_format([uslm], prefer=("uslm",)) is uslm
    # xml and uslm share the .xml extension; only the folder segment tells them apart.
    assert choose_format([uslm], prefer=("xml",)) is None
    assert choose_format([_fmt("https://example.invalid/a.unknown", None)], prefer=("xml", "txt", "pdf")) is None


def test_choose_format_on_real_billstatus_data_uses_the_folder_fallback() -> None:
    """BILLSTATUS's <formats><item> carries <url> only, never <type>, on every measured fixture."""
    status = parse_bill_status((FIXTURES / "status-119hr6028.xml").read_bytes(), identity=BillIdentity(119, "hr", 6028))
    eh_version = next(v for v in status.text_versions if v.type == "Engrossed in House")
    assert all(f.type is None for f in eh_version.formats)
    chosen = choose_format(eh_version.formats)
    assert chosen is not None
    assert chosen.type is None
    assert "/xml/" in chosen.url


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


@pytest.mark.parametrize(
    "version_code,section_count,body_bytes,expected_kind,expected_rule",
    [
        ("engrossed-amendment-senate", None, None, "procedural_amendments", "procedural_amendments_slug"),
        ("statement-of-substance", None, None, "procedural_summary", "procedural_summary_slug"),
        ("introduced-in-house", None, 50_000, "full_text", "full_text_slug"),
        ("engrossed-in-house", None, 5_000, "kind_uncertain", "full_text_slug_thin"),
        ("introduced-in-house", 3, 50_000, "kind_uncertain", "full_text_slug_thin"),
        ("some-new-amendment-type", None, None, "procedural_amendments", "amendment_substring"),
        ("some-new-version-type", None, 50_000, "full_text", "size_heuristic"),
        ("some-new-version-type", None, 2_000, "unknown", "unknown"),
        (None, None, None, "unknown", "unknown"),
    ],
)
def test_version_kind_finding_names_the_rule_that_fired(
    version_code: str | None, section_count: int | None, body_bytes: int | None, expected_kind: str, expected_rule: str
) -> None:
    finding = version_kind_finding(version_code, section_count=section_count, body_bytes=body_bytes)
    assert finding == VersionKindFinding(expected_kind, expected_rule, section_count, body_bytes)
    # version_kind is a thin wrapper: same slug and size evidence, same kind.
    assert version_kind(version_code, section_count=section_count, body_bytes=body_bytes) == finding.kind


# ---------------------------------------------------------------------------
# acquire_bill_pdf's own validation (no network -- these raise before any
# request is made).
# ---------------------------------------------------------------------------


def test_acquire_bill_pdf_requires_exactly_one_of_slug_or_package_id() -> None:
    from spicy_docs.sources.congress.bill_pdf import acquire_bill_pdf
    from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget

    budget = GovInfoBodyBudget(
        max_requests=1,
        max_body_bytes=1024,
        max_metadata_bytes=1024,
        timeout_seconds=1.0,
        min_request_interval_seconds=0,
    )
    identity = BillIdentity(119, "hconres", 11)
    with GovInfoBodyAcquirer(budget=budget, api_key="test-credential") as client:
        with pytest.raises(ValueError, match="exactly one of"):
            acquire_bill_pdf(identity, acquirer=client)
        with pytest.raises(ValueError, match="exactly one of"):
            acquire_bill_pdf(identity, acquirer=client, slug="ih", package_id="BILLS-119hconres11ih")


def test_acquire_bill_pdf_requires_a_govinfo_body_acquirer() -> None:
    from spicy_docs.sources.congress.bill_pdf import acquire_bill_pdf

    with pytest.raises(TypeError, match="GovInfoBodyAcquirer"):
        acquire_bill_pdf(BillIdentity(119, "hconres", 11), acquirer=object(), slug="ih")


# ---------------------------------------------------------------------------
# Live PDF acquisition, mirroring test_govinfo_package_body_acquisition.py's
# read_api_key(...) pattern -- credentials header-only, never in a fixture.
# ---------------------------------------------------------------------------

ENV_FILE = Path(os.environ.get("SPICY_DOCS_ENV_FILE", Path.home() / "Work/spicy-stack/spicy-docs/.env"))


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
        result = acquire_bill_pdf(identity, acquirer=client, slug="engrossed-in-house")

    assert result.identity.package_id == "BILLS-119hconres11eh"
    assert result.format == "pdf"
    assert result.body_capture.body.startswith(b"%PDF-")
    assert result.body_capture.byte_size > 10_000
    assert key.encode() not in result.body_capture.body
