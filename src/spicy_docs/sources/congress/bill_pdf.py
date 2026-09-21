"""Fetch one bill version's PDF as a GovInfo BILLS package body.

Ported from BillTrax's `govinfo-pdf-fetch.ts` fetch half, without its second
HTTP path: `GovInfoBodyAcquirer` already proves a BILLS package's identity
from its summary and MODS before fetching any body byte, so this module only
derives a package id and delegates. A publisher-stated package id is preferred
over one derived from the version-code vocabulary, whose name-derived fallback
cannot distinguish a numbered reprint (`eas2`) from its original (`eas`). Bill
PDFs measure small (median 246 KB; max 4.77 MB sampled), so no separate PDF
budget is needed beyond what `GovInfoBodyBudget` bounds.
"""

from __future__ import annotations

from spicy_docs.sources.congress.bill_status import BillIdentity
from spicy_docs.sources.congress.bill_versions import bill_version_package_id
from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoPackageBody

#: This module wants the PDF specifically, not "the best body available", so
#: it names PDF alone rather than leaning on the sealed
#: `bodies.BODY_PREFERENCE`, whose last entry PDF is: under that order a bill
#: that also offers XML would answer with XML, which is not what a PDF fetch
#: asked for.
_PREFER_PDF: tuple[str, ...] = ("pdf",)


def acquire_bill_pdf(
    identity: BillIdentity,
    *,
    acquirer: GovInfoBodyAcquirer,
    slug: str | None = None,
    package_id: str | None = None,
    max_bytes: int | None = None,
) -> GovInfoPackageBody:
    """Fetch the PDF rendition of one bill version.

    Exactly one of `slug` and `package_id` must be given -- `slug` is
    keyword-only so it cannot sit unused beside a `package_id` a caller already
    trusts more. `package_id` is the publisher's own stated package id (read
    from a BILLSTATUS or Congress.gov format URL via
    `bill_status.bill_package_id_from_url`) and is used exactly as given, with
    no cross-check against `slug`: a numbered reprint's real package id
    (`BILLS-119hr6644eas2`) legitimately disagrees with the slug its shared
    type name derives, and rejecting that disagreement would block the exact
    case a stated package id exists to fix. `slug` is the name-derived
    fallback and cannot tell a numbered reprint from its original by name.

    The caller owns `acquirer` -- its budget, credential and transport -- so
    this function makes no request of its own beyond the one delegated call;
    `max_bytes` narrows the acquirer's own body allowance for this call, never
    raises it.
    """
    if not isinstance(acquirer, GovInfoBodyAcquirer):
        raise TypeError("acquirer must be a GovInfoBodyAcquirer")
    if (slug is None) == (package_id is None):
        raise ValueError("exactly one of slug or package_id must be given")
    if package_id is not None:
        resolved_package_id = package_id
    else:
        assert slug is not None  # guaranteed by the exactly-one-of check above
        resolved_package_id = bill_version_package_id(identity, slug)
    return acquirer.acquire(resolved_package_id, prefer=_PREFER_PDF, max_bytes=max_bytes)


__all__ = ["acquire_bill_pdf"]
