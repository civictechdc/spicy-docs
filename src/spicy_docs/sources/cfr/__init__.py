"""Source identities, locators and offline CFR/eCFR response validation."""

from .annual import (
    AnnualCfrSection,
    AnnualCfrSectionNumber,
    annual_cfr_granule_token,
    annual_cfr_xml_locator,
    scan_annual_cfr_sections,
    split_annual_cfr_section,
    validate_annual_cfr_xml,
)
from .ecfr import (
    ecfr_bulk_xml_locator,
    ecfr_titles_locator,
    ecfr_xml_locator,
    parse_ecfr_titles,
    validate_ecfr_bulk_xml,
    validate_ecfr_xml,
)
from .edition import AnnualCfrEdition, CfrEditionType, annual_cfr_edition_locator, parse_annual_cfr_edition
from .models import (
    DEFAULT_MAX_BYTES,
    MAX_CFR_BYTES,
    AnnualCfrSelection,
    CfrSourceError,
    CfrXmlMetadata,
    EcfrSelection,
    EcfrTitle,
    EcfrTitles,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "MAX_CFR_BYTES",
    "AnnualCfrEdition",
    "AnnualCfrSection",
    "AnnualCfrSectionNumber",
    "AnnualCfrSelection",
    "CfrEditionType",
    "CfrSourceError",
    "CfrXmlMetadata",
    "EcfrSelection",
    "EcfrTitle",
    "EcfrTitles",
    "annual_cfr_edition_locator",
    "annual_cfr_granule_token",
    "annual_cfr_xml_locator",
    "ecfr_bulk_xml_locator",
    "ecfr_titles_locator",
    "ecfr_xml_locator",
    "parse_annual_cfr_edition",
    "parse_ecfr_titles",
    "scan_annual_cfr_sections",
    "split_annual_cfr_section",
    "validate_annual_cfr_xml",
    "validate_ecfr_bulk_xml",
    "validate_ecfr_xml",
]
