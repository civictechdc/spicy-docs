"""FERC sources: comments, new dockets, docket sheets, file lists, originals and generated PDFs from eLibrary.

The Mirrulations regulations.gov mirror holds FERC documents but no FERC
dockets or comments, so comments are acquired from FERC itself. eLibrary
(``elibrary.ferc.gov``) is FERC's document repository keyed by accession
number, and eComment submissions land in it under the ``Comments/Protest``
class; the eComment portal on ``www.ferc.gov`` sits behind a bot wall this
package does not cross (403 to a scripted browser-profiled GET, 2026-09-24).

Import from the submodules, following this package's convention:
``spicy_docs.sources.ferc.elibrary`` for the routes and the page reader,
``spicy_docs.sources.ferc.download`` for the bounded ``DownloadPDF`` acquirer,
``spicy_docs.sources.ferc.originals`` for public file-list-stated P8 originals,
``spicy_docs.sources.ferc.vocabulary`` for the pinned docket-prefix and
class/type rosters, and ``spicy_docs.sources.ferc.readers`` for the ``Reader``
connectors.
"""
