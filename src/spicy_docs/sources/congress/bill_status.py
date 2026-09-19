"""Read source fields and offered text versions from one GovInfo BILLSTATUS XML.

The caller retains the original XML for fields outside this small typed subset.
Publisher strings, ordering, duplicate actions, and summary HTML remain intact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from spicy_docs.reading.xml import parse_xml

BILL_TYPES = frozenset({"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"})
BILLSTATUS_BULKDATA = "https://www.govinfo.gov/bulkdata/BILLSTATUS"
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
        if not isinstance(self.bill_type, str) or self.bill_type not in BILL_TYPES:
            raise BillSourceError("bill_type must be a supported lowercase bill or resolution type")


@dataclass(frozen=True, slots=True)
class BillAction:
    """``text`` is ``None`` when the publisher states the action without one.

    The user guide lists every child of ``<actions>`` as one the element "may
    include" and names none required, and the corpus agrees: 7 of the 12,938
    files in the 119th H.R., H.Res. and S.Res. status zips carry an action item
    with an ``actionCode`` and ``sourceSystem`` but no ``<text>`` (2026-09-19;
    ``docs/sources/congress-bulk-status.md``). Refusing the whole document over
    an absent optional field lost those bills entirely.

    An action has two states here, not three: an absent ``<text>`` and one
    present but blank both read as ``None``, because a blank element states no
    action text any more than a missing one does and no caller should have to
    tell them apart. Text that is there is kept exactly as written, interior
    and surrounding whitespace included.
    """

    text: str | None
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
    """``text`` is the summary as the publisher escaped it, from either placement.

    Most summaries carry ``<text>`` directly; some carry it inside a ``<cdata>``
    element, whose only child it then is. Both are current -- 984 of the 3,984
    summaries in the 119th H.R., H.Res. and S.Res. status zips use the wrapper,
    with last-update dates interleaved with the direct form (2026-09-19) -- and
    the two placements also escape differently, every direct one in that corpus
    as a CDATA section and every wrapped one as entity references. Neither
    difference reaches this field: the XML reader resolves both forms and this
    module decodes nothing itself, so the value is the same HTML either way.
    """

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
        f"{BILLSTATUS_BULKDATA}/{identity.congress}/{identity.bill_type}/"
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
    return parse_xml(
        body,
        max_bytes=max_bytes,
        error_type=BillSourceError,
        label="bill XML",
        allow_external_doctype=allow_external_doctype,
    )


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


def _summary(element: Element) -> BillSummary:
    """Read the summary's text where the publisher put it, directly or in ``<cdata>``.

    A summary that states text in both places is refused: nothing in the
    publisher's guide says which would win, and none of the 40,260 files
    measured across the 108th, 113th and 119th Congresses does it.
    """
    wrapper = _one(element, "cdata")
    in_cdata = wrapper is not None and bool(wrapper.findall("text"))
    if in_cdata and element.findall("text"):
        raise BillSourceError("bill XML summary states its text twice")
    return BillSummary(
        text=_required_text(wrapper if in_cdata else element, "text"),
        version_code=_text(element, "versionCode"),
        action_date=_text(element, "actionDate"),
        action_desc=_text(element, "actionDesc"),
        update_date=_text(element, "updateDate"),
    )


def _action(element: Element) -> BillAction:
    system = _one(element, "sourceSystem")
    text = _text(element, "text")
    return BillAction(
        text=text if text and text.strip() else None,
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
    # One file in the 40,260 measured across the 108th, 113th and 119th
    # Congresses (BILLSTATUS-113hr4200.xml) is still the 1.0.0 schema the
    # publisher's user guide documents: <billType>/<billNumber> for the
    # identity and <version> inside <bill>. Only 3.0.0 is read here, so say
    # which schema arrived rather than refuse it for a missing <type>.
    if _one(bill, "billType") is not None or _one(bill, "billNumber") is not None:
        raise BillSourceError("BILLSTATUS XML uses the superseded 1.0.0 element names")
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
        summaries=tuple(_summary(item) for item in _items(bill, "summaries", "summary")),
        actions=tuple(_action(item) for item in _items(bill, "actions")),
        sponsors=tuple(
            BillSponsor(_text(item, "bioguideId"), _text(item, "fullName")) for item in _items(bill, "sponsors")
        ),
        text_versions=tuple(_text_version(item, identity) for item in _items(bill, "textVersions")),
    )


__all__ = [
    "BILLSTATUS_BULKDATA",
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
