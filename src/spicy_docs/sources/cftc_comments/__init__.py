"""CFTC public comments on proposed rules, from the Commission's own portal.

The portal (``comments.cftc.gov``) is a server-rendered ASP.NET WebForms
application behind Cloudflare; this package walks its GET-reachable pages and
captures its letter PDFs, one bounded operation at a time:

* :mod:`spicy_docs.sources.cftc_comments.pages` -- the three page shapes as
  the portal states them, parsed in one linear pass each.
* :mod:`spicy_docs.sources.cftc_comments.acquisition` -- keyless, paced page
  captures with optional raw-byte proxy recovery and named refusals.
* :mod:`spicy_docs.sources.cftc_comments.attachments` -- bounded capture of
  one declared letter PDF (``Handlers/PdfHandler.ashx?id={fileId}``).
* :mod:`spicy_docs.sources.cftc_comments.reader` -- the walk as a
  :class:`~spicy_docs.sources.base.Reader` with ``last_keys``/``failed_keys``
  recovery semantics.

The publisher directs comment files opened on or after 2026-04-28 to
Regulations.gov. This package covers what the older portal lists; see
``docs/sources/cftc-comments.md`` for the separate source selections.
"""
