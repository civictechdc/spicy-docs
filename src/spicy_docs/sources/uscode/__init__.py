"""Explicit OLRC U.S. Code sources: release points, annual archives, popular names and Table III.

The Office of the Law Revision Counsel publishes the Code itself, keyless, with
no API and no content negotiation. Four families arrive here and each proves its
own identity from its own bytes:

* **Release point.** One edition of the Code current through a public law. Each
  title is a one-member zip of United States Legislative Markup whose ``<meta>``
  states the title (``docNumber``) and the release point (``docPublicationName``,
  spelled ``Online@119-103``). ``xml_uscAll`` is the same 58 documents in one
  zip of about 108 MB.
* **Annual historical archive.** One year of the Code as XHTML. Every title
  member states its edition, year, title and currency in ``AUTHORITIES-*`` HTML
  comments, so a member proves its own year without its file name.
* **Popular Name Tool.** One generated page, about 11 MB, one flat
  ``<div class='popular-name-table-entry'>`` per name with the identifying facts
  in attributes. It also links each name's own Table III page, so the Table III
  file name is read rather than derived.
* **Table III.** Which act section went to which Code section: one page per act,
  and one bulk zip whose member is a bare concatenation of ``<act>`` fragments
  rather than a well-formed document.

This publisher's USLM is **not** GovInfo's. OLRC serves USLM 1.0 in
``http://xml.house.gov/schemas/uslm/1.0`` under a ``uscDoc`` root;
:mod:`spicy_docs.sources.govinfo.uslm` serves USLM 2.x in
``http://schemas.gpo.gov/xml/uslm`` under ``pLaw`` and ``statuteCompilation``.
The two share no element name, but they do share the document shape, so this
module binds that module's :class:`~spicy_docs.sources.govinfo.uslm.UslmScan` to
this namespace, root and body sections rather than scanning twice.

Three publisher behaviours shape every check below, all measured on 2026-09-14
and retained in ``corpora/supply-2026-09-02/receipts/port-P01-uscode-2026-09-14/``:

1. **An absent Table III act answers HTTP 200 and a truncated page.** The server
   sends 16,134 bytes of site furniture and closes the stream. It carries no
   rows, so a reader that trusted the status would record "this act classified
   nothing". :func:`parse_table3_page` therefore requires the page to state the
   requested act and to be closed, and refuses the truncated answer by name.
2. **A title the publisher lists but does not serve answers 302**, to
   ``/docnotfound.xhtml``. Title 53 is listed on the download page and answers
   that way. A redirect is neither data nor absence; it is refused with its
   status.
3. **The zip routes carry no ``Content-Type`` and no ``Content-Length``.** The
   shape is proved from the bytes: a local file header, a CRC check, then the
   native identity of every member.
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
