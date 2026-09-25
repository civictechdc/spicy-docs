"""Explicit GovInfo USLM sources: public and private laws (PLAW) and statute compilations (COMPS).

Both collections are keyless GovInfo bulkdata in United States Legislative
Markup (USLM), which the publisher labels beta. Each file states its own
identity in ``<meta>``: a law names its Congress, public/private kind, number
and citable forms; a compilation names its file identifier, act title and, when
present, the public law it is current through. Validation proves that native
identity against the request and the caller keeps the exact bytes. Archive
readers apply the same checks to every entry of a bulkdata zip, both ways:
each entry's name must parse to a selection and its content must agree.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from spicy_docs.reading.xml import IdentityXmlScan
from spicy_docs.reading.zip_archive import archive_members, open_archive, read_member
from spicy_docs.transport.source_acquirer import limit_byte_bound

USLM_NAMESPACE = "http://schemas.gpo.gov/xml/uslm"
DUBLIN_CORE_NAMESPACE = "http://purl.org/dc/elements/1.1/"
BULKDATA = "https://www.govinfo.gov/bulkdata"
# The largest observed file is the Social Security Act compilation at 20.4 MB.
DEFAULT_MAX_BYTES = 32 * 1024 * 1024
MAX_USLM_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_ENTRIES = 4096
KINDS = ("public", "private")
type LawKind = Literal["public", "private"]
type UslmSource = Literal["public-law", "statute-compilation"]

_PLAW_NAME = re.compile(r"PLAW-([0-9]+)(publ|pvtl)([0-9]+)\.xml")
_COMPS_NAME = re.compile(r"COMPS-([0-9]+)\.xml")


class UslmSourceError(ValueError):
    """The request or response cannot establish the selected USLM source."""


class UslmIdentityError(UslmSourceError):
    """A well-formed USLM document states another law or citation than the one requested.

    Separate from a shape refusal (an HTML page served with HTTP 200, a missing
    meta block), so a caller can report which of the two the publisher answered.
    """


def _positive(value: int, name: str, limit: int) -> int:
    if type(value) is not int or not 1 <= value <= limit:
        raise UslmSourceError(f"{name} must be an integer from 1 to {limit}")
    return value


# Congress numbers are small; law numbers and compilation file identifiers are
# publisher-assigned and can be large (the Social Security Act is COMPS-88888888).
_MAX_CONGRESS = 999
_MAX_NUMBER = 999_999
_MAX_FILE_ID = 999_999_999


def _limit(max_bytes: int) -> None:
    limit_byte_bound(max_bytes, name="max_bytes", cap=MAX_USLM_BYTES, error_type=UslmSourceError)


@dataclass(frozen=True, slots=True)
class PublicLawSelection:
    """One public or private law, by Congress, kind and number, with its publisher file name."""

    congress: int
    kind: LawKind
    number: int

    def __post_init__(self) -> None:
        _positive(self.congress, "congress", _MAX_CONGRESS)
        _positive(self.number, "number", _MAX_NUMBER)
        if self.kind not in KINDS:
            raise UslmSourceError("kind must be 'public' or 'private'")

    @property
    def file_name(self) -> str:
        return f"PLAW-{self.congress}{'publ' if self.kind == 'public' else 'pvtl'}{self.number}.xml"

    @property
    def citation(self) -> str:
        """The publisher's citable form, spelled with an en dash."""
        return f"{'Public' if self.kind == 'public' else 'Private'} Law {self.congress}–{self.number}"

    @classmethod
    def from_file_name(cls, name: str) -> PublicLawSelection:
        match = _PLAW_NAME.fullmatch(name)
        if match is None:
            raise UslmSourceError("public law file name is unsupported")
        return cls(int(match[1]), "public" if match[2] == "publ" else "private", int(match[3]))


@dataclass(frozen=True, slots=True)
class StatuteCompilationSelection:
    """One statute compilation, by its publisher-assigned file identifier."""

    file_id: int

    def __post_init__(self) -> None:
        _positive(self.file_id, "file_id", _MAX_FILE_ID)

    @property
    def file_name(self) -> str:
        return f"COMPS-{self.file_id}.xml"

    @classmethod
    def from_file_name(cls, name: str) -> StatuteCompilationSelection:
        match = _COMPS_NAME.fullmatch(name)
        if match is None:
            raise UslmSourceError("statute compilation file name is unsupported")
        return cls(int(match[1]))


def public_law_xml_locator(selection: PublicLawSelection) -> str:
    if not isinstance(selection, PublicLawSelection):
        raise UslmSourceError("selection must be a PublicLawSelection")
    return f"{BULKDATA}/PLAW/{selection.congress}/{selection.kind}/{selection.file_name}"


def public_law_archive_locator(congress: int, kind: LawKind) -> str:
    """One zip per Congress and kind; the publisher offers no private-law folder for some Congresses."""
    _positive(congress, "congress", _MAX_CONGRESS)
    if kind not in KINDS:
        raise UslmSourceError("kind must be 'public' or 'private'")
    return f"{BULKDATA}/PLAW/{congress}/{kind}/PLAW-{congress}-{kind}.zip"


def statute_compilation_xml_locator(selection: StatuteCompilationSelection) -> str:
    if not isinstance(selection, StatuteCompilationSelection):
        raise UslmSourceError("selection must be a StatuteCompilationSelection")
    return f"{BULKDATA}/COMPS/{selection.file_name}"


def statute_compilations_archive_locator() -> str:
    """The whole collection in one zip; per-file listing times are not act currency."""
    return f"{BULKDATA}/COMPS/COMPS.zip"


@dataclass(frozen=True, slots=True)
class UslmMetadata:
    """Native ``<meta>`` facts. Publisher spellings are kept; nothing is normalized.

    ``current_through_public_law`` holds the compiler's own currency statements
    in document order. Three compilations state two; the form varies
    (``118–42``, ``Public Law 117–121``, ``P.L.  111–148``, ``ch883``). A stale
    compilation and an unamended one look alike here; the enacted-law list is
    what distinguishes them.
    """

    source: UslmSource
    root_tag: str
    title: str
    document_type: str | None
    doc_number: str | None
    congress: str | None
    citable_as: tuple[str, ...]
    approved_date: str | None
    processed_by: str | None
    processed_date: str | None
    schema_location: str | None
    identity_basis: tuple[str, ...]
    body_present: bool = True
    public_private: str | None = None
    file_id: str | None = None
    short_title: str | None = None
    current_through_public_law: tuple[str, ...] = ()


def _u(tag: str, namespace: str = USLM_NAMESPACE) -> str:
    return "{" + namespace + "}" + tag


def _dc(tag: str) -> str:
    return "{" + DUBLIN_CORE_NAMESPACE + "}" + tag


_META_FIELDS = (
    _dc("title"),
    _dc("type"),
    _u("docNumber"),
    _u("congress"),
    _u("publicPrivate"),
    _u("citableAs"),
    _u("approvedDate"),
    _u("processedBy"),
    _u("processedDate"),
    _u("currentThroughPublicLaw"),
    _u("citableAsShortTitle"),
    _u("property"),
)
_SCHEMA_LOCATION = "{http://www.w3.org/2001/XMLSchema-instance}schemaLocation"


class UslmScan(IdentityXmlScan):
    """One USLM document root: its single meta block, its stated property roles and whether it carries text.

    Two publishers serve USLM and share only this shape. GPO serves 2.x in
    ``http://schemas.gpo.gov/xml/uslm`` under ``pLaw`` and
    ``statuteCompilation``, whose own text lives in ``main``; OLRC serves 1.0 in
    ``http://xml.house.gov/schemas/uslm/1.0`` under ``uscDoc``, whose own text
    lives in ``main`` or ``appendix`` (:mod:`spicy_docs.sources.uscode`). The
    namespace, root, body sections, meta fields and refusal words are therefore
    arguments and the scan is written once.

    ``referring_sections`` name sections whose text accounts for a document's
    content without being it: a stub compilation carries an empty ``main`` and
    points to the U.S. Code from its ``preface`` (COMPS-3101, Paperwork
    Reduction Act). Their text sets ``body_found`` but not ``body_text``, so a
    caller can report a document that states a body without carrying one.
    """

    def __init__(
        self,
        root: str,
        *,
        namespace: str = USLM_NAMESPACE,
        body_sections: tuple[str, ...] = ("main",),
        referring_sections: tuple[str, ...] = ("preface",),
        meta_fields: tuple[str, ...] = _META_FIELDS,
        error_type: type[ValueError] = UslmSourceError,
        label: str = "USLM XML",
        root_refusal: str = "USLM XML root is not the requested document type",
    ) -> None:
        self.expected_root = _u(root, namespace)
        self._meta = _u("meta", namespace)
        self.meta_path = (self.expected_root, self._meta)
        self._property = _u("property", namespace)
        self._body = frozenset(_u(name, namespace) for name in body_sections)
        self._referring = frozenset(_u(name, namespace) for name in referring_sections)
        self._sections = " or ".join(body_sections + referring_sections)
        self._root_refusal = root_refusal
        super().__init__({self.meta_path + (name,) for name in meta_fields}, error_type=error_type, label=label)
        self.meta_count = 0
        self.property_roles: list[str | None] = []
        self.schema_location: str | None = None
        self.identifier: str | None = None
        self.body_text = False

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        depth = len(self.stack)
        if depth == 1:
            if tag != self.expected_root:
                raise self.error_type(self._root_refusal)
            self.schema_location = attributes.get(_SCHEMA_LOCATION)
            # Absent in one retained U.S. Code file: the eliminated Title 50
            # Appendix, converted in 2015 and reissued unchanged since.
            self.identifier = attributes.get("identifier")
        elif tag == self.expected_root:
            raise self.error_type(f"{self.label} contains a nested document root")
        # Depth and parent, not self.path: the largest title is 1.1 million
        # elements, and rebuilding the ancestor tuple twice per element cost
        # more than the parse (2.4 s of usc42's 3.4 s, measured).
        elif depth == 2 and tag == self._meta:
            self.meta_count += 1
        elif depth == 3 and tag == self._property and self.stack[1][0] == self._meta:
            self.property_roles.append(attributes.get("role"))

    def observe_text(self, text: str) -> None:
        if self.body_text or not text.strip() or len(self.stack) < 2:
            return
        section = self.stack[1][0]
        if section in self._body:
            self.body_text = self.body_found = True
        elif section in self._referring:
            self.body_found = True

    def read(self, body: bytes, max_bytes: int) -> None:
        super().read(body, max_bytes)
        if self.meta_count != 1:
            raise self.error_type(f"{self.label} requires exactly one meta block")
        if not self.body_found:
            raise self.error_type(f"{self.label} lacks source content in {self._sections}")

    def meta(self, name: str, *, required: bool = False) -> str | None:
        value = self.field(self.meta_path + (name,), required=required)
        return value.strip() if value is not None else None

    def meta_values(self, name: str) -> tuple[str, ...]:
        return tuple(value.strip() for value in self.values.get(self.meta_path + (name,), []))


def _scan(body: bytes, root: str, max_bytes: int) -> UslmScan:
    _limit(max_bytes)
    scan = UslmScan(root)
    scan.read(body, max_bytes)
    return scan


def _comparable(citation: str) -> str:
    return re.sub(r"\s+", " ", citation.replace("–", "-").replace("—", "-")).strip()


def validate_public_law_xml(
    body: bytes,
    *,
    selection: PublicLawSelection,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> UslmMetadata:
    """Prove the law's native Congress, kind, number and citation match the request."""
    if final_url != public_law_xml_locator(selection):
        raise UslmSourceError("public law response URL differs from the requested law")
    scan = _scan(body, "pLaw", max_bytes)
    congress = scan.meta(_u("congress"), required=True)
    kind = scan.meta(_u("publicPrivate"), required=True)
    number = scan.meta(_u("docNumber"), required=True)
    if (congress, kind, number) != (str(selection.congress), selection.kind, str(selection.number)):
        raise UslmIdentityError("public law native identity differs from the request")
    citations = scan.meta_values(_u("citableAs"))
    if _comparable(selection.citation) not in {_comparable(citation) for citation in citations}:
        raise UslmIdentityError("public law citable form differs from the request")
    return UslmMetadata(
        "public-law",
        "pLaw",
        scan.meta(_dc("title"), required=True) or "",
        scan.meta(_dc("type")),
        number,
        congress,
        citations,
        scan.meta(_u("approvedDate")),
        scan.meta(_u("processedBy")),
        scan.meta(_u("processedDate")),
        scan.schema_location,
        ("congress:native", "kind:native", "number:native", "citation:native"),
        body_present=scan.body_text,
        public_private=kind,
    )


def validate_statute_compilation_xml(
    body: bytes,
    *,
    selection: StatuteCompilationSelection,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> UslmMetadata:
    """Prove the compilation's native file identifier matches the request; keep its stated currency raw."""
    if final_url != statute_compilation_xml_locator(selection):
        raise UslmSourceError("statute compilation response URL differs from the requested compilation")
    scan = _scan(body, "statuteCompilation", max_bytes)
    properties = scan.meta_values(_u("property"))
    file_ids = [value for role, value in zip(scan.property_roles, properties, strict=True) if role == "fileId"]
    if len(file_ids) != 1:
        raise UslmSourceError("statute compilation requires exactly one fileId property")
    if file_ids[0] != str(selection.file_id):
        raise UslmSourceError("statute compilation native file identifier differs from the request")
    document_type = scan.meta(_dc("type"))
    if document_type is not None and document_type != "Statute Compilation":
        raise UslmSourceError("statute compilation document type is unsupported")
    return UslmMetadata(
        "statute-compilation",
        "statuteCompilation",
        scan.meta(_dc("title"), required=True) or "",
        document_type,
        scan.meta(_u("docNumber")),
        scan.meta(_u("congress")),
        scan.meta_values(_u("citableAs")),
        scan.meta(_u("approvedDate")),
        scan.meta(_u("processedBy")),
        scan.meta(_u("processedDate")),
        scan.schema_location,
        ("file-id:native",),
        body_present=scan.body_text,
        file_id=file_ids[0],
        short_title=scan.meta(_u("citableAsShortTitle")),
        current_through_public_law=scan.meta_values(_u("currentThroughPublicLaw")),
    )


@dataclass(frozen=True, slots=True)
class UslmArchiveEntry:
    """One validated archive member: its name, size, digest and native metadata."""

    name: str
    byte_size: int
    sha256: str
    metadata: UslmMetadata


@dataclass(frozen=True, slots=True)
class UslmArchive:
    """Every entry validated against the identity its own file name declares."""

    source: UslmSource
    entries: tuple[UslmArchiveEntry, ...]


def _read_archive[Selection](
    body: bytes,
    *,
    source: UslmSource,
    select: Callable[[str], Selection],
    validate: Callable[[bytes, Selection], UslmMetadata],
    max_bytes: int,
    max_entry_bytes: int,
    max_entries: int,
) -> UslmArchive:
    _limit(max_bytes)
    _limit(max_entry_bytes)
    if type(max_entries) is not int or max_entries <= 0:
        raise UslmSourceError("max_entries must be a positive integer")
    label = "USLM archive"
    entries = []
    with open_archive(
        body,
        max_bytes=max_bytes,
        max_entries=max_entries,
        max_entry_bytes=max_entry_bytes,
        error_type=UslmSourceError,
        label=label,
    ) as archive:
        for info in archive_members(archive, max_entries=max_entries, error_type=UslmSourceError, label=label):
            selection = select(info.filename.rsplit("/", 1)[-1])
            data = read_member(archive, info, max_bytes=max_entry_bytes, error_type=UslmSourceError, label=label)
            entries.append(
                UslmArchiveEntry(
                    info.filename, len(data), "sha256:" + hashlib.sha256(data).hexdigest(), validate(data, selection)
                )
            )
    return UslmArchive(source, tuple(entries))


def read_public_law_archive(
    body: bytes,
    *,
    congress: int,
    kind: LawKind,
    max_bytes: int = MAX_USLM_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_BYTES,
    max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
) -> UslmArchive:
    """Read one Congress/kind zip; every entry must belong to it and prove its own identity."""
    public_law_archive_locator(congress, kind)

    def select(name: str) -> PublicLawSelection:
        selection = PublicLawSelection.from_file_name(name)
        if (selection.congress, selection.kind) != (congress, kind):
            raise UslmSourceError("public law archive entry belongs to another Congress or kind")
        return selection

    return _read_archive(
        body,
        source="public-law",
        select=select,
        validate=lambda data, selection: validate_public_law_xml(
            data, selection=selection, final_url=public_law_xml_locator(selection), max_bytes=max_entry_bytes
        ),
        max_bytes=max_bytes,
        max_entry_bytes=max_entry_bytes,
        max_entries=max_entries,
    )


def read_statute_compilations_archive(
    body: bytes,
    *,
    max_bytes: int = MAX_USLM_BYTES,
    max_entry_bytes: int = DEFAULT_MAX_BYTES,
    max_entries: int = DEFAULT_MAX_ARCHIVE_ENTRIES,
) -> UslmArchive:
    """Read the whole-collection zip; each entry proves the file identifier its name declares."""
    return _read_archive(
        body,
        source="statute-compilation",
        select=StatuteCompilationSelection.from_file_name,
        validate=lambda data, selection: validate_statute_compilation_xml(
            data, selection=selection, final_url=statute_compilation_xml_locator(selection), max_bytes=max_entry_bytes
        ),
        max_bytes=max_bytes,
        max_entry_bytes=max_entry_bytes,
        max_entries=max_entries,
    )
