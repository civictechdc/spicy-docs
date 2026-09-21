"""Source-specific Federal Register body locator and identity rules."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from spicy_docs.sources.federal_register.body_sources import (
    FederalRegisterBodySourceError,
    body_source_locators,
    resolve_govinfo_granule_from_mods,
    validate_govinfo_granule,
)


def _record(**changes: object) -> dict[str, object]:
    """A document record over the given identity fields."""
    record: dict[str, object] = {
        "body_html_url": ("https://www.federalregister.gov/documents/full_text/html/1998/06/03/X98-10603.html"),
        "document_number": "X98-10603",
        "publication_date": "1998-06-03",
        "start_page": 30359,
    }
    record.update(changes)
    return record


def test_body_source_locators_preserve_every_identity_without_choosing() -> None:
    """Each body-source locator preserves every identity field without choosing a route."""
    locators = body_source_locators(_record())

    assert asdict(locators) == {
        "document_number": "X98-10603",
        "publication_date": "1998-06-03",
        "publisher_body_html_url": (
            "https://www.federalregister.gov/documents/full_text/html/1998/06/03/X98-10603.html"
        ),
        "publisher_text_url": ("https://www.federalregister.gov/documents/full_text/text/1998/06/03/X98-10603.txt"),
        "publisher_xml_url": ("https://www.federalregister.gov/documents/full_text/xml/1998/06/03/X98-10603.xml"),
        "govinfo_granule_url": ("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/X98-10603.htm"),
        "govinfo_mods_url": ("https://www.govinfo.gov/metadata/pkg/FR-1998-06-03/mods.xml"),
    }


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"body_html_url": "https://example.com/documents/full_text/html/1998/06/03/X98-10603.html"},
            "body_html_url",
        ),
        (
            {"body_html_url": ("https://www.federalregister.gov/documents/full_text/html/1998/06/04/X98-10603.html")},
            "publication date",
        ),
        (
            {"body_html_url": ("https://www.federalregister.gov/documents/full_text/html/1998/06/03/98-14931.html")},
            "document number",
        ),
        ({"publication_date": "1998-6-3"}, "publication_date"),
        ({"document_number": "../escape"}, "document_number"),
    ],
)
def test_body_source_locators_refuse_identity_drift(changes: dict[str, object], message: str) -> None:
    """Locators refuse identity drift with their named reason."""
    with pytest.raises(FederalRegisterBodySourceError, match=message):
        body_source_locators(_record(**changes))


def test_exact_govinfo_document_marker_is_required() -> None:
    """An exact GovInfo document marker is required for the granule route."""
    identity = validate_govinfo_granule(
        b"Federal Register\n[FR Doc No: 98-14931]\n",
        source_document_number="98-14931",
        publication_date="1998-06-03",
        access_id="98-14931",
        final_url=("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"),
        max_bytes=1_024,
    )

    assert asdict(identity) == {
        "access_id": "98-14931",
        "marker_document_number": "98-14931",
        "match_kind": "exact-source",
        "publication_date": "1998-06-03",
        "source_document_number": "98-14931",
    }


def test_split_publisher_number_may_match_the_printed_base_number() -> None:
    """A split publisher number may match the printed base number, marked split-base."""
    identity = validate_govinfo_granule(
        b"[FR Doc No: 97-26440]",
        source_document_number="97-26440-2",
        publication_date="1997-10-01",
        access_id="97-26440-2",
        final_url=("https://www.govinfo.gov/content/pkg/FR-1997-10-01/html/97-26440-2.htm"),
        max_bytes=1_024,
    )

    assert identity.marker_document_number == "97-26440"
    assert identity.match_kind == "split-base"


def test_mods_resolved_number_must_match_the_resolved_granule() -> None:
    """A MODS-resolved number must match the resolved granule access id."""
    identity = validate_govinfo_granule(
        b"[FR Doc No: 98-14931]",
        source_document_number="X98-10603",
        publication_date="1998-06-03",
        access_id="98-14931",
        final_url=("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"),
        max_bytes=1_024,
    )

    assert identity.marker_document_number == "98-14931"
    assert identity.match_kind == "resolved-access-id"

    with pytest.raises(FederalRegisterBodySourceError, match="resolved access ID"):
        validate_govinfo_granule(
            b"[FR Doc No: X98-10603]",
            source_document_number="X98-10603",
            publication_date="1998-06-03",
            access_id="98-14931",
            final_url=("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"),
            max_bytes=1_024,
        )


@pytest.mark.parametrize(
    ("body", "final_url", "message"),
    [
        (b"", "https://www.govinfo.gov/error", "empty"),
        (
            b"<html>govinfo.gov/error</html>",
            "https://www.govinfo.gov/error",
            "soft-404",
        ),
        (
            b"unrelated page",
            "https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm",
            "marker",
        ),
        (
            b"[FR Doc No: 98-14931]",
            "https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14932.htm",
            "final URL",
        ),
    ],
)
def test_govinfo_response_refusals(body: bytes, final_url: str, message: str) -> None:
    """GovInfo response refusals name the failed check."""
    with pytest.raises(FederalRegisterBodySourceError, match=message):
        validate_govinfo_granule(
            body,
            source_document_number="98-14931",
            publication_date="1998-06-03",
            access_id="98-14931",
            final_url=final_url,
            max_bytes=1_024,
        )


def test_a_marker_bearing_body_at_another_locator_reports_the_locator() -> None:
    """A marker-bearing body at another locator reports the locator mismatch first."""
    # The MODS start-page route can request one granule and be answered by
    # another. Both error-page witnesses hold here, so this pins which check
    # runs first: the locator mismatch is the more precise fact.
    with pytest.raises(FederalRegisterBodySourceError, match="final URL"):
        validate_govinfo_granule(
            b"<html>govinfo.gov/error</html>",
            source_document_number="98-14931",
            publication_date="1998-06-03",
            access_id="98-14931",
            final_url="https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14932.htm",
            max_bytes=1_024,
        )


def test_dated_soft_404_byte_length_is_not_treated_as_an_identity_rule() -> None:
    """A dated soft-404 byte length is not treated as an identity rule."""
    marker = b"[FR Doc No: 98-14931]"
    body = marker + b" " * (44_165 - len(marker))

    identity = validate_govinfo_granule(
        body,
        source_document_number="98-14931",
        publication_date="1998-06-03",
        access_id="98-14931",
        final_url=("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"),
        max_bytes=44_165,
    )

    assert identity.match_kind == "exact-source"


def _mods(*constituents: str) -> bytes:
    """A MODS document over the given constituent markup."""
    return (
        """<?xml version="1.0" encoding="UTF-8"?>
<mods xmlns="http://www.loc.gov/mods/v3">
  <extension><accessId>FR-1998-06-03</accessId></extension>
"""
        + "\n".join(constituents)
        + "\n</mods>"
    ).encode()


def _constituent(access_id: str, start_page: int, *, nested_id: str = "citation") -> str:
    """A constituent block over the given extension markup."""
    return f"""
  <relatedItem type="constituent" ID="id-{access_id}">
    <part><extent unit="pages"><start>{start_page}</start><end>{start_page + 2}</end></extent></part>
    <relatedItem type="isReferencedBy"><identifier>{nested_id}</identifier></relatedItem>
    <extension><accessId>{access_id}</accessId></extension>
  </relatedItem>"""


def test_mods_start_page_resolution_preserves_both_identifiers() -> None:
    """MODS start-page resolution preserves both the source and marker identifiers."""
    resolution = resolve_govinfo_granule_from_mods(
        _mods(_constituent("98-14903", 30345), _constituent("98-14931", 30359)),
        publication_date="1998-06-03",
        start_page=30359,
        max_bytes=8_192,
    )

    assert asdict(resolution) == {
        "access_id": "98-14931",
        "granule_url": ("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"),
        "publication_date": "1998-06-03",
        "start_page": 30359,
    }


def test_mods_start_page_resolution_retains_only_one_access_id() -> None:
    """Start-page resolution requires exactly one access id."""
    duplicate_access_id = _constituent("98-14931", 30359).replace(
        "</extension>",
        "<accessId>98-14931</accessId></extension>",
    )

    with pytest.raises(FederalRegisterBodySourceError, match="single accessId"):
        resolve_govinfo_granule_from_mods(
            _mods(duplicate_access_id),
            publication_date="1998-06-03",
            start_page=30359,
            max_bytes=8_192,
        )


def test_mods_resolution_ignores_start_outside_page_extent_path() -> None:
    """A start element outside the page-extent path is ignored."""
    constituent = _constituent("98-14931", 30345).replace(
        "<extension>",
        "<extension><start>30359</start>",
    )

    with pytest.raises(FederalRegisterBodySourceError, match="no constituent"):
        resolve_govinfo_granule_from_mods(
            _mods(constituent),
            publication_date="1998-06-03",
            start_page=30359,
            max_bytes=8_192,
        )


def test_mods_resolution_ignores_access_id_outside_constituent_extension_path() -> None:
    """An access id outside the constituent extension path is ignored."""
    constituent = _constituent("98-14931", 30359).replace(
        "<extension><accessId>98-14931</accessId></extension>",
        ('<relatedItem type="isReferencedBy"><extension><accessId>98-14931</accessId></extension></relatedItem>'),
    )

    with pytest.raises(FederalRegisterBodySourceError, match="single accessId"):
        resolve_govinfo_granule_from_mods(
            _mods(constituent),
            publication_date="1998-06-03",
            start_page=30359,
            max_bytes=8_192,
        )


def test_mods_resolution_ignores_same_named_elements_from_a_foreign_namespace() -> None:
    """Same-named elements from a foreign namespace are ignored."""
    constituent = """
  <relatedItem type="constituent" xmlns:foreign="https://example.test/not-mods">
    <foreign:part><foreign:extent unit="pages"><foreign:start>30359</foreign:start></foreign:extent></foreign:part>
    <foreign:extension><foreign:accessId>98-14931</foreign:accessId></foreign:extension>
  </relatedItem>"""

    with pytest.raises(FederalRegisterBodySourceError, match="no constituent"):
        resolve_govinfo_granule_from_mods(
            _mods(constituent),
            publication_date="1998-06-03",
            start_page=30359,
            max_bytes=8_192,
        )


def test_mods_resolution_refuses_an_extra_empty_access_id() -> None:
    """An extra empty access id is refused."""
    constituent = _constituent("98-14931", 30359).replace(
        "</extension>",
        "<accessId></accessId></extension>",
    )

    with pytest.raises(FederalRegisterBodySourceError, match="single accessId"):
        resolve_govinfo_granule_from_mods(
            _mods(constituent),
            publication_date="1998-06-03",
            start_page=30359,
            max_bytes=8_192,
        )


@pytest.mark.parametrize(
    ("mods", "start_page", "message"),
    [
        (_mods(_constituent("98-14903", 30345)), 30359, "no constituent"),
        (
            _mods(_constituent("98-14931", 30359), _constituent("98-14932", 30359)),
            30359,
            "more than one",
        ),
        (_mods(_constituent("../escape", 30359)), 30359, "accessId"),
        (b"<mods><relatedItem>", 30359, "XML"),
        (b'<!DOCTYPE mods [<!ENTITY x "boom">]><mods>&x;</mods>', 30359, "DTD"),
    ],
)
def test_mods_resolution_refuses_ambiguous_or_untrusted_identity(mods: bytes, start_page: int, message: str) -> None:
    """Ambiguous or untrusted MODS identity is refused."""
    with pytest.raises(FederalRegisterBodySourceError, match=message):
        resolve_govinfo_granule_from_mods(
            mods,
            publication_date="1998-06-03",
            start_page=start_page,
            max_bytes=8_192,
        )


def test_every_parser_has_a_caller_supplied_byte_bound() -> None:
    """Every parser requires a caller-supplied byte bound."""
    with pytest.raises(FederalRegisterBodySourceError, match="byte bound"):
        resolve_govinfo_granule_from_mods(
            _mods(_constituent("98-14931", 30359)),
            publication_date="1998-06-03",
            start_page=30359,
            max_bytes=32,
        )

    with pytest.raises(FederalRegisterBodySourceError, match="byte bound"):
        validate_govinfo_granule(
            b"[FR Doc No: 98-14931]",
            source_document_number="98-14931",
            publication_date="1998-06-03",
            access_id="98-14931",
            final_url=("https://www.govinfo.gov/content/pkg/FR-1998-06-03/html/98-14931.htm"),
            max_bytes=4,
        )
