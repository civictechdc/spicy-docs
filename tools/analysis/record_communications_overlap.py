"""Score the Record parse rule against the publisher's own decomposition, field by field.

`sources/congress/record_communications.py` reconstructs a House executive communication from the
sentence the Congressional Record printed; from the 114th Congress on, the same communications also
exist as Congress.gov ``house-communication`` detail records (26,725 of them), so the rule can be
scored against the publisher on rows it was never fitted to. Two phases, because acquisition costs
keyed requests and scoring does not:

    uv run --frozen python -m tools.analysis.record_communications_overlap fetch \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/record-communications-overlap-2026-09-20
    uv run --frozen python -m tools.analysis.record_communications_overlap score \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/record-communications-overlap-2026-09-20 \\
        --output docs/research/record-communications-overlap-2026-09-20.json
    uv run --frozen python -m tools.analysis.record_communications_overlap render \\
        --output docs/research/record-communications-overlap-2026-09-20.json \\
        --report docs/research/record-communications-overlap-2026-09-20.md

The campaign caps are declared before the run and enforced by the retained request log, counted
across resumes rather than per process: :data:`MAX_GOVINFO_REQUESTS` = 40, four per sampled issue
(one keyed granules page plus ``acquire_granule``'s summary, MODS and keyless HTML) and
:data:`MAX_CONGRESS_REQUESTS` = 600, one detail request per printed number. The ten issues are
named in :data:`SAMPLE_ISSUES` rather than discovered, since discovery is itself a keyed walk.
Detail locators use the publisher's own upper-case ``house-communication/{congress}/EC/{n}``
spelling, and entries are requested round-robin across issues so a cap truncates every issue's
tail. A 404 is the publisher's answer and is recorded ``absent``, a 200 with an empty body is
``requested-empty`` (never absence), a transport failure is ``refused`` and establishes nothing,
and 401/403 ends the run. Scoring is linear in retained bytes; ``API_GOV`` travels as a header
only, and every URL and message is scrubbed before any truncation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spicy_docs.extraction.body_text import rendition_text
from spicy_docs.interpretation.communication_rin import rin_from_report_nature
from spicy_docs.reading.paged_json import PagedJsonBudget
from spicy_docs.sources.congress.listing import API as CONGRESS_API
from spicy_docs.sources.congress.record_communications import (
    RECORD_COMMUNICATION_RULE_VERSION,
    RecordCommunicationEntry,
    contiguity_witness,
    executive_communication_granules,
    normalized_entry_text,
    parse_record_communications,
    publisher_normalized,
)
from spicy_docs.sources.govinfo.body_acquisition import GovInfoBodyAcquirer, GovInfoBodyBudget
from spicy_docs.sources.govinfo.discovery import GovInfoDiscoveryReader, package_granules_url
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential

USER_AGENT = "spicy-docs-record-communications-overlap/1.0 (https://github.com/civictechdc/spicy-docs)"

#: The whole campaign's allowances, counted across resumes. Stated here and in
#: `tools/README.md` before the first request was made.
MAX_GOVINFO_REQUESTS = 40
MAX_CONGRESS_REQUESTS = 600

MAX_DETAIL_BYTES = 1 * 1024 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024

#: ``(congress, issue date)``. Two House sitting days per overlap-era Congress.
SAMPLE_ISSUES: tuple[tuple[int, str], ...] = (
    (114, "2015-06-10"),
    (114, "2016-06-15"),
    (115, "2017-06-14"),
    (115, "2018-06-13"),
    (116, "2019-06-12"),
    (116, "2020-09-16"),
    (117, "2021-06-16"),
    (117, "2022-06-15"),
    (118, "2023-06-14"),
    (118, "2024-06-12"),
)

#: The repository root, so `score` can be run from anywhere.
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV = ROOT / ".env"

_GENERATED_START = "<!-- generated: record-communications-overlap -->"
_GENERATED_END = "<!-- end generated -->"


class OverlapError(RuntimeError):
    """This measurement could not obtain or read what it asked for."""


def detail_locator(congress: int, number: int) -> str:
    """The publisher's own stated locator shape for one House communication.

    Upper-case ``EC``: every list row spells its own ``url`` that way. The
    lower-case form this repository's route builder produces answers the same
    in the detail era, but the point of a measurement is to ask the
    publisher's spelling, not ours.
    """
    return f"{CONGRESS_API}/house-communication/{congress}/EC/{number}?format=json"


# --- the request log ------------------------------------------------------------------


@dataclass
class RequestLog:
    """Every request this measurement made, with its status, bytes and digest.

    Append-only and the only source of the request counts, so a resume spends
    what the campaign has left rather than a fresh process allowance.
    """

    receipt: Path
    secrets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for folder in ("granules", "sections", "details"):
            (self.receipt / folder).mkdir(parents=True, exist_ok=True)
        self.path = self.receipt / "requests.jsonl"
        self.rows: list[dict[str, Any]] = (
            [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
            if self.path.exists()
            else []
        )

    def scrub(self, text: str) -> str:
        """``text`` with every configured secret removed, before it is written or printed."""
        for secret in self.secrets:
            text = scrub_credential(text, secret)
        return text

    def spent(self, publisher: str) -> int:
        """Requests already counted against a publisher's cap, across every resume."""
        return sum(row.get("requests", 1) for row in self.rows if row["publisher"] == publisher)

    def retained(self, folder: str, key: str, suffix: str) -> Path | None:
        """The retained body for one key, or None when no resume can reuse one."""
        path = self.receipt / folder / f"{_safe(key)}{suffix}"
        return path if path.exists() else None

    def record(
        self,
        *,
        publisher: str,
        purpose: str,
        key: str,
        url: str,
        status: int | None,
        media_type: str | None,
        body: bytes | None,
        answer: str,
        requests: int = 1,
        note: str | None = None,
    ) -> None:
        """One log row. ``answer`` is the publisher's answer, read the way ``AGENTS.md`` requires.

        ``ok`` a usable response, ``absent`` a 404/410 the publisher gave for
        this exact locator, ``requested-empty`` a success with no body, and
        ``refused`` a transport failure -- which establishes nothing at all and
        is re-requested on the next resume.
        """
        row = {
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "publisher": publisher,
            "purpose": purpose,
            "key": key,
            "method": "GET",
            # Scrubbed before anything is written, never after: truncating
            # first can cut a key in half and leave its front standing.
            "url": self.scrub(url),
            "status": status,
            "media_type": media_type,
            "bytes": len(body) if body is not None else None,
            "sha256": hashlib.sha256(body).hexdigest() if body else None,
            "answer": answer,
            "requests": requests,
            "note": self.scrub(note)[:400] if note else None,
        }
        self.rows.append(row)
        with self.path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _safe(value: str) -> str:
    """A log key reduced to a bounded file-name-safe stem."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:96]


# --- fetch --------------------------------------------------------------------------


def _answers(log: RequestLog, publisher: str, purpose: str) -> dict[str, str]:
    """The last answer recorded for each key, so a resume knows what still needs asking."""
    return {
        row["key"]: row["answer"] for row in log.rows if row["publisher"] == publisher and row["purpose"] == purpose
    }


def fetch_sections(receipt: Path, key: str, log: RequestLog) -> None:
    """One granule page and one section body per sampled issue, bounded by the GovInfo cap."""
    reader = GovInfoDiscoveryReader(
        budget=PagedJsonBudget(
            max_requests=MAX_GOVINFO_REQUESTS,
            max_page_bytes=32_000_000,
            timeout_seconds=90.0,
            min_request_interval_seconds=0.4,
        ),
        api_key=key,
    )
    acquirer = GovInfoBodyAcquirer(
        budget=GovInfoBodyBudget(
            max_requests=6,
            max_body_bytes=MAX_BODY_BYTES,
            max_metadata_bytes=8_000_000,
            timeout_seconds=90.0,
            min_request_interval_seconds=0.4,
        ),
        api_key=key,
    )
    try:
        for congress, day in SAMPLE_ISSUES:
            package = f"CREC-{day}"
            # The budget is checked against what is still *unretained*: a
            # resume must not refuse to read a page it already paid for.
            if log.retained("granules", package, ".json") is None and log.spent("govinfo") + 4 > MAX_GOVINFO_REQUESTS:
                print(f"{package}: not requested, would exceed the {MAX_GOVINFO_REQUESTS}-request GovInfo cap")
                continue
            granules = _granule_page(reader, log, package, key)
            if granules is None:
                continue
            for granule_id in executive_communication_granules(granules):
                if log.retained("sections", granule_id, ".htm") is not None:
                    continue
                if log.spent("govinfo") + 3 > MAX_GOVINFO_REQUESTS:
                    print(f"{granule_id}: not requested, GovInfo cap reached")
                    break
                _granule_body(acquirer, log, receipt, package, granule_id, congress, key)
    finally:
        acquirer.close()


def _granule_page(
    reader: GovInfoDiscoveryReader, log: RequestLog, package: str, key: str
) -> Sequence[Mapping[str, Any]] | None:
    retained = log.retained("granules", package, ".json")
    if retained is not None:
        return json.loads(retained.read_text()).get("granules", [])
    try:
        page = next(iter(reader.granules(package_granules_url(package, page_size=1000), max_pages=1)))
    except CredentialRefusedError:
        log.record(
            publisher="govinfo",
            purpose="granules",
            key=package,
            url=package_granules_url(package, page_size=1000),
            status=None,
            media_type=None,
            body=None,
            answer="refused",
            note="credential refused",
        )
        raise
    except Exception as error:  # noqa: BLE001 - a refusal is evidence, and the next resume retries it
        log.record(
            publisher="govinfo",
            purpose="granules",
            key=package,
            url=package_granules_url(package, page_size=1000),
            status=None,
            media_type=None,
            body=None,
            answer="refused",
            note=f"{type(error).__name__}: {error}",
        )
        print(f"{package}: granule page refused: {log.scrub(str(error))}")
        return None
    records = list(page.records)
    (log.receipt / "granules" / f"{_safe(package)}.json").write_bytes(page.capture.body)
    log.record(
        publisher="govinfo",
        purpose="granules",
        key=package,
        url=package_granules_url(package, page_size=1000),
        status=200,
        media_type=page.capture.content_type,
        body=page.capture.body,
        # A granule page with no rows is the publisher answering "nothing
        # here", which is a record of a request, not an absent issue.
        answer="ok" if records else "requested-empty",
        note=f"{len(records)} granules, declared {page.declared_count}",
    )
    return records


def _granule_body(
    acquirer: GovInfoBodyAcquirer,
    log: RequestLog,
    receipt: Path,
    package: str,
    granule_id: str,
    congress: int,
    key: str,
) -> None:
    try:
        body = acquirer.acquire_granule(package, granule_id)
    except CredentialRefusedError:
        log.record(
            publisher="govinfo",
            purpose="section",
            key=granule_id,
            url=f"{package}/{granule_id}",
            status=None,
            media_type=None,
            body=None,
            answer="refused",
            requests=3,
            note="credential refused",
        )
        raise
    except Exception as error:  # noqa: BLE001
        log.record(
            publisher="govinfo",
            purpose="section",
            key=granule_id,
            url=f"{package}/{granule_id}",
            status=None,
            media_type=None,
            body=None,
            answer="refused",
            requests=3,
            note=f"{type(error).__name__}: {error}",
        )
        print(f"{granule_id}: body refused: {log.scrub(str(error))}")
        return
    (receipt / "sections" / f"{_safe(granule_id)}.htm").write_bytes(body.body_capture.body)
    (receipt / "sections" / f"{_safe(granule_id)}.json").write_text(
        json.dumps({"packageId": package, "granuleId": granule_id, "congress": congress, "format": body.format}) + "\n"
    )
    log.record(
        publisher="govinfo",
        purpose="section",
        key=granule_id,
        url=log.scrub(body.body_capture.resolved_url),
        status=200,
        media_type=body.body_capture.content_type,
        body=body.body_capture.body,
        answer="ok",
        requests=body.request_count,
        note=f"format {body.format}, offered {','.join(body.offered_formats)}",
    )
    print(f"{granule_id}: {body.body_capture.byte_size} bytes ({body.format})")


def retained_entries(receipt: Path) -> Iterator[tuple[int, str, RecordCommunicationEntry]]:
    """Every entry the retained sections printed: ``(congress, granule id, entry)``."""
    for meta_path in sorted((receipt / "sections").glob("*.json")):
        meta = json.loads(meta_path.read_text())
        body = meta_path.with_suffix(".htm").read_bytes()
        text = rendition_text(body, rendition="htm").text
        for entry in parse_record_communications(text, package_id=meta["packageId"], granule_id=meta["granuleId"]):
            yield int(meta["congress"]), meta["granuleId"], entry


def _round_robin(
    rows: Sequence[tuple[int, str, RecordCommunicationEntry]],
) -> list[tuple[int, RecordCommunicationEntry]]:
    """Entries interleaved across their granules, so a cap truncates every issue's tail.

    Taking them in issue order would spend the whole allowance on the first
    Congresses and leave the last with nothing -- a sample shaped by the
    budget rather than by the question.
    """
    by_granule: dict[str, list[tuple[int, RecordCommunicationEntry]]] = {}
    for congress, granule_id, entry in rows:
        by_granule.setdefault(granule_id, []).append((congress, entry))
    ordered: list[tuple[int, RecordCommunicationEntry]] = []
    for index in range(max((len(values) for values in by_granule.values()), default=0)):
        for granule_id in sorted(by_granule):
            if index < len(by_granule[granule_id]):
                ordered.append(by_granule[granule_id][index])
    return ordered


def fetch_details(receipt: Path, key: str, log: RequestLog) -> None:
    """One detail record per printed number, bounded by the Congress.gov cap."""
    from spicy_docs.sources.congress.listing import PagedJsonSourceError
    from spicy_docs.transport.source_acquirer import SourceAcquirer

    answers = _answers(log, "congress-gov", "detail")
    outstanding = [
        (congress, entry)
        for congress, entry in _round_robin(list(retained_entries(receipt)))
        # Resume rule: a row is done only when the publisher gave an answer
        # this measurement can use. "refused" is a transport failure and is
        # asked again; "absent" is the publisher's own answer and is not.
        if answers.get(f"{congress}-ec-{entry.number}") not in {"ok", "absent", "requested-empty"}
    ]
    remaining = MAX_CONGRESS_REQUESTS - log.spent("congress-gov")
    if remaining <= 0:
        print(f"congress.gov: cap {MAX_CONGRESS_REQUESTS} already spent; nothing requested")
        return
    acquirer = SourceAcquirer(
        max_requests=MAX_CONGRESS_REQUESTS,
        timeout_seconds=60,
        min_request_interval_seconds=0.4,
        user_agent=USER_AGENT,
        label="Congress.gov house communication",
        error_type=PagedJsonSourceError,
        context_key="record_communications_overlap",
        headers={"X-Api-Key": key},
        credential=key,
    )
    try:
        for congress, entry in outstanding[:remaining]:
            row_key = f"{congress}-ec-{entry.number}"
            url = detail_locator(congress, entry.number)
            try:
                capture = acquirer.capture_validated(
                    url,
                    media_types=("application/json",),
                    parse=lambda capture, _max_bytes: capture,
                    max_bytes=MAX_DETAIL_BYTES,
                    unavailable=lambda capture: PagedJsonSourceError(f"detail unavailable: {capture.status_code}"),
                    context={"communication": row_key},
                    reset_budget=False,
                )[0]
            except CredentialRefusedError:
                log.record(
                    publisher="congress-gov",
                    purpose="detail",
                    key=row_key,
                    url=url,
                    status=None,
                    media_type=None,
                    body=None,
                    answer="refused",
                    note="credential refused",
                )
                raise
            except Exception as error:  # noqa: BLE001
                attached = error.__dict__.get("capture")
                status = getattr(attached, "status_code", None)
                # A 404 here is the publisher's answer about this exact
                # locator and is recorded as such; anything else established
                # nothing and is asked again on the next resume.
                answer = "absent" if status in (404, 410) else "refused"
                log.record(
                    publisher="congress-gov",
                    purpose="detail",
                    key=row_key,
                    url=url,
                    status=status,
                    media_type=getattr(attached, "content_type", None),
                    body=None,
                    answer=answer,
                    note=f"{type(error).__name__}: {error}",
                )
                continue
            answer = "ok" if capture.body.strip() else "requested-empty"
            if answer == "ok":
                (receipt / "details" / f"{_safe(row_key)}.json").write_bytes(capture.body)
            log.record(
                publisher="congress-gov",
                purpose="detail",
                key=row_key,
                url=url,
                status=capture.status_code,
                media_type=capture.content_type,
                body=capture.body,
                answer=answer,
            )
    finally:
        acquirer.close()


def fetch(receipt: Path, env_file: Path) -> None:
    """Acquire the sampled sections and their detail records, then print what each cap has left."""
    receipt.mkdir(parents=True, exist_ok=True)
    key = read_api_key(env_file, "API_GOV")
    log = RequestLog(receipt, secrets=(key,))
    fetch_sections(receipt, key, log)
    fetch_details(receipt, key, log)
    print(
        json.dumps(
            {
                "govinfoRequests": log.spent("govinfo"),
                "govinfoCap": MAX_GOVINFO_REQUESTS,
                "congressRequests": log.spent("congress-gov"),
                "congressCap": MAX_CONGRESS_REQUESTS,
            }
        )
    )


# --- score --------------------------------------------------------------------------


def _normalized_committee(name: str) -> str:
    """One committee name reduced to what both publishers agree on.

    Congress.gov says *Education and Workforce Committee* where the Record
    says *Education and the Workforce*: the suffix and the articles are
    presentation, the rest is the name. This is a comparison aid for the
    measurement only -- a published row resolves the name against the
    committee roster (§3.3), never through this.
    """
    stripped = re.sub(r"\bcommittee\b", " ", name.casefold())
    return " ".join(word for word in re.findall(r"[a-z]+", stripped) if word not in {"the", "and", "on", "of"})


@dataclass
class FieldScore:
    """One field's agreement: how often it could be compared, and how often it agreed."""

    stated: int = 0
    agreed: int = 0
    examples: list[dict[str, str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.examples is None:
            self.examples = []

    def observe(self, *, stated: bool, agreed: bool, example: dict[str, str] | None = None) -> None:
        """Count one compared row, keeping up to five examples of disagreement."""
        if not stated:
            return
        self.stated += 1
        if agreed:
            self.agreed += 1
        elif example is not None and len(self.examples) < 5:
            self.examples.append(example)

    def as_json(self) -> dict[str, Any]:
        """This field's counts and precision, or a None precision when nothing was stated."""
        return {
            "stated": self.stated,
            "agreed": self.agreed,
            "precision": round(self.agreed / self.stated, 4) if self.stated else None,
            "disagreements": self.examples,
        }


#: The Congresses whose disagreements the parse rule was revised against, after
#: the first run scored `abstract` at 58.4%. Three print artifacts were found
#: there and fixed (`Pub. L.`, a four-hyphen print dash, GPO's hyphenated line
#: wrap), so the tuning half's score is an **in-sample upper bound**. The
#: held-out half was never read while the rules were being changed, and its
#: score is the one the threshold is applied to.
TUNING_CONGRESSES: frozenset[int] = frozenset({114, 115})

FIELD_NAMES: tuple[str, ...] = (
    "abstract",
    "report_nature",
    "legal_authority",
    "submitting_official",
    "submitting_agency",
    "submitting_split",
    "submitting_official_where_both_stated",
    "submitting_agency_where_both_stated",
    "from_clause_concatenation",
    "referral_count",
    "referral_names",
    "rin",
)


def _score_rows(rows: Sequence[tuple[str, RecordCommunicationEntry, Mapping[str, Any]]]) -> dict[str, Any]:
    fields = {name: FieldScore() for name in FIELD_NAMES}
    for key, entry, detail in rows:
        _score_row(fields, entry, detail, key)
    return {
        "entriesCompared": len(rows),
        "splitRuleFired": sum(1 for _, entry, _ in rows if entry.split_resolved),
        "fields": {name: score.as_json() for name, score in fields.items()},
    }


def score(receipt: Path) -> dict[str, Any]:
    """Compare every retained detail record against the entry the Record printed.

    Reported three ways: the whole sample, the tuning half the rule was revised
    against, and the held-out half it never saw. A score measured on the rows
    that produced the fixes is an upper bound, and saying so is the difference
    between a measurement and a formatting assertion.
    """
    log_rows = [json.loads(line) for line in (receipt / "requests.jsonl").read_text().splitlines() if line.strip()]
    # Read once: parsing every retained section is the expensive half of this
    # command, and the witness and the scoring both want the same entries.
    printed = list(retained_entries(receipt))
    entries = {
        f"{congress}-ec-{entry.number}": (congress, granule_id, entry) for congress, granule_id, entry in printed
    }
    rows: list[tuple[int, str, RecordCommunicationEntry, Mapping[str, Any]]] = []
    for path in sorted((receipt / "details").glob("*.json")):
        row_key = path.stem
        if row_key not in entries:
            continue
        detail = json.loads(path.read_text()).get("houseCommunication")
        if not isinstance(detail, Mapping):
            continue
        congress, _, entry = entries[row_key]
        rows.append((congress, row_key, entry, detail))

    answers: dict[str, int] = {}
    for row in log_rows:
        if row["publisher"] == "congress-gov" and row["purpose"] == "detail":
            answers[row["answer"]] = answers.get(row["answer"], 0) + 1
    whole = _score_rows([(key, entry, detail) for _, key, entry, detail in rows])
    return {
        "measuredOn": datetime.now(UTC).date().isoformat(),
        "ruleVersion": RECORD_COMMUNICATION_RULE_VERSION,
        "caps": {"govinfo": MAX_GOVINFO_REQUESTS, "congressGov": MAX_CONGRESS_REQUESTS},
        "requests": {
            "govinfo": sum(row.get("requests", 1) for row in log_rows if row["publisher"] == "govinfo"),
            "congressGov": sum(row.get("requests", 1) for row in log_rows if row["publisher"] == "congress-gov"),
        },
        "publisherAnswers": answers,
        "issues": _witnesses(printed),
        "entriesPrinted": len(entries),
        "tuningCongresses": sorted(TUNING_CONGRESSES),
        "tuning": _score_rows(
            [(key, entry, detail) for congress, key, entry, detail in rows if congress in TUNING_CONGRESSES]
        ),
        "heldOut": _score_rows(
            [(key, entry, detail) for congress, key, entry, detail in rows if congress not in TUNING_CONGRESSES]
        ),
        **whole,
    }


def _score_row(
    fields: Mapping[str, FieldScore], entry: RecordCommunicationEntry, detail: Mapping[str, Any], key: str
) -> None:
    abstract = detail.get("abstract")
    fields["abstract"].observe(
        stated=isinstance(abstract, str) and bool(abstract),
        agreed=isinstance(abstract, str)
        and publisher_normalized(entry.entry_text) == publisher_normalized(normalized_entry_text(abstract)),
        example={"key": key, "printed": entry.entry_text[:300], "published": str(abstract)[:300]},
    )

    nature = detail.get("reportNature")
    parsed_nature = publisher_normalized(entry.report_nature or "")
    fields["report_nature"].observe(
        stated=isinstance(nature, str) and bool(nature),
        agreed=isinstance(nature, str)
        and publisher_normalized(normalized_entry_text(nature)).rstrip(".")
        == parsed_nature[:1].upper() + parsed_nature[1:],
        example={"key": key, "printed": (entry.report_nature or "")[:300], "published": str(nature)[:300]},
    )

    authority = detail.get("legalAuthority")
    fields["legal_authority"].observe(
        stated=isinstance(authority, str) and bool(authority),
        agreed=isinstance(authority, str)
        and publisher_normalized(normalized_entry_text(authority)) == publisher_normalized(entry.legal_authority or ""),
        example={"key": key, "printed": (entry.legal_authority or "")[:300], "published": str(authority)[:300]},
    )

    official = detail.get("submittingOfficial") or None
    agency = detail.get("submittingAgency") or None
    # THE DECLARED DENOMINATOR for the split: every row where the rule fired
    # and the publisher decomposed at all. Not "where the publisher states this
    # side", which is a different denominator per side and made the pair look
    # like one passing field and one failing one. On the 2026-09-20 sample the
    # two denominators differ by 8 held-out rows -- `118-ec-4522..4530`, one
    # granule, where the publisher put the whole printed from-clause in
    # `submittingAgency` and stated no official -- and which side "fails"
    # flips with the choice. The pair is one boundary decision, so it is
    # scored on one denominator; the narrower view is reported beside it
    # rather than instead of it.
    #
    # A row where the rule *declined* is still excluded: a NULL is the rule
    # refusing, and counting it as a miss would read "refused to guess" as
    # "guessed wrong". How often it declines is reported as coverage.
    decomposed = entry.split_resolved and (official is not None or agency is not None)
    official_agrees = entry.submitting_official == official
    agency_agrees = entry.submitting_agency == agency
    fields["submitting_official"].observe(
        stated=decomposed,
        agreed=official_agrees,
        example={"key": key, "printed": str(entry.submitting_official), "published": str(official)},
    )
    fields["submitting_agency"].observe(
        stated=decomposed,
        agreed=agency_agrees,
        example={"key": key, "printed": str(entry.submitting_agency), "published": str(agency)},
    )
    fields["submitting_split"].observe(
        stated=decomposed,
        agreed=official_agrees and agency_agrees,
        example={
            "key": key,
            "printed": f"{entry.submitting_official} | {entry.submitting_agency}",
            "published": f"{official} | {agency}",
        },
    )
    # The narrower view, reported so the denominator artifact is legible: the
    # same two comparisons over only the rows the publisher decomposed into
    # both sides.
    both_stated = decomposed and official is not None and agency is not None
    fields["submitting_official_where_both_stated"].observe(stated=both_stated, agreed=official_agrees)
    fields["submitting_agency_where_both_stated"].observe(stated=both_stated, agreed=agency_agrees)
    # The fallback fact, on every row the publisher states both: the from-clause
    # this rule keeps whole is the publisher's two fields concatenated, whether
    # or not the split itself resolved.
    fields["from_clause_concatenation"].observe(
        stated=isinstance(official, str) and isinstance(agency, str) and bool(official) and bool(agency),
        agreed=publisher_normalized(entry.from_clause or "") == publisher_normalized(f"{official}, {agency}"),
        example={"key": key, "printed": str(entry.from_clause), "published": f"{official}, {agency}"},
    )

    committees = detail.get("committees")
    published_names = [str(row.get("name") or "") for row in committees] if isinstance(committees, list) else []
    fields["referral_count"].observe(
        stated=bool(published_names),
        agreed=len(published_names) == len(entry.committee_names),
        example={"key": key, "printed": str(entry.committee_names), "published": str(published_names)},
    )
    fields["referral_names"].observe(
        stated=bool(published_names),
        agreed=_referral_names_agree(entry.committee_names, published_names),
        example={"key": key, "printed": str(entry.committee_names), "published": str(published_names)},
    )

    published_rin = rin_from_report_nature(nature if isinstance(nature, str) else None).rin
    fields["rin"].observe(
        stated=published_rin is not None,
        agreed=rin_from_report_nature(entry.report_nature).rin == published_rin,
        example={
            "key": key,
            "printed": str(rin_from_report_nature(entry.report_nature).rin),
            "published": str(published_rin),
        },
    )


def _referral_names_agree(printed: Sequence[str], published: Sequence[str]) -> bool:
    """Every published committee is named by a printed one, under the normalization above.

    A joint referral the Record prints as one run-on name (*House
    Administration and Education and the Workforce*) is matched by
    containment rather than pairwise: the sentence genuinely does not separate
    them, which is the finding, not a parse failure.
    """
    if not published:
        return False
    haystack = _normalized_committee(" ".join(printed))
    return all(all(word in haystack.split() for word in _normalized_committee(name).split()) for name in published)


def _witnesses(printed: Sequence[tuple[int, str, RecordCommunicationEntry]]) -> list[dict[str, Any]]:
    """The per-issue contiguity witness over entries already read off the retained sections."""
    rows: list[dict[str, Any]] = []
    by_granule: dict[str, list[RecordCommunicationEntry]] = {}
    congresses: dict[str, int] = {}
    for congress, granule_id, entry in printed:
        by_granule.setdefault(granule_id, []).append(entry)
        congresses[granule_id] = congress
    for granule_id in sorted(by_granule):
        witness = contiguity_witness(by_granule[granule_id])
        rows.append(
            {
                "congress": congresses[granule_id],
                "granuleId": granule_id,
                "entries": witness.count,
                "first": witness.first,
                "last": witness.last,
                "holes": list(witness.holes),
                "strictlyIncreasing": witness.strictly_increasing,
                "contiguous": witness.contiguous,
            }
        )
    return rows


# --- render -------------------------------------------------------------------------


def _row(name: str, whole: Mapping[str, Any], tuning: Mapping[str, Any], held: Mapping[str, Any]) -> str:
    def share(field: Mapping[str, Any]) -> str:
        precision = field["precision"]
        return "n/a" if precision is None else f"{precision * 100:.1f}%"

    def counted(field: Mapping[str, Any]) -> str:
        return f"{field['agreed']}/{field['stated']}"

    return (
        f"| `{name}` | {counted(held[name])} | {share(held[name])} | "
        f"{counted(tuning[name])} | {share(tuning[name])} | {counted(whole[name])} | {share(whole[name])} |"
    )


def generated_block(measurement: Mapping[str, Any]) -> str:
    """The report's measured block, rebuilt from the sidecar alone."""
    whole, tuning, held = measurement["fields"], measurement["tuning"], measurement["heldOut"]
    congresses = " and ".join(f"{number}th" for number in measurement["tuningCongresses"])
    lines = [
        _GENERATED_START,
        "",
        (
            f"Measured {measurement['measuredOn']} against rule `{measurement['ruleVersion']}`. "
            f"{measurement['requests']['govinfo']} GovInfo requests of {measurement['caps']['govinfo']} "
            f"and {measurement['requests']['congressGov']} keyed Congress.gov requests of "
            f"{measurement['caps']['congressGov']}."
        ),
        "",
        (
            f"{measurement['entriesPrinted']} entries printed across {len(measurement['issues'])} retained "
            f"sections; {measurement['entriesCompared']} have a publisher decomposition to score against. "
            f"The official/agency split rule fired on {measurement['splitRuleFired']} of them."
        ),
        "",
        (
            f"**Held out** is the {measurement['heldOut']['entriesCompared']} rows of the Congresses the rule "
            f"was never revised against; **tuning** is the {measurement['tuning']['entriesCompared']} rows of "
            f"the {congresses}, whose disagreements produced the three print-artifact fixes, so its column is "
            "an in-sample upper bound. The threshold applies to the held-out column."
        ),
        "",
        "| Field | Held out | | Tuning | | Whole sample | |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| | agreed/stated | precision | agreed/stated | precision | agreed/stated | precision |",
    ]
    lines += [_row(name, whole, tuning["fields"], held["fields"]) for name in sorted(whole)]
    lines += [
        "",
        (
            "`submitting_official`, `submitting_agency` and `submitting_split` share one denominator: the rows "
            "the split rule answered and the publisher decomposed at all. The two `_where_both_stated` rows are "
            "the narrower view, over the rows the publisher decomposed into both sides. Which side of the pair "
            "looks like the failure depends on that choice, so both are printed."
        ),
    ]
    lines += [
        "",
        "Per-issue completeness witness:",
        "",
        "| Congress | Granule | Entries | Block | Holes | Contiguous |",
        "| ---: | --- | ---: | --- | ---: | --- |",
    ]
    for issue in measurement["issues"]:
        block = f"{issue['first']}-{issue['last']}"
        lines.append(
            f"| {issue['congress']} | `{issue['granuleId']}` | {issue['entries']} | {block} | "
            f"{len(issue['holes'])} | {'yes' if issue['contiguous'] else 'no'} |"
        )
    answers = measurement["publisherAnswers"]
    lines += [
        "",
        "Publisher answers on the detail route: "
        + ", ".join(f"{count} {answer}" for answer, count in sorted(answers.items()))
        + ".",
        "",
        _GENERATED_END,
    ]
    return "\n".join(lines)


def render(output: Path, report: Path) -> None:
    """Replace the report's generated block with the one the sidecar renders."""
    measurement = json.loads(output.read_text())
    text = report.read_text()
    start, end = text.index(_GENERATED_START), text.index(_GENERATED_END) + len(_GENERATED_END)
    report.write_text(text[:start] + generated_block(measurement) + text[end:])
    print(f"rewrote {report}")


# --- command ------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch the ``fetch``, ``score`` or ``render`` command named on the command line."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch_parser = sub.add_parser("fetch", help="acquire the sampled sections and their detail records")
    fetch_parser.add_argument("--receipt", type=Path, required=True)
    fetch_parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)

    score_parser = sub.add_parser("score", help="score the parse rule against the retained detail records")
    score_parser.add_argument("--receipt", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)

    render_parser = sub.add_parser("render", help="rewrite the report's generated block from the sidecar")
    render_parser.add_argument("--output", type=Path, required=True)
    render_parser.add_argument("--report", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command == "fetch":
        fetch(args.receipt.expanduser(), args.env_file.expanduser())
        return 0
    if args.command == "score":
        measurement = score(args.receipt.expanduser())
        args.output.write_text(json.dumps(measurement, indent=1, sort_keys=True) + "\n")
        print(json.dumps({"wrote": str(args.output), "compared": measurement["entriesCompared"]}))
        return 0
    render(args.output, args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
