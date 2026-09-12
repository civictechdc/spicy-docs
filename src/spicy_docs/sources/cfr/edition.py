"""Annual publication facts from GovInfo package MODS, separate from body XML."""

from dataclasses import dataclass
from enum import StrEnum

from ._xml import IdentityXmlScan
from .models import DEFAULT_MAX_BYTES, AnnualCfrSelection, CfrSourceError, _date


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


def _path(*names: str) -> tuple[str, ...]:
    return tuple("{http://www.loc.gov/mods/v3}" + name for name in ("mods", *names))


_EXTENSION_FIELDS = (
    "collectionCode",
    "accessId",
    "titleNumber",
    "volumeNumber",
    "isCoverOnly",
    "originalDateIssued",
    "editionId",
    "isCurrentEdition",
    "isFallbackTitle",
)


class _EditionScan(IdentityXmlScan):
    def __init__(self) -> None:
        super().__init__(
            {
                *(_path("extension", name) for name in _EXTENSION_FIELDS),
                _path("originInfo", "dateIssued"),
                _path("titleInfo", "title"),
            }
        )

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        if len(self.path) == 1 and tag != _path()[0]:
            raise CfrSourceError("annual edition metadata must be MODS v3 XML")
        if any(active_path != self.path for active_path, _parts in self._active):
            raise CfrSourceError("annual edition metadata fields must contain scalar text")

    def value(self, *names: str, required: bool = False) -> str | None:
        path = _path(*names)
        # An absent optional flag is unknown; a supplied empty value is invalid.
        return self.field(path, required=required or path in self.values)

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
    """Read root package facts; nested granule metadata cannot supply them."""
    if final_url != annual_cfr_edition_locator(selection):
        raise CfrSourceError("annual edition response URL differs from the requested volume")
    scan = _EditionScan()
    scan.read(body, max_bytes)
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
    return AnnualCfrEdition(
        selection.year,
        selection.title,
        selection.volume,
        issued,
        original,
        scan.flag("isCoverOnly"),
        edition_id,
        scan.flag("isCurrentEdition"),
        scan.flag("isFallbackTitle"),
        scan.value("titleInfo", "title"),
    )
