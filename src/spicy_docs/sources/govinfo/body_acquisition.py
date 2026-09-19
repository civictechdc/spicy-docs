"""Acquire one GovInfo package or granule body: keyed summary, keyed MODS, then the keyless rendition.

Three sequential requests under one budget. The summary proves the package
exists and is the one asked for -- it is the only route that answers 404 for a
missing package, since the MODS route answers 400 and the keyless body routes
redirect to an error page that answers 200. The MODS then states which
renditions the package offers, so the caller's preference is matched against
the publisher's own statement instead of a guess, and the body request is only
made for a format the publisher named. Identity is proved before the body is
fetched, which also keeps a mistaken request from spending tens of megabytes.

``acquire_granule`` follows the same three-request shape for one constituent
of a package -- the daily Record's speeches and page ranges -- except the
summary and MODS routes are keyed under the package id
(``packages/{pkg}/granules/{gid}/...``), so a granule that does not belong to
the requested package answers HTTP 400 rather than 404 (measured 2026-09-19),
and is read the same way any other summary or MODS shape mismatch is.

Two clients, because the routes differ in kind: ``api.govinfo.gov`` carries the
credential in ``X-Api-Key`` and must never retain a refusal body that could
echo it, while ``www.govinfo.gov`` is keyless and its 401/403 body is the
publisher's own answer, worth keeping. Both draw on the same request budget.

Callers retain and process the returned bytes; this module publishes nothing
and caches nothing. Install ``spicy-docs[acquisition]`` for its HTTPX client.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Self

from spicy_docs.reading.refusals import attach_refused_response
from spicy_docs.releases.format import MAX_EVIDENCE_BYTES
from spicy_docs.sources.govinfo.bodies import (
    BODY_PREFERENCE,
    GRANULE_BODY_PREFERENCE,
    PACKAGE_BODY_FORMATS,
    GovInfoBodySourceError,
    GranuleBodyIdentity,
    GranuleIdentity,
    GranuleModsIdentity,
    GranuleSummary,
    PackageBodyIdentity,
    PackageIdentity,
    PackageModsIdentity,
    PackageSummary,
    granule_body_locator,
    granule_mods_locator,
    granule_summary_locator,
    package_body_locator,
    package_mods_locator,
    package_summary_locator,
    parse_granule_identity,
    parse_package_id,
    validate_granule_body,
    validate_granule_mods,
    validate_granule_summary,
    validate_package_body,
    validate_package_mods,
    validate_package_summary,
)
from spicy_docs.transport.captured import CapturedBodyResponse, attached_capture, refused_capture
from spicy_docs.transport.credentials import CredentialRefusedError
from spicy_docs.transport.source_acquirer import (
    check_byte_bound,
    check_request_count,
    check_timing,
    narrow_byte_limit,
    utc_now,
)

if TYPE_CHECKING:
    import httpx

_USER_AGENT = "spicy-docs-govinfo-bodies/1.0"
_REDIRECT_STATUSES = (301, 302, 303, 307, 308)


@dataclass(frozen=True, slots=True)
class GovInfoBodyBudget:
    """Per-acquisition request/byte bounds and per-client request-start pacing.

    ``max_requests`` covers the summary, the MODS, the body and every retry on
    both clients. The timeout bounds transport waits, not total elapsed time.
    A zero start interval explicitly disables pacing; a nonzero one meters each
    client separately, so the keyed API host and the keyless content host are
    paced apart, as they are answered apart.
    """

    max_requests: int
    max_body_bytes: int
    max_metadata_bytes: int
    timeout_seconds: float
    min_request_interval_seconds: float

    def __post_init__(self) -> None:
        check_request_count(self.max_requests)
        check_byte_bound(self.max_body_bytes, "max_body_bytes", MAX_EVIDENCE_BYTES)
        check_byte_bound(self.max_metadata_bytes, "max_metadata_bytes", MAX_EVIDENCE_BYTES)
        check_timing(self.timeout_seconds, self.min_request_interval_seconds)


@dataclass(frozen=True, slots=True)
class GovInfoPackageBody:
    """Exact bytes for one package rendition with every capture that proved it."""

    identity: PackageIdentity
    format: str
    preference: tuple[str, ...]
    offered_formats: tuple[str, ...]
    summary: PackageSummary
    mods: PackageModsIdentity
    body: PackageBodyIdentity
    summary_capture: CapturedBodyResponse
    mods_capture: CapturedBodyResponse
    body_capture: CapturedBodyResponse
    request_count: int
    budget: GovInfoBodyBudget

    @property
    def captures(self) -> tuple[CapturedBodyResponse, ...]:
        """The three responses in request order; each carries its own facts."""
        return (self.summary_capture, self.mods_capture, self.body_capture)


@dataclass(frozen=True, slots=True)
class GovInfoGranuleBody:
    """Exact bytes for one granule rendition with every capture that proved it.

    Mirrors ``GovInfoPackageBody``: the granule and its host package identity
    together, rather than a package id alone.
    """

    identity: GranuleIdentity
    format: str
    preference: tuple[str, ...]
    offered_formats: tuple[str, ...]
    summary: GranuleSummary
    mods: GranuleModsIdentity
    body: GranuleBodyIdentity
    summary_capture: CapturedBodyResponse
    mods_capture: CapturedBodyResponse
    body_capture: CapturedBodyResponse
    request_count: int
    budget: GovInfoBodyBudget

    @property
    def captures(self) -> tuple[CapturedBodyResponse, ...]:
        """The three responses in request order; each carries its own facts."""
        return (self.summary_capture, self.mods_capture, self.body_capture)


class GovInfoPackageUnavailableError(GovInfoBodySourceError):
    """The exact requested locator answered that the object is not there.

    That is 404/410 on the keyed routes and a redirect on the keyless body
    routes, where an absent or unoffered rendition is sent to the error page.
    """

    def __init__(self, capture: CapturedBodyResponse, *, label: str) -> None:
        super().__init__(f"GovInfo {label} answered HTTP {capture.status_code} for the requested locator")
        self.capture = capture


class GovInfoFormatNotOfferedError(GovInfoBodySourceError):
    """The package or granule states its renditions and none of them was preferred."""

    def __init__(self, label: str, preference: Sequence[str], offered: Sequence[str]) -> None:
        super().__init__(
            f"{label} offers {', '.join(offered) or 'no supported rendition'}; "
            f"none matches the preferred {', '.join(preference)}"
        )
        self.offered_formats = tuple(offered)
        self.preference = tuple(preference)


class GovInfoRenditionAddressError(GovInfoBodySourceError):
    """The package or granule states a preferred format, at an address this module does not derive.

    Absence and disagreement are different answers. The publisher's own URL is
    in the message and on the error, so the caller can see what it named.
    """

    def __init__(self, label: str, moved: Sequence[tuple[str, str]]) -> None:
        stated = "; ".join(f"{name} at {url}" for name, url in moved)
        super().__init__(f"{label} states {stated}, which is not where this module fetches it")
        self.moved_renditions = tuple(moved)


def _unavailable(capture: CapturedBodyResponse, label: str) -> GovInfoPackageUnavailableError:
    """Absence is evidence too: the refusal carries the response that stated it."""
    error = GovInfoPackageUnavailableError(capture, label=label)
    attach_refused_response(error, refused_capture(capture, stage="source-validation"))
    return error


def _checked_preference(prefer: Sequence[str]) -> tuple[str, ...]:
    if isinstance(prefer, str) or not isinstance(prefer, Sequence):
        raise TypeError("prefer must be a sequence of format names, not one name")
    preference = tuple(prefer)
    if not preference or len(set(preference)) != len(preference):
        raise ValueError("prefer must be a nonempty sequence of distinct format names")
    unknown = [name for name in preference if name not in PACKAGE_BODY_FORMATS]
    if unknown:
        raise ValueError(f"prefer names unsupported formats: {', '.join(unknown)}")
    return preference


class GovInfoBodyAcquirer:
    """A sequential, caller-owned client for one package body at a time.

    Request counts reset per ``acquire``; pacing persists until ``close``.
    Redirects and credentials in URLs are refused. Injected transports must
    honor HTTPX's streaming interface and add no hidden requests or
    authentication. This class is not a concurrent scheduler.
    """

    def __init__(
        self,
        *,
        budget: GovInfoBodyBudget,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not isinstance(budget, GovInfoBodyBudget):
            raise TypeError("budget must be a GovInfoBodyBudget")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key must be a nonempty string; the summary and MODS routes are keyed")
        from spicy_docs.transport.capture import BoundedHttpCapture

        self._budget = budget
        self._credential = api_key
        self._closed = False

        def client(*, headers: dict[str, str] | None, retain_refusal_bodies: bool) -> BoundedHttpCapture:
            return BoundedHttpCapture(
                max_requests=budget.max_requests,
                timeout_seconds=budget.timeout_seconds,
                min_request_interval_seconds=budget.min_request_interval_seconds,
                user_agent=_USER_AGENT,
                error_type=GovInfoBodySourceError,
                transport=transport,
                clock=clock,
                headers=headers,
                retain_refusal_bodies=retain_refusal_bodies,
            )

        # The keyed client keeps no refusal body: an api.data.gov error can
        # echo the key. The keyless client keeps one: there it is a bot wall
        # or an access-denied document, which is the publisher's answer.
        self._api = client(headers={"X-Api-Key": api_key}, retain_refusal_bodies=False)
        self._content = client(headers=None, retain_refusal_bodies=True)

    @property
    def budget(self) -> GovInfoBodyBudget:
        return self._budget

    @property
    def request_count(self) -> int:
        return self._api.request_count + self._content.request_count

    def __enter__(self) -> Self:
        if self._closed:
            raise ValueError("GovInfo body acquirer is closed")
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._api.close()
            self._content.close()

    def _capture(self, url: str, *, keyed: bool, max_bytes: int) -> CapturedBodyResponse:
        """One request against the shared budget, including its retries."""
        client = self._api if keyed else self._content
        # Both clients spend one budget, so each is allowed only what is left.
        # Setting it before the call also bounds retries inside that call.
        client.max_requests = client.request_count + max(self.budget.max_requests - self.request_count, 0)
        capture = client.capture(url, max_bytes=max_bytes, allow_unavailable=True)
        if keyed and self._credential.encode() in capture.body:
            raise CredentialRefusedError("GovInfo response echoed the API credential; capture was not retained")
        return capture

    def _require_present(self, capture: CapturedBodyResponse, *, label: str) -> CapturedBodyResponse:
        if capture.status_code in (404, 410):
            raise _unavailable(capture, label)
        return capture

    def acquire(
        self,
        package_id: str,
        *,
        prefer: Sequence[str] = BODY_PREFERENCE,
        max_bytes: int | None = None,
    ) -> GovInfoPackageBody:
        """Capture the first preferred rendition the package actually offers.

        ``prefer`` is matched in order against the renditions the package MODS
        states. It defaults to the sealed ``bodies.BODY_PREFERENCE`` -- XML
        first, PDF last -- so a package offered only as PDF still yields a
        body; the previous default, ``("xml", "htm", "txt")``, refused one
        with ``GovInfoFormatNotOfferedError``. A PDF can be large (the
        CHRG-119hhrg64242 PDF is 46.6 MB, above the evidence bound), so it is
        reached only after every text-bearing rendition and it is the one
        format a narrow ``max_bytes`` is most likely to refuse.

        ``max_bytes`` may narrow the body allowance for this call, never raise
        it. Every refusal carries its capture, the stage it failed at and this
        context.
        """
        if self._closed:
            raise ValueError("GovInfo body acquirer is closed")
        identity = parse_package_id(package_id)
        preference = _checked_preference(prefer)
        budget = replace(self.budget, max_body_bytes=narrow_byte_limit(self.budget.max_body_bytes, max_bytes))
        self._api.reset_budget()
        self._content.reset_budget()
        stage = "summary"
        chosen: str | None = None
        offered: tuple[str, ...] = ()
        capture: CapturedBodyResponse | None = None
        try:
            summary_capture = self._require_present(
                self._capture(package_summary_locator(identity), keyed=True, max_bytes=budget.max_metadata_bytes),
                label="package summary",
            )
            capture = summary_capture
            summary = validate_package_summary(
                summary_capture.body,
                package=identity,
                final_url=summary_capture.resolved_url,
                max_bytes=budget.max_metadata_bytes,
            )

            stage = "mods"
            capture = None
            mods_capture = self._require_present(
                self._capture(package_mods_locator(identity), keyed=True, max_bytes=budget.max_metadata_bytes),
                label="package MODS",
            )
            capture = mods_capture
            mods = validate_package_mods(
                mods_capture.body,
                package=identity,
                final_url=mods_capture.resolved_url,
                max_bytes=budget.max_metadata_bytes,
            )
            offered = mods.offered_formats
            chosen = next((name for name in preference if name in offered), None)
            if chosen is None:
                moved = [(name, url) for name, url in mods.moved_renditions if name in preference]
                if moved:
                    raise GovInfoRenditionAddressError(identity.package_id, moved)
                raise GovInfoFormatNotOfferedError(identity.package_id, preference, offered)

            stage = "body"
            # A body failure must never be attributed to the metadata captures.
            capture = None
            body_capture = self._body_capture(package_body_locator(identity, chosen), max_bytes=budget.max_body_bytes)
            capture = body_capture
            body = validate_package_body(
                body_capture.body,
                package=identity,
                format=chosen,
                content_type=body_capture.content_type,
                final_url=body_capture.resolved_url,
                max_bytes=budget.max_body_bytes,
            )
            return GovInfoPackageBody(
                identity=identity,
                format=chosen,
                preference=preference,
                offered_formats=offered,
                summary=summary,
                mods=mods,
                body=body,
                summary_capture=summary_capture,
                mods_capture=mods_capture,
                body_capture=body_capture,
                request_count=self.request_count,
                budget=budget,
            )
        except Exception as error:
            # A credential refusal keeps no capture: the body may echo the key.
            if capture is not None and not isinstance(error, CredentialRefusedError):
                attach_refused_response(error, refused_capture(capture, stage="source-validation"))
            error.__dict__["govinfo_body_acquisition"] = {
                "packageId": identity.package_id,
                "collection": identity.collection,
                "stage": stage,
                "preference": list(preference),
                "offeredFormats": list(offered),
                "format": chosen,
                "requestCount": self.request_count,
                "budget": asdict(budget),
            }
            raise

    def acquire_granule(
        self,
        package_id: str,
        granule_id: str,
        *,
        prefer: Sequence[str] = GRANULE_BODY_PREFERENCE,
        max_bytes: int | None = None,
    ) -> GovInfoGranuleBody:
        """Capture the first preferred rendition one granule actually offers.

        Mirrors ``acquire`` at granule scope: the granule summary proves the
        granule and its host package both exist and agree with the request --
        GovInfo's granule summary states both ``packageId`` and ``granuleId``,
        and a granule that does not belong to the requested package answers
        HTTP 400 with neither field, rather than 404 (measured 2026-09-19: a
        wrong-day granule id under CREC-2026-09-18, and that same real granule
        id requested under CREC-2026-09-17, both ``invalid granuleId``), so it
        is read as the same packageId/granuleId mismatch a genuinely absent
        granule would be, not a distinct status-code rule. The granule MODS
        then states its own accessId directly and its host package's nested
        in a ``relatedItem type="host"`` -- GovInfo's own proof of membership,
        checked before any rendition is read -- and the offered renditions,
        addressed through the granule's own locator (the package's folder,
        the granule's file stem). ``prefer`` defaults to
        ``GRANULE_BODY_PREFERENCE`` -- the daily Record's own HTML first,
        measured on CREC-2026-09-18 to be what every one of its 11 granules
        offers, its own PDF the fallback. The whole-issue package PDF stays
        reachable unchanged through ``acquire(package_id)``.

        ``max_bytes`` may narrow the body allowance for this call, never raise
        it. Every refusal carries its capture, the stage it failed at and this
        context.
        """
        if self._closed:
            raise ValueError("GovInfo body acquirer is closed")
        identity = parse_granule_identity(package_id, granule_id)
        preference = _checked_preference(prefer)
        budget = replace(self.budget, max_body_bytes=narrow_byte_limit(self.budget.max_body_bytes, max_bytes))
        self._api.reset_budget()
        self._content.reset_budget()
        stage = "summary"
        chosen: str | None = None
        offered: tuple[str, ...] = ()
        capture: CapturedBodyResponse | None = None
        label = f"{identity.package.package_id}/{identity.granule_id}"
        try:
            summary_capture = self._granule_metadata_capture(
                granule_summary_locator(identity.package, identity.granule_id),
                max_bytes=budget.max_metadata_bytes,
                label="granule summary",
            )
            capture = summary_capture
            summary = validate_granule_summary(
                summary_capture.body,
                package=identity.package,
                granule_id=identity.granule_id,
                final_url=summary_capture.resolved_url,
                max_bytes=budget.max_metadata_bytes,
            )

            stage = "mods"
            capture = None
            mods_capture = self._granule_metadata_capture(
                granule_mods_locator(identity.package, identity.granule_id),
                max_bytes=budget.max_metadata_bytes,
                label="granule MODS",
            )
            capture = mods_capture
            mods = validate_granule_mods(
                mods_capture.body,
                package=identity.package,
                granule_id=identity.granule_id,
                final_url=mods_capture.resolved_url,
                max_bytes=budget.max_metadata_bytes,
            )
            offered = mods.offered_formats
            chosen = next((name for name in preference if name in offered), None)
            if chosen is None:
                moved = [(name, url) for name, url in mods.moved_renditions if name in preference]
                if moved:
                    raise GovInfoRenditionAddressError(label, moved)
                raise GovInfoFormatNotOfferedError(label, preference, offered)

            stage = "body"
            # A body failure must never be attributed to the metadata captures.
            capture = None
            body_capture = self._body_capture(
                granule_body_locator(identity.package, identity.granule_id, chosen),
                max_bytes=budget.max_body_bytes,
                label="granule body rendition",
            )
            capture = body_capture
            body = validate_granule_body(
                body_capture.body,
                package=identity.package,
                granule_id=identity.granule_id,
                format=chosen,
                content_type=body_capture.content_type,
                final_url=body_capture.resolved_url,
                max_bytes=budget.max_body_bytes,
            )
            return GovInfoGranuleBody(
                identity=identity,
                format=chosen,
                preference=preference,
                offered_formats=offered,
                summary=summary,
                mods=mods,
                body=body,
                summary_capture=summary_capture,
                mods_capture=mods_capture,
                body_capture=body_capture,
                request_count=self.request_count,
                budget=budget,
            )
        except Exception as error:
            # A credential refusal keeps no capture: the body may echo the key.
            if capture is not None and not isinstance(error, CredentialRefusedError):
                attach_refused_response(error, refused_capture(capture, stage="source-validation"))
            error.__dict__["govinfo_granule_acquisition"] = {
                "packageId": identity.package.package_id,
                "granuleId": identity.granule_id,
                "collection": identity.package.collection,
                "stage": stage,
                "preference": list(preference),
                "offeredFormats": list(offered),
                "format": chosen,
                "requestCount": self.request_count,
                "budget": asdict(budget),
            }
            raise

    def _granule_metadata_capture(self, url: str, *, max_bytes: int, label: str) -> CapturedBodyResponse:
        """Capture a granule summary or MODS request, typing a package/granule mismatch as unavailable.

        GovInfo answers HTTP 400, not 404, when the requested granule does not
        belong to the requested package (measured 2026-09-19: a wrong-day
        granule id under CREC-2026-09-18, and that same real granule id
        requested under CREC-2026-09-17, both ``invalid granuleId``). This
        reads that the same way ``_require_present`` reads a package's own
        404/410: identity proved before bytes, typed the same way either
        route states it.
        """
        try:
            capture = self._capture(url, keyed=True, max_bytes=max_bytes)
        except GovInfoBodySourceError as error:
            refused = attached_capture(error)
            if refused is not None and refused.status_code == 400:
                raise _unavailable(refused, label) from error
            raise
        return self._require_present(capture, label=label)

    def _body_capture(self, url: str, *, max_bytes: int, label: str = "body rendition") -> CapturedBodyResponse:
        """Capture the keyless rendition, reading a redirect as the object's absence."""
        try:
            capture = self._capture(url, keyed=False, max_bytes=max_bytes)
        except GovInfoBodySourceError as error:
            refused = attached_capture(error)
            if refused is not None and refused.status_code in _REDIRECT_STATUSES:
                raise _unavailable(refused, label) from error
            raise
        return self._require_present(capture, label=label)


__all__ = [
    "GovInfoBodyAcquirer",
    "GovInfoBodyBudget",
    "GovInfoFormatNotOfferedError",
    "GovInfoGranuleBody",
    "GovInfoPackageBody",
    "GovInfoPackageUnavailableError",
    "GovInfoRenditionAddressError",
]
