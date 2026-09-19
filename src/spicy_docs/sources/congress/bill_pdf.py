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

#: `acquire()` fetches a body only for a format the caller names; PDF is
#: never the acquirer's own default (`body_acquisition.DEFAULT_PREFERENCE`
#: is text-first), so this module always asks for it explicitly.
_PREFER_PDF: tuple[str, ...] = ("pdf",)


def acquire_bill_pdf(
    identity: BillIdentity,
    slug: str,
    *,
    acquirer: GovInfoBodyAcquirer,
    package_id: str | None = None,
    max_bytes: int | None = None,
) -> GovInfoPackageBody:
    """Fetch the PDF rendition of one bill version.

    `package_id` is the publisher's own stated package id for this version --
    pass it whenever the caller has one (read from a BILLSTATUS or
    Congress.gov format URL via `bill_status.bill_package_id_from_url`). Only
    when no stated package id exists does this fall back to
    `bill_versions.bill_version_package_id(identity, slug)`, the name-derived
    vocabulary lookup that cannot tell a numbered reprint from its original
    (see the module docstring and `bill_versions`'s).

    The caller owns `acquirer` -- its budget, credential and transport -- so
    this function makes no request of its own beyond the one delegated call;
    there is no second HTTP path for bill PDFs. `max_bytes` narrows the
    acquirer's own body allowance for this call, never raises it.
    """
    if not isinstance(acquirer, GovInfoBodyAcquirer):
        raise TypeError("acquirer must be a GovInfoBodyAcquirer")
    resolved_package_id = package_id if package_id is not None else bill_version_package_id(identity, slug)
    return acquirer.acquire(resolved_package_id, prefer=_PREFER_PDF, max_bytes=max_bytes)


__all__ = ["acquire_bill_pdf"]
