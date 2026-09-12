"""Annual CFR bulk volumes and explicitly selected GovInfo section granules."""

from __future__ import annotations

import re
from datetime import date

from ._xml import IdentityXmlScan
from .models import DEFAULT_MAX_BYTES, AnnualCfrSelection, CfrSourceError, CfrXmlMetadata, _date


def annual_cfr_xml_locator(identity: AnnualCfrSelection) -> str:
    """Name the requested edition; older printed revision dates may remain inside."""
    if not isinstance(identity, AnnualCfrSelection):
        raise CfrSourceError("identity must be an AnnualCfrSelection")
    package = f"CFR-{identity.year}-title{identity.title}-vol{identity.volume}"
    if identity.section is not None:
        granule = package + "-sec" + identity.section.replace(".", "-")
        return f"https://www.govinfo.gov/content/pkg/{package}/xml/{granule}.xml"
    return f"https://www.govinfo.gov/bulkdata/CFR/{identity.year}/title-{identity.title}/{package}.xml"


class _AnnualScan(IdentityXmlScan):
    def __init__(self, identity: AnnualCfrSelection) -> None:
        self.identity = identity
        self.expected_root = "CFRGRANULE" if identity.section is not None else "CFRDOC"
        self.header = (self.expected_root, "FDSYS")
        self.front = (self.expected_root, "FMTR", "TITLEPG")
        super().__init__(
            {
                *(self.header + (field,) for field in ("CFRTITLE", "CFRTITLETEXT", "VOL", "DATE")),
                *(self.front + (field,) for field in ("TITLENUM", "SUBJECT", "REVISED", "DATE")),
                (self.expected_root, "TITLE", "CFRTITLE", "TITLEHD", "HD"),
                (self.expected_root, "AMDDATE"),
                (self.expected_root, "SECTION", "SECTNO"),
            }
        )
        self.sections = 0

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        if len(self.stack) == 1 and tag != self.expected_root:
            raise CfrSourceError("annual CFR XML root differs from the requested scope")
        if len(self.stack) > 1 and tag in {"CFRDOC", "CFRGRANULE", "DLPSTEXTCLASS", "ECFR"}:
            raise CfrSourceError("annual CFR XML contains a nested document root")
        if tag == "SECTION":
            self.sections += 1

    def observe_text(self, text: str) -> None:
        if not text.strip() or "SECTION" not in self.path:
            return
        if any(tag in {"P", "FP", "PSPACE", "ENTRY", "ENT", "TD", "RESERVED"} for tag in self.path) or self.path[
            -2:
        ] == ("GPH", "GID"):
            self.body_found = True


def _integer(value: str, label: str) -> int:
    value = value.strip()
    if re.fullmatch(r"[0-9]+", value) is None:
        raise CfrSourceError(f"annual CFR native {label} must be an integer")
    return int(value)


def _revision_year(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.fullmatch(
        r"(?:Revised as of|As of) (January|February|March|April|May|June|July|August|September|October|November|December) "
        r"([0-9]{1,2}), ([0-9]{4})",
        value.strip(),
    )
    if match is None:
        return None
    months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    try:
        return date(int(match[3]), months.index(match[1]) + 1, int(match[2])).year
    except ValueError:
        return None


def validate_annual_cfr_xml(
    body: bytes,
    *,
    identity: AnnualCfrSelection,
    final_url: str,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> CfrXmlMetadata:
    """Check native fields without treating a requested edition as a printed date.

    Full volumes need not state their volume number. The canonical response URL
    establishes that requested coordinate; it does not independently verify it
    inside the body. Section granules carry stronger FDSYS identity fields.
    """
    if final_url != annual_cfr_xml_locator(identity):
        raise CfrSourceError("annual CFR response URL differs from the requested edition and scope")
    scan = _AnnualScan(identity)
    scan.read(body, max_bytes)
    if not scan.body_found:
        raise CfrSourceError("annual CFR XML lacks source section content")
    granule = identity.section is not None
    native_title = scan.field((*scan.header, "CFRTITLE"), required=granule)
    native_volume = scan.field((*scan.header, "VOL"), required=granule)
    title_numbers = [] if native_title is None else [_integer(native_title, "title")]
    for path in [(*scan.front, "TITLENUM"), (scan.root, "TITLE", "CFRTITLE", "TITLEHD", "HD")]:
        field = scan.field(path)
        if field is not None:
            match = re.match(r"\s*Title\s+([0-9]+)(?=\s|[—–:-]|$)", field)
            if match is None:
                raise CfrSourceError("annual CFR title heading lacks its title number")
            title_numbers.append(int(match[1]))
    if not title_numbers or any(number != identity.title for number in title_numbers):
        raise CfrSourceError("annual CFR native title differs from the request or is absent")
    volume = _integer(native_volume, "volume") if native_volume is not None else None
    if volume is not None and volume != identity.volume:
        raise CfrSourceError("annual CFR native volume differs from the request")
    section = scan.field((scan.root, "SECTION", "SECTNO"), required=granule)
    if granule and (
        section is None or section.strip().removeprefix("§").strip() != identity.section or scan.sections != 1
    ):
        raise CfrSourceError("annual CFR XML must contain exactly the requested section")
    stated_date = scan.field((*scan.header, "DATE"), required=granule)
    if stated_date is not None:
        _date(stated_date.strip())
    else:
        stated_date = scan.field((*scan.front, "DATE"))
    basis = ["title:native", "volume:native" if volume is not None else "volume:request-url", "edition:request-url"]
    if granule:
        basis.append("section:native")
    revision = scan.field((*scan.front, "REVISED"))
    front_date = scan.field((*scan.front, "DATE"))
    warnings = (
        ("requested-edition-differs-from-printed-revision",)
        if any(
            year is not None and year != identity.year
            for year in (_revision_year(revision), _revision_year(front_date))
        )
        else ()
    )
    return CfrXmlMetadata(
        "annual-cfr",
        identity.title,
        volume,
        None,
        identity.section,
        scan.root,
        scan.field((*scan.header, "CFRTITLETEXT")) or scan.field((*scan.front, "SUBJECT")),
        stated_date,
        revision,
        tuple(scan.values.get((scan.root, "AMDDATE"), [])),
        tuple(basis),
        warnings,
    )
