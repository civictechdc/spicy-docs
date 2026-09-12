"""Current printed bill XML identity, body shape, and inert external DTDs."""

from pathlib import Path

import pytest

from spicy_docs.sources.congress.bill_status import BillIdentity, BillSourceError
from spicy_docs.sources.congress.bill_text import bill_xml_locator, validate_bill_text

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
IDENTITY = BillIdentity(119, "hr", 6028)
PACKAGE = "BILLS-119hr6028eh"


def body() -> bytes:
    return (FIXTURES / "text-119hr6028eh.xml").read_bytes()


def validate(value: bytes, **kwargs: object):
    args = {"identity": IDENTITY, "package_id": PACKAGE, "final_url": bill_xml_locator(IDENTITY, PACKAGE), **kwargs}
    return validate_bill_text(value, **args)


@pytest.mark.parametrize(
    "bill_type,number,version", [("hr", 6028, "eh"), ("hr", 6028, "ih"), ("s", 5, "enr"), ("hjres", 25, "enr")]
)
def test_current_publisher_bill_and_resolution_shapes(bill_type: str, number: int, version: str) -> None:
    identity = BillIdentity(119, bill_type, number)
    package = f"BILLS-119{bill_type}{number}{version}"
    result = validate_bill_text(
        (FIXTURES / f"text-119{bill_type}{number}{version}.xml").read_bytes(),
        identity=identity,
        package_id=package,
        final_url=bill_xml_locator(identity, package),
    )
    assert result.identity == identity
    assert result.package_id == package
    assert result.version_code == version
    assert result.root_tag == ("resolution" if bill_type == "hjres" else "bill")
    if version == "enr":
        assert result.congress_text == "One Hundred Nineteenth Congress of the United States of America"
        assert result.stage == "Enrolled-Bill"
        assert result.title.startswith(" ")
    else:
        assert result.legis_num == "H. R. 6028"
        assert result.congress_text == "119th CONGRESS"


@pytest.mark.parametrize(
    "before,after",
    [
        (b"119th CONGRESS", b"118th CONGRESS"),
        (b"H. R. 6028", b"H. R. 6029"),
        (b"119 HR 6028 EH:", b"119 HR 6028 IH:"),
        (b"119 HR 6028 EH:", b"118 HR 6028 EH:"),
        (b"119 HR 6028 EH:", b"119 S 6028 EH:"),
        (b"119 HR 6028 EH:", b"119 HR 6029 EH:"),
        (b"119 HR 6028 EH:", b"A page about bills:"),
        (b"</form>", b"<legis-num>H. R. 6028</legis-num></form>"),
        (b"</dublinCore>", b"<dc:title>119 HR 6028 IH: Wrong</dc:title></dublinCore>"),
    ],
)
def test_native_identity_or_version_conflicts_refuse(before: bytes, after: bytes) -> None:
    with pytest.raises(BillSourceError):
        validate(body().replace(before, after))


def test_observed_stage_conflicts_refuse_but_unknown_stage_is_retained() -> None:
    for stage in [b"Introduced-in-House", b"Enrolled-Bill"]:
        with pytest.raises(BillSourceError, match="stage contradicts"):
            validate(body().replace(b"Engrossed-in-House", stage))
    assert validate(body().replace(b"Engrossed-in-House", b"Unfamiliar-stage")).stage == "Unfamiliar-stage"


@pytest.mark.parametrize(
    "value",
    [
        b"",
        b" ",
        b"<html><body>Checking your browser</body></html>",
        b"<error/>",
        b"<bill/>",
        b'<bill xmlns="http://schemas.gpo.gov/xml/uslm"/>',
        b"<bill",
    ],
)
def test_empty_error_and_unsupported_shapes_refuse(value: bytes) -> None:
    with pytest.raises(BillSourceError):
        validate(value)


def test_body_must_have_content_and_not_nest_document_roots() -> None:
    prefix = body().split(b"<legis-body", 1)[0]
    for replacement in [
        b"<legis-body/>",
        b"<legis-body><section/></legis-body>",
        b"<legis-body><section><header>Only a heading</header></section></legis-body>",
        b"<legis-body><p>Unrecognized content</p></legis-body>",
        b"<legis-body><html>Checking browser</html></legis-body>",
        b"<legis-body><bill>Wrong document</bill></legis-body>",
    ]:
        with pytest.raises(BillSourceError):
            validate(prefix + replacement + b"</bill>")


def test_final_url_and_requested_package_must_agree() -> None:
    locator = bill_xml_locator(IDENTITY, PACKAGE)
    for url in [
        locator.replace("6028eh", "6028ih"),
        locator + "?download=1",
        locator.replace("https://", "http://"),
        locator.replace("govinfo.gov", "example.invalid"),
    ]:
        with pytest.raises(BillSourceError, match="final URL"):
            validate(body(), final_url=url)
    with pytest.raises(BillSourceError, match="identity differs"):
        validate(body(), package_id="BILLS-119hr6029eh")


def test_inert_external_dtd_is_not_loaded_and_entity_references_refuse() -> None:
    assert validate(body().replace(b'"bill.dtd"', b'"file:///definitely-not-present.dtd"')).version_code == "eh"
    assert validate(body().replace(b'"bill.dtd"', b'"https://example.invalid/never-load.dtd"')).version_code == "eh"
    with pytest.raises(BillSourceError, match="entity"):
        validate(body().replace(b"This Act may be cited", b"&undefined;"))


@pytest.mark.parametrize(
    "declaration",
    [
        b'<!DOCTYPE bill [<!ENTITY secret SYSTEM "file:///etc/passwd">]>',
        b'<!DOCTYPE bill [<!ENTITY a "replacement">]>',
        b'<!DOCTYPE bill [<!ENTITY % p SYSTEM "https://example.invalid/never-load.dtd">%p;]>',
        b'<!DOCTYPE bill SYSTEM "bill.dtd" []>',
    ],
)
def test_internal_doctype_subsets_refuse(declaration: bytes) -> None:
    value = body().replace(b'<!DOCTYPE bill PUBLIC "-//US Congress//DTDs/bill.dtd//EN" "bill.dtd">', declaration)
    with pytest.raises(BillSourceError, match="DOCTYPE"):
        validate(value)


def test_declared_namespace_cannot_spoof_dublin_core() -> None:
    with pytest.raises(BillSourceError):
        validate(body().replace(b"http://purl.org/dc/elements/1.1/", b"urn:wrong"))


def test_byte_limit_and_scalar_type_are_checked_before_parsing() -> None:
    assert validate(body(), max_bytes=len(body())).identity == IDENTITY
    for value, limit in [(body(), len(body()) - 1), (body(), True), (body().decode(), len(body()))]:
        with pytest.raises(BillSourceError):
            validate(value, max_bytes=limit)
