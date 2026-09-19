"""Fetch one bill version's PDF as a GovInfo BILLS package body.

Ported from BillTrax `src/lib/govinfo-pdf-fetch.ts` fetch half (read-only,
`/Users/mikewolfd/Work/spicy-stack/BillTrax`), which builds a govinfo PDF URL
from a `version_code` slug and downloads it with its own `fetch` call. That
second HTTP path is not ported: `sources.govinfo.body_acquisition.
GovInfoBodyAcquirer` already proves a package's identity from its summary and
MODS before fetching any body byte, and BILLS is one of the collections it
already serves (`sources.govinfo.bodies`). This module only derives a package
id and delegates.

Measured 2026-09-19 (`docs/research/billtrax-raw-data-2026-09-19.md` §3, §7):
the congress.gov and govinfo PDF addresses for the same version serve
byte-identical files (2/2 sampled), and every bill this project measured
states its own PDF package id in a Congress.gov or BILLSTATUS format URL
(`sources.congress.bill_status.bill_package_id_from_url`). A stated package
id is therefore preferred over deriving one from the version-code vocabulary:
the vocabulary's name-derived fallback cannot distinguish a numbered reprint
(`eas2`) from its original (`eas`), because Congress.gov gives both the same
`type` string. Bill PDFs run small -- median 246 KB, max 4.77 MB across 15
packages sampled, 0 over the 24 MiB evidence bound -- so no separate PDF
budget is needed beyond what `GovInfoBodyBudget` already bounds.
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
    keyword-only precisely so it cannot sit unused beside a `package_id` a
    caller already trusts more.

    `package_id` is the publisher's own stated package id for this version --
    pass it whenever the caller has one (read from a BILLSTATUS or
    Congress.gov format URL via `bill_status.bill_package_id_from_url`). It is
    used exactly as given, with **no cross-check against `slug`**: a numbered
    reprint's real package id (`BILLS-119hr6644eas2`) legitimately disagrees
    with the slug its shared type name derives
    (`bill_versions.version_slug("Engrossed Amendment Senate")` is
    `engrossed-amendment-senate`, which names `eas`, not `eas2`) -- see
    `bill_versions`'s module docstring and `version_slug_reprints`. Rejecting
    that disagreement would block the exact case a stated package id exists
    to fix.

    `slug` is the name-derived fallback for when no stated package id exists:
    `bill_versions.bill_version_package_id(identity, slug)`. It cannot tell a
    numbered reprint from its original by name alone.

    The caller owns `acquirer` -- its budget, credential and transport -- so
    this function makes no request of its own beyond the one delegated call;
    there is no second HTTP path for bill PDFs. `max_bytes` narrows the
    acquirer's own body allowance for this call, never raises it.
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
