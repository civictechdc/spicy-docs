"""Measure what the PDF-only source families would add to the hosted tables.

Two owner rules bound the measurement -- never recreate data a publisher's index already states,
and never leave uncaptured what only the PDF holds and a consumer would otherwise re-read -- so each
family is measured against its index record and against its documents, and the difference is the
yield. Two phases, separate because acquisition costs requests and analysis does not:

    uv run --frozen python -m tools.analysis.pdf_family_rollup acquire \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20
    uv run --frozen python -m tools.analysis.pdf_family_rollup analyze \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20 \\
        --output docs/research/pdf-family-rollup-yield-2026-09-20.json

``acquire`` is resumable: every request is appended to ``requests.jsonl`` and every successful body
written to ``blobs/<sha256>``, so a re-run re-requests only rows with no body yet. ``analyze`` reads
retained bytes alone and makes no request. Extraction streams one page at a time and each join-key
pattern scans a page's text once, so cost is linear in pages except PyMuPDF's ``find_tables()``,
which this tool times per page so the report can state what it cost. ``API_GOV`` and
``ZYTE_TOKEN`` are read through ``read_api_key`` and sent as headers only: no URL, receipt row, blob,
error or log line carries either, because every recorded URL is scrubbed first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from spicy_docs.interpretation.citations import (
    CITATION_RULES,
    CitationRule,
    canonical_alnum,
    rejected_lookalikes,
    resolve_committee_names,
)
from spicy_docs.interpretation.citations import committee_vocabulary as build_committee_vocabulary
from spicy_docs.sources.govinfo.activity_reports import is_activity_report, names_activity
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential

ROOT = Path(__file__).resolve().parents[2]
REFSPEC_ENV = Path("/Users/mikewolfd/Work/spicy-stack/RefSpec/.env")
#: The checkout's own credential file; an isolated checkout copy does not carry it.
CHECKOUT_ENV = Path("/Users/mikewolfd/Work/spicy-stack/spicy-docs/.env")
USER_AGENT = "spicy-docs-pdf-family-rollup/1.0 (https://github.com/civictechdc/spicy-docs)"
MAX_PDF_BYTES = 32 * 1024**2
MAX_PAGE_BYTES = 8 * 1024**2
#: How far into a document the measurement reads. Twelve pages was too few:
#: GAO prints its recommendation list at the back and the Secretary of the
#: Senate's expenditure tables sit behind dozens of front-matter pages, so a
#: short window measured front matter and reported it as the document. Sixty
#: still bounds a 1,000-page budget volume, and every row records the page
#: count the document actually has beside the pages read.
MAX_EXTRACT_PAGES = 60


class RollupError(RuntimeError):
    """This measurement could not obtain or read what it asked for."""


# --- the request log -----------------------------------------------------------------


@dataclass
class RequestLog:
    """Every request this measurement made, with its class and its bytes."""

    receipt: Path
    secrets: tuple[str, ...] = ()
    rows: list[dict[str, Any]] = field(default_factory=list)
    _succeeded: dict[str, str] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        (self.receipt / "blobs").mkdir(parents=True, exist_ok=True)
        path = self.receipt / "requests.jsonl"
        if path.exists():
            self.rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = scrub_credential(text, secret)
        return text

    def succeeded(self, url: str) -> str | None:
        """The digest of a retained successful body for this URL, if one exists.

        Indexed rather than scanned: this is asked once per document and the log
        grows with every request, so a scan makes resuming quadratic in the run.
        """
        if self._succeeded is None:
            self._succeeded = {
                row["url"]: row["sha256"] for row in self.rows if row.get("sha256") and row.get("status") == 200
            }
        return self._succeeded.get(self.scrub(url))

    def body(self, digest: str) -> bytes:
        """The retained body bytes for one digest."""
        return (self.receipt / "blobs" / digest).read_bytes()

    def record(
        self,
        *,
        family: str,
        purpose: str,
        url: str,
        method: str,
        request_class: str,
        status: int | None,
        media_type: str | None,
        body: bytes | None,
        note: str | None = None,
        zyte: Mapping[str, Any] | None = None,
    ) -> str | None:
        digest = None
        if body is not None:
            digest = hashlib.sha256(body).hexdigest()
            blob = self.receipt / "blobs" / digest
            if not blob.exists():
                blob.write_bytes(body)
        row = {
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "family": family,
            "purpose": purpose,
            "url": self.scrub(url),
            "method": method,
            "class": request_class,
            "status": status,
            "media_type": media_type,
            "bytes": None if body is None else len(body),
            "sha256": digest,
            "note": None if note is None else self.scrub(note),
            "zyte": None
            if zyte is None
            else {k: (self.scrub(v) if isinstance(v, str) else v) for k, v in zyte.items()},
        }
        self.rows.append(row)
        if self._succeeded is not None and digest and status == 200:
            self._succeeded[row["url"]] = digest
        with (self.receipt / "requests.jsonl").open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        return digest

    def counts(self) -> dict[str, int]:
        """How many logged requests per request class."""
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row["class"]] = counts.get(row["class"], 0) + 1
        return counts


# --- the three request classes -------------------------------------------------------


@dataclass
class Fetchers:
    """One client per request class, each bounded and each logged the same way."""

    log: RequestLog
    api_key: str | None
    zyte_budget: Any = None
    zyte_fetcher: Any = None
    _clients: dict[str, Any] = field(default_factory=dict)

    def _client(self, kind: str, headers: Mapping[str, str] | None = None) -> Any:
        """The shared bounded client for a request class, created on first use."""
        from spicy_docs.transport.capture import BoundedHttpCapture

        if kind not in self._clients:
            self._clients[kind] = BoundedHttpCapture(
                max_requests=400,
                timeout_seconds=120,
                min_request_interval_seconds=1.5,
                user_agent=USER_AGENT,
                error_type=RollupError,
                transport=None,
                clock=lambda: datetime.now(UTC),
                headers=dict(headers or {}),
                # A keyless 401/403 is a bot wall or an S3 denial: the body is
                # the publisher's answer and is evidence. A keyed route must
                # not retain it, because such a body can echo the key.
                retain_refusal_bodies=kind == "keyless",
            )
        return self._clients[kind]

    def zyte_client(self, mode: str, max_bytes: int) -> tuple[Any, Any]:
        """A fresh Zyte-proxied client and its transport, one per proxied call."""
        from spicy_docs.transport.capture import BoundedHttpCapture
        from spicy_docs.transport.zyte import ZyteTransport

        transport = ZyteTransport(
            self.zyte_fetcher,
            max_bytes=max_bytes,
            timeout_seconds=180,
            mode=mode,
            budget=self.zyte_budget,
        )
        client = BoundedHttpCapture(
            max_requests=2,
            timeout_seconds=180,
            min_request_interval_seconds=0.0,
            user_agent=USER_AGENT,
            error_type=RollupError,
            transport=transport,
            clock=lambda: datetime.now(UTC),
            retain_refusal_bodies=True,
        )
        return client, transport

    def get(
        self,
        url: str,
        *,
        family: str,
        purpose: str,
        request_class: str = "keyless",
        max_bytes: int = MAX_PAGE_BYTES,
        reuse: bool = True,
        mode: str = "httpResponseBody",
    ) -> bytes | None:
        """One bounded GET; returns the body, or ``None`` when the route refused."""
        if reuse and (digest := self.log.succeeded(url)) is not None:
            return self.log.body(digest)
        if request_class == "zyte":
            return self._get_zyte(url, family=family, purpose=purpose, max_bytes=max_bytes, mode=mode)
        headers = {"X-Api-Key": self.api_key} if request_class == "keyed" and self.api_key else None
        client = self._client(request_class, headers)
        client.reset_budget()
        try:
            capture = client.capture(url, max_bytes=max_bytes)
        except Exception as error:
            # Every outcome is a measurement -- except a credential refusal,
            # which fetcher rule 1 says must abort rather than be skipped as a
            # bad row. It is logged first so the receipt holds it either way.
            self._record_refusal(error, url, family=family, purpose=purpose, request_class=request_class)
            if isinstance(error, CredentialRefusedError):
                raise
            return None
        self.log.record(
            family=family,
            purpose=purpose,
            url=url,
            method="GET",
            request_class=request_class,
            status=capture.status_code,
            media_type=capture.content_type,
            body=capture.body,
        )
        return capture.body

    def _get_zyte(self, url: str, *, family: str, purpose: str, max_bytes: int, mode: str) -> bytes | None:
        client, transport = self.zyte_client(mode, max_bytes)
        client.reset_budget()
        try:
            capture = client.capture(url, max_bytes=max_bytes)
        except Exception as error:
            self._record_refusal(
                error,
                url,
                family=family,
                purpose=purpose,
                request_class="zyte",
                zyte=_zyte_record(transport, mode),
            )
            if isinstance(error, CredentialRefusedError):
                raise
            return None
        finally:
            client.close()
        self.log.record(
            family=family,
            purpose=purpose,
            url=url,
            method="GET",
            request_class="zyte",
            status=capture.status_code,
            media_type=capture.content_type,
            body=capture.body,
            zyte=_zyte_record(transport, mode),
        )
        return capture.body

    def _record_refusal(
        self,
        error: BaseException,
        url: str,
        *,
        family: str,
        purpose: str,
        request_class: str,
        zyte: Mapping[str, Any] | None = None,
    ) -> None:
        """Log a failed request from the attached capture or refused response, then let the caller decide."""
        from spicy_docs.reading.refusals import RefusedResponse
        from spicy_docs.transport.captured import attached_capture

        capture = attached_capture(error)
        refused = getattr(error, "refused_response", None)
        status: int | None = None
        media_type: str | None = None
        body: bytes | None = None
        if capture is not None:
            status, media_type, body = capture.status_code, capture.content_type, capture.body
        elif isinstance(refused, RefusedResponse):
            media_type = refused.media_type
            body = refused.response_bytes
            if isinstance(error, CredentialRefusedError):
                match = re.search(r"HTTP (\d{3})", str(error))
                status = int(match.group(1)) if match else None
        self.log.record(
            family=family,
            purpose=purpose,
            url=url,
            method="GET",
            request_class=request_class,
            status=status,
            media_type=media_type,
            body=body,
            note=f"{type(error).__name__}: {error}",
            zyte=zyte,
        )

    def close(self) -> None:
        for client in self._clients.values():
            client.close()


def _zyte_record(transport: Any, mode: str) -> dict[str, Any]:
    """One row's proxy provenance, including how many provider calls it took.

    ``provider_calls`` is what makes a run's total derivable: the shared client
    may retry, so a logged row is not necessarily one call, and a receipt that
    records only rows cannot be added up.
    """
    records = list(transport.records)
    if not records:
        return {
            "mode": mode,
            "request_id": None,
            "proxied_client": "zyte",
            "provider_calls": 0,
            "note": "no provider response",
        }
    record = records[-1]
    return {
        "mode": record.mode,
        "request_id": record.zyte_request_id,
        "proxied_client": record.proxied_client,
        "provider_calls": len(records),
        "target_status": record.status_code,
        "body_is_publisher_bytes": record.body_is_publisher_bytes,
    }


# --- join-key patterns ---------------------------------------------------------------
#
# The patterns themselves are not here, with one dated exception below. Every
# pattern rule this measurement runs lives in
# ``spicy_docs.interpretation.citations``, which the ``document_citations``
# contract also runs, so the measurement and the product cannot drift apart:
# a rule corrected here is corrected there, and a rule widened there shows up
# in this tool's own spot check. Each rule names the hosted table it joins to
# and carries the lookalikes it must reject. The exception is the four kinds
# the product now reads through the citation grammar (``MEASURED_001_RULES``).
#
# This module keeps only what is *not* a rule: which roster files the committee
# vocabulary is pinned to here, and the acquisition that reads them. The
# resolver itself is pure and takes that vocabulary as an argument.

#: The chamber rosters this repository already pins, read through this
#: repository's own readers. They are the vocabulary a printed committee name
#: has to resolve against before it counts as a committee; the House file is
#: the complete ``<committees>`` block, the Senate excerpt states only the
#: committees its sampled senators sit on, so the Senate side is a floor.
HOUSE_ROSTER = ROOT / "tests" / "fixtures" / "congress_rosters" / "memberdata-119-excerpt.xml"
SENATE_ROSTER = ROOT / "tests" / "fixtures" / "congress_rosters" / "cvc-member-data-excerpt.xml"


def _canonical_law_number(value: str) -> str:
    """``P.L. 98-369``, ``Public Law 98–369`` and the index's ``PUB 98-369`` are one key."""
    digits = re.search(r"(\d{1,3})[-–](\d{1,4})", value)
    return f"{digits.group(1)}-{digits.group(2)}" if digits else canonical_alnum(value)


def _canonical_digits(value: str) -> str:
    """Every run of non-digits becomes one hyphen: ``12 Stat. 45`` is ``12-45``."""
    return re.sub(r"[^0-9]+", "-", value.strip())


#: The four rules this measurement ran as patterns on 2026-09-20 and the
#: citation grammar has read since their 002 (``public_law``,
#: ``statutes_at_large``, ``usc_section``, ``cfr_section``), kept here at their
#: 001 exactly as measured. This tool compares canonical *pattern* matches
#: against an index record's rendered text -- where Congress.gov spells a law
#: ``PUB 98-369``, which the grammar does not read -- and the committed sidecar
#: and the MODS re-check's receipts are keyed in that space. They are the
#: dated measurement's rules, not the product's: ``document_citations`` reads
#: these kinds through the grammar and compares them with the package MODS in
#: target-key space (``stated_by_index``).
MEASURED_001_RULES: dict[str, CitationRule] = {
    rule.name: rule
    for rule in (
        CitationRule(
            name="public_law",
            version="001",
            pattern=r"\bP(?:ub(?:lic)?)?\.?\s*L(?:aw)?\.?\s?(?:No\.\s?)?\d{1,3}[-–]\d{1,4}\b",
            index_pattern=(
                r"\b(?:P(?:ub(?:lic)?)?\.?\s*L(?:aw)?\.?\s?(?:No\.\s?)?|PUB\s+|PRIV\s+)\d{1,3}[-–]\d{1,4}\b"
            ),
            canonical=_canonical_law_number,
            target_table="laws",
            target_key_shape="(congress, law_type, number), joined: {congress}-public-{number}",
            rejects=("Public Lands", "P.L. Smith", "Pub L", "Republic Law 5", "Pub. L. Rev."),
        ),
        CitationRule(
            name="statutes_at_large",
            version="001",
            pattern=r"\b\d{1,3}\s+Stat\.\s+\d{1,4}\b",
            canonical=_canonical_digits,
            target_table="laws",
            target_key_shape="statutes_at_large_cite as {volume}-{page}",
            rejects=("Stat. of the Union", "12 State 45"),
        ),
        CitationRule(
            name="usc_section",
            version="001",
            pattern=r"\b\d{1,2}\s+U\.?\s?S\.?\s?C\.?\s+(?:§{1,2}\s?)?\d[\w.–-]*",
            target_table="law_code_sections",
            target_key_shape="{usc_title}-{usc_section}",
            rejects=("U.S. Code of conduct", "42 USC for"),
        ),
        CitationRule(
            name="cfr_section",
            version="001",
            pattern=r"\b\d{1,2}\s+C\.?\s?F\.?\s?R\.?\s+(?:part\s+|§\s?)?\d[\w.–-]*",
            target_table="cfr sections (host-side)",
            target_key_shape="{title}-{part}",
            rejects=("CFR is the", "40 CRF 60"),
        ),
    )
}

#: Every citation rule, in the library's order: the library's own where it is
#: read by a pattern, the measured 001 pattern where the grammar reads it now.
JOIN_KEY_RULES: tuple[CitationRule, ...] = tuple(
    rule if rule.reader is None else MEASURED_001_RULES[rule.name] for rule in CITATION_RULES
)


@cache
def committee_vocabulary() -> tuple[tuple[str, str], ...]:
    """``(canonical name, system_code)`` for every committee the pinned rosters state."""
    from spicy_docs.sources.congress.committee_rosters import parse_house_member_data, parse_senate_cvc

    house = parse_house_member_data(HOUSE_ROSTER.read_bytes(), congress=119)
    senate = parse_senate_cvc(SENATE_ROSTER.read_bytes())
    return build_committee_vocabulary(house=(house,), senate=(senate,))


#: Structured content a consumer would otherwise have to re-read the PDF for.
#: Each marker is a *heading* the publisher prints, not a word: the first pass
#: of this measurement used "We recommend that" alone and scored GAO at 1 in 8,
#: while the sample's own prose showed the real headers are "Recommendations
#: for Executive Action" and a numbered "Recommendation N".
STRUCTURE_RULES: tuple[tuple[str, str], ...] = (
    (
        "recommendation_list",
        (
            r"(?im)Recommendations?\s+for\s+(?:Executive|Agency|Congressional)\s+Action"
            r"|^[ \t]*Recommendation\s+\d+\b"
            r"|\b(?:We|GAO)\s+(?:are|is)?\s*recommend(?:s|ed|ing)?\s+that\b"
            r"|\bmaking\s+\d+\s+recommendations?\b"
        ),
    ),
    ("matters_for_congress", r"(?i)\bMatters?\s+for\s+Congressional\s+Consideration\b"),
    (
        "cost_table_marker",
        (
            r"(?i)\b(?:Estimated Budgetary Effects|By Fiscal Year, Millions of Dollars"
            r"|Increases? in (?:Spending|Revenues)|Net Increase or Decrease"
            r"|Estimated Outlays|Estimated Budget Authority)\b"
        ),
    ),
    ("holding_or_syllabus", r"(?m)^\s*(?:Syllabus|Held:|Held\b|Per Curiam)"),
    (
        "appropriation_account",
        r"(?im)^\s*(?:SALARIES AND EXPENSES|Appropriations, \d{4}|Budget Authority|Obligations by program activity)\b",
    ),
    (
        "expenditure_line",
        r"(?im)^\s*(?:Total(?:\s+\w+){0,3}\s*\.{3,}|\w[\w ,'\-]{3,60}\.{5,}\s*[\d,$])",
    ),
)


# --- the families --------------------------------------------------------------------


@dataclass(frozen=True)
class Family:
    """One PDF family: its key, index route, discovery callable and request class."""

    key: str
    title: str
    index_route: str
    discover: Callable[[Fetchers], dict[str, Any]]
    request_class: str = "keyless"


def _json_or_none(body: bytes | None) -> Any:
    """A retained body parsed as JSON, or None when it is absent or is not JSON."""
    if body is None:
        return None
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def discover_crs(fetchers: Fetchers) -> dict[str, Any]:
    """Congress.gov states the report's own formats[]; both file routes are keyless."""
    listing = _json_or_none(
        fetchers.get(
            "https://api.congress.gov/v3/crsreport?format=json&limit=12",
            family="crs",
            purpose="index-list",
            request_class="keyed",
        )
    )
    reports = (listing or {}).get("CRSReports", [])[:8]
    documents = []
    index_fields: dict[str, Any] = {}
    for row in reports:
        detail = _json_or_none(
            fetchers.get(
                f"https://api.congress.gov/v3/crsreport/{row['id']}?format=json",
                family="crs",
                purpose="index-detail",
                request_class="keyed",
            )
        )
        record = (detail or {}).get("CRSReport")
        if not record:
            continue
        index_fields = index_fields or {k: type(v).__name__ for k, v in sorted(record.items())}
        pdf = next((f["url"] for f in record.get("formats", []) if f.get("format") == "PDF"), None)
        html = next((f["url"] for f in record.get("formats", []) if f.get("format") == "HTML"), None)
        if pdf:
            documents.append({"id": record["id"], "url": pdf, "html_url": html, "index": _crs_index_row(record)})
    return {"index_fields": index_fields, "documents": documents, "list_count": (listing or {}).get("pagination")}


def _crs_index_row(record: Mapping[str, Any]) -> dict[str, Any]:
    """The CRS report fields the index already states, kept for the yield comparison."""
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "version": record.get("version"),
        "publishDate": record.get("publishDate"),
        "updateDate": record.get("updateDate"),
        "status": record.get("status"),
        "topics": [t.get("topic") for t in record.get("topics", [])],
        "authors": [a.get("author") for a in record.get("authors", [])],
        "relatedMaterials": [
            {"type": m.get("type"), "number": m.get("number"), "congress": m.get("congress"), "title": m.get("title")}
            for m in record.get("relatedMaterials", [])
        ],
        "summary_present": bool(record.get("summary")),
    }


def discover_gao(fetchers: Fetchers) -> dict[str, Any]:
    """GAO's own keyless feed states the product; the keyless file host serves the PDF."""
    from spicy_docs.sources.gao.files import gao_report_pdf_locator
    from spicy_docs.sources.gao.rss import gao_reports_feed_locator, parse_gao_reports_feed

    body = fetchers.get(gao_reports_feed_locator(), family="gao", purpose="index-list")
    if body is None:
        return {"index_fields": {}, "documents": []}
    feed = parse_gao_reports_feed(body)
    documents = [
        {
            "id": item.product_id,
            "url": gao_report_pdf_locator(item.product_id),
            "index": {
                "product_id": item.product_id,
                "title": item.title,
                "link": item.link,
                "guid": item.guid,
                "pub_date": item.pub_date,
                "description": item.description,
            },
        }
        for item in feed.items[:8]
    ]
    return {
        "index_fields": {
            name: "publisher text" for name in ("product_id", "title", "link", "guid", "description", "pub_date")
        },
        "documents": documents,
        "channel": {"title": feed.title, "link": feed.link, "last_build_date": feed.last_build_date},
    }


def discover_cbo(fetchers: Fetchers) -> dict[str, Any]:
    """The per-Congress feed is the one keyless route; every document route is walled."""
    from spicy_docs.sources.cbo import cbo_per_congress_feed_locator, parse_cbo_cost_estimates_feed

    body = fetchers.get(
        cbo_per_congress_feed_locator(119),
        family="cbo",
        purpose="index-list",
        max_bytes=4 * 1024**2,
    )
    if body is None:
        return {"index_fields": {}, "documents": []}
    feed = parse_cbo_cost_estimates_feed(body, max_bytes=4 * 1024**2)
    # A procedural notice states no bill number and has no estimate table to
    # measure, so the sample takes the newest eight items that name a bill.
    named = [item for item in feed.items if item.bill_number][:8]
    documents = [
        {
            "id": item.publication_id,
            "url": item.link,
            "index": {
                "publication_id": item.publication_id,
                "title": item.title,
                "date": item.date,
                "link": item.link,
                "bill_number": item.bill_number,
                "description": item.description,
            },
        }
        for item in named
    ]
    return {
        "index_fields": {name: "publisher text" for name in ("Title", "Date", "Link", "Description", "Bill_Number")},
        "documents": documents,
        "feed_items": len(feed.items),
        "items_naming_a_bill": sum(1 for item in feed.items if item.bill_number),
    }


def discover_scotus(fetchers: Fetchers) -> dict[str, Any]:
    """The term index is a live render; a PDF link is only what a retained index stated."""
    from spicy_docs.sources.supreme_court import (
        SLIP_OPINION,
        parse_supreme_court_term_index,
        supreme_court_term_index_locator,
    )

    term_year = 2025
    body = fetchers.get(
        supreme_court_term_index_locator(term_year),
        family="scotus",
        purpose="index-list",
    )
    if body is None:
        return {"index_fields": {}, "documents": []}
    index = parse_supreme_court_term_index(body, term_year=term_year)
    documents = []
    for opinion in index.opinions:
        if not opinion.pdf_url or opinion.pdf_kind != SLIP_OPINION:
            continue
        documents.append(
            {
                "id": opinion.pdf_url.rsplit("/", 1)[-1],
                "url": opinion.pdf_url,
                "index": {
                    "release_number": opinion.release_number,
                    "date_decided": opinion.date_decided,
                    "docket_number": opinion.docket_number,
                    "case_name": opinion.case_name,
                    "holding": opinion.holding,
                    "author_code": opinion.author_code,
                    "citation": opinion.citation,
                    "revisions": [r.url for r in opinion.revisions],
                },
            }
        )
        if len(documents) == 8:
            break
    return {
        "index_fields": {
            name: "publisher text"
            for name in (
                "release_number",
                "date_decided",
                "docket_number",
                "case_name",
                "holding",
                "author_code",
                "citation",
                "pdf_url",
                "revisions",
            )
        },
        "documents": documents,
        "stated_term": index.stated_term,
        "rows": len(index.opinions),
        "rows_with_a_slip_link": sum(1 for o in index.opinions if o.pdf_url and o.pdf_kind == SLIP_OPINION),
    }


def discover_courtlistener(fetchers: Fetchers) -> dict[str, Any]:
    """The keyless search route states download_url; the cluster route carries the citations."""
    search = _json_or_none(
        fetchers.get(
            "https://www.courtlistener.com/api/rest/v4/search/?type=o&court=scotus&order_by=dateFiled%20desc",
            family="courtlistener",
            purpose="index-list",
        )
    )
    documents: list[dict[str, Any]] = []
    index_fields: dict[str, Any] = {}
    for result in (search or {}).get("results", [])[:8]:
        index_fields = index_fields or {k: type(v).__name__ for k, v in sorted(result.items())}
        opinions = result.get("opinions") or []
        download = next((o.get("download_url") for o in opinions if o.get("download_url")), None)
        if not download:
            continue
        documents.append(
            {
                "id": str(result.get("cluster_id") or result.get("id")),
                "url": download,
                "index": {
                    "cluster_id": result.get("cluster_id"),
                    "caseName": result.get("caseName"),
                    "docketNumber": result.get("docketNumber"),
                    "dateFiled": result.get("dateFiled"),
                    "citation": result.get("citation"),
                    "court": result.get("court"),
                    "court_id": result.get("court_id"),
                    "status": result.get("status"),
                    "opinion_count": len(opinions),
                    "snippet_present": any(o.get("snippet") for o in opinions),
                },
            }
        )
    return {"index_fields": index_fields, "documents": documents}


def discover_house_activity(fetchers: Fetchers) -> dict[str, Any]:
    """End-of-Congress committee activity reports, found in GovInfo's own CRPT index.

    The title rule and its rejected bare-word alternative are
    ``sources.govinfo.activity_reports``'s, not this tool's, so the precision
    this function reports is measured on the same object the product selects
    with -- the arrangement ``JOIN_KEY_RULES`` already has with the citation
    rules.
    """
    from spicy_docs.sources.govinfo.discovery import published_url

    documents: list[dict[str, Any]] = []
    index_fields: dict[str, Any] = {}
    considered = 0
    loose_matches = 0
    next_url: str | None = published_url("2025-01-01", "2025-03-31", collections=["CRPT"])
    pages = 0
    while next_url and len(documents) < 8 and pages < 3:
        page = _json_or_none(
            fetchers.get(next_url, family="house_activity", purpose="index-list", request_class="keyed")
        )
        pages += 1
        if not page:
            break
        for package in page.get("packages", []):
            index_fields = index_fields or {k: type(v).__name__ for k, v in sorted(package.items())}
            considered += 1
            title = package.get("title") or ""
            if names_activity(title):
                loose_matches += 1
            package_id = package.get("packageId") or ""
            if not is_activity_report(package_id, title):
                continue
            documents.append(
                {
                    "id": package_id,
                    "url": f"https://www.govinfo.gov/content/pkg/{package_id}/pdf/{package_id}.pdf",
                    "index": {
                        "packageId": package_id,
                        "title": title,
                        "dateIssued": package.get("dateIssued"),
                        "lastModified": package.get("lastModified"),
                        "congress": package.get("congress"),
                        "docClass": package.get("docClass"),
                        "packageLink": package.get("packageLink"),
                    },
                }
            )
            if len(documents) == 8:
                break
        next_url = page.get("nextPage")
    return {
        "index_fields": index_fields,
        "documents": documents,
        "packages_considered": considered,
        "titles_containing_activit": loose_matches,
        "titles_matching_the_phrase_rule": len(documents),
    }


def discover_senate_secretary(fetchers: Fetchers) -> dict[str, Any]:
    """The Secretary of the Senate's own report page is the only index there is."""
    page = fetchers.get(
        "https://www.senate.gov/legislative/common/generic/report_secsen.htm",
        family="senate_secretary",
        purpose="index-list",
    )
    documents: list[dict[str, Any]] = []
    index_fields: dict[str, Any] = {}
    if page is not None:
        html = page.decode("utf-8", "replace")
        index_fields = {"link_text": "text", "href": "text"}
        for href, label in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.DOTALL | re.IGNORECASE):
            url = href if href.startswith("http") else "https://www.senate.gov" + href
            documents.append(
                {
                    "id": url.rsplit("/", 1)[-1],
                    "url": url,
                    "index": {"link_text": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", label)).strip(), "href": url},
                }
            )
            if len(documents) == 8:
                break
    return {"index_fields": index_fields, "documents": documents}


def discover_house_clerk(fetchers: Fetchers) -> dict[str, Any]:
    """The Clerk's disclosure microsite: a yearly filing index ZIP and per-filing PDFs."""
    documents: list[dict[str, Any]] = []
    index_fields: dict[str, Any] = {}
    index = fetchers.get(
        "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/2025FD.zip",
        family="house_clerk",
        purpose="index-list",
        max_bytes=16 * 1024**2,
    )
    docids: list[dict[str, str]] = []
    if index is not None:
        import io
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(index)) as archive:
                name = next((n for n in archive.namelist() if n.lower().endswith(".txt")), None)
                if name:
                    text = archive.read(name).decode("utf-8", "replace").splitlines()
                    header = text[0].split("\t")
                    index_fields = {column: "text" for column in header}
                    for line in text[1:]:
                        row = dict(zip(header, line.split("\t"), strict=False))
                        if row.get("DocID") and row.get("FilingType") in {"O", "P", "A"}:
                            docids.append(row)
                        if len(docids) >= 8:
                            break
        except zipfile.BadZipFile:
            index_fields = {}
    for row in docids[:8]:
        year = row.get("Year") or "2025"
        documents.append(
            {
                "id": row["DocID"],
                "url": f"https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}/{row['DocID']}.pdf",
                "index": {k: v for k, v in row.items() if v},
            }
        )
    return {"index_fields": index_fields, "documents": documents}


def discover_budget(fetchers: Fetchers) -> dict[str, Any]:
    """The President's Budget volumes, the one budget-justification family with a publisher index.

    ``/collections/BUDGET/{lastModified}`` answered with packages from other
    collections on 2026-09-20 (SERIALSET rows among BUDGET rows), so the
    issued-date route is used instead and every row's own ``packageId`` prefix
    is checked rather than trusted from the request.
    """
    from spicy_docs.sources.govinfo.discovery import published_url

    documents: list[dict[str, Any]] = []
    index_fields: dict[str, Any] = {}
    page = _json_or_none(
        fetchers.get(
            published_url("2025-01-01", "2026-09-20", collections=["BUDGET"]),
            family="budget",
            purpose="index-list",
            request_class="keyed",
        )
    )
    for package in (page or {}).get("packages", []):
        index_fields = index_fields or {k: type(v).__name__ for k, v in sorted(package.items())}
        package_id = package["packageId"]
        if not package_id.startswith("BUDGET-"):
            continue
        documents.append(
            {
                "id": package_id,
                "url": f"https://www.govinfo.gov/content/pkg/{package_id}/pdf/{package_id}.pdf",
                "index": {
                    "packageId": package_id,
                    "title": package.get("title"),
                    "dateIssued": package.get("dateIssued"),
                    "lastModified": package.get("lastModified"),
                    "docClass": package.get("docClass"),
                    "packageLink": package.get("packageLink"),
                },
            }
        )
        if len(documents) == 8:
            break
    return {"index_fields": index_fields, "documents": documents}


def discover_agency_upload(fetchers: Fetchers) -> dict[str, Any]:
    """No publisher and no index: an upload channel holds whatever a caller hands it.

    The BillTrax upload channel has no index record to compare a PDF against, so
    the family is measured on the nearest public analogue that *does* have one:
    Oversight.gov, whose report page is an indexed HTML record carrying the
    agency, the report number and the recommendation table, and which links the
    agency's own PDF. That comparison is what says whether an upload channel's
    PDF would add anything an indexed record does not already state.
    """
    from spicy_docs.sources.agency_reports.oversight import parse_oversight_report

    listing = fetchers.get(
        "https://www.oversight.gov/reports/federal",
        family="agency_upload",
        purpose="index-list",
    )
    if listing is None:
        return {"index_fields": {}, "documents": []}
    slugs: list[str] = []
    for match in re.finditer(r'href="(/reports/[a-z0-9-]+/[a-z0-9-]+)"', listing.decode("utf-8", "replace")):
        if match.group(1) not in slugs:
            slugs.append(match.group(1))
    documents: list[dict[str, Any]] = []
    index_fields: dict[str, Any] = {}
    for slug in slugs:
        if len(documents) == 8:
            break
        url = "https://www.oversight.gov" + slug
        page = fetchers.get(url, family="agency_upload", purpose="index-detail")
        if page is None:
            continue
        try:
            report = parse_oversight_report(page, url=url)
        except Exception as error:  # noqa: BLE001 - an unsupported page shape is a measurement
            fetchers.log.record(
                family="agency_upload",
                purpose="index-detail-refused",
                url=url,
                method="GET",
                request_class="keyless",
                status=200,
                media_type="text/html",
                body=None,
                note=f"{type(error).__name__}: {error}",
            )
            continue
        fields = {field["native_field"]: field.get("label") for field in report["metadata"]["fields"]}
        index_fields = index_fields or fields
        pdf = next(
            (
                asset["url"]
                for asset in report.get("assets", [])
                if str(asset.get("url") or "").lower().endswith(".pdf")
            ),
            None,
        )
        if not pdf:
            continue
        documents.append(
            {
                "id": slug.rsplit("/", 1)[-1],
                "url": pdf,
                "index": {
                    "page_url": url,
                    "title": report["metadata"].get("title"),
                    "fields": {
                        field["native_field"]: field.get("value")
                        or [item.get("text") for item in field.get("items", [])]
                        for field in report["metadata"]["fields"]
                    },
                    "recommendation_tables": sum(len(body.get("tables", [])) for body in report.get("bodies", [])),
                    "recommendation_rows": sum(
                        len(table.get("rows", []))
                        for body in report.get("bodies", [])
                        for table in body.get("tables", [])
                    ),
                },
            }
        )
    return {"index_fields": index_fields, "documents": documents}


FAMILIES: tuple[Family, ...] = (
    Family("crs", "CRS report files", "api.congress.gov/v3/crsreport/{id}", discover_crs),
    Family("gao", "GAO reports", "gao.gov/rss/reports.xml, then files.gao.gov", discover_gao),
    Family("cbo", "CBO cost estimates", "cbo.gov/rss/{congress}congress-cost-estimates.xml", discover_cbo, "zyte"),
    Family("scotus", "Supreme Court slip opinions", "supremecourt.gov/opinions/slipopinion/{term}", discover_scotus),
    Family("courtlistener", "CourtListener opinions", "courtlistener.com/api/rest/v4/search", discover_courtlistener),
    Family(
        "house_activity", "House committee activity reports", "api.govinfo.gov/published CRPT", discover_house_activity
    ),
    Family(
        "senate_secretary",
        "Report of the Secretary of the Senate",
        "senate.gov report_secsen.htm",
        discover_senate_secretary,
    ),
    Family("house_clerk", "House Clerk disclosures", "disclosures-clerk.house.gov", discover_house_clerk),
    Family("budget", "Budget justifications", "api.govinfo.gov/published BUDGET", discover_budget),
    Family(
        "agency_upload",
        "Agency uploaded-report PDFs",
        "oversight.gov/reports/federal + each report page (nearest indexed analogue)",
        discover_agency_upload,
    ),
)


# --- acquire -------------------------------------------------------------------------


def acquire(receipt: Path, families: Sequence[str], zyte_max: int) -> None:
    """Discover each family's documents (reusing retained indexes) and fetch up to eight bodies."""
    api_key = _api_key()
    secrets = tuple(s for s in (api_key,) if s)
    log = RequestLog(receipt, secrets=secrets)
    fetchers = Fetchers(log=log, api_key=api_key)
    zyte_token = _zyte_token()
    if zyte_token:
        from spicy_docs.sources.zyte import ZyteHttpFetcher
        from spicy_docs.transport.zyte import ZyteBudget

        log.secrets = (*log.secrets, zyte_token)
        fetchers.zyte_fetcher = ZyteHttpFetcher(token=zyte_token)
        fetchers.zyte_budget = ZyteBudget(zyte_max)
    try:
        for family in FAMILIES:
            if families and family.key not in families:
                continue
            path = receipt / "index" / f"{family.key}.json"
            if path.exists():
                discovered = json.loads(path.read_text())
            else:
                discovered = family.discover(fetchers)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(discovered, indent=2, sort_keys=True, default=str))
            if family.key == "cbo":
                _acquire_cbo_documents(fetchers, discovered, path)
                continue
            for document in discovered["documents"][:8]:
                fetchers.get(
                    document["url"],
                    family=family.key,
                    purpose="document",
                    request_class=family.request_class,
                    max_bytes=MAX_PDF_BYTES,
                )
                time.sleep(0.2)
            if family.key == "crs":
                _probe_crs_html(fetchers, discovered)
    finally:
        fetchers.close()
    spent = fetchers.zyte_budget.spent if fetchers.zyte_budget is not None else 0
    summary = {
        "requests": log.counts(),
        "zyte_provider_calls": spent,
        "zyte_budget": None if fetchers.zyte_budget is None else fetchers.zyte_budget.max_requests,
        "receipt": str(receipt),
    }
    (receipt / "acquire-summary.jsonl").open("a").write(json.dumps(summary, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2))


#: A CBO publication page names its own estimate PDF here, and nowhere else.
_CBO_PDF_LINK = re.compile(r'href="(/(?:system|sites/default)/files/[^"]+\.pdf)"')
#: The publisher's own statement that this is its page. Checked before a missing
#: PDF link is read as a fact about the publication.
_CBO_PAGE_MARKER = re.compile(r"(?i)congressional budget office|cbo\.gov/publication")


def _acquire_cbo_documents(fetchers: Fetchers, discovered: dict[str, Any], index_path: Path) -> None:
    """Two proxied hops: the walled publication page, then the PDF it names.

    The feed's ``<Link>`` is a publication page, never a PDF locator, so no
    keyless route states a document URL at all. Each hop is one Zyte request
    and each is recorded; a page that answers but names no PDF is a real
    outcome, not a retry.
    """
    for document in discovered["documents"][:8]:
        page = fetchers.get(
            document["url"],
            family="cbo",
            purpose="document-page",
            request_class="zyte",
            max_bytes=MAX_PAGE_BYTES,
        )
        if page is None:
            continue
        rendered = page.decode("utf-8", "replace")
        if not _CBO_PAGE_MARKER.search(rendered):
            # A 200 that is not a CBO publication page cannot establish that the
            # page names no PDF: a challenge or an error page states no link
            # either, and recording that as "no document" would be the census's
            # own empty-success mistake.
            fetchers.log.record(
                family="cbo",
                purpose="document-page-unexpected-shape",
                url=document["url"],
                method="GET",
                request_class="zyte",
                status=200,
                media_type=None,
                body=None,
                note="200 lacks the publisher's own page marker; no absence established",
            )
            continue
        links = _CBO_PDF_LINK.findall(rendered)
        document["pdf_url"] = "https://www.cbo.gov" + links[0] if links else None
        if not document["pdf_url"]:
            continue
        fetchers.get(
            document["pdf_url"],
            family="cbo",
            purpose="document",
            request_class="zyte",
            max_bytes=MAX_PDF_BYTES,
        )
    index_path.write_text(json.dumps(discovered, indent=2, sort_keys=True, default=str))


def _probe_crs_html(fetchers: Fetchers, discovered: dict[str, Any]) -> None:
    """The census recorded a 403 on the HTML route; ask it directly, then through Zyte.

    Two reports, because one success does not establish a route and one refusal
    does not establish a wall.
    """
    for document in discovered["documents"][:2]:
        html_url = document.get("html_url")
        if not html_url:
            continue
        direct = fetchers.get(html_url, family="crs", purpose="html-direct", max_bytes=MAX_PAGE_BYTES)
        if direct is None:
            fetchers.get(
                html_url,
                family="crs",
                purpose="html-zyte",
                request_class="zyte",
                max_bytes=MAX_PAGE_BYTES,
            )


def _api_key() -> str | None:
    """The first API_GOV found in ``.env`` then the checkout/refspec environments, or None."""
    for candidate in (Path(".env"), CHECKOUT_ENV, REFSPEC_ENV):
        if candidate.exists():
            try:
                return read_api_key(candidate, "API_GOV")
            except SystemExit:
                continue
    return None


def _zyte_token() -> str | None:
    """ZYTE_TOKEN from the refspec environment, or None when there is no token file."""
    if not REFSPEC_ENV.exists():
        return None
    try:
        return read_api_key(REFSPEC_ENV, "ZYTE_TOKEN")
    except SystemExit:
        return None


# --- analyze -------------------------------------------------------------------------


def extract_document(body: bytes) -> dict[str, Any]:
    """Native text, table geometry and per-page timings for one retained PDF."""
    from spicy_docs.extraction import DocumentExtractor, NativeText
    from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages

    extractor = DocumentExtractor(NativeText(), tables=True)
    pages: list[dict[str, Any]] = []
    texts: list[str] = []
    started = time.perf_counter()
    # A page at a time, closed explicitly on the early stop the extraction API
    # asks for: a 500-page budget volume would otherwise dominate the
    # measurement without moving any per-family verdict.
    results = extractor.extract(body, media_type="application/pdf")
    page_count: int | None = None
    try:
        while True:
            # ``next`` is where the page is rendered and ``find_tables`` runs, so
            # that is what is timed. The first version started the timer after
            # the yield and published a column of zeros.
            page_started = time.perf_counter()
            result = next(results, None)
            page_seconds = time.perf_counter() - page_started
            if result is None:
                break
            page_count = result.metadata.get("page_count", page_count)
            texts.append(result.text)
            pages.append(
                {
                    "page": result.metadata.get("page_number") or result.metadata.get("page"),
                    "characters": len(result.text),
                    "blocks": len(result.content.blocks),
                    "seconds": round(page_seconds, 4),
                    "tables": [
                        {
                            "page": t.page,
                            "rows": t.row_count,
                            "columns": t.column_count,
                            "bbox": [round(v, 4) for v in (t.bbox.x0, t.bbox.y0, t.bbox.x1, t.bbox.y1)],
                            "cells_present": sum(1 for row in t.cells for cell in row if cell is not None),
                            "first_row": [c for c in (t.cells[0] if t.cells else ())][:6],
                        }
                        for t in result.tables
                    ],
                }
            )
            if len(pages) >= MAX_EXTRACT_PAGES:
                break
    finally:
        results.close()
    # GPO print artifacts come off before any text-driven rule reads the page:
    # the gutter line numbers and running heads of a GPO print are what made
    # ``HR974`` look like a bill number. The step is evidence-gated, so it is a
    # no-op on a document that is not a GPO print, and it reports what it
    # removed either way.
    normalized, cleanup = normalize_gpo_pages(tuple(texts))
    text = "\n".join(normalized)
    return {
        "pages_read": len(pages),
        "page_count": page_count,
        "truncated": page_count is not None and page_count > len(pages),
        "seconds": round(time.perf_counter() - started, 3),
        "page_detail": pages,
        "gpo_cleanup": {
            "line_numbers_stripped": cleanup.line_numbers,
            "gpo_footers_stripped": cleanup.gpo_footers,
            "running_footer_lines": cleanup.running_footer_lines,
            "hyphen_rejoins": cleanup.hyphen_rejoin_count,
            "small_caps_merges": cleanup.small_caps_merges,
        },
        "text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def capture_probe(body: bytes, digest: str) -> dict[str, Any]:
    """The line assembly every PDF capture profile is built on, run over one document.

    ``tools/analysis/document_capture.py``'s slip-opinion profile converts a PDF
    by extracting pages, assembling printed lines through
    ``reconstruction.evidence.evidence_from_pages``, and hanging structure off
    those lines. This runs only that shared half -- the part that is the same
    for every PDF family -- and reports what a capture would carry: how many
    evidence blocks the document partitions into, and whether concatenating
    them reproduces the text stream, which is the round-trip witness the parent
    schema requires.

    A seventh profile is deliberately not written here. What a family-specific
    profile adds over this is a *grammar* -- which lines are a heading, a
    recommendation or a cost row -- and choosing that grammar is the contract
    build this measurement is supposed to inform, not part of measuring it.
    """
    from spicy_docs.extraction import DocumentExtractor, NativeText
    from spicy_docs.reconstruction.evidence import evidence_from_pages

    results = DocumentExtractor(NativeText()).extract(body, media_type="application/pdf")
    pages = []
    try:
        for result in results:
            pages.append(result)
            if len(pages) >= MAX_EXTRACT_PAGES:
                break
    finally:
        results.close()
    evidence = evidence_from_pages(pages, source_sha256=digest)
    joined = "\n".join(block.text for block in evidence.blocks)
    raw = "\n".join(page.text for page in pages)
    # The witness has to compare two things. ``evidence_from_pages`` stores the
    # digest it was handed, so checking it against that same digest is a
    # tautology; what a capture must establish is that concatenating the blocks
    # reproduces the page text. Whitespace is normalized on both sides because
    # line assembly is allowed to rejoin a wrapped line, which is the one thing
    # it is for.
    return {
        "pages": len(pages),
        "evidence_blocks": len(evidence.blocks),
        "rendition": evidence.rendition,
        "derivation": evidence.derivation,
        "round_trip_sha256": hashlib.sha256(joined.encode()).hexdigest(),
        "round_trip_matches": re.sub(r"\s+", " ", joined).strip() == re.sub(r"\s+", " ", raw).strip(),
        "characters": len(joined),
    }


def index_text(value: Any) -> str:
    """The index record as plain text, so the same rules can be read off both sides.

    A mapping's values are joined with a space rather than printed as JSON, so
    ``{"type": "HR", "number": 7806}`` reads as ``HR 7806`` -- the shape the
    print itself uses -- instead of as punctuation a pattern cannot see through.
    Every ordered pair of one record's values is offered as well, because the
    key order in a retained record is the serializer's and not the publisher's:
    written out sorted, that same record reads ``119 7806 <title> HR`` and its
    two halves are no longer adjacent. That is O(k^2) in one record's field
    count, which the publisher's schema bounds at a handful.

    Pairing every value with every other also invents index tokens that the
    publisher never stated -- a record carrying both ``congress: 119`` and
    ``type: S`` offers ``S 119`` as well as the real ``S 3948``. That bias runs
    one way on purpose: it can only make the index look like it states *more*,
    so a key still counted as yield is one the index genuinely lacks, and every
    "beyond the index" number this tool reports is a floor.
    """
    if isinstance(value, Mapping):
        scalars = [index_text(item) for item in value.values()]
        pairs = [f"{first} {second}" for i, first in enumerate(scalars) for j, second in enumerate(scalars) if i != j]
        return " | ".join([" ".join(scalars), *pairs])
    if isinstance(value, (list, tuple)):
        return " | ".join(index_text(item) for item in value)
    return "" if value is None else str(value)


def measure_keys(text: str, index_row: Any) -> dict[str, Any]:
    """Every key the PDF states, and which of them the index already states.

    The owner's first rule -- data that already exists is not recreated from
    the PDF -- is only checkable if "already exists" is measured rather than
    assumed, so the same rule is read off the index record and both sides are
    reduced to one canonical key before the comparison.
    """
    rendered_index = index_text(index_row)
    found: dict[str, Any] = {}
    for rule in JOIN_KEY_RULES:
        matches = rule.compiled().findall(text)
        flat = [m if isinstance(m, str) else m[0] for m in matches]
        distinct = sorted({rule.canonical(value) for value in flat})
        stated = {rule.canonical(value) for value in rule.compiled_index().findall(rendered_index)}
        new_values = sorted(value for value in distinct if value and value not in stated)
        found[rule.name] = {
            "count": len(flat),
            "distinct_count": len(distinct),
            # The full sets, so the family's union can be taken across
            # documents; ``compact`` truncates them for the committed sidecar
            # and the receipt keeps them whole.
            "distinct": distinct,
            "stated_by_index_count": len(stated & set(distinct)),
            "not_in_index_count": len(new_values),
            "not_in_index": new_values,
        }
    # A printed committee name is a candidate until a roster settles it. The
    # route each one settled by is reported too: two of the four are roster
    # lookups and two are inferences from the print, and a reader of this
    # report should be able to tell which produced a given code.
    resolution = resolve_committee_names(found["committee_name"]["distinct"], committee_vocabulary())
    found["committee_name"]["resolved"] = {
        value: outcome.system_code for value, outcome in sorted(resolution.items()) if outcome.system_code is not None
    }
    found["committee_name"]["resolved_by_route"] = {
        value: outcome.route for value, outcome in sorted(resolution.items()) if outcome.system_code is not None
    }
    found["committee_name"]["unresolved"] = sorted(v for v, o in resolution.items() if o.system_code is None)
    found["committee_name"]["resolved_system_codes"] = sorted(
        {outcome.system_code for outcome in resolution.values() if outcome.system_code is not None}
    )
    structure = {}
    for name, pattern in STRUCTURE_RULES:
        structure[name] = len(re.findall(pattern, text))
    return {"join_keys": found, "structure": structure}


def spot_check() -> dict[str, list[str]]:
    """Each rule's rejected lookalikes, plus a compile of every structure marker before any document is read.

    An inline flag in the wrong place raises only on first use, which once left a stale report on
    disk looking fresh.
    """
    for _, pattern in STRUCTURE_RULES:
        re.compile(pattern)
    # The join-key half is the library's own check, run here so this report and
    # `tests/test_citations.py` assert the same thing about the same patterns,
    # plus the same check over the measured 001 rules this tool still runs.
    failures = rejected_lookalikes()
    for rule in MEASURED_001_RULES.values():
        bad = [candidate for candidate in rule.rejects if rule.reads(candidate)]
        if bad:
            failures[f"{rule.name}@001"] = bad
    return failures


def analyze(receipt: Path, output: Path) -> None:
    """Measure every retained document against its index row and write the receipt tables and sidecar."""
    log = RequestLog(receipt)
    report: dict[str, Any] = {
        "measured_at": datetime.now(UTC).date().isoformat(),
        "receipt": str(receipt),
        "request_counts_by_class": log.counts(),
        "spot_check_failures": spot_check(),
        "join_key_rules": [
            {
                "name": rule.name,
                "pattern": rule.pattern,
                "target_table": rule.target_table,
                "target_key": rule.target_key_shape,
                "rejects": list(rule.rejects),
                "note": rule.note,
            }
            for rule in JOIN_KEY_RULES
        ],
        "families": {},
    }
    for family in FAMILIES:
        path = receipt / "index" / f"{family.key}.json"
        discovered = json.loads(path.read_text()) if path.exists() else {"documents": [], "index_fields": {}}
        documents: list[dict[str, Any]] = []
        for document in discovered["documents"][:8]:
            # CBO is the one family whose index states a publication page, not a
            # document: the PDF locator is discovered from that page.
            locator = document.get("pdf_url") or document["url"]
            digest = log.succeeded(locator)
            row: dict[str, Any] = {
                "id": document["id"],
                "url": log.scrub(locator),
                "index_row": document.get("index"),
                "retained": digest is not None,
            }
            if digest is not None:
                body = log.body(digest)
                row["sha256"] = digest
                row["bytes"] = len(body)
                row["is_pdf"] = body[:5] == b"%PDF-"
                if row["is_pdf"]:
                    extracted = extract_document(body)
                    text = extracted.pop("text")
                    (receipt / "extract" / f"{family.key}-{_safe(document['id'])}.txt").write_text(text)
                    row["extraction"] = extracted
                    row.update(measure_keys(text, document.get("index")))
                    if not any(d.get("capture") for d in documents):
                        row["capture"] = capture_probe(body, digest)
            else:
                refusals = [r for r in log.rows if r["url"] == log.scrub(locator)]
                row["refusal"] = refusals[-1] if refusals else None
            documents.append(row)
        report["families"][family.key] = {
            "title": family.title,
            "index_route": family.index_route,
            "request_class": family.request_class,
            "index_fields": discovered.get("index_fields", {}),
            "documents": documents,
            "presence": _presence(documents),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    # The full per-page detail -- one entry per page of 71 documents, with each
    # table's box and header row -- is receipt-sized, not repository-sized. The
    # committed sidecar keeps the per-document summary the report cites; the
    # receipt keeps everything.
    (receipt / "tables" / "per-family.json").write_text(json.dumps(report["families"], indent=2, sort_keys=True))
    output.write_text(json.dumps(compact(report), indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: len(v["documents"]) for k, v in report["families"].items()}, indent=2))


def compact(report: Mapping[str, Any]) -> dict[str, Any]:
    """The committed sidecar: every number the report cites, without the per-page detail."""
    result = json.loads(json.dumps(report, default=str))
    for family in result["families"].values():
        for document in family["documents"]:
            extraction = document.get("extraction")
            if not extraction:
                continue
            pages = extraction.pop("page_detail", [])
            tables = [table for page in pages for table in page["tables"]]
            extraction["characters"] = sum(page["characters"] for page in pages)
            extraction["blocks"] = sum(page["blocks"] for page in pages)
            extraction["tables"] = len(tables)
            # Lists, not tuples: what this returns is what is serialized.
            extraction["table_shapes"] = [list(shape) for shape in sorted({(t["rows"], t["columns"]) for t in tables})]
            extraction["slowest_page_seconds"] = max((page["seconds"] for page in pages), default=None)
            # A rule that matched nothing in this document is already reported
            # by its absence; carrying sixteen zero rows per document is bulk.
            document["join_keys"] = {
                name: found | {"distinct": found["distinct"][:12], "not_in_index": found["not_in_index"][:12]}
                for name, found in document["join_keys"].items()
                if found["count"]
            }
            document["structure"] = {name: n for name, n in document["structure"].items() if n}
    return result


def _safe(value: str) -> str:
    """A document id reduced to a bounded file-name-safe stem."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:80]


def _presence(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    read = [d for d in documents if d.get("join_keys")]
    if not read:
        return {"documents_read": 0}
    presence = {"documents_read": len(read)}
    for rule in JOIN_KEY_RULES:
        hits = sum(1 for d in read if d["join_keys"][rule.name]["count"] > 0)
        beyond = sum(1 for d in read if d["join_keys"][rule.name]["not_in_index_count"] > 0)
        # Two different numbers, and conflating them overstates the yield: the
        # per-document sum is how many rows a link table would hold, because one
        # document citing a law is one row; the union is how many distinct keys
        # the family reaches. The Detroit Timber boilerplate cite appears in
        # eight of eight slip opinions -- eight rows, one key.
        presence[rule.name] = {
            "documents": hits,
            "rate": round(hits / len(read), 3),
            "documents_beyond_index": beyond,
            "rate_beyond_index": round(beyond / len(read), 3),
            "link_rows": sum(d["join_keys"][rule.name]["distinct_count"] for d in read),
            "link_rows_beyond_index": sum(d["join_keys"][rule.name]["not_in_index_count"] for d in read),
            "distinct_values": len({v for d in read for v in d["join_keys"][rule.name]["distinct"]}),
            "distinct_values_beyond_index": len({v for d in read for v in d["join_keys"][rule.name]["not_in_index"]}),
        }
    presence["committee_system_codes"] = sorted(
        {code for d in read for code in d["join_keys"]["committee_name"]["resolved_system_codes"]}
    )
    presence["committee_candidates_unresolved"] = len(
        {v for d in read for v in d["join_keys"]["committee_name"]["unresolved"]}
    )
    structure = {}
    for name, _ in STRUCTURE_RULES:
        hits = sum(1 for d in read if d["structure"][name] > 0)
        structure[name] = {"documents": hits, "rate": round(hits / len(read), 3)}
    presence["structure"] = structure
    presence["tables_observed"] = sum(
        len(p["tables"]) for d in read for p in d.get("extraction", {}).get("page_detail", [])
    )
    presence["documents_with_a_table"] = sum(
        1 for d in read if any(p["tables"] for p in d.get("extraction", {}).get("page_detail", []))
    )
    return presence


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the ``acquire`` or ``analyze`` phase named on the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="phase", required=True)
    acquire_parser = sub.add_parser("acquire")
    acquire_parser.add_argument("--receipt", type=Path, required=True)
    acquire_parser.add_argument("--family", action="append", default=[])
    acquire_parser.add_argument("--zyte-max", type=int, default=30)
    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("--receipt", type=Path, required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.phase == "acquire":
        acquire(args.receipt.expanduser(), args.family, args.zyte_max)
    else:
        analyze(args.receipt.expanduser(), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
