"""Check current Congressional bill/resolution XML without rewriting its bytes.

This checks native bill and printed-version identity, not the full publisher DTD
or legal meaning. Other XML dialects require their own demonstrated validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .bill_status import (
    DEFAULT_MAX_BYTES,
    BillIdentity,
    BillSourceError,
    _one,
    _package_version,
    _required_text,
    _xml_root,
    bill_xml_locator,
    select_bill_xml,
)

_DC_TITLE = "{http://purl.org/dc/elements/1.1/}title"
_TITLE_ID = re.compile(
    r"(?:(?P<congress>[1-9][0-9]*)\s+)?(?P<type>HCONRES|SCONRES|HJRES|SJRES|HRES|SRES|HCON|SCON|HJ|SJ|HR|S)\s*(?P<number>[1-9][0-9]*)\s+(?P<version>[A-Z][A-Z0-9]*)"
)
_TITLE_TYPES = {"HJ": "hjres", "SJ": "sjres", "HCON": "hconres", "SCON": "sconres"}
_ORDINALS = (
    "",
    "first",
    "second",
    "third",
    "fourth",
    "fifth",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
    "eleventh",
    "twelfth",
    "thirteenth",
    "fourteenth",
    "fifteenth",
    "sixteenth",
    "seventeenth",
    "eighteenth",
    "nineteenth",
)
_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
_TENTHS = ("", "", "twentieth", "thirtieth", "fortieth", "fiftieth", "sixtieth", "seventieth", "eightieth", "ninetieth")


@dataclass(frozen=True, slots=True)
class BillTextIdentity:
    identity: BillIdentity
    package_id: str
    version_code: str
    root_tag: str
    congress_text: str
    legis_num: str
    title: str
    stage: str | None
    final_url: str


def _ordinal(number: int) -> str | None:
    # Enrolled bills print Congress in words; other current versions use digits.
    if 0 < number < 20:
        return _ORDINALS[number]
    if number < 100:
        tens, units = divmod(number, 10)
        return f"{_TENS[tens]} {_ORDINALS[units]}" if units else _TENTHS[tens]
    if number == 100:
        return "one hundredth"
    if number < 200:
        return f"one hundred {_ordinal(number - 100)}"
    return None


def _check_congress(value: str, identity: BillIdentity) -> None:
    normalized = " ".join(value.lower().replace("-", " ").split())
    numeric = re.fullmatch(r"([1-9][0-9]*)(?:st|nd|rd|th)? congress(?: of the united states of america)?", normalized)
    if numeric is not None and numeric[1] == str(identity.congress):
        return
    ordinal = _ordinal(identity.congress)
    if ordinal is not None and normalized in {
        f"{ordinal} congress",
        f"{ordinal} congress of the united states of america",
    }:
        return
    raise BillSourceError("bill text Congress differs from the request or has an unsupported form")


def _check_title(title: str, identity: BillIdentity, version: str) -> None:
    prefix, separator, _rest = title.partition(":")
    match = _TITLE_ID.fullmatch(prefix.replace(".", "").strip()) if separator else None
    if match is None:
        raise BillSourceError("bill text Dublin Core title has no supported bill/version identity")
    title_type = _TITLE_TYPES.get(match["type"], match["type"].lower())
    if (
        title_type != identity.bill_type
        or match["number"] != str(identity.number)
        or match["version"].lower() != version
        or (match["congress"] is not None and match["congress"] != str(identity.congress))
    ):
        raise BillSourceError("bill text Dublin Core identity or version differs from the request")


def validate_bill_text(
    body: bytes,
    *,
    identity: BillIdentity,
    package_id: str,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> BillTextIdentity:
    """Prove the requested package URL, native bill number, Congress, and version.

    Inert external DTD declarations are accepted but never loaded. Declared or
    unresolved entities, empty legislative bodies, and unsupported roots refuse.
    """
    version = _package_version(identity, package_id)
    if final_url != bill_xml_locator(identity, package_id):
        raise BillSourceError("bill text final URL differs from the requested XML locator")
    root = _xml_root(body, max_bytes, allow_external_doctype=True)
    expected_root = "bill" if identity.bill_type in {"hr", "s"} else "resolution"
    if root.tag != expected_root:
        raise BillSourceError("bill text XML root is unsupported for the requested bill type")
    form = _one(root, "form", required=True)
    congress = _required_text(form, "congress")
    _check_congress(congress, identity)
    legis_num = _required_text(form, "legis-num")
    compact_number = re.sub(r"[.\s]", "", legis_num).lower()
    if compact_number != f"{identity.bill_type}{identity.number}":
        raise BillSourceError("bill text legislative number differs from the request")
    metadata = _one(root, "metadata", required=True)
    dublin_core = _one(metadata, "dublinCore", required=True)
    title = _required_text(dublin_core, _DC_TITLE)
    _check_title(title, identity, version)
    stage = root.get(f"{expected_root}-stage")
    # These stages are demonstrated by retained current samples. Other literal
    # stages remain available; this is not full stage-vocabulary validation.
    observed_stages = {"Engrossed-in-House": "eh", "Introduced-in-House": "ih", "Enrolled-Bill": "enr"}
    if stage in observed_stages and observed_stages[stage] != version:
        raise BillSourceError("bill text stage contradicts the requested version")
    body_tag = "legis-body" if expected_root == "bill" else "resolution-body"
    legislative_body = _one(root, body_tag, required=True)
    assert legislative_body is not None
    if not any("".join(element.itertext()).strip() for element in legislative_body.iter("text")):
        raise BillSourceError("bill text has no legislative body content")
    if any(element.tag in {"bill", "resolution", "html"} for element in root.iter() if element is not root):
        raise BillSourceError("bill text contains a nested document root")
    return BillTextIdentity(
        identity=identity,
        package_id=package_id,
        version_code=version,
        root_tag=root.tag,
        congress_text=congress,
        legis_num=legis_num,
        title=title,
        stage=stage,
        final_url=final_url,
    )


__all__ = ["BillTextIdentity", "bill_xml_locator", "select_bill_xml", "validate_bill_text"]
