"""Release-point title USLM: native identity proven against the request."""

from __future__ import annotations

from dataclasses import dataclass

from spicy_docs.sources.uscode.core import (
    DEFAULT_MAX_XML_BYTES,
    DUBLIN_CORE_NAMESPACE,
    DUBLIN_CORE_TERMS_NAMESPACE,
    USLM_NAMESPACE,
    TitleSelection,
    UsCodeSource,
    UsCodeSourceError,
    _limit,
    title_xml_locator,
)

from ..govinfo.uslm import UslmScan

# --------------------------------------------------------------------------- #
# release-point USLM
# --------------------------------------------------------------------------- #


def _u(tag: str) -> str:
    return "{" + USLM_NAMESPACE + "}" + tag


def _dc(tag: str) -> str:
    return "{" + DUBLIN_CORE_NAMESPACE + "}" + tag


def _dcterms(tag: str) -> str:
    return "{" + DUBLIN_CORE_TERMS_NAMESPACE + "}" + tag


_USC_META_FIELDS = (
    _dc("title"),
    _dc("type"),
    _dc("publisher"),
    _dc("creator"),
    _dcterms("created"),
    _u("docNumber"),
    _u("docPublicationName"),
    _u("property"),
)


@dataclass(frozen=True, slots=True)
class UsCodeTitleMetadata:
    """Native ``<meta>`` facts of one title. Publisher spellings are kept; nothing is normalized."""

    source: UsCodeSource
    title: str
    doc_number: str
    release_point: str
    document_type: str
    heading: str
    publisher: str | None
    converter: str | None
    created: str | None
    positive_law: str | None
    schema_location: str | None
    identifier: str | None
    identity_basis: tuple[str, ...]
    body_present: bool = True


def _usc_scan() -> UslmScan:
    """The shared USLM scan bound to OLRC's namespace, root, body sections and refusals.

    A title's text lives in ``main`` and an appendix title's in ``appendix``;
    both are the document's own text, so this publisher has no section that
    states a body it does not carry.
    """
    return UslmScan(
        "uscDoc",
        namespace=USLM_NAMESPACE,
        body_sections=("main", "appendix"),
        referring_sections=(),
        meta_fields=_USC_META_FIELDS,
        error_type=UsCodeSourceError,
        label="U.S. Code USLM",
        root_refusal="U.S. Code USLM root is not uscDoc in the OLRC namespace",
    )


def _property(scan: UslmScan, role: str) -> str | None:
    """The one value the meta block states for a property role, or None where it states none."""
    values = scan.values.get(scan.meta_path + (_u("property"),), [])
    stated = [value.strip() for found, value in zip(scan.property_roles, values, strict=True) if found == role]
    if len(stated) > 1:
        raise UsCodeSourceError(f"U.S. Code USLM repeats the {role} property")
    return stated[0] if stated else None


def validate_title_xml(
    body: bytes,
    *,
    selection: TitleSelection,
    final_url: str | None = None,
    max_bytes: int = DEFAULT_MAX_XML_BYTES,
) -> UsCodeTitleMetadata:
    """Prove the title's native number and release point match the request.

    ``docNumber`` and ``docPublicationName`` are the identity; the file name is
    not consulted, because the publisher's own names disagree with themselves
    (``xml_usc05a@…zip`` carries ``usc05A.xml``, and ``11a`` stays lower case).
    ``identifier`` is a second native witness and is checked where the document
    states one.
    """
    if not isinstance(selection, TitleSelection):
        raise UsCodeSourceError("selection must be a TitleSelection")
    if final_url is not None and final_url != title_xml_locator(selection):
        raise UsCodeSourceError("U.S. Code title response URL differs from the requested title")
    _limit(max_bytes)
    scan = _usc_scan()
    scan.read(body, max_bytes)
    doc_number = scan.meta(_u("docNumber"), required=True) or ""
    if doc_number != selection.doc_number:
        raise UsCodeSourceError("U.S. Code title native number differs from the request")
    release_point = scan.meta(_u("docPublicationName"), required=True) or ""
    if release_point != f"Online@{selection.release_point.label}":
        raise UsCodeSourceError("U.S. Code title native release point differs from the request")
    document_type = scan.meta(_dc("type"), required=True) or ""
    expected_type = "USCTitleAppendix" if selection.is_appendix else "USCTitle"
    if document_type != expected_type:
        raise UsCodeSourceError("U.S. Code title document type differs from the requested title kind")
    if scan.identifier is not None and scan.identifier != selection.identifier:
        raise UsCodeSourceError("U.S. Code title native identifier differs from the request")
    basis = ["doc-number:native", "release-point:native", "document-type:native"]
    if scan.identifier is not None:
        basis.append("identifier:native")
    return UsCodeTitleMetadata(
        "release-point-title",
        selection.title,
        doc_number,
        release_point,
        document_type,
        scan.meta(_dc("title"), required=True) or "",
        scan.meta(_dc("publisher")),
        scan.meta(_dc("creator")),
        scan.meta(_dcterms("created")),
        _property(scan, "is-positive-law"),
        scan.schema_location,
        scan.identifier,
        tuple(basis),
        body_present=scan.body_text,
    )
