"""Reader connector for the Mirrulations S3 mirror of regulations.gov.

Wraps the existing S3 discovery + download functions so that one agency's files
for a single :class:`~spicy_docs.schemas.RecordType` are exposed through the
:class:`~spicy_docs.sources.base.Reader` interface. Listing, year-filtering, and
dedup against already-processed keys are delegated to ``list_json_files``;
per-file download + JSON decode is delegated to ``download_and_parse``.

The reader is a *pure source*: it yields the raw JSON payloads. Flattening them
into schema-shaped records is the job of the
:class:`~spicy_regs.transforms.extract.ExtractRecords` transform, which stays
in spicy-regs.

Recovery follows the package's fetcher rules (``AGENTS.md``):

1. A 401/403 while listing agency objects or fetching one aborts the run as
   ``MirrulationsAccessRefusedError``.
   It is never recorded as a key that merely failed.
2. Every key that produced no record -- transport answer, unreadable bytes, or a
   2xx whose body held no record -- stays out of ``last_keys`` and is retried on
   the next run, with its last answer retained as a :class:`KeyOutcome`.
3. An empty or mis-shaped 2xx, including an object without record identity, is
   ``requested-empty``: what the mirror answered, never proof of absence.
4. Reasons are scrubbed before they are truncated, logged, or retained.
"""

import random
import re
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Sized
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import chain
from json import loads
from threading import Lock
from typing import Any, Final

import boto3
from botocore import UNSIGNED
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from loguru import logger
from tqdm import tqdm

from spicy_docs.schemas import RecordType
from spicy_docs.sources.base import Reader
from spicy_docs.transport.credentials import (
    ACCESS_REFUSED_STATUSES,
    CredentialRefusedError,
    refusal_message,
    scrub_credential,
)

# Connection details for the public Mirrulations mirror live with the source
# that uses them, not in the pipeline.
BUCKET = "mirrulations"
PREFIX = "raw-data"

# Downloads are tiny JSON GETs against S3 — I/O-bound, so a pool of threads per
# agency turns thousands of serial round-trips into concurrent ones. The single
# anonymous resource is shared across the pool: unsigned read-only GetObject has
# no credential-refresh race, and botocore's connection pool is thread-safe.
DEFAULT_DOWNLOAD_WORKERS = 16

# Emit a download-progress line every this many files, so a large agency's
# multi-hour download reports how far along it is (small agencies finish before
# the first mark and just log their staged total).
_PROGRESS_EVERY = 25_000


def s3_resource(max_pool_connections: int = DEFAULT_DOWNLOAD_WORKERS) -> Any:
    """A fresh anonymous S3 resource (one per worker keeps threads independent).

    The connection pool is sized to the download concurrency: botocore defaults
    to 10, but the reader fans GETs across ``DEFAULT_DOWNLOAD_WORKERS`` threads.
    A pool smaller than the thread count oversubscribes — connections churn into
    CLOSE_WAIT and the run stalls — so the pool must be at least the worker count.
    """
    return boto3.resource(
        "s3",
        region_name="us-east-1",
        config=BotoConfig(
            signature_version=UNSIGNED,
            max_pool_connections=max_pool_connections,
            # Bound every S3 op so a stalled connection fails fast and retries
            # instead of wedging a worker indefinitely; standard mode retries
            # transient errors (throttling, resets) rather than dropping records.
            connect_timeout=30,
            # Allow a default 16 MiB object roughly 120s at ~136 KB/s on a busy link.
            # _retry_transient adds per-key retries after botocore's attempts exhaust.
            read_timeout=120,
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def s3_client() -> Any:
    """Anonymous S3 client (used only for agency discovery)."""
    return boto3.client("s3", region_name="us-east-1", config=BotoConfig(signature_version=UNSIGNED))


def get_agencies(s3_client: Any, bucket_name: str, prefix: str) -> list[str]:
    """Get the list of all agencies from the S3 bucket.

    Uses the S3 client directly with ``Delimiter='/'`` to efficiently list
    only top-level folder names without iterating all objects.
    """
    response = s3_client.list_objects_v2(
        Bucket=bucket_name,
        Prefix=f"{prefix}/",
        Delimiter="/",
    )
    agencies = []
    for p in response.get("CommonPrefixes", []):
        agency = p["Prefix"].split("/")[1]
        if agency:
            agencies.append(agency)
    return sorted(agencies)


def _iter_objects(bucket: Any, prefix: str) -> Iterator[Any]:
    """List objects with refusal handling across lazy pagination."""
    try:
        yield from bucket.objects.filter(Prefix=prefix)
    except ClientError as error:
        _raise_if_access_refused(error, prefix)
        raise


def iter_json_files(
    s3_resource: Any,
    bucket_name: str,
    prefix: str,
    agency: str,
    data_type: str,
    path_pattern: str,
    processed_keys: Any = None,
    verbose: bool = False,
    since_year: int | None = None,
) -> Iterator[str]:
    """Stream matching agency keys without retaining the whole listing."""
    # Match year from docket ID in path: raw-data/{agency}/{agency}-{YYYY}-...
    year_pattern = re.compile(rf"{re.escape(prefix)}/{re.escape(agency)}/{re.escape(agency)}-(\d{{4}})-")

    matched = 0
    skipped = 0
    filtered_by_year = 0
    total_scanned = 0
    bucket = s3_resource.Bucket(bucket_name)

    for obj in _iter_objects(bucket, f"{prefix}/{agency}/"):
        key = obj.key
        if "/text-" in key and path_pattern in key and key.endswith(".json"):
            total_scanned += 1
            if since_year:
                m = year_pattern.search(key)
                if m and int(m.group(1)) < since_year:
                    filtered_by_year += 1
                    continue
            if processed_keys and key in processed_keys:
                skipped += 1
                continue
            matched += 1
            yield key

    if verbose:
        year_msg = f", filtered_by_year {filtered_by_year}" if since_year else ""
        tqdm.write(f"    [{agency}] {data_type}: scanned {total_scanned}, skipped {skipped}{year_msg}, new {matched}")


def list_json_files(
    s3_resource: Any,
    bucket_name: str,
    prefix: str,
    agency: str,
    data_type: str,
    path_pattern: str,
    processed_keys: Any = None,
    verbose: bool = False,
    since_year: int | None = None,
) -> list[str]:
    """Materialize matching keys for callers that need a reusable manifest list."""

    return list(
        iter_json_files(
            s3_resource,
            bucket_name,
            prefix,
            agency,
            data_type,
            path_pattern,
            processed_keys,
            verbose,
            since_year,
        )
    )


def list_agency_files_by_type(
    s3_resource: Any,
    bucket_name: str,
    prefix: str,
    agency: str,
    record_types: list[RecordType],
    processed_keys: Any = None,
    verbose: bool = False,
    since_year: int | None = None,
) -> dict[str, list[str]]:
    """List one agency's JSON files in a single pass, bucketed by record type.

    The Mirrulations layout nests every record type under the same agency
    prefix, so calling :func:`list_json_files` once per type re-scans the whole
    (potentially millions of objects) prefix N times. This scans it once and
    classifies each key by which record type's ``path_pattern`` it contains —
    the patterns (``/docket/``, ``/documents/``, ``/comments/``) are mutually
    exclusive, so each key maps to at most one type.
    """
    year_pattern = re.compile(rf"{re.escape(prefix)}/{re.escape(agency)}/{re.escape(agency)}-(\d{{4}})-")
    patterns = [(rt.name, rt.path_pattern) for rt in record_types if rt.path_pattern]
    result: dict[str, list[str]] = {rt.name: [] for rt in record_types}

    bucket = s3_resource.Bucket(bucket_name)
    for obj in _iter_objects(bucket, f"{prefix}/{agency}/"):
        key = obj.key
        if "/text-" not in key or not key.endswith(".json"):
            continue
        matched = next((name for name, pattern in patterns if pattern in key), None)
        if matched is None:
            continue
        if since_year:
            m = year_pattern.search(key)
            if m and int(m.group(1)) < since_year:
                continue
        if processed_keys and key in processed_keys:
            continue
        result[matched].append(key)

    if verbose:
        summary = ", ".join(f"{name} {len(keys)}" for name, keys in result.items())
        tqdm.write(f"    [{agency}] single-scan listing: {summary}")

    return result


class MirrulationsAccessRefusedError(CredentialRefusedError):
    """The mirror refused the request with 401/403; the run ends here.

    A ``CredentialRefusedError`` subclass on purpose. The mirror is read
    anonymously, so this is the bucket refusing access rather than a key being
    rejected -- but a refusal still ends the operation, so every caller that
    already aborts on one keeps aborting. It is deliberately *not* an
    :class:`UnresolvedKeyError`: recorded as a key that failed, a refusal over a
    whole prefix would read downstream as those objects being absent.
    """


#: ``KeyOutcome.status`` values. A run's unresolved keys are all retried, so the
#: status is not a retry switch -- it names what the mirror last answered, which
#: a repeated ``requested-empty`` (a mirror that holds an empty object) and a
#: repeated ``transport`` (an outage) mean very differently to an operator.
STATUS_TRANSPORT: Final = "transport"
STATUS_UNREADABLE: Final = "unreadable"
STATUS_REQUESTED_EMPTY: Final = "requested-empty"


class UnresolvedKeyError(Exception):
    """One key that produced no record, carrying the status its observation records.

    Every subclass leaves the key out of ``last_keys``, so the next run retries
    it. Nothing here is ever "processed": a malformed object that is later
    repaired upstream, or a parser that is later fixed, must be able to come
    back, and a key recorded as done never can.
    """

    status: str = STATUS_TRANSPORT

    def __init__(self, key: str, detail: str = "") -> None:
        super().__init__(f"{key}: {detail}" if detail else key)
        self.key = key
        self.detail = detail


class TransientDownloadError(UnresolvedKeyError):
    """S3 GET/read failed (network, throttle, 5xx, or a vanished object).

    The body was never (fully) read, so the key may well succeed on a later
    attempt. It is the one class worth an immediate in-run retry.
    """


class PayloadParseError(UnresolvedKeyError):
    """Body downloaded but JSON decode / extract failed — the bytes are not a record.

    The bytes came off S3 fine; they just don't parse, so re-fetching now would
    only return the same ones and this is not retried within the run. It is
    still retried on the *next* run: the object or the parser may have changed
    in between, and that is the only way a repair can land.
    """

    status = STATUS_UNREADABLE


class EmptyPayloadError(PayloadParseError):
    """A 2xx that carried no record: empty bytes, unexpected JSON, or missing identity.

    A subclass because the handling is identical -- the bytes arrived, the
    record did not -- while the status separates "the mirror answered with
    nothing" from "the bytes are not JSON at all". Recorded as an observation of
    that answer, with the shape named, and never as the object being absent.
    """

    status = STATUS_REQUESTED_EMPTY


@dataclass(frozen=True, slots=True)
class DownloadedObject:
    """Exact bytes and source metadata returned by one anonymous S3 GET."""

    content: bytes
    etag: str | None
    version_id: str | None
    last_modified: datetime | None
    content_length: int | None


@dataclass(frozen=True, slots=True)
class MirrulationsSourceObject:
    """One exact listed object, pinned through its source-issued metadata."""

    key: str
    etag: str
    version_id: str | None
    content: bytes


def download_object_bytes(
    s3_resource: Any,
    bucket_name: str,
    key: str,
    *,
    if_match: str | None = None,
    max_bytes: int | None = None,
) -> DownloadedObject:
    """Read one S3 object exactly, optionally pinned to its listed ETag.

    ``IfMatch`` closes the gap between an immutable draw and a later fetch: if
    the mirror replaces an object after listing, S3 refuses the GET instead of
    handing the caller different bytes under the old key.  The response body
    is closed on every path so concurrent batch readers return connections to
    botocore's pool promptly.

    A GET's 401/403 becomes :class:`MirrulationsAccessRefusedError` here, using
    the same refusal check as agency-object listings.
    """

    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max_bytes must be greater than zero")
    obj = s3_resource.Object(bucket_name, key)
    try:
        response = obj.get(**({"IfMatch": if_match} if if_match is not None else {}))
    except ClientError as error:
        _raise_if_access_refused(error, key)
        raise
    content_length = response.get("ContentLength")
    if max_bytes is not None and content_length is not None and content_length > max_bytes:
        raise ValueError(f"{key} exceeds the {max_bytes} byte cap")
    body = response["Body"]
    try:
        content = body.read(max_bytes + 1) if max_bytes is not None else body.read()
    finally:
        body.close()
    if max_bytes is not None and len(content) > max_bytes:
        raise ValueError(f"{key} exceeds the {max_bytes} byte cap")
    if content_length is not None and content_length != len(content):
        raise ValueError(f"{key} returned {len(content)} bytes but declared {content_length}")
    etag = response.get("ETag")
    if if_match is not None and etag != if_match:
        raise ValueError(f"{key} returned ETag {etag!r}, expected {if_match!r}")
    return DownloadedObject(
        content=content,
        etag=etag,
        version_id=response.get("VersionId"),
        last_modified=response.get("LastModified"),
        content_length=content_length,
    )


# Retry temporary S3 congestion after botocore's own retries are exhausted.
# Fourteen attempts allow 13 jittered sleeps, capped at 60s each (~542s total).
# Changed objects and incomplete evidence still fail immediately.
_MAX_TRANSIENT_ATTEMPTS = 14
_TRANSIENT_BACKOFF_CEILING_SECONDS = 60.0


def _response_status(exc: BaseException) -> int | None:
    """The HTTP status a botocore error carries, if it carries one."""
    if isinstance(exc, ClientError):
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        return status if isinstance(status, int) else None
    return None


def _raise_if_access_refused(error: ClientError, subject: str) -> None:
    """Raise the typed refusal for a GET or agency-object listing."""
    status = _response_status(error)
    if status in ACCESS_REFUSED_STATUSES:
        raise MirrulationsAccessRefusedError(refusal_message("the Mirrulations mirror", status, subject)) from error


def _is_transient_transport_error(exc: BaseException) -> bool:
    """Retry connection/HTTP-client failures and responses with status 429 or 5xx.

    Other failures abort: 404, IfMatch 412, missing or changed ETags, size
    mismatches, incomplete bodies, and PayloadParseError. Retrying those cannot
    establish faithful complete-snapshot evidence. A 401/403 never reaches here
    as a ``ClientError``; ``download_object_bytes`` has already turned it into
    the refusal that ends the run.
    """
    if isinstance(exc, (BotoConnectionError, HTTPClientError)):
        return True
    status = _response_status(exc)
    return status == 429 or (status is not None and status >= 500)


def _retry_transient[DownloadResult](key: str, operation: Callable[[], DownloadResult]) -> DownloadResult:
    """Retry transient transport failures with capped exponential backoff and full jitter.

    A uniform delay from zero to the ceiling separates concurrent workers' retries.
    Log each retry with its key, attempt, delay, and exception. Non-transient errors
    and exhausted retries propagate as the original exception.
    """
    for attempt in range(1, _MAX_TRANSIENT_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:
            if not _is_transient_transport_error(exc) or attempt == _MAX_TRANSIENT_ATTEMPTS:
                raise
            ceiling = min(2**attempt, _TRANSIENT_BACKOFF_CEILING_SECONDS)
            delay = random.uniform(0.0, ceiling)
            logger.warning(
                "{}: retry {}/{} in {:.1f}s (cap {:.0f}s) after {}",
                key,
                attempt,
                _MAX_TRANSIENT_ATTEMPTS - 1,
                delay,
                ceiling,
                _reason(exc),
            )
            time.sleep(delay)
    raise AssertionError("unreachable")


#: Enough of an answer to act on, short enough that a receipt can print it whole.
_REASON_CHARACTERS = 300


def _reason(exc: BaseException) -> str:
    """One line naming the answer, scrubbed *then* truncated.

    Never the other way round: truncating first can cut a credential in half and
    leave the front of it standing (``transport.credentials.scrub_credential``).
    A botocore message can render the endpoint URL, so this runs even though the
    mirror itself is read anonymously.
    """
    cause = exc.__cause__
    if cause is not None:
        text = f"{type(cause).__name__}: {cause}"
    elif isinstance(exc, UnresolvedKeyError) and exc.detail:
        text = exc.detail
    else:
        text = f"{type(exc).__name__}: {exc}"
    return scrub_credential(text)[:_REASON_CHARACTERS]


@dataclass(frozen=True, slots=True)
class KeyOutcome:
    """What one unresolved key last answered, retained so the next run can retry it.

    An explicit observation, not a verdict: ``status`` names the class of answer,
    ``reason`` the scrubbed detail, and ``attempted_at`` when it was asked.
    ``attempts`` counts reader download attempts, including in-run retries and
    supplied prior outcomes, but excluding botocore's internal retries. None of
    them mark the key processed.
    """

    key: str
    status: str
    reason: str
    attempted_at: str
    attempts: int = 1


def _describe_shape(payload: object) -> str:
    """Name what arrived instead of a record, for a requested-empty observation."""
    if payload is None:
        return "null"
    if isinstance(payload, dict):
        if "errors" in payload:
            return "a publisher error envelope"
        if "data" in payload:
            return f"a data envelope containing {_describe_shape(payload['data'])}"
        return "a populated object" if payload else "an empty object"
    if isinstance(payload, list):
        return f"an array of {len(payload)} items"
    return f"a bare {type(payload).__name__}"


def download_and_parse(
    s3_resource: Any,
    bucket_name: str,
    key: str,
    extract_fn: Callable[[dict], dict],
    *,
    record_type: RecordType | None = None,
) -> dict:
    """Download and extract one S3 JSON object.

    GET/read failures become TransientDownloadError; unparseable bytes become
    PayloadParseError; a 2xx that decodes to no record becomes EmptyPayloadError.
    All three preserve the key and the original exception, and all three leave
    the key unresolved. A 401/403 is none of them: it propagates as the refusal
    that ends the run. The download helper closes the response on every path to
    prevent connection-pool exhaustion.

    Identity is the line between a record and an answer that must remain
    unresolved: accepting an identity-free object lets callers manifest a key
    and write a null-id row. All supported Mirrulations types (dockets,
    documents, comments) define their identity from ``data.id``. Require that
    nonblank string only; other fields and unknown fields stay untouched for
    the caller. ``record_type`` names its declared key in the reason; direct
    download callers use the same source identity check without a type label.
    """
    try:
        content = download_object_bytes(s3_resource, bucket_name, key).content
    except CredentialRefusedError:
        raise
    except Exception as exc:
        raise TransientDownloadError(key) from exc
    if not content:
        raise EmptyPayloadError(key, "the mirror answered with zero bytes")
    try:
        payload = loads(content)
    except Exception as exc:
        raise PayloadParseError(key) from exc
    if not isinstance(payload, dict) or not payload:
        raise EmptyPayloadError(key, f"the body decoded to {_describe_shape(payload)}, not a record")
    data = payload.get("data")
    identity = data.get("id") if isinstance(data, dict) else None
    missing_identity = not isinstance(identity, str) or not identity.strip()
    if missing_identity or "errors" in payload:
        expected = f" for {record_type.name} ({record_type.dedup_key})" if record_type is not None else ""
        detail = f"the body decoded to {_describe_shape(payload)}"
        if missing_identity:
            detail += f"; missing nonblank data.id identity{expected}"
        if "errors" in payload:
            # The publisher's own message is useful evidence. Scrub the entire
            # value before truncation, including exceptions raised to direct callers.
            detail += f"; publisher errors: {payload['errors']}"
        raise EmptyPayloadError(key, scrub_credential(detail)[:_REASON_CHARACTERS])
    try:
        return extract_fn(payload)
    except Exception as exc:
        raise PayloadParseError(key) from exc


def discover_agencies() -> list[str]:
    """List every agency present in the mirror."""
    return get_agencies(s3_client(), BUCKET, PREFIX)


def _identity(payload: dict) -> dict:
    """Decode-only 'extract' — the reader yields raw JSON; flattening is a Transform."""
    return payload


def _record_outcome(
    exc: UnresolvedKeyError, key: str, label: str, outcomes: list[KeyOutcome] | None, attempts: int
) -> None:
    """Log one unresolved key and, when collecting, retain its observation.

    Every class is surfaced at ``warning`` and every class is retried next run,
    so the log says so plainly. The exception carries its own key, but ``key`` is
    passed explicitly so the caller stays authoritative.
    """
    reason = _reason(exc)
    logger.warning(
        "{}{} ({}), unresolved and retried next run: {}", f"{label}: " if label else "", reason, exc.status, key
    )
    if outcomes is not None:
        outcomes.append(
            KeyOutcome(
                key=key,
                status=exc.status,
                reason=reason,
                attempted_at=datetime.now(UTC).isoformat(timespec="seconds"),
                attempts=attempts,
            )
        )


def download_keys(
    s3_resource: Any,
    bucket_name: str,
    keys: Iterable[str],
    workers: int = DEFAULT_DOWNLOAD_WORKERS,
    *,
    record_type: RecordType | None = None,
    label: str = "",
    outcomes: list[KeyOutcome] | None = None,
    prior_outcomes: Iterable[KeyOutcome] = (),
    raise_failures: bool = False,
    transient_retries: int = 0,
) -> Iterator[dict]:
    """Concurrently download + parse the given keys, yielding raw payloads.

    The shared download engine for both :class:`MirrulationsReader` and the
    chunked ingest path. It accepts a key stream and keeps at most twice the
    worker count in flight. Order is not preserved; dedup happens later by key.

    When ``outcomes`` is provided, every key that produced no record appends its
    :class:`KeyOutcome` there instead of being silently dropped, so the caller
    can keep all of them out of the manifest. ``outcomes=None`` keeps the
    drop-and-continue behavior for callers that don't track keys. ``raise_failures``
    governs those answers only: a 401/403 propagates either way.
    ``prior_outcomes`` carries attempt counts forward when retrying keys.
    """
    if transient_retries < 0:
        raise ValueError("transient_retries cannot be negative")

    prior_attempts = {outcome.key: outcome.attempts for outcome in prior_outcomes}

    def download(key: str) -> dict | None:
        for attempt in range(transient_retries + 1):
            try:
                return download_and_parse(s3_resource, bucket_name, key, _identity, record_type=record_type)
            except UnresolvedKeyError as exc:
                if isinstance(exc, TransientDownloadError) and attempt < transient_retries:
                    continue
                _record_outcome(exc, key, label, outcomes, prior_attempts.get(key, 0) + attempt + 1)
                if raise_failures:
                    raise
                return None
        raise AssertionError("unreachable")

    total = len(keys) if isinstance(keys, Sized) else None
    n = max(1, min(workers, total)) if total is not None and total else max(1, workers)
    if n <= 1:
        for key in keys:
            payload = download(key)
            if payload is not None:
                yield payload
        return

    done = 0
    with ThreadPoolExecutor(max_workers=n) as executor:
        iterator = iter(keys)
        submitted: dict[Future[dict | None], str] = {}
        exhausted = False
        while submitted or not exhausted:
            while not exhausted and len(submitted) < 2 * n:
                try:
                    key = next(iterator)
                except StopIteration:
                    exhausted = True
                    break
                future = executor.submit(download, key)
                submitted[future] = key
            if not submitted:
                break
            completed, _pending = wait(submitted, return_when=FIRST_COMPLETED)
            for future in completed:
                submitted.pop(future)
                done += 1
                if label and done % _PROGRESS_EVERY == 0:
                    logger.info(
                        "{}: downloaded {}{}",
                        label,
                        done,
                        f"/{total}" if total is not None else "",
                    )
                payload = future.result()
                if payload is not None:
                    yield payload


_EXHAUSTED = object()


def _bounded_ordered_results(
    executor: ThreadPoolExecutor,
    items: Iterator[Any],
    work: Callable[[Any], Any],
    window: int,
) -> Iterator[tuple[Any, Any]]:
    """Yield (item, result) in listing order with at most window futures in flight.

    The first listed failure aborts, regardless of completion order. Stop submitting
    as soon as any pending failure is observed. Failure or early close cancels
    unstarted work; running work drains under its timeouts during executor shutdown.
    """
    pending: deque[tuple[Any, Future[Any]]] = deque()

    def failure_observed() -> bool:
        # Bounded by ``window`` futures, so this stays a constant-factor scan.
        return any(future.done() and future.exception() is not None for _item, future in pending)

    def fill() -> None:
        while len(pending) < window and not failure_observed():
            item = next(items, _EXHAUSTED)
            if item is _EXHAUSTED:
                return
            pending.append((item, executor.submit(work, item)))

    try:
        fill()
        while pending:
            item, future = pending.popleft()
            result = future.result()
            fill()
            yield item, result
    finally:
        for _item, future in pending:
            future.cancel()
        pending.clear()


class MirrulationsReader(Reader):
    """Reads one agency's records of a single record type from Mirrulations S3.

    Yields the raw JSON payload for each file. After a complete ``iter_records``
    pass, ``last_keys`` holds only the keys that produced a record -- the caller
    may manifest exactly those -- while ``failed_keys`` and the richer
    ``unresolved`` observations hold every key that did not, for the next run to
    retry. ``unresolved_keys`` feeds the previous run's observations back in, and
    those keys are attempted before any newly listed work.

    ``fail_fast`` governs unresolved-key failures. A 401/403 raises
    :class:`MirrulationsAccessRefusedError` either way; a refusal is never a row.
    """

    def __init__(
        self,
        s3_resource: Any,
        bucket: str,
        prefix: str,
        agency: str,
        record_type: RecordType,
        processed_keys: Any = None,
        since_year: int | None = None,
        verbose: bool = False,
        download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
        key_lister: Callable[[], Iterable[str]] | None = None,
        retain_keys: bool = True,
        fail_fast: bool = False,
        unresolved_keys: Iterable[str | KeyOutcome] | None = None,
    ) -> None:
        self.s3_resource = s3_resource
        self.bucket = bucket
        self.prefix = prefix
        self.agency = agency
        self.record_type = record_type
        self.processed_keys = processed_keys
        self.since_year = since_year
        self.verbose = verbose
        self.download_workers = download_workers
        # When set, supplies this record type's keys (e.g. from a shared
        # single-scan listing); otherwise the reader lists them itself.
        self.key_lister = key_lister
        self.retain_keys = retain_keys
        self.fail_fast = fail_fast
        # Retried before new work, so a run that is capped or interrupted cannot
        # keep postponing the keys a previous run already failed to resolve.
        prior = list(unresolved_keys or ())
        self._prior_outcomes = [outcome for outcome in prior if isinstance(outcome, KeyOutcome)]
        self.unresolved_keys = list(dict.fromkeys(item.key if isinstance(item, KeyOutcome) else item for item in prior))
        super().__init__()
        self.unresolved: list[KeyOutcome] = []

    @property
    def parse_failed_keys(self) -> list[str]:
        """The unresolved keys whose bytes, not the transport, were the problem.

        Kept for callers that split failures; they are retried like every other
        unresolved key now, and ``unresolved`` carries why each one is here.
        """
        return [outcome.key for outcome in self.unresolved if outcome.status != STATUS_TRANSPORT]

    def _path_pattern(self) -> str:
        """This record type's path segment, or refuse: the reader is path-addressed."""
        if self.record_type.path_pattern is None:
            raise ValueError(
                f"MirrulationsReader requires a path-addressable record type, "
                f"but {self.record_type.name!r} has no path_pattern."
            )
        return self.record_type.path_pattern

    def iter_source_objects(
        self,
        *,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> Iterator[MirrulationsSourceObject]:
        """Capture ordered listing membership and ETag-pinned bytes for every object.

        Missing ETags, changed objects, size mismatches, and incomplete bodies abort
        immediately. _retry_transient retries transport failures within its budget.
        Listing stays serial to check strictly ascending keys; GETs use at most
        download_workers futures and yield in listing order.
        """

        path_pattern = self._path_pattern()
        if self.processed_keys:
            raise ValueError("complete Mirrulations enumeration cannot omit processed keys")
        year_pattern = re.compile(
            rf"{re.escape(self.prefix)}/{re.escape(self.agency)}/"
            rf"{re.escape(self.agency)}-(\d{{4}})-"
        )
        bucket = self.s3_resource.Bucket(self.bucket)

        def listed_entries() -> Iterator[tuple[str, str, int | None]]:
            previous_key: str | None = None
            for summary in _iter_objects(bucket, f"{self.prefix}/{self.agency}/"):
                key = summary.key
                if "/text-" not in key or path_pattern not in key or not key.endswith(".json"):
                    continue
                if self.since_year:
                    match = year_pattern.search(key)
                    if match and int(match.group(1)) < self.since_year:
                        continue
                if previous_key is not None and key <= previous_key:
                    raise ValueError("Mirrulations listing keys are not strictly ordered")
                previous_key = key
                etag = getattr(summary, "e_tag", None)
                if not isinstance(etag, str) or not etag:
                    raise ValueError(f"Mirrulations listing lacks an ETag for {key}")
                listed_size = getattr(summary, "size", None)
                if listed_size is not None and (
                    isinstance(listed_size, bool) or not isinstance(listed_size, int) or listed_size < 0
                ):
                    raise ValueError(f"Mirrulations listing size is invalid for {key}")
                yield key, etag, listed_size

        def get(entry: tuple[str, str, int | None]) -> DownloadedObject:
            key, etag, _listed_size = entry
            return _retry_transient(
                key,
                lambda: download_object_bytes(self.s3_resource, self.bucket, key, if_match=etag, max_bytes=max_bytes),
            )

        workers = max(1, self.download_workers)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for (key, etag, listed_size), downloaded in _bounded_ordered_results(
                executor, listed_entries(), get, workers
            ):
                if listed_size is not None and listed_size != len(downloaded.content):
                    raise ValueError(f"Mirrulations listed size differs from bytes for {key}")
                yield MirrulationsSourceObject(
                    key=key,
                    etag=etag,
                    version_id=downloaded.version_id,
                    content=downloaded.content,
                )

    def iter_records(self) -> Iterator[dict]:
        path_pattern = self._path_pattern()
        if self.key_lister is not None:
            keys = self.key_lister()
        else:
            keys = list_json_files(
                self.s3_resource,
                self.bucket,
                self.prefix,
                self.agency,
                self.record_type.name,
                path_pattern,
                self.processed_keys,
                self.verbose,
                self.since_year,
            )
        # The previous run's unresolved keys go first, and drop out of the
        # listing so neither run nor manifest sees them twice.
        retry_first = self.unresolved_keys
        if retry_first:
            already = set(retry_first)
            keys = chain(retry_first, (key for key in keys if key not in already))
        if self.retain_keys:
            keys = list(keys)
        # Empty until the pass finishes. ``last_keys`` now means "produced a
        # record", which only a completed pass can say: eagerly holding the whole
        # listing would hand a caller that stopped early -- or that hit the
        # refusal below -- keys to manifest that were never downloaded.
        self.last_keys = []

        # Fan the per-file GETs across a thread pool via the shared engine —
        # independent, I/O-bound round trips; order is irrelevant (dedup by key).
        label = f"[{self.agency}] {self.record_type.name}"
        outcomes: list[KeyOutcome] = []
        yield from download_keys(
            self.s3_resource,
            self.bucket,
            keys,
            self.download_workers,
            record_type=self.record_type,
            label=label,
            outcomes=outcomes,
            prior_outcomes=self._prior_outcomes,
            raise_failures=self.fail_fast,
            transient_retries=1 if self.fail_fast else 0,
        )
        # One in-run retry pass over the transport answers, the only class whose
        # bytes could differ on an immediate second ask. Everything still
        # unresolved -- including the unreadable and requested-empty answers --
        # stays out of last_keys, so the next run re-lists and re-asks for it.
        if not self.fail_fast:
            retry_outcomes = [outcome for outcome in outcomes if outcome.status == STATUS_TRANSPORT]
            again = [outcome.key for outcome in retry_outcomes]
            if again:
                outcomes = [outcome for outcome in outcomes if outcome.status != STATUS_TRANSPORT]
                yield from download_keys(
                    self.s3_resource,
                    self.bucket,
                    again,
                    self.download_workers,
                    record_type=self.record_type,
                    label=f"{label} retry",
                    outcomes=outcomes,
                    prior_outcomes=retry_outcomes,
                )

        self.unresolved = outcomes
        self.failed_keys = [outcome.key for outcome in outcomes]
        if self.retain_keys:
            unresolved = {outcome.key for outcome in outcomes}
            self.last_keys = [key for key in keys if key not in unresolved]


class _AgencyListingCache:
    """Memoizes one single-scan listing per agency, shared across its readers.

    ``stage_agencies`` builds a reader per (agency, record type) and runs an
    agency's record types sequentially within one worker thread, so the first
    default reader for an agency triggers the scan and the rest read from the
    cache. Bounded readers bypass this cache and stream their matching keys.
    """

    def __init__(
        self,
        record_types: list[RecordType],
        *,
        processed_keys: Any,
        since_year: int | None,
        verbose: bool,
    ) -> None:
        self._record_types = record_types
        self._processed_keys = processed_keys
        self._since_year = since_year
        self._verbose = verbose
        self._by_agency: dict[str, dict[str, list[str]]] = {}
        self._lock = Lock()

    def keys_for(self, s3_resource: Any, agency: str, record_type: RecordType) -> list[str]:
        with self._lock:
            listed = self._by_agency.get(agency)
        if listed is None:
            scanned = list_agency_files_by_type(
                s3_resource,
                BUCKET,
                PREFIX,
                agency,
                self._record_types,
                processed_keys=self._processed_keys,
                verbose=self._verbose,
                since_year=self._since_year,
            )
            with self._lock:
                listed = self._by_agency.setdefault(agency, scanned)
        return listed.get(record_type.name, [])


def reader_factory(
    record_types: list[RecordType],
    *,
    processed_keys: Any = None,
    since_year: int | None = None,
    verbose: bool = False,
    download_workers: int = DEFAULT_DOWNLOAD_WORKERS,
    resource_factory: Callable[[], Any] | None = None,
    bounded: bool = False,
    unresolved_keys: Callable[[str, RecordType], Iterable[str | KeyOutcome]] | None = None,
) -> Callable[[str, RecordType], MirrulationsReader]:
    """Build a ``read(agency, record_type) -> MirrulationsReader`` factory.

    The shared options (manifest membership test, year filter, verbosity) are
    bound once; the caller supplies the agency and record type. Default readers
    cache one reusable agency listing for manifest-producing ingest. With
    ``bounded=True``, a reader streams keys, keeps bounded downloads in flight,
    retries a transient failure once, and then fails closed without retaining a
    manifest list. Each reader gets its own S3 resource.

    ``unresolved_keys`` hands each reader the keys the previous run left
    unresolved, to attempt before its newly listed work. Pass ``KeyOutcome``
    values to preserve attempt counts; bare keys carry no attempt history.
    Without it a resume still re-asks for them -- they were never manifested --
    but only wherever the listing happens to place them.
    """
    cache = (
        None
        if bounded
        else _AgencyListingCache(
            record_types,
            processed_keys=processed_keys,
            since_year=since_year,
            verbose=verbose,
        )
    )
    # Resolve at call time (not as a default arg) so a monkeypatched
    # ``mirrulations.s3_resource`` is honored, and each reader still gets its
    # own resource — safe to call from the staging worker threads. ``s3_resource``
    # sizes its connection pool to ``DEFAULT_DOWNLOAD_WORKERS``, which matches the
    # reader's default ``download_workers`` so the pool is never oversubscribed.
    make_resource = resource_factory or s3_resource

    def read(agency: str, record_type: RecordType) -> MirrulationsReader:
        resource = make_resource()
        if bounded:
            path_pattern = record_type.path_pattern
            if path_pattern is None:
                raise ValueError(f"{record_type.name!r} has no Mirrulations path pattern")

            def list_keys() -> Iterable[str]:
                return iter_json_files(
                    resource,
                    BUCKET,
                    PREFIX,
                    agency,
                    record_type.name,
                    path_pattern,
                    processed_keys,
                    verbose,
                    since_year,
                )

        else:
            assert cache is not None

            def list_keys() -> Iterable[str]:
                return cache.keys_for(resource, agency, record_type)

        return MirrulationsReader(
            resource,
            BUCKET,
            PREFIX,
            agency,
            record_type,
            processed_keys=processed_keys,
            since_year=since_year,
            verbose=verbose,
            download_workers=download_workers,
            key_lister=list_keys,
            retain_keys=not bounded,
            fail_fast=bounded,
            unresolved_keys=unresolved_keys(agency, record_type) if unresolved_keys else None,
        )

    return read
