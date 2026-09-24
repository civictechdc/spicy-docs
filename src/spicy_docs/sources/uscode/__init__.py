"""Explicit OLRC U.S. Code sources: release points, annual archives, popular names, Table III and classification tables.

The Office of the Law Revision Counsel publishes the Code itself, keyless, with
no API, and each family proves its own identity from its own bytes: a
release-point title's ``<meta>`` states its number and release point, an annual
member's ``AUTHORITIES-*`` comments state its year, and the zip routes carry
neither ``Content-Type`` nor ``Content-Length``, so archive shape is proved
from a local file header and CRC check instead. Two publisher answers shape the
readers: a Table III act without a page answers HTTP 200 and a connection
dropped inside the site template, and a title the publisher lists but does not
serve answers 302, so neither status is read as data or absence; Table III
absence is read from the chain of acts its pages link. This publisher's USLM is
not GovInfo's -- OLRC serves USLM 1.0 under ``uscDoc``, GovInfo 2.x under
``pLaw`` -- so
:mod:`spicy_docs.sources.govinfo.uslm`'s
:class:`~spicy_docs.sources.govinfo.uslm.UslmScan` is bound to this namespace,
root and body sections rather than written twice.
"""

from .annual import ANNUAL_FIELDS, AnnualTitleMetadata, validate_annual_title_html
from .core import (
    ANNUAL_HEADER_BYTES,
    DEFAULT_MAX_ARCHIVE_BYTES,
    DEFAULT_MAX_ARCHIVE_ENTRIES,
    DEFAULT_MAX_ENTRIES_PER_PAGE,
    DEFAULT_MAX_PAGE_BYTES,
    DEFAULT_MAX_TABLE3_MEMBER_BYTES,
    DEFAULT_MAX_XML_BYTES,
    DUBLIN_CORE_NAMESPACE,
    DUBLIN_CORE_TERMS_NAMESPACE,
    FIRST_ANNUAL_YEAR,
    MAX_USCODE_BYTES,
    OLRC,
    TITLES,
    USLM_NAMESPACE,
    ReleasePoint,
    TitleSelection,
    UsCodeSource,
    UsCodeSourceError,
    annual_archive_locator,
    corpus_xml_locator,
    popular_names_locator,
    table3_act_locator,
    table3_bulk_locator,
    table3_file_name,
    title_xml_locator,
)
from .popular_names import (
    POPULAR_NAME_DEFECTS,
    PopularNameDefect,
    PopularNameRecord,
    PopularNames,
    parse_popular_names,
)
from .table3 import (
    Table3Act,
    Table3ActRecord,
    Table3Bulk,
    Table3Page,
    Table3Record,
    iter_act_fragments,
    iter_table3_acts,
    iter_table3_chain,
    parse_act_fragment,
    parse_table3_page,
    read_table3_bulk_archive,
    read_table3_bulk_member,
)
from .titles import UsCodeTitleMetadata, validate_title_xml

__all__ = [
    "ANNUAL_FIELDS",
    "ANNUAL_HEADER_BYTES",
    "DEFAULT_MAX_ARCHIVE_BYTES",
    "DEFAULT_MAX_ARCHIVE_ENTRIES",
    "DEFAULT_MAX_ENTRIES_PER_PAGE",
    "DEFAULT_MAX_PAGE_BYTES",
    "DEFAULT_MAX_TABLE3_MEMBER_BYTES",
    "DEFAULT_MAX_XML_BYTES",
    "DUBLIN_CORE_NAMESPACE",
    "DUBLIN_CORE_TERMS_NAMESPACE",
    "FIRST_ANNUAL_YEAR",
    "MAX_USCODE_BYTES",
    "OLRC",
    "POPULAR_NAME_DEFECTS",
    "TITLES",
    "USLM_NAMESPACE",
    "AnnualTitleMetadata",
    "PopularNameDefect",
    "PopularNameRecord",
    "PopularNames",
    "ReleasePoint",
    "Table3Act",
    "Table3ActRecord",
    "Table3Bulk",
    "Table3Page",
    "Table3Record",
    "TitleSelection",
    "UsCodeSource",
    "UsCodeSourceError",
    "UsCodeTitleMetadata",
    "annual_archive_locator",
    "corpus_xml_locator",
    "iter_act_fragments",
    "iter_table3_acts",
    "iter_table3_chain",
    "parse_act_fragment",
    "parse_popular_names",
    "parse_table3_page",
    "popular_names_locator",
    "read_table3_bulk_archive",
    "read_table3_bulk_member",
    "table3_act_locator",
    "table3_bulk_locator",
    "table3_file_name",
    "title_xml_locator",
    "validate_annual_title_html",
    "validate_title_xml",
]
