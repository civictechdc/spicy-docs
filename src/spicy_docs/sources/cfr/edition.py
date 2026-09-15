"""Annual publication facts from GovInfo package MODS, separate from body XML."""

from dataclasses import dataclass
from enum import StrEnum

from ..govinfo.mods import MODS_NAMESPACE, GovInfoModsError, GovInfoModsPackage, ModsRecord, parse_govinfo_mods
from .models import DEFAULT_MAX_BYTES, AnnualCfrSelection, CfrSourceError, _date, _limit


class CfrEditionType(StrEnum):
    COVER_ONLY = "cover-only"
    NOT_COVER_ONLY = "not-cover-only"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AnnualCfrEdition:
    year: int
    title: int
    volume: int
    date_issued: str
    original_date_issued: str | None
    is_cover_only: bool | None
    edition_id: str | None
    is_current_edition: bool | None
    is_fallback_title: bool | None
    title_text: str | None

    @property
    def edition_type(self) -> CfrEditionType:
        """Publication type; a cover-only edition can still supply the full body."""
        if self.is_cover_only is None:
            return CfrEditionType.UNKNOWN
        return CfrEditionType.COVER_ONLY if self.is_cover_only else CfrEditionType.NOT_COVER_ONLY


def annual_cfr_edition_locator(selection: AnnualCfrSelection) -> str:
    if not isinstance(selection, AnnualCfrSelection) or selection.section is not None:
        raise CfrSourceError("annual edition metadata requires a volume selection without a section")
    return (
        "https://www.govinfo.gov/metadata/pkg/"
        f"CFR-{selection.year}-title{selection.title}-vol{selection.volume}/mods.xml"
    )


class _EditionFields:
    def __init__(self, record: ModsRecord) -> None:
        self.record = record

    def value(self, *names: str, required: bool = False) -> str | None:
        elements = self.record.fields(*names)
        if len(elements) > 1:
            raise CfrSourceError("annual edition repeats a field: " + "/".join(names))
        if not elements:
            if required:
                raise CfrSourceError("annual edition lacks a field: " + "/".join(names))
            return None
        element = elements[0]
        if element.children:
            raise CfrSourceError("annual edition metadata fields must contain scalar text")
        value = element.text
        if not value.strip() or len(value) > 65_536:
            raise CfrSourceError("annual edition fields must contain bounded nonempty text")
        return value

    def flag(self, name: str) -> bool | None:
        value = self.value("extension", name)
        if value is None:
            return None
        if value.strip() not in {"true", "false", "1", "0"}:
            raise CfrSourceError(f"annual edition {name} must be a boolean")
        return value.strip() in {"true", "1"}


def parse_annual_cfr_edition(
    body: bytes,
    *,
    selection: AnnualCfrSelection,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> AnnualCfrEdition:
    """Read typed edition facts; use the shared MODS parser for all source fields."""
    edition, _metadata = _parse_annual_cfr_metadata(body, selection=selection, final_url=final_url, max_bytes=max_bytes)
    return edition


def _parse_annual_cfr_metadata(
    body: bytes,
    *,
    selection: AnnualCfrSelection,
    final_url: str,
    max_bytes: int,
) -> tuple[AnnualCfrEdition, GovInfoModsPackage]:
    """Map once, then validate the selected package using only its root fields."""
    if final_url != annual_cfr_edition_locator(selection):
        raise CfrSourceError("annual edition response URL differs from the requested volume")
    _limit(max_bytes)
    try:
        metadata = parse_govinfo_mods(body, max_bytes=max_bytes)
    except GovInfoModsError as error:
        raise CfrSourceError(str(error)) from error
    scan = _EditionFields(metadata.package)
    expected = {
        "collectionCode": "CFR",
        "accessId": f"CFR-{selection.year}-title{selection.title}-vol{selection.volume}",
        "titleNumber": str(selection.title),
        "volumeNumber": str(selection.volume),
    }
    for name, value in expected.items():
        actual = scan.value("extension", name, required=True)
        if actual is None or actual.strip() != value:
            raise CfrSourceError(f"annual edition native {name} differs from the request")
    issued = scan.value("originInfo", "dateIssued", required=True)
    assert issued is not None
    issued = _date(issued.strip())
    if int(issued[:4]) != selection.year:
        raise CfrSourceError("annual edition native dateIssued differs from the requested year")
    original = scan.value("extension", "originalDateIssued")
    if original is not None:
        original = _date(original.strip())
    edition_id = scan.value("extension", "editionId")
    if edition_id is not None and edition_id.strip() != f"CFR-title{selection.title}-vol{selection.volume}":
        raise CfrSourceError("annual edition native editionId differs from the requested volume")
    # Alternate/repeated titles belong in the full mapping. A singular display
    # title is available only when the package supplies one untyped title.
    titles = [
        title
        for info in metadata.package.titles
        if info.attribute("type") is None
        for title in info.findall(f"{{{MODS_NAMESPACE}}}title")
    ]
    edition = AnnualCfrEdition(
        selection.year,
        selection.title,
        selection.volume,
        issued,
        original,
        scan.flag("isCoverOnly"),
        edition_id,
        scan.flag("isCurrentEdition"),
        scan.flag("isFallbackTitle"),
        titles[0].text if len(titles) == 1 else None,
    )
    return edition, metadata
