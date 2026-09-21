"""One registration per source: scope, acquisition, profile, and optional table."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any

from spicy_docs.public_tables.profiles import (
    FEDERAL_REGISTER_PUBLIC_TABLE,
    REGULATIONS_GOV_COMMENT_PUBLIC_TABLE,
    REGULATIONS_GOV_DOCKET_PUBLIC_TABLE,
    REGULATIONS_GOV_DOCUMENT_PUBLIC_TABLE,
    PublicTableProfile,
)
from spicy_docs.releases.format import SourceNativeReleaseError
from spicy_docs.releases.profile import SourceNativePage, SourceNativeProfile
from spicy_docs.sources.federal_register.native import (
    FederalRegisterFetch,
    FederalRegisterSourceError,
    iter_federal_register_pages,
)
from spicy_docs.sources.federal_register.profile import (
    FEDERAL_REGISTER_PROFILE,
)
from spicy_docs.sources.gao.native import (
    GaoProductFetch,
    GaoProductSourceError,
    gao_product_query_scope,
    iter_gao_product_pages,
)
from spicy_docs.sources.gao.profile import (
    GAO_PRODUCT_PAGE_PROFILE,
)
from spicy_docs.sources.public_comments.native import (
    COMMENT_TABLE,
    PublicTableFetch,
    PublicTableSourceError,
    iter_spicy_regs_public_comment_pages,
)
from spicy_docs.sources.public_comments.profile import (
    SPICY_REGS_PUBLIC_COMMENT_PROFILE,
)
from spicy_docs.sources.regulations_gov.acquisition import (
    iter_regulations_gov_comment_pages,
    iter_regulations_gov_docket_pages,
    iter_regulations_gov_document_pages,
)
from spicy_docs.sources.regulations_gov.definitions import (
    COMMENT_COLLECTION,
    DOCKET_COLLECTION,
    DOCUMENT_COLLECTION,
    MirrulationsObjectReader,
    RegulationsGovSourceError,
)
from spicy_docs.sources.regulations_gov.profile import (
    REGULATIONS_GOV_COMMENT_PROFILE,
    REGULATIONS_GOV_DOCKET_PROFILE,
    REGULATIONS_GOV_DOCUMENT_PROFILE,
)
from spicy_docs.transport.acquisition import (
    default_regulations_reader,
    federal_register_fetcher,
    gao_fetcher,
    public_table_fetcher,
)

RegulationsReaderFactory = Callable[[str, str], MirrulationsObjectReader]


@dataclass(frozen=True)
class AcquisitionInputs:
    """External operations a command can replace with offline fixtures."""

    clock: Callable[[], datetime]
    fetch: FederalRegisterFetch | None = None
    fetch_gao: GaoProductFetch | None = None
    fetch_public_table: PublicTableFetch | None = None
    read_regulations: RegulationsReaderFactory | None = None


@contextmanager
def _federal_pages(
    inputs: AcquisitionInputs, scope: Mapping[str, Any]
) -> Iterator[Generator[SourceNativePage, None, None]]:
    with federal_register_fetcher(inputs.fetch) as fetch:
        yield iter_federal_register_pages(fetch, query_scope=scope)


@contextmanager
def _gao_pages(
    inputs: AcquisitionInputs, scope: Mapping[str, Any]
) -> Iterator[Generator[SourceNativePage, None, None]]:
    with gao_fetcher(inputs.fetch_gao) as fetch:
        yield iter_gao_product_pages(fetch, query_scope=scope)


@contextmanager
def _table_pages(
    inputs: AcquisitionInputs, scope: Mapping[str, Any]
) -> Iterator[Generator[SourceNativePage, None, None]]:
    with public_table_fetcher(inputs.fetch_public_table, inputs.clock) as fetch:
        yield iter_spicy_regs_public_comment_pages(fetch, query_scope=scope)


@contextmanager
def _regulations_pages(
    inputs: AcquisitionInputs,
    scope: Mapping[str, Any],
    *,
    collection: str,
    iterate: Callable[..., Generator[SourceNativePage, None, None]],
) -> Iterator[Generator[SourceNativePage, None, None]]:
    reader = inputs.read_regulations or default_regulations_reader
    yield iterate(lambda agency: reader(agency, collection), query_scope=scope)


@dataclass(frozen=True)
class SourceRegistration:
    """One source's profile, acquisition context manager, error type, and CLI scope rules."""

    profile: SourceNativeProfile
    acquire: Callable[
        [AcquisitionInputs, Mapping[str, Any]], AbstractContextManager[Generator[SourceNativePage, None, None]]
    ]
    error_type: type[ValueError]
    date_fields: tuple[str, str] | None = None
    agency_label: str | None = None
    products: bool = False
    public_table: PublicTableProfile | None = None

    def query_scope(self, args: argparse.Namespace) -> dict[str, Any]:
        """Build the canonical query scope from parsed CLI flags, refusing flags this source does not accept."""

        if self.date_fields and (args.since is None or args.until is None):
            raise SourceNativeReleaseError(f"--since and --until are required for {args.source}")
        if not self.date_fields and (args.since is not None or args.until is not None):
            raise SourceNativeReleaseError(
                f"--since and --until are not valid for {args.source}; its scope names partitions, not dates"
            )
        if not self.products and args.product_id:
            raise SourceNativeReleaseError("--product-id is only valid for GAO product pages")
        if self.products:
            if args.agency:
                raise SourceNativeReleaseError("--agency is not valid for GAO product pages")
            product_ids = args.product_id or []
            if not product_ids:
                raise SourceNativeReleaseError("at least one --product-id is required for GAO product pages")
            if len(set(product_ids)) != len(product_ids):
                raise SourceNativeReleaseError("GAO --product-id values must be distinct")
            return gao_product_query_scope({"productIds": sorted(product_ids)})
        scope: dict[str, Any] = {}
        if self.agency_label:
            agencies = sorted(set(args.agency or []))
            if not agencies:
                raise SourceNativeReleaseError(f"at least one --agency is required for {self.agency_label}")
            scope["agencies"] = agencies
        elif args.agency:
            raise SourceNativeReleaseError("--agency is only valid for Regulations.gov")
        if self.date_fields:
            first, last = self.date_fields
            scope.update({first: args.since.isoformat(), last: args.until.isoformat()})
        else:
            scope["table"] = COMMENT_TABLE
        return scope


SOURCES = {
    "federal-register": SourceRegistration(
        FEDERAL_REGISTER_PROFILE,
        _federal_pages,
        FederalRegisterSourceError,
        date_fields=("publishedFrom", "publishedThrough"),
        public_table=FEDERAL_REGISTER_PUBLIC_TABLE,
    ),
    "gao-product-pages": SourceRegistration(
        GAO_PRODUCT_PAGE_PROFILE,
        _gao_pages,
        GaoProductSourceError,
        products=True,
    ),
    "regulations-documents": SourceRegistration(
        REGULATIONS_GOV_DOCUMENT_PROFILE,
        partial(_regulations_pages, collection=DOCUMENT_COLLECTION, iterate=iter_regulations_gov_document_pages),
        RegulationsGovSourceError,
        date_fields=("publishedFrom", "publishedThrough"),
        agency_label="Regulations.gov",
        public_table=REGULATIONS_GOV_DOCUMENT_PUBLIC_TABLE,
    ),
    "regulations-dockets": SourceRegistration(
        REGULATIONS_GOV_DOCKET_PROFILE,
        partial(_regulations_pages, collection=DOCKET_COLLECTION, iterate=iter_regulations_gov_docket_pages),
        RegulationsGovSourceError,
        date_fields=("modifiedFrom", "modifiedThrough"),
        agency_label="Regulations.gov",
        public_table=REGULATIONS_GOV_DOCKET_PUBLIC_TABLE,
    ),
    "regulations-comments": SourceRegistration(
        REGULATIONS_GOV_COMMENT_PROFILE,
        partial(_regulations_pages, collection=COMMENT_COLLECTION, iterate=iter_regulations_gov_comment_pages),
        RegulationsGovSourceError,
        date_fields=("postedFrom", "postedThrough"),
        agency_label="Regulations.gov",
        public_table=REGULATIONS_GOV_COMMENT_PUBLIC_TABLE,
    ),
    "spicy-regs-public-comments": SourceRegistration(
        SPICY_REGS_PUBLIC_COMMENT_PROFILE,
        _table_pages,
        PublicTableSourceError,
        agency_label="the spicy-regs public tables",
    ),
}
SOURCE_CHOICES = tuple(SOURCES)
PUBLIC_TABLE_CHOICES = tuple(name for name, source in SOURCES.items() if source.public_table is not None)
ACQUISITION_ERRORS = tuple(dict.fromkeys(source.error_type for source in SOURCES.values()))


def source_registration(name: str) -> SourceRegistration:
    """Return the registration for one source name, refusing an unknown source."""

    try:
        return SOURCES[name]
    except KeyError as error:
        raise SourceNativeReleaseError(f"unsupported source {name!r}") from error


def public_table_profile(name: str) -> PublicTableProfile:
    """Return the public-table profile for a source name, refusing one without a registered table."""

    registration = SOURCES.get(name)
    if registration is None or registration.public_table is None:
        raise SourceNativeReleaseError(f"unsupported public table {name!r}")
    return registration.public_table
