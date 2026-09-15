"""Fixity comparison requires an exact URL, supported source layer and one digest."""

from dataclasses import replace

import pytest

from spicy_docs.sources.govinfo.premis import compare_govinfo_premis, read_govinfo_premis
from spicy_docs.transport.captured import CapturedBodyResponse

URL = "https://www.govinfo.gov/content/pkg/CFR-2023-title1-vol1/xml/CFR-2023-title1-vol1.xml"
SHA256_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
FIXITY = f"<fixity><messageDigestAlgorithm>SHA-256</messageDigestAlgorithm><messageDigest>{SHA256_ABC}</messageDigest></fixity>"
CHARACTERISTICS = (
    f"<objectCharacteristics><compositionLevel>0</compositionLevel>{FIXITY}<size>3</size></objectCharacteristics>"
)
LOCATION = f"<storage><contentLocation><contentLocationType>URI</contentLocationType><contentLocationValue>Public Access Rendition {URL}</contentLocationValue></contentLocation></storage>"
OBJECT = f'<object xsi:type="file"><objectIdentifier/><originalName>original.xml</originalName>{CHARACTERISTICS}{LOCATION}</object>'


def read(objects=OBJECT):
    return read_govinfo_premis(
        f'<premis xmlns="info:lc/xmlns/premis-v2" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">{objects}</premis>'.encode()
    )


def capture(**changes):
    return replace(CapturedBodyResponse(URL, URL, 200, "application/xml", "2026-09-15T00:00:00Z", b"abc"), **changes)


def test_exact_url_and_sha256_agreement_records_both_pins_and_source_positions():
    metadata = read()
    result = compare_govinfo_premis(capture(), metadata)
    assert (result.status, result.reason) == ("consistent", "sha256-match")
    assert result.premis_sha256 == metadata.source_sha256
    assert result.premis_byte_size == metadata.source_byte_size
    assert result.capture_sha256 == result.published_sha256 == "sha256:" + SHA256_ABC
    assert result.capture_byte_size == 3 and result.capture_url == URL
    assert result.object_path == (1, 1)
    assert result.characteristics_path == (1, 1, 3)
    assert result.fixity_path == (1, 1, 3, 2)
    assert compare_govinfo_premis(capture(requested_url="https://example.org/request"), metadata).status == "consistent"
    assert compare_govinfo_premis(capture(), metadata, original_name="original.xml").status == "consistent"


def test_modified_capture_is_mismatch_without_claiming_authenticity():
    result = compare_govinfo_premis(capture(body=b"changed"), read())
    assert (result.status, result.reason) == ("mismatch", "sha256-mismatch")
    assert result.capture_sha256 != result.published_sha256


def test_empty_get_can_compare_but_head_is_not_a_file_capture():
    metadata = read(OBJECT.replace(SHA256_ABC, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"))
    assert compare_govinfo_premis(capture(body=b""), metadata).status == "consistent"
    result = compare_govinfo_premis(capture(body=b"", method="HEAD"), metadata)
    assert (result.status, result.reason) == ("not-comparable", "unsupported-request-method")


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"status_code": 206}, "unsupported-response-status"),
        ({"status_code": 404}, "unsupported-response-status"),
        ({"content_encoding": "gzip"}, "encoded-capture"),
        ({"resolved_url": URL + "?revision=2"}, "no-matching-file"),
        ({"resolved_url": URL.replace("/xml/", "/other/")}, "no-matching-file"),
        ({"resolved_url": URL.replace("https:", "http:")}, "no-matching-file"),
    ],
)
def test_partial_encoded_or_different_resolved_capture_never_compares(changes, reason):
    result = compare_govinfo_premis(capture(**changes), read())
    assert (result.status, result.reason) == ("not-comparable", reason)


@pytest.mark.parametrize(
    "objects,reason",
    [
        ("", "no-matching-file"),
        (OBJECT * 2, "ambiguous-file"),
        (OBJECT.replace('xsi:type="file"', 'xsi:type="bitstream"'), "unsupported-object-type"),
        (
            OBJECT.replace('xsi:type="file"', 'xmlns:p="info:lc/xmlns/premis-v2" xsi:type="p:file"'),
            "unsupported-object-type",
        ),
        (OBJECT.replace(FIXITY, ""), "missing-fixity"),
        (OBJECT.replace("SHA-256", "MD5"), "unsupported-algorithm"),
        (OBJECT.replace(FIXITY, FIXITY * 2), "ambiguous-fixity"),
        (OBJECT.replace("<compositionLevel>0</compositionLevel>", ""), "unsupported-composition"),
        (OBJECT.replace("<compositionLevel>0", "<compositionLevel>1"), "unsupported-composition"),
        (
            OBJECT.replace("<compositionLevel>0</compositionLevel>", "<compositionLevel>0</compositionLevel>" * 2),
            "unsupported-composition",
        ),
        (OBJECT.replace(SHA256_ABC, "not-a-digest"), "malformed-sha256"),
        (OBJECT.replace(f"<messageDigest>{SHA256_ABC}</messageDigest>", ""), "malformed-sha256"),
        (
            OBJECT.replace(
                f"<messageDigest>{SHA256_ABC}</messageDigest>", f"<messageDigest>{SHA256_ABC}</messageDigest>" * 2
            ),
            "malformed-sha256",
        ),
        (OBJECT.replace(SHA256_ABC, SHA256_ABC[:20] + "<extension/>" + SHA256_ABC[20:]), "malformed-sha256"),
        (OBJECT.replace("<contentLocationType>URI", "<contentLocationType>Future"), "unsupported-location-type"),
        (OBJECT.replace(URL, URL + " https://example.org/second"), "ambiguous-location-uri"),
        (OBJECT.replace(URL, "relative/path.xml"), "no-matching-file"),
        (OBJECT.replace(URL, "https://[invalid"), "no-matching-file"),
    ],
)
def test_missing_ambiguous_unsupported_and_malformed_source_shapes_are_explicit(objects, reason):
    result = compare_govinfo_premis(capture(), read(objects))
    assert (result.status, result.reason) == ("not-comparable", reason)


def test_original_name_only_narrows_exact_url_matches():
    result = compare_govinfo_premis(capture(), read(), original_name="CFR-2023-title1-vol1.xml")
    assert result.reason == "no-matching-file"
    assert compare_govinfo_premis(capture(), read(), original_name=" original.xml ").reason == "no-matching-file"
    second = OBJECT.replace("original.xml", "other.xml")
    assert compare_govinfo_premis(capture(), read(OBJECT + second), original_name="original.xml").status == "consistent"
    assert (
        compare_govinfo_premis(capture(resolved_url=URL + "?other"), read(), original_name="original.xml").reason
        == "no-matching-file"
    )


@pytest.mark.parametrize(
    "name",
    [
        "<originalName>original.xml<extra/></originalName>",
        "<originalName>original.xml</originalName><originalName>original.xml</originalName>",
        "<originalName>other.xml</originalName><originalName>original.xml</originalName>",
    ],
)
def test_optional_original_name_refuses_repeated_and_mixed_claims(name):
    metadata = read(OBJECT.replace("<originalName>original.xml</originalName>", name))
    result = compare_govinfo_premis(capture(), metadata, original_name="original.xml")
    assert (result.status, result.reason) == ("not-comparable", "ambiguous-original-name")
    assert compare_govinfo_premis(capture(), metadata).status == "consistent"


@pytest.mark.parametrize(
    "algorithm",
    [
        "<messageDigestAlgorithm>SHA-256</messageDigestAlgorithm>" * 2,
        "<messageDigestAlgorithm>SHA-256<extra/></messageDigestAlgorithm>",
        "<messageDigestAlgorithm>MD5</messageDigestAlgorithm><messageDigestAlgorithm>SHA-256</messageDigestAlgorithm>",
        "",
    ],
)
def test_malformed_competing_fixity_cannot_create_apparent_unique_sha256(algorithm):
    malformed = FIXITY.replace("<messageDigestAlgorithm>SHA-256</messageDigestAlgorithm>", algorithm)
    metadata = read(OBJECT.replace(FIXITY, malformed + FIXITY))
    result = compare_govinfo_premis(capture(), metadata)
    assert (result.status, result.reason) == ("not-comparable", "ambiguous-algorithm")


@pytest.mark.parametrize("other_claim", ["https://[invalid", "https:/missing-authority"])
@pytest.mark.parametrize("valid_competitor", [False, True])
def test_malformed_competing_uri_claim_cannot_hide_an_object(other_claim, valid_competitor):
    malformed = OBJECT.replace(URL, other_claim + " " + URL)
    metadata = read(malformed + (OBJECT if valid_competitor else ""))
    result = compare_govinfo_premis(capture(), metadata)
    assert (result.status, result.reason) == ("not-comparable", "malformed-location-uri")


@pytest.mark.parametrize(
    "replacement,reason",
    [
        ("<contentLocationType>URI</contentLocationType>" * 2, "ambiguous-location-type"),
        (f"<contentLocationValue>{URL}</contentLocationValue>" * 2, "ambiguous-location-value"),
    ],
)
def test_repeated_relevant_location_fields_do_not_hide_competing_object(replacement, reason):
    field = "contentLocationType" if "Type" in replacement else "contentLocationValue"
    value = "URI" if field.endswith("Type") else "Public Access Rendition " + URL
    malformed = OBJECT.replace(f"<{field}>{value}</{field}>", replacement)
    result = compare_govinfo_premis(capture(), read(malformed + OBJECT))
    assert (result.status, result.reason) == ("not-comparable", reason)


def test_characteristics_layers_and_sizes_are_never_combined():
    # One supported digest and another layer without a digest: the selected
    # digest still belongs to its own level-zero block, never the first block.
    level_one = "<objectCharacteristics><compositionLevel>1</compositionLevel><size>999</size></objectCharacteristics>"
    metadata = read(OBJECT.replace(CHARACTERISTICS, level_one + CHARACTERISTICS))
    result = compare_govinfo_premis(capture(), metadata)
    assert result.status == "consistent" and result.characteristics_path == (1, 1, 4)
    metadata = read(
        OBJECT.replace(
            CHARACTERISTICS,
            CHARACTERISTICS.replace("<compositionLevel>0", "<compositionLevel>1")
            + "<objectCharacteristics><compositionLevel>0</compositionLevel></objectCharacteristics>",
        )
    )
    assert compare_govinfo_premis(capture(), metadata).reason == "unsupported-composition"
    # The API compares SHA-256 only; conflicting published size remains raw.
    assert compare_govinfo_premis(capture(), read(OBJECT.replace("<size>3", "<size>999"))).status == "consistent"


def test_other_algorithms_unknown_fields_and_digest_case_are_source_preserving():
    changed = OBJECT.replace(FIXITY, FIXITY.replace("SHA-256", "MD5") + FIXITY).replace(SHA256_ABC, SHA256_ABC.upper())
    changed = changed.replace("</object>", "<future value='unknown'/></object>")
    metadata = read(changed)
    assert compare_govinfo_premis(capture(), metadata).status == "consistent"
    assert len(metadata.objects[0].fixities) == 2
