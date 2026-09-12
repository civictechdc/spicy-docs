"""Read source fields and offered text versions from one GovInfo BILLSTATUS XML.

The caller retains the original XML for fields outside this small typed subset.
Publisher strings, ordering, duplicate actions, and summary HTML remain intact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NoReturn
from xml.etree.ElementTree import Element, TreeBuilder
from xml.parsers import expat

_BILL_TYPES = frozenset({"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"})
_PACKAGE = re.compile(r"BILLS-([1-9][0-9]*)(hconres|sconres|hjres|sjres|hres|sres|hr|s)([1-9][0-9]*)([a-z][a-z0-9]*)")
_PACKAGE_URL = re.compile(
    r"https://www\.govinfo\.gov/content/pkg/(?P<package>BILLS-[A-Za-z0-9]+)/"
    r"(?P<format>xml|pdf|html|text)/(?P=package)\.(?P<extension>xml|pdf|htm|txt)"
)
DEFAULT_MAX_BYTES = 16 * 1024 * 1024


class BillSourceError(ValueError):
    """A response cannot establish the requested bill or text version."""


@dataclass(frozen=True, slots=True)
class BillIdentity:
    congress: int
    bill_type: str
    number: int

    def __post_init__(self) -> None:
        if type(self.congress) is not int or self.congress <= 0:
            raise BillSourceError("congress must be a positive integer")
        if type(self.number) is not int or self.number <= 0:
            raise BillSourceError("bill number must be a positive integer")
        if not isinstance(self.bill_type, str) or self.bill_type not in _BILL_TYPES:
            raise BillSourceError("bill_type must be a supported lowercase bill or resolution type")


@dataclass(frozen=True, slots=True)
class BillAction:
    text: str
    action_date: str | None
    action_time: str | None
    action_code: str | None
    action_type: str | None
    source_system_code: str | None
    source_system_name: str | None


@dataclass(frozen=True, slots=True)
class BillSponsor:
    bioguide_id: str | None
    full_name: str | None


@dataclass(frozen=True, slots=True)
class BillSummary:
    text: str
    version_code: str | None
    action_date: str | None
    action_desc: str | None
    update_date: str | None


@dataclass(frozen=True, slots=True)
class BillTextFormat:
    url: str
    type: str | None
    package_id: str | None


@dataclass(frozen=True, slots=True)
class BillTextVersion:
    type: str | None
    date: str | None
    formats: tuple[BillTextFormat, ...]
    package_id: str | None


@dataclass(frozen=True, slots=True)
class BillStatus:
    identity: BillIdentity
    schema_version: str
    title: str
    origin_chamber: str | None
    introduced_date: str | None
    update_date: str | None
    update_date_including_text: str | None
    legislation_url: str | None
    latest_action: BillAction | None
    policy_area: str | None
    subjects: tuple[str, ...]
    summaries: tuple[BillSummary, ...]
    actions: tuple[BillAction, ...]
    sponsors: tuple[BillSponsor, ...]
    text_versions: tuple[BillTextVersion, ...]


def _validated_identity(identity: BillIdentity) -> BillIdentity:
    if not isinstance(identity, BillIdentity):
        raise BillSourceError("identity must be a BillIdentity")
    return identity


def bill_status_locator(identity: BillIdentity) -> str:
    """Return a locator, without asserting that the publisher serves it."""
    _validated_identity(identity)
    return (
        f"https://www.govinfo.gov/bulkdata/BILLSTATUS/{identity.congress}/{identity.bill_type}/"
        f"BILLSTATUS-{identity.congress}{identity.bill_type}{identity.number}.xml"
    )


def _package_version(identity: BillIdentity, package_id: str) -> str:
    _validated_identity(identity)
    match = _PACKAGE.fullmatch(package_id) if isinstance(package_id, str) else None
    if match is None:
        raise BillSourceError("bill text package ID is malformed")
    congress, bill_type, number, version = match.groups()
    if (congress, bill_type, number) != (str(identity.congress), identity.bill_type, str(identity.number)):
        raise BillSourceError("bill text package identity differs from the requested bill")
    return version


def bill_xml_locator(identity: BillIdentity, package_id: str) -> str:
    """Return a version's XML locator; selection still requires an offered link."""
    _package_version(identity, package_id)
    return f"https://www.govinfo.gov/content/pkg/{package_id}/xml/{package_id}.xml"


def bill_package_id_from_url(identity: BillIdentity, url: str) -> str | None:
    """Recognize canonical GovInfo format URLs; leave other publisher links intact."""
    _validated_identity(identity)
    match = _PACKAGE_URL.fullmatch(url)
    if match is None:
        return None
    if {"xml": "xml", "pdf": "pdf", "html": "htm", "text": "txt"}[match["format"]] != match["extension"]:
        return None
    _package_version(identity, match["package"])
    return match["package"]


def select_bill_xml(status: BillStatus, package_id: str) -> tuple[BillTextVersion, BillTextFormat]:
    """Select exactly one XML link explicitly offered for the requested package."""
    locator = bill_xml_locator(status.identity, package_id)
    matches = [
        (version, format_) for version in status.text_versions for format_ in version.formats if format_.url == locator
    ]
    if len(matches) != 1:
        raise BillSourceError("requested bill text XML must be offered exactly once in BILLSTATUS")
    return matches[0]


def _xml_root(body: bytes, max_bytes: int, *, allow_external_doctype: bool = False) -> Element:
    if type(max_bytes) is not int or max_bytes <= 0:
        raise BillSourceError("max_bytes must be a positive integer")
    if not isinstance(body, bytes) or not body or len(body) > max_bytes:
        raise BillSourceError("bill XML must be nonempty bytes within max_bytes")
    builder = TreeBuilder()
    parser = expat.ParserCreate(namespace_separator="}")
    depth = 0

    def start(name: str, attributes: dict[str, str]) -> None:
        nonlocal depth
        depth += 1
        if depth > 256:
            raise BillSourceError("bill XML exceeds the supported nesting depth")
        builder.start("{" + name if "}" in name else name, attributes)

    def end(name: str) -> None:
        nonlocal depth
        builder.end("{" + name if "}" in name else name)
        depth -= 1

    def refuse_entity(*_args: object) -> NoReturn:
        raise BillSourceError("bill XML entity declarations and references are forbidden")

    def doctype(_name: str, system_id: str | None, _public_id: str | None, internal: bool) -> None:
        # Current Congressional bill XML declares a relative external DTD.
        # Expat never loads it; internal declarations would alter source text.
        if not allow_external_doctype or internal or not system_id:
            raise BillSourceError("bill XML permits only an inert external DOCTYPE")

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = builder.data
    parser.StartDoctypeDeclHandler = doctype
    parser.EntityDeclHandler = refuse_entity
    parser.ExternalEntityRefHandler = refuse_entity
    parser.SkippedEntityHandler = refuse_entity
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    try:
        parser.Parse(body, True)
        return builder.close()
    except (expat.ExpatError, ValueError) as error:
        if isinstance(error, BillSourceError):
            raise
        raise BillSourceError("bill XML is malformed") from error


def _one(parent: Element | None, name: str, *, required: bool = False) -> Element | None:
    elements = [] if parent is None else parent.findall(name)
    if len(elements) > 1 or (required and not elements):
        raise BillSourceError(f"bill XML requires one {name} element")
    return elements[0] if elements else None


def _text(parent: Element | None, name: str, *, required: bool = False) -> str | None:
    element = _one(parent, name, required=required)
    if element is None:
        return None
    if len(element):
        raise BillSourceError(f"bill XML {name} must be a text leaf")
    value = element.text or ""
    if required and not value.strip():
        raise BillSourceError(f"bill XML {name} must contain text")
    return value


def _required_text(parent: Element | None, name: str) -> str:
    value = _text(parent, name, required=True)
    assert value is not None
    return value


def _items(parent: Element | None, name: str, item_tag: str = "item") -> tuple[Element, ...]:
    container = _one(parent, name)
    if container is None:
        return ()
    if (container.text or "").strip() or any(child.tag != item_tag for child in container):
        raise BillSourceError(f"bill XML {name} has an unsupported list shape")
    return tuple(container)


def _action(element: Element) -> BillAction:
    system = _one(element, "sourceSystem")
    return BillAction(
        text=_required_text(element, "text"),
        action_date=_text(element, "actionDate"),
        action_time=_text(element, "actionTime"),
        action_code=_text(element, "actionCode"),
        action_type=_text(element, "type"),
        source_system_code=_text(system, "code"),
        source_system_name=_text(system, "name"),
    )


def _text_version(element: Element, identity: BillIdentity) -> BillTextVersion:
    formats = tuple(
        BillTextFormat(url=url, type=_text(item, "type"), package_id=bill_package_id_from_url(identity, url))
        for item in _items(element, "formats")
        for url in [_required_text(item, "url")]
    )
    packages = {format_.package_id for format_ in formats if format_.package_id is not None}
    if len(packages) > 1:
        raise BillSourceError("bill text version links disagree on package identity")
    return BillTextVersion(_text(element, "type"), _text(element, "date"), formats, next(iter(packages), None))


def parse_bill_status(body: bytes, *, identity: BillIdentity, max_bytes: int = DEFAULT_MAX_BYTES) -> BillStatus:
    """Validate one BILLSTATUS identity and retain literal fields in publisher order."""
    _validated_identity(identity)
    root = _xml_root(body, max_bytes)
    if root.tag != "billStatus":
        raise BillSourceError("BILLSTATUS XML root is unsupported")
    bill = _one(root, "bill", required=True)
    if (
        _required_text(bill, "congress") != str(identity.congress)
        or _required_text(bill, "type") != identity.bill_type.upper()
        or _required_text(bill, "number") != str(identity.number)
    ):
        raise BillSourceError("BILLSTATUS XML identity differs from the requested bill")
    latest = _one(bill, "latestAction")
    subjects = _one(bill, "subjects")
    policy_area = _text(_one(bill, "policyArea"), "name")
    subject_policy_area = _text(_one(subjects, "policyArea"), "name")
    # Current BILLSTATUS repeats this source term in both documented locations.
    if policy_area is not None and subject_policy_area is not None and policy_area != subject_policy_area:
        raise BillSourceError("BILLSTATUS policy area fields disagree")
    return BillStatus(
        identity=identity,
        schema_version=_required_text(root, "version"),
        title=_required_text(bill, "title"),
        origin_chamber=_text(bill, "originChamber"),
        introduced_date=_text(bill, "introducedDate"),
        update_date=_text(bill, "updateDate"),
        update_date_including_text=_text(bill, "updateDateIncludingText"),
        legislation_url=_text(bill, "legislationUrl"),
        latest_action=None if latest is None else _action(latest),
        policy_area=policy_area if policy_area is not None else subject_policy_area,
        subjects=tuple(_required_text(item, "name") for item in _items(subjects, "legislativeSubjects")),
        summaries=tuple(
            BillSummary(
                text=_required_text(item, "text"),
                version_code=_text(item, "versionCode"),
                action_date=_text(item, "actionDate"),
                action_desc=_text(item, "actionDesc"),
                update_date=_text(item, "updateDate"),
            )
            for item in _items(bill, "summaries", "summary")
        ),
        actions=tuple(_action(item) for item in _items(bill, "actions")),
        sponsors=tuple(
            BillSponsor(_text(item, "bioguideId"), _text(item, "fullName")) for item in _items(bill, "sponsors")
        ),
        text_versions=tuple(_text_version(item, identity) for item in _items(bill, "textVersions")),
    )


__all__ = [
    "BillAction",
    "BillIdentity",
    "BillSourceError",
    "BillSponsor",
    "BillStatus",
    "BillSummary",
    "BillTextFormat",
    "BillTextVersion",
    "bill_package_id_from_url",
    "bill_status_locator",
    "bill_xml_locator",
    "parse_bill_status",
    "select_bill_xml",
]
