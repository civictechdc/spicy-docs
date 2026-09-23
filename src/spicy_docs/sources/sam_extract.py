"""SAM.gov bulk entity extracts: trigger, poll, defensive parse.

The Entity Management API's asynchronous extract (``format=json``) answers the
trigger with a plain-text sentence naming a download URL whose ``api_key`` is
the literal ``REPLACE_WITH_API_KEY`` placeholder; the download answers HTTP
400 with ``errorCode`` ``FSP`` while the file generates (both measured
2026-09-23). The trigger states no count, so the downloaded file's own
``totalRecords`` is the selection's count, and a floor: the file is written while
registrations change, so it may hold more (never fewer) registrations, each keyed
by UEI and EFT indicator (:func:`registrations`). The key travels merged into each
URL's own query: httpx's ``params`` replaces a query rather than extending it,
which once dropped every selection filter. This module owns that loop and the
defensive file parse, so callers receive validated entity records or a
refusal, never a partial, unchecked population.

The synchronous paged walk lives in :mod:`spicy_docs.sources.sam` and refuses a
too-deep query after one page; this extract path is the full-coverage
mechanism (up to the publisher's per-file bound, one file per
``registrationDate`` year window).
"""

from __future__ import annotations

import gzip
import io
import json
import re
import time
import zipfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx
from loguru import logger

from spicy_docs.transport.retry import retry_http

API = "https://api.sam.gov/entity-information/v4"
API_KEY_PLACEHOLDER = "REPLACE_WITH_API_KEY"

# The async extract may not be ready on the first GET: poll with a fixed
# interval up to this many attempts before refusing the selection.
EXTRACT_POLL_MAX = 60
EXTRACT_POLL_INTERVAL = 10.0
MAX_RETRIES = 5
DEFAULT_TIMEOUT = httpx.Timeout(120.0, connect=30.0)


_SENTENCE_URL = re.compile(r"https://api\.sam\.gov/\S+")


class SamExtractError(RuntimeError):
    """A selected SAM extract could not be acquired and validated."""


def year_window_literal(year: int) -> str:
    """SAM ``registrationDate`` range literal spanning a whole calendar year."""
    if isinstance(year, bool) or not isinstance(year, int) or not 1 <= year <= 9999:
        raise SamExtractError("year must be a valid calendar year")
    return f"[01/01/{year},12/31/{year}]"


def extract_entities_url(*, registration_status: str = "A", year: int | None = None) -> str:
    """Name one extract trigger: ``format=json``, optionally scoped to one registration year."""
    if registration_status not in ("A", "E"):
        raise SamExtractError("registration_status must be 'A' or 'E'")
    query = [("registrationStatus", registration_status), ("format", "json")]
    if year is not None:
        query.append(("registrationDate", year_window_literal(year)))
    return f"{API}/entities?{urlencode(query, safe='[],/')}"


def registration_key(record: Mapping[str, Any]) -> tuple[str, str | None]:
    """A SAM registration's identity: its UEI and its EFT indicator.

    One entity registers once per EFT indicator (measured 2026-09-23: 187 of the 147,038 UEIs in the
    2026 registration-year extract carry more than one), so the UEI alone is not a key.
    """
    registration = record["entityRegistration"]
    return validate_entity(record), registration.get("entityEFTIndicator")


def registrations(records: Sequence[dict]) -> list[dict]:
    """One record per registration: a repeated key keeps its newest ``lastUpdateDate``.

    The extract is generated over minutes while registrations change, so a file can carry two
    versions of one registration (two in the 2026 extract, 2026-09-23) and registrations newer
    than its own ``totalRecords``. Identical repeats collapse; differing ones at one date refuse.
    """
    chosen: dict[tuple[str, str | None], dict] = {}
    for record in records:
        key = registration_key(record)
        held = chosen.get(key)
        if held is None:
            chosen[key] = record
            continue
        mine = str(record["entityRegistration"].get("lastUpdateDate") or "")
        theirs = str(held["entityRegistration"].get("lastUpdateDate") or "")
        if mine == theirs and record != held:
            raise SamExtractError(f"SAM extract holds two differing versions of {key} at one lastUpdateDate")
        if mine > theirs:
            chosen[key] = record
    return list(chosen.values())


def validate_entity(record: object) -> str:
    """Return the record's nonempty ``entityRegistration.ueiSAM`` or refuse the record."""
    registration = cast(dict[str, object], record).get("entityRegistration") if isinstance(record, dict) else None
    uei = cast(dict[str, object], registration).get("ueiSAM") if isinstance(registration, dict) else None
    if not isinstance(uei, str) or not uei.strip():
        raise SamExtractError("SAM entity requires a nonempty entityRegistration.ueiSAM")
    return uei


def _total_records(payload: object) -> int:
    """The payload's nonnegative integer ``totalRecords``; a reported source error refuses."""
    _refuse_source_error(payload)
    total = cast(dict[str, object], payload).get("totalRecords") if isinstance(payload, dict) else None
    if type(total) is not int or total < 0:
        raise SamExtractError("SAM response requires a nonnegative integer totalRecords")
    return total


def _entity_data(payload: object) -> list[dict]:
    """The payload's validated ``entityData`` array; a missing array refuses."""
    _refuse_source_error(payload)
    records = cast(dict[str, object], payload).get("entityData") if isinstance(payload, dict) else None
    if not isinstance(records, list):
        raise SamExtractError("SAM response requires an entityData array")
    for record in records:
        validate_entity(record)
    return cast(list[dict], records)


def _refuse_source_error(payload: object) -> None:
    if isinstance(payload, dict) and any(
        cast(dict[str, object], payload).get(key) for key in ("error", "errors", "errorCode", "errorMessage")
    ):
        raise SamExtractError("SAM response reports a source error")


def find_extract_download_url(payload: object) -> str | None:
    """Locate an extract download URL in a trigger response.

    SAM embeds the download link carrying the literal ``REPLACE_WITH_API_KEY``
    placeholder, and the exact key path has varied across API versions, so the
    structure is walked and the first string that looks like that URL is
    returned (placeholder preferred; otherwise any http(s) URL whose path
    mentions download/extract).
    """
    if isinstance(payload, str):
        # The trigger answers a sentence: "Extract File will be available for download with
        # url: https://api.sam.gov/.../download-entities?api_key=REPLACE_WITH_API_KEY&token=...
        # in some time." (measured 2026-09-23).
        match = _SENTENCE_URL.search(payload)
        return match.group(0).rstrip(".,;") if match else None
    fallback: str | None = None

    def walk(node: object) -> str | None:
        nonlocal fallback
        if isinstance(node, str):
            if API_KEY_PLACEHOLDER in node and node.startswith("http"):
                return node
            if (
                fallback is None
                and node.startswith("http")
                and ("download" in node.lower() or "extract" in node.lower())
            ):
                fallback = node
            return None
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"selfLink", "nextLink", "prevLink", "previousLink"}:
                    continue
                hit = walk(value)
                if hit:
                    return hit
        elif isinstance(node, list):
            for value in node:
                hit = walk(value)
                if hit:
                    return hit
        return None

    return walk(payload) or fallback


def _still_generating(response: httpx.Response) -> bool:
    """True for SAM's in-progress answer: HTTP 400 whose JSON body carries ``errorCode`` ``FSP``."""
    if response.status_code != 400:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("errorCode") == "FSP"


def reinject_extract_key(link: str, api_key: str) -> str:
    """Return ``link`` with the real api_key re-injected on the SAM host.

    SAM returns links with the key masked — as a query-param placeholder or the
    literal ``REPLACE_WITH_API_KEY`` token. Both are swapped for ``api_key``;
    anything outside the authorized API host refuses.
    """
    parts = urlparse(link)
    if parts.scheme != "https" or parts.hostname != "api.sam.gov" or parts.username or parts.password:
        raise SamExtractError("SAM response link is outside the authorized API host")
    link = link.replace(API_KEY_PLACEHOLDER, api_key)
    parts = urlparse(link)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["api_key"] = [api_key]
    return urlunparse(parts._replace(query=urlencode(query, doseq=True)))


def _body(response: httpx.Response) -> object:
    """A JSON body when the response is one, otherwise its text (the trigger answers a sentence)."""
    try:
        return response.json()
    except ValueError:
        return response.text


def extract_population(raw: bytes) -> tuple[int, list[dict]]:
    """A downloaded extract's own ``totalRecords`` and its validated records.

    The trigger states no count (it answers a sentence), so the file's envelope is the only
    publisher count for the selection; an extract without one refuses. Measured 2026-09-23: the
    download is a gzip JSON envelope, ``{"totalRecords": 508, "entityData": [508 entities]}`` for
    one registration day, equal to the paged route's count for the same selection.
    """
    try:
        doc = json.loads(_decompress_extract(raw))
    except ValueError:
        raise SamExtractError("SAM extract is not one JSON envelope") from None
    if not isinstance(doc, dict) or "totalRecords" not in doc:
        raise SamExtractError("SAM extract states no totalRecords")
    return _total_records(doc), _entity_data(doc)


def parse_extract_records(raw: bytes) -> list[dict]:
    """Return the validated entity records of one downloaded extract.

    Handles gzip- and zip-compressed payloads, then parses the inner text as
    either a JSON envelope (``{"entityData": [...]}``), a bare JSON array, a
    single entity object, or newline-delimited JSON. Malformed or unrecognized
    input refuses the selection rather than yielding a partial population.
    """
    return list(_iter_extract_records(raw))


def _iter_extract_records(raw: bytes) -> Iterator[dict]:
    text = _decompress_extract(raw)
    if not text.strip():
        raise SamExtractError("SAM extract is empty without an explicit source population")
    stripped = text.lstrip()
    if stripped[:1] in ("{", "["):
        try:
            doc = json.loads(stripped)
        except ValueError:
            yield from _iter_ndjson(text)
            return
        if isinstance(doc, dict):
            if "entityData" in doc:
                records = _entity_data(doc)
                if "totalRecords" in doc and len(records) != _total_records(doc):
                    raise SamExtractError("SAM extract entityData differs from totalRecords")
                yield from records
            elif "entityRegistration" in doc or "ueiSAM" in doc:
                validate_entity(doc)
                yield doc
            else:
                raise SamExtractError("SAM extract has no recognized entity population")
            return
        if isinstance(doc, list):
            for record in doc:
                validate_entity(record)
                yield record
            return
    yield from _iter_ndjson(text)


def _decompress_extract(raw: bytes) -> str:
    """The extract's inner text, transparently decompressing gzip/zip."""
    if raw[:2] == b"\x1f\x8b":  # gzip magic
        try:
            return gzip.decompress(raw).decode("utf-8")
        except (OSError, EOFError, UnicodeError):
            raise SamExtractError("SAM gzip extract is malformed") from None
    if raw[:2] == b"PK":  # zip magic
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members = [member for member in archive.infolist() if not member.is_dir()]
                if len(members) != 1:
                    raise SamExtractError("SAM ZIP extract requires exactly one data member")
                return archive.read(members[0]).decode("utf-8")
        except (zipfile.BadZipFile, UnicodeError):
            raise SamExtractError("SAM ZIP extract is malformed") from None
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise SamExtractError("SAM extract is not valid UTF-8") from None


def _iter_ndjson(text: str) -> Iterator[dict]:
    """Each non-blank line as a validated entity; malformed JSON refuses the extract."""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            raise SamExtractError("SAM extract contains malformed JSON records") from None
        validate_entity(record)
        yield record


class SamBulkExtract:
    """One extract selection: trigger it, poll its download, and yield validated entities.

    ``api_key`` is sent as a query parameter (the publisher's contract for the
    extract route); links returned by the publisher have it masked and are
    re-injected with the real key on the SAM host only. ``max_records`` bounds
    emitted records, not downloaded bytes. Records yielded before a refusal are
    partial — callers must exhaust the iterator before writing output.
    """

    def __init__(
        self,
        *,
        api_key: str,
        registration_status: str = "A",
        year: int | None = None,
        max_records: int | None = None,
        transport: httpx.BaseTransport | None = None,
        poll_max: int = EXTRACT_POLL_MAX,
        poll_interval: float = EXTRACT_POLL_INTERVAL,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key or not api_key.strip():
            raise SamExtractError("SAM extracts require a SAM-authorized API key")
        if max_records is not None and (type(max_records) is not int or max_records <= 0):
            raise SamExtractError("max_records must be a positive integer or None")
        if (
            type(poll_max) is not int
            or poll_max <= 0
            or not isinstance(poll_interval, (int, float))
            or poll_interval < 0
        ):
            raise SamExtractError("extract poll budget must be a positive integer and a nonnegative interval")
        self.api_key = api_key
        self.registration_status = registration_status
        self.year = year
        self.max_records = max_records
        self.transport = transport
        self.poll_max = poll_max
        self.poll_interval = poll_interval
        self.sleep = sleep
        self._seen = 0

    def records(self) -> Iterator[dict]:
        """Trigger the extract, download it, and yield validated entities."""
        self._seen = 0
        # Extract download URLs commonly 302 to a signed blob URL.
        with httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            headers={"Accept": "application/json"},
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            url = extract_entities_url(registration_status=self.registration_status, year=self.year)
            trigger = _body(self._get(client, url))
            if isinstance(trigger, dict) and "entityData" in trigger:
                total, records = _total_records(trigger), _entity_data(trigger)
            else:
                download_url = find_extract_download_url(trigger)
                if download_url is None:
                    raise SamExtractError("SAM extract trigger named no download URL")
                total, records = self._download_records(client, download_url)
            records = registrations(records)
            if len(records) < total:
                raise SamExtractError(
                    f"SAM extract holds {len(records):,} registrations, fewer than its totalRecords {total:,}"
                )
            if len(records) > total:
                logger.info("SAM extract: {:,} registrations beyond its totalRecords {:,}", len(records) - total, total)
            for record in records:
                if not self._budget_left():
                    return
                self._seen += 1
                yield record

    def _budget_left(self) -> bool:
        return self.max_records is None or self._seen < self.max_records

    def _get(self, client: httpx.Client, url: str) -> httpx.Response:
        """GET ``url`` with the key merged into its own query, under bounded retries.

        Passing ``params`` to httpx replaces a URL's query rather than extending it, which
        silently dropped every selection filter (measured 2026-09-23: the trigger answered
        the unfiltered 1,845,420-entity default page), so the key is merged here instead.
        """
        keyed = httpx.URL(url).copy_merge_params({"api_key": self.api_key})

        def attempt() -> httpx.Response:
            response = client.get(keyed)
            if response.status_code == 429 or response.status_code >= 500:
                raise httpx.HTTPStatusError("retryable", request=response.request, response=response)
            if response.status_code != 200:
                raise SamExtractError(
                    f"SAM request refused with HTTP {response.status_code}; verify SAM-specific access"
                )
            return response

        return retry_http(attempt, retryable=(httpx.HTTPError,), max_attempts=MAX_RETRIES, api_key=self.api_key)

    def _download_records(self, client: httpx.Client, download_url: str) -> tuple[int, list[dict]]:
        """Poll the extract download until ready, then defensively parse its bytes."""
        url = reinject_extract_key(download_url, self.api_key)
        for attempt in range(1, self.poll_max + 1):
            try:
                response = client.get(url)
            except httpx.HTTPError:
                if attempt == self.poll_max:
                    raise SamExtractError("SAM extract transport retries exhausted") from None
                self.sleep(self.poll_interval)
                continue
            # The file may still be generating: SAM answers 400 with errorCode FSP ("Extract
            # File Generation is Still in Progress", measured 2026-09-23), and 202/404/429/5xx.
            if _still_generating(response) or response.status_code in (202, 404, 429) or response.status_code >= 500:
                if attempt == self.poll_max:
                    raise SamExtractError("SAM extract did not finish within its poll budget")
                self.sleep(self.poll_interval)
                continue
            if response.status_code != 200:
                raise SamExtractError(f"SAM extract refused with HTTP {response.status_code}")
            return extract_population(response.content)
        raise SamExtractError("SAM extract poll budget exhausted")


__all__ = [
    "API",
    "API_KEY_PLACEHOLDER",
    "EXTRACT_POLL_INTERVAL",
    "EXTRACT_POLL_MAX",
    "SamBulkExtract",
    "SamExtractError",
    "extract_entities_url",
    "extract_population",
    "find_extract_download_url",
    "parse_extract_records",
    "registration_key",
    "registrations",
    "reinject_extract_key",
    "validate_entity",
    "year_window_literal",
]
