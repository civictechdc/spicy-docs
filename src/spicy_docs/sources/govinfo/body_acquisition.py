"""Acquire one GovInfo package or granule body: keyed summary, keyed MODS, then the keyless rendition.

Three sequential requests under one budget: the summary proves the package
exists and is the one asked for (the only route that answers 404 for a missing
package, since the MODS route answers 400 and the keyless body routes redirect
to an error page that answers 200), and the MODS then states which renditions
the package offers, so the caller's preference is matched against the
publisher's own statement and the body request is made only for a format the
publisher named. Identity is proved before the body is fetched, which keeps a
mistaken request from spending tens of megabytes; ``acquire_granule`` follows
the same shape, except a granule that does not belong to the requested package
answers HTTP 400 rather than 404, and ``acquire_parts`` fetches one body per
part a report's record states. Two clients draw on the same budget: the keyed
one retains no refusal body, since an api.data.gov error can echo the
credential, while the keyless one keeps its 401/403 answer.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Self

from spicy_docs.reading.json_input import load_decimal_json
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
    ReportPart,
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
    both clients; ``acquire_parts`` needs ``2 + P`` for a report of ``P`` parts,
    so a caller sizes it per part. The timeout bounds transport waits, not
    total elapsed time. A zero start interval explicitly disables pacing; a
    nonzero one meters each client separately, so the keyed API host and the
    keyless content host are paced apart, as they are answered apart.
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
    """Exact bytes for one package rendition with every capture that proved it.

    ``part`` is the part of the package the bytes are, as the record states
    it, or ``None`` for a collection whose records state no parts.
    """

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
    part: ReportPart | None = None

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


class GovInfoPartsOverBudgetError(GovInfoBodySourceError):
    """The record states more parts than the request budget can fetch; no body request was made.

    Not transient: the same record refuses under the same budget on every run,
    so the caller grows ``max_requests`` rather than retrying.
    """

    def __init__(self, label: str, *, parts: int, max_requests: int) -> None:
        super().__init__(
            f"{label} states {parts} parts, which need {2 + parts} requests; the request budget allows {max_requests}"
        )
        self.required_requests = 2 + parts
        self.max_requests = max_requests


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


def _is_invalid_granule_body(body: bytes) -> bool:
    """Whether a granule-route 400 body matches the one documented shape.

    Measured 2026-09-19, two ways (fixture README): GovInfo answers exactly
    ``{"message":"invalid granuleId"}`` for a granule that does not belong to
    the requested package. Any other 400 -- a shape this module has not
    measured, a different publisher message, a transient answer -- is not
    this, and is left as the generic ``GovInfoBodySourceError`` the capture
    layer already raises, with its capture, rather than silently relabeled
    unavailable on the strength of a status code alone.
    """
    try:
        document = load_decimal_json(body, source="GovInfo granule 400 body", error_type=ValueError)
    except ValueError:
        return False
    return isinstance(document, dict) and document.get("message") == "invalid granuleId"


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
        states; it defaults to the sealed ``bodies.BODY_PREFERENCE`` -- XML
        first, PDF last -- so a package offered only as PDF still yields a body,
        where the previous default ``("xml", "htm", "txt")`` refused one. A PDF
        can be large (the CHRG-119hhrg64242 PDF is 46.6 MB, above the evidence
        bound), so it is reached only after every text-bearing rendition and is
        the format a narrow ``max_bytes`` is most likely to refuse.

        A one-part report whose MODS states its part in place of the package
        stem (``mods.part_id``) is read at that part's stem, the only address
        its record names. The result's ``part`` names the part the bytes are.
        A record listing several parts is read at its root only where the root
        restates a part's renditions -- CRPT-119hrpt494's Part 1, at the
        package stem, with ``mods.parts`` listing the rest; CRPT-119hrpt455's
        root states none, so it is refused as offering no format.
        ``acquire_parts`` reads every part.

        ``max_bytes`` may narrow the body allowance for this call, never raise
        it. Every refusal carries its capture, the stage it failed at and this
        context.
        """
        (body,) = self._acquire(package_id, prefer=prefer, max_bytes=max_bytes, every_part=False)
        return body

    def acquire_parts(
        self,
        package_id: str,
        *,
        prefer: Sequence[str] = BODY_PREFERENCE,
        max_bytes: int | None = None,
    ) -> tuple[GovInfoPackageBody, ...]:
        """Capture every part the package record states, each at its own stem, or refuse the package.

        One summary and one MODS, then one body per part in ``mods.parts``
        order, each the first preferred rendition that part offers: ``2 + P``
        requests from the one budget. A record stating more parts than the
        budget can fetch is refused before any body request
        (``GovInfoPartsOverBudgetError``). A report published in one part is one
        body, exactly what ``acquire`` returns. A format is chosen for every
        part before any body is requested, and any refusal refuses the whole
        package: a host replaces a package's part rows as a set, so half a
        report is never a result. ``max_bytes`` narrows each body's allowance.
        """
        return self._acquire(package_id, prefer=prefer, max_bytes=max_bytes, every_part=True)

    def _acquire(
        self,
        package_id: str,
        *,
        prefer: Sequence[str],
        max_bytes: int | None,
        every_part: bool,
    ) -> tuple[GovInfoPackageBody, ...]:
        """Summary, MODS, then a body for the root's part or for every part; refusals carry this context."""
        if self._closed:
            raise ValueError("GovInfo body acquirer is closed")
        identity = parse_package_id(package_id)
        preference = _checked_preference(prefer)
        budget = replace(self.budget, max_body_bytes=narrow_byte_limit(self.budget.max_body_bytes, max_bytes))
        self._api.reset_budget()
        self._content.reset_budget()
        stage = "summary"
        part_id: str | None = None
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
            if every_part:
                if not mods.parts:
                    raise GovInfoBodySourceError(f"GovInfo {identity.collection} records state no parts to acquire")
                if 2 + len(mods.parts) > budget.max_requests:
                    raise GovInfoPartsOverBudgetError(
                        identity.package_id, parts=len(mods.parts), max_requests=budget.max_requests
                    )
                targets = [(part, part.offered_formats, part.moved_renditions) for part in mods.parts]
            else:
                # The root's renditions were proved at the stem of the part its record states there.
                stem = mods.part_id or identity.package_id
                root = next((part for part in mods.parts if part.part_id == stem), None)
                targets = [(root, mods.offered_formats, mods.moved_renditions)]
            choices = []
            for part, offered, moved_renditions in targets:
                part_id = None if part is None else part.part_id
                label = part_id if every_part else identity.package_id
                chosen = next((name for name in preference if name in offered), None)
                if chosen is None:
                    moved = [(name, url) for name, url in moved_renditions if name in preference]
                    if moved:
                        raise GovInfoRenditionAddressError(label, moved)
                    raise GovInfoFormatNotOfferedError(label, preference, offered)
                choices.append((part_id, offered, chosen, part))

            stage = "body"
            fetched = []
            for part_id, offered, chosen, part in choices:
                # A body failure must never be attributed to the metadata captures.
                capture = None
                body_capture = self._body_capture(
                    package_body_locator(identity, chosen, part_id=part_id), max_bytes=budget.max_body_bytes
                )
                capture = body_capture
                body = validate_package_body(
                    body_capture.body,
                    package=identity,
                    format=chosen,
                    content_type=body_capture.content_type,
                    final_url=body_capture.resolved_url,
                    max_bytes=budget.max_body_bytes,
                    part_id=part_id,
                )
                fetched.append((offered, chosen, part, body, body_capture))
            return tuple(
                GovInfoPackageBody(
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
                    part=part,
                )
                for offered, chosen, part, body, body_capture in fetched
            )
        except Exception as error:
            # A credential refusal keeps no capture: the body may echo the key.
            if capture is not None and not isinstance(error, CredentialRefusedError):
                attach_refused_response(error, refused_capture(capture, stage="source-validation"))
            error.__dict__["govinfo_body_acquisition"] = {
                "packageId": identity.package_id,
                "collection": identity.collection,
                "stage": stage,
                "partId": part_id,
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
        GovInfo's granule summary states both ``packageId`` and ``granuleId`` --
        and the granule MODS states its own accessId directly and its host
        package's nested in a ``relatedItem type="host"``, GovInfo's own proof
        of membership, checked before any rendition is read. A granule that does
        not belong to the requested package answers HTTP 400 with
        ``invalid granuleId``, not 404, so it is read as the same
        packageId/granuleId mismatch an absent granule would be. ``prefer``
        defaults to ``GRANULE_BODY_PREFERENCE`` -- the daily Record's own HTML
        first, its own PDF the fallback -- and the whole-issue package PDF stays
        reachable through ``acquire(package_id)``.

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
        belong to the requested package, so that route is read the way
        ``_require_present`` reads a package's 404/410 -- identity proved
        before bytes -- but only where the body matches the one measured
        ``invalid granuleId`` shape. A 400 for any other reason is not this,
        and stays the generic ``GovInfoBodySourceError`` the capture layer
        raised, with its capture, rather than being relabeled on the status
        code alone.
        """
        try:
            capture = self._capture(url, keyed=True, max_bytes=max_bytes)
        except GovInfoBodySourceError as error:
            refused = attached_capture(error)
            if refused is not None and refused.status_code == 400 and _is_invalid_granule_body(refused.body):
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
    "GovInfoPartsOverBudgetError",
    "GovInfoRenditionAddressError",
]
