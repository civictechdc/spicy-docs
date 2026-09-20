"""Re-check the PDF-family rollup's "beyond the index" figures against the package MODS.

The [rollup](../../docs/research/pdf-family-rollup-yield-2026-09-20.md) compared
each print's citations against the *listing row* GovInfo's ``published`` walk
returns -- seven fields, none of them a citation. That is not the index a
GovInfo body has. ``GovInfoBodyAcquirer`` fetches the package MODS for every
body it reads, and the MODS states bills, laws, committees, U.S. Code sections,
CFR parts, Statutes at Large pages and RINs as **named elements**. So every
"beyond the index" figure for a GovInfo-served family was compared against the
weaker of the two records, and the owner's own rule -- never recreate data an
index already states -- was applied to the wrong index.

This tool restates those figures. Two phases, the same shape the rollup uses,
because acquisition costs keyed requests and analysis does not:

    uv run --frozen python -m tools.analysis.pdf_yield_mods_recheck fetch \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/pdf-yield-mods-recheck-2026-09-20 \\
        --source-receipt ~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20
    uv run --frozen python -m tools.analysis.pdf_yield_mods_recheck analyze \\
        --receipt ~/Work/corpora/supply-2026-09-02/receipts/pdf-yield-mods-recheck-2026-09-20 \\
        --source-receipt ~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20 \\
        --output docs/research/pdf-yield-mods-recheck-2026-09-20.json

``fetch`` is resumable and bounded: every request is appended to
``requests.jsonl`` with its scrubbed URL, status, byte count and digest, every
successful MODS body is retained under ``mods/``, and a re-run re-requests only
what has no retained body yet. ``analyze`` reads retained bytes alone -- the new
receipt's MODS and the rollup receipt's own ``tables/per-family.json``, which
keeps the per-document key sets whole -- and makes no request at all.

**Which documents.** Not a hand-listed set: the rollup receipt's own index
records state each sampled document's URL, and a GovInfo-served one is exactly
a ``www.govinfo.gov/content/pkg/{package}/{folder}/{stem}.{ext}`` locator. A
stem equal to the package id is a package body, so its index is the package
MODS; a stem that differs names a granule, whose index is the granule MODS --
the two records ``acquire`` and ``acquire_granule`` respectively read.

**Which MODS elements.** Not assumed either. ``element_census`` walks the
retained bytes and reports every path the record carries, per collection, and
``MODS_KINDS`` maps only what the census found to the rollup's own rule names.
A rule with no entry there is one no sampled MODS states at all, and its print
set is carried through whole -- that is the surviving PDF-only yield.

**Complexity.** One keyed request per distinct MODS, bounded by
``--max-requests``. Analysis is linear in retained MODS bytes plus the rollup's
own per-document key sets: ``O(sum(M) + D*K)``.

**Credentials.** ``API_GOV`` is read through ``read_api_key`` and sent as a
header only. No URL, receipt row, retained file or error here carries it; every
recorded URL and message is scrubbed first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spicy_docs.reading.xml_tree import XmlTreeElement
from spicy_docs.sources.govinfo.bodies import (
    GovInfoBodySourceError,
    granule_mods_locator,
    package_mods_locator,
    parse_package_id,
    validate_granule_mods,
    validate_package_mods,
)
from spicy_docs.sources.govinfo.discovery import API
from spicy_docs.sources.govinfo.mods import MODS_NAMESPACE, ModsRecord, parse_govinfo_mods
from spicy_docs.transport.credentials import CredentialRefusedError, read_api_key, scrub_credential
from tools.analysis.pdf_family_rollup import (
    CHECKOUT_ENV,
    JOIN_KEY_RULES,
    REFSPEC_ENV,
    committee_vocabulary,
    resolve_committee_names,
)

USER_AGENT = "spicy-docs-pdf-yield-mods-recheck/1.0 (https://github.com/civictechdc/spicy-docs)"
MAX_MODS_BYTES = 24 * 1024 * 1024
#: The whole run's keyed allowance. The sample needs 24; the bound is stated so
#: an unexpected retry cannot walk the publisher's API.
DEFAULT_MAX_REQUESTS = 40

#: A GovInfo-served document, read off the rollup receipt's own index record.
GOVINFO_CONTENT = re.compile(
    r"^https://www\.govinfo\.gov/content/pkg/(?P<package>[^/]+)/(?P<folder>[^/]+)/(?P<stem>.+)\.(?P<ext>[A-Za-z0-9]+)$"
)

_NS = f"{{{MODS_NAMESPACE}}}"


class RecheckError(RuntimeError):
    """This recheck could not obtain or read what it asked for."""


# --- which sampled documents GovInfo serves ------------------------------------------


@dataclass(frozen=True, slots=True)
class GovInfoDocument:
    """One sampled document GovInfo serves, and the MODS record that indexes it."""

    family: str
    document_id: str
    package_id: str
    #: The granule id when the sampled locator's file stem is not the package
    #: id -- ``GPO-CDOC-119sdoc6-1.pdf`` under ``GPO-CDOC-119sdoc6`` -- else None.
    granule_id: str | None
    url: str

    @property
    def mods_key(self) -> str:
        return self.package_id if self.granule_id is None else f"{self.package_id}/{self.granule_id}"

    @property
    def collection(self) -> str:
        """The collection the package id names, as the publisher spells it.

        ``GPO-CDOC-119sdoc3`` is a ``GPO``-collection reprint of a Senate
        document, not a ``CDOC`` package, and its MODS says so in its own
        ``collectionCode``; keeping the two apart is what lets the vocabulary
        census below be read per collection.
        """
        head, _, rest = self.package_id.partition("-")
        return f"{head}-{rest.partition('-')[0]}" if head == "GPO" else head

    @property
    def mods_url(self) -> str:
        """The keyed MODS locator, from this repository's own locators where the grammar reaches.

        ``bodies.py``'s package-id grammar covers CRPT, CHRG, CDOC, CPRT, CREC,
        CDIR and BILLS. It does not cover ``BUDGET-2027-APP`` or the
        ``GPO-``-prefixed CDOC reprints the Secretary of the Senate's volumes
        are published under, and that refusal is deliberate there: a
        ``published`` walk returns neighbouring collections' ids, so a guessed
        address would be worse than a refusal. This tool still has to read
        their MODS, so it falls back to the published route shape and proves
        identity the same way ``validate_package_mods`` does -- against the
        ``accessId`` the MODS states about itself.
        """
        try:
            identity = parse_package_id(self.package_id)
        except GovInfoBodySourceError:
            suffix = "" if self.granule_id is None else f"/granules/{self.granule_id}"
            return f"{API}/packages/{self.package_id}{suffix}/mods"
        if self.granule_id is None:
            return package_mods_locator(identity)
        return granule_mods_locator(identity, self.granule_id)


def govinfo_documents(source_receipt: Path) -> tuple[GovInfoDocument, ...]:
    """Every sampled document whose locator is a GovInfo content path, in receipt order."""
    found: list[GovInfoDocument] = []
    for path in sorted((source_receipt / "index").glob("*.json")):
        if path.name.count(".") > 1:
            # A superseded index kept beside the one the run used.
            continue
        discovered = json.loads(path.read_text())
        for document in discovered.get("documents", [])[:8]:
            url = document.get("pdf_url") or document.get("url") or ""
            match = GOVINFO_CONTENT.match(url)
            if match is None:
                continue
            package, stem = match["package"], match["stem"]
            found.append(
                GovInfoDocument(
                    family=path.stem,
                    document_id=document["id"],
                    package_id=package,
                    granule_id=None if stem == package else stem,
                    url=url,
                )
            )
    return tuple(found)


# --- the request log -----------------------------------------------------------------


@dataclass
class RequestLog:
    """Every request this recheck made, with its status, bytes and digest."""

    receipt: Path
    secrets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        (self.receipt / "mods").mkdir(parents=True, exist_ok=True)
        self.path = self.receipt / "requests.jsonl"
        self.rows: list[dict[str, Any]] = (
            [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]
            if self.path.exists()
            else []
        )

    def scrub(self, text: str) -> str:
        for secret in self.secrets:
            text = scrub_credential(text, secret)
        return text

    def retained(self, mods_key: str) -> Path | None:
        path = self.receipt / "mods" / f"{_safe(mods_key)}.xml"
        return path if path.exists() else None

    @property
    def request_count(self) -> int:
        return len(self.rows)

    def record(
        self,
        *,
        purpose: str,
        mods_key: str,
        url: str,
        status: int | None,
        media_type: str | None,
        body: bytes | None,
        note: str | None = None,
    ) -> None:
        row = {
            "observed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "class": "keyed",
            "purpose": purpose,
            "mods_key": mods_key,
            "method": "GET",
            # Scrubbed before anything is written, never after: truncating
            # first can cut a key in half and leave its front standing.
            "url": self.scrub(url),
            "status": status,
            "media_type": media_type,
            "bytes": len(body) if body is not None else None,
            "sha256": hashlib.sha256(body).hexdigest() if body else None,
            "note": self.scrub(note) if note else None,
        }
        self.rows.append(row)
        with self.path.open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)[:96]


def _api_key() -> str:
    """The same credential-file order the rollup uses; an isolated checkout carries none of its own."""
    for candidate in (Path(".env"), CHECKOUT_ENV, REFSPEC_ENV):
        if candidate.exists():
            try:
                return read_api_key(candidate, "API_GOV")
            except SystemExit:
                continue
    raise RecheckError("API_GOV not found; the GovInfo MODS route is keyed")


# --- fetch ---------------------------------------------------------------------------


def _prove_identity(body: bytes, document: GovInfoDocument, final_url: str) -> str:
    """Prove the MODS is about the requested record, by this repository's own validators where they reach.

    Where ``bodies.py``'s grammar covers the collection, its validator is the
    proof: it checks the final URL, every root ``accessId``, the
    ``collectionCode``, and for a granule the host package nested in a
    ``relatedItem type="host"``. Where the grammar does not, the record still
    has to name itself, so the ``accessId`` check is applied directly and a
    granule's host package is checked the same way ``validate_granule_mods``
    checks it.

    **The fallback proves less than the sealed validators**, and the report
    says so: it does not check the final URL against a derived locator, and it
    does not check ``collectionCode``, because this module derives neither for
    a collection the grammar does not cover. A measurement may read a record
    the sealed acquirer would refuse to fetch; a contract may not.

    **As run on 2026-09-20, 16 of the 24 records took the fallback** because
    the grammar reached neither ``BUDGET-*`` nor the GPO-prefixed CDOC
    reprints. It reaches both since the decision record "BUDGET and the
    GPO-prefixed CDOC reprints join the package-id grammar"
    (``docs/decisions.md``), so a re-run of those two families now takes the
    sealed branch and the fallback is reached only by a collection still
    outside the grammar -- ``ERP-*``, ``GPO-J6-REPORT`` and the other
    neighbouring-collection ids a scoped ``published`` walk returns.
    """
    try:
        identity = parse_package_id(document.package_id)
    except GovInfoBodySourceError as error:
        parsed = parse_govinfo_mods(body, max_bytes=MAX_MODS_BYTES)
        access_ids = tuple(element.text.strip() for element in parsed.package.fields("extension", "accessId"))
        expected = document.granule_id or document.package_id
        if not access_ids:
            raise RecheckError(f"{document.mods_key}: MODS states no accessId") from error
        if any(value != expected for value in access_ids):
            raise RecheckError(f"{document.mods_key}: MODS accessId differs from the requested record") from error
        if document.granule_id is not None:
            hosts = [record for record in parsed.package.related_items if record.element.attribute("type") == "host"]
            host_ids = tuple(
                element.text.strip() for record in hosts for element in record.fields("extension", "accessId")
            )
            if not host_ids:
                raise RecheckError(f"{document.mods_key}: granule MODS states no host package") from error
            if any(value != document.package_id for value in host_ids):
                raise RecheckError(
                    f"{document.mods_key}: granule MODS host package differs from the requested package"
                ) from error
            return "accessId+host"
        return "accessId"
    if document.granule_id is None:
        validate_package_mods(body, package=identity, final_url=final_url, max_bytes=MAX_MODS_BYTES)
        return "validate_package_mods"
    validate_granule_mods(
        body,
        package=identity,
        granule_id=document.granule_id,
        final_url=final_url,
        max_bytes=MAX_MODS_BYTES,
    )
    return "validate_granule_mods"


def fetch(receipt: Path, source_receipt: Path, max_requests: int) -> None:
    from spicy_docs.transport.source_acquirer import SourceAcquirer

    receipt.mkdir(parents=True, exist_ok=True)
    key = _api_key()
    log = RequestLog(receipt, secrets=(key,))
    wanted: dict[str, GovInfoDocument] = {}
    for document in govinfo_documents(source_receipt):
        wanted.setdefault(document.mods_key, document)
    # Resume rule: every row without a retained body is re-requested, and only those.
    outstanding = [document for mods_key, document in wanted.items() if log.retained(mods_key) is None]
    if len(outstanding) > max_requests:
        raise RecheckError(f"{len(outstanding)} MODS to fetch exceeds the {max_requests}-request bound")

    acquirer = SourceAcquirer(
        max_requests=max_requests,
        timeout_seconds=60,
        min_request_interval_seconds=0.5,
        user_agent=USER_AGENT,
        label="GovInfo MODS recheck",
        error_type=GovInfoBodySourceError,
        context_key="pdf_yield_mods_recheck",
        headers={"X-Api-Key": key},
        credential=key,
    )
    try:
        for document in outstanding:
            purpose = "package-mods" if document.granule_id is None else "granule-mods"
            url = document.mods_url
            try:
                capture = acquirer.capture_validated(
                    url,
                    media_types=("application/xml", "text/xml"),
                    parse=lambda capture, _max_bytes: capture,
                    max_bytes=MAX_MODS_BYTES,
                    unavailable=lambda capture: GovInfoBodySourceError(f"MODS unavailable: {capture.status_code}"),
                    context={"modsKey": document.mods_key},
                    reset_budget=False,
                )[0]
            except CredentialRefusedError:
                # A credential refusal ends the run; it is not a bad row to skip.
                log.record(
                    purpose=purpose,
                    mods_key=document.mods_key,
                    url=url,
                    status=None,
                    media_type=None,
                    body=None,
                    note="credential refused",
                )
                raise
            except Exception as error:  # noqa: BLE001 - every refusal is recorded, then the run continues
                attached = error.__dict__.get("capture")
                log.record(
                    purpose=purpose,
                    mods_key=document.mods_key,
                    url=url,
                    status=getattr(attached, "status_code", None),
                    media_type=getattr(attached, "content_type", None),
                    body=getattr(attached, "body", None),
                    note=f"{type(error).__name__}: {error}",
                )
                print(f"refused {document.mods_key}: {log.scrub(str(error))}")
                continue
            proof = _prove_identity(capture.body, document, capture.resolved_url)
            (receipt / "mods" / f"{_safe(document.mods_key)}.xml").write_bytes(capture.body)
            log.record(
                purpose=purpose,
                mods_key=document.mods_key,
                url=url,
                status=capture.status_code,
                media_type=capture.content_type,
                body=capture.body,
                note=proof,
            )
            print(f"{document.mods_key}: {len(capture.body)} bytes, identity by {proof}")
    finally:
        acquirer.close()
    retained = len(list((receipt / "mods").glob("*.xml")))
    print(json.dumps({"requests": log.request_count, "mods_retained": retained}))


# --- what a MODS states --------------------------------------------------------------


def element_census(root: XmlTreeElement) -> dict[str, int]:
    """Every element path the MODS carries, with its count.

    Read rather than assumed: which structured citations a collection's MODS
    states is a publisher fact, and the only way to know it is to walk the
    retained bytes. Paths are namespace-stripped and joined with ``/``.
    """
    counts: Counter[str] = Counter()

    def walk(element: XmlTreeElement, path: str) -> None:
        here = f"{path}/{element.name.removeprefix(_NS)}" if path else element.name.removeprefix(_NS)
        counts[here] += 1
        for child in element.children:
            walk(child, here)

    walk(root, "")
    return dict(sorted(counts.items()))


def _attributes(element: XmlTreeElement) -> dict[str, str]:
    return {name.removeprefix(_NS): value for name, value in element.attributes}


def _alnum(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _bill_keys(root: ModsRecord) -> tuple[set[str], set[str]]:
    """``(type+number, natural_key)`` for every ``<bill>`` the MODS names."""
    blind: set[str] = set()
    natural: set[str] = set()
    for element in root.fields("extension", "bill"):
        attributes = _attributes(element)
        congress, kind, number = attributes.get("congress"), attributes.get("type"), attributes.get("number")
        if not (congress and kind and number):
            continue
        blind.add(_alnum(f"{kind}{number}"))
        natural.add(f"{congress}-{kind.lower()}-{number}")
    return blind, natural


def _law_keys(root: ModsRecord) -> tuple[set[str], set[str]]:
    """``(congress-number, natural_key)`` for every ``<law>``; ``isPrivate`` gives the type."""
    blind: set[str] = set()
    natural: set[str] = set()
    for element in root.fields("extension", "law"):
        attributes = _attributes(element)
        congress, number = attributes.get("congress"), attributes.get("number")
        if not (congress and number):
            continue
        law_type = "private" if (attributes.get("isPrivate") or "").lower() == "true" else "public"
        blind.add(f"{congress}-{number}")
        natural.add(f"{congress}-{law_type}-{number}")
    return blind, natural


def _usc_keys(root: ModsRecord) -> set[str]:
    """``{title}USC{section}`` from ``<USCode><section>``, plus its chapters and appendices.

    A chapter or appendix cite has no counterpart the print rule can produce --
    its pattern requires a digit straight after ``U.S.C.`` -- so those land on
    the MODS-only side by construction, which is what they are: something the
    index states and the capped read never could.
    """
    keys: set[str] = set()
    for element in root.fields("extension", "USCode"):
        title = _attributes(element).get("title")
        if not title:
            continue
        for child in element.children:
            name = child.name.removeprefix(_NS)
            number = _attributes(child).get("number")
            if not number:
                continue
            keys.add(
                f"{title}USC{_alnum(number)}" if name == "section" else f"{title}USC{name.upper()}{_alnum(number)}"
            )
    return keys


def _cfr_keys(root: ModsRecord) -> set[str]:
    keys: set[str] = set()
    for element in root.fields("extension", "cfr"):
        title = _attributes(element).get("title")
        if not title:
            continue
        for child in element.children:
            number = _attributes(child).get("number")
            if number:
                keys.add(f"{title}CFR{_alnum(number)}")
    return keys


def _statute_keys(root: ModsRecord) -> set[str]:
    """``{volume}-{pages}``, the spelling the print rule's own canonical produces."""
    keys: set[str] = set()
    for element in root.fields("extension", "statuteAtLarge"):
        volume = _attributes(element).get("volume")
        if not volume:
            continue
        for child in element.children:
            pages = _attributes(child).get("pages")
            if pages:
                keys.add(f"{volume}-{pages}")
    return keys


def _rin_keys(root: ModsRecord) -> set[str]:
    return {
        f"RIN{_alnum(number)}"
        for element in root.fields("extension", "rin")
        if (number := _attributes(element).get("number"))
    }


def _committee_codes_stated(root: ModsRecord) -> set[str]:
    """The ``authorityId`` on every ``<congCommittee>`` -- a ``committees.system_code`` already."""
    return {
        code.lower()
        for element in root.fields("extension", "congCommittee")
        if (code := _attributes(element).get("authorityId"))
    }


def _member_ids(root: ModsRecord) -> set[str]:
    """Every ``bioGuideId`` a ``<congMember>`` states -- a ``members.bioguide_id`` already.

    Stated, not derived: the rollup's own ``bioguide_id`` rule looks for a
    printed identifier and finds none anywhere, because no congressional print
    contains one. The MODS states it as an attribute instead. It is not
    universal -- one of the eight sampled activity reports carries a
    ``<congMember role="SUBMITTEDBY">`` with a state, a chamber and a parsed
    name but no ``bioGuideId`` -- so this is read as what it is, a per-record
    statement, never as a property of the collection.
    """
    return {
        code for element in root.fields("extension", "congMember") if (code := _attributes(element).get("bioGuideId"))
    }


def _fiscal_years(root: ModsRecord) -> set[str]:
    """Every four-digit year a ``<field name="Fiscal Year">`` states.

    Compared on the year alone: the print rule's own canonical keeps the
    spelling, so ``FY2025`` and ``FISCALYEAR2025`` are two of its keys for one
    year, and a spelling-for-spelling comparison would report a year the MODS
    states as yield in the other spelling.
    """
    years: set[str] = set()
    for element in root.fields("extension", "field"):
        if _attributes(element).get("name", "").casefold() == "fiscal year":
            years.update(re.findall(r"\b(?:19|20)\d{2}\b", element.text))
    return years


def _year(value: str) -> str:
    match = re.search(r"(?:19|20)\d{2}", value)
    return match.group(0) if match else value


#: Rule name -> (what the MODS states for it, how each side is reduced to one key).
#: Only what the element census found is here. Every other rule is one no
#: sampled MODS states at all, and its print set survives whole.
MODS_KINDS: dict[str, tuple[Callable[[ModsRecord], set[str]], Callable[[str], str]]] = {
    "bill_number": (lambda root: _bill_keys(root)[0], lambda value: value),
    "public_law": (lambda root: _law_keys(root)[0], lambda value: value),
    "usc_section": (_usc_keys, lambda value: value),
    "cfr_section": (_cfr_keys, lambda value: re.sub(r"^(\d{1,2}CFR)PART", r"\1", value)),
    "statutes_at_large": (_statute_keys, lambda value: value),
    "rin": (_rin_keys, lambda value: value),
    "committee_name": (_committee_codes_stated, lambda value: value),
    "bioguide_id": (_member_ids, lambda value: value),
    "fiscal_year": (_fiscal_years, _year),
}

#: GovInfo document cross-references the MODS states and no rollup rule looks
#: for: report-to-report, report-to-document, report-to-hearing edges.
DOCUMENT_REFERENCE_ELEMENTS: tuple[str, ...] = ("congReport", "congDoc", "congHearing", "congSerial")


def mods_facts(body: bytes) -> dict[str, Any]:
    """What one MODS states, read as named elements rather than by pattern over rendered text.

    Only the root's own ``extension`` children are read -- the same boundary
    ``validate_package_mods`` draws for ``accessId`` -- so a constituent's own
    statements are never attributed to the package.
    """
    parsed = parse_govinfo_mods(body, max_bytes=MAX_MODS_BYTES)
    root = parsed.package
    stated = {name: sorted(reader(root)) for name, (reader, _) in MODS_KINDS.items()}
    references: dict[str, list[str]] = {}
    for name in DOCUMENT_REFERENCE_ELEMENTS:
        values = []
        for element in root.fields("extension", name):
            attributes = _attributes(element)
            parts = [attributes.get("congress"), attributes.get("type"), attributes.get("number")]
            values.append("-".join(part for part in parts if part))
        if values:
            references[name] = sorted(set(values))
    return {
        "element_census": element_census(root.element),
        "stated": stated,
        "bill_natural_keys": sorted(_bill_keys(root)[1]),
        "law_natural_keys": sorted(_law_keys(root)[1]),
        "document_references": references,
        # The publisher's own collection for this record. It is not the
        # package-id prefix: BUDGET and the GPO-CDOC reprints both state GPO.
        "collection_code": sorted({element.text.strip() for element in root.fields("extension", "collectionCode")}),
        "source_sha256": parsed.source_sha256,
        "source_byte_size": parsed.source_byte_size,
    }


# --- the restated comparison ---------------------------------------------------------


def _print_sets(document: Mapping[str, Any]) -> dict[str, list[str]]:
    keys = document.get("join_keys") or {}
    return {rule.name: list(keys.get(rule.name, {}).get("distinct", [])) for rule in JOIN_KEY_RULES}


def _committee_codes(values: Iterable[str]) -> set[str]:
    """A printed committee candidate counts only once a pinned roster settles it to a system code."""
    # The resolver is pure and takes its roster vocabulary as an argument; the rollup tool
    # builds it from the pinned chamber excerpts, and the re-check must resolve the same way.
    resolution = resolve_committee_names(values, committee_vocabulary())
    return {outcome.system_code for outcome in resolution.values() if outcome.system_code is not None}


def compare_document(print_sets: Mapping[str, Sequence[str]], facts: Mapping[str, Any]) -> dict[str, Any]:
    """Per rule: the print's set, the MODS-stated set, the intersection, print-only and MODS-only.

    Committees compare on the resolved ``system_code`` on both sides: the print
    candidate is settled against the pinned chamber rosters exactly as the
    rollup settles it, and the MODS states a ``congCommittee/@authorityId``,
    which *is* a ``committees.system_code``.
    """
    result: dict[str, Any] = {}
    for rule in JOIN_KEY_RULES:
        printed = set(print_sets.get(rule.name, ()))
        entry = MODS_KINDS.get(rule.name)
        if rule.name == "committee_name":
            printed = _committee_codes(printed)
        stated = set(facts["stated"].get(rule.name, ())) if entry else set()
        if entry is not None:
            canonical = entry[1]
            printed = {canonical(value) for value in printed}
            stated = {canonical(value) for value in stated}
        result[rule.name] = {
            "print_distinct": sorted(printed),
            "mods_distinct": len(stated),
            "mods_values": sorted(stated),
            "intersection": len(printed & stated),
            "print_only": sorted(printed - stated),
            "mods_only": len(stated - printed),
            "mods_states_this_kind": entry is not None,
        }
    return result


def _request_counts(receipt: Path) -> dict[str, Any]:
    """What the receipt's own log says this measurement spent, read back rather than asserted."""
    path = receipt / "requests.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    statuses: Counter[str] = Counter(str(row["status"]) for row in rows)
    purposes: Counter[str] = Counter(row["purpose"] for row in rows)
    proofs: Counter[str] = Counter(row["note"] for row in rows if row["note"])
    return {
        "total": len(rows),
        "keyed": sum(1 for row in rows if row["class"] == "keyed"),
        "bytes": sum(row["bytes"] or 0 for row in rows),
        "by_status": dict(sorted(statuses.items())),
        "by_purpose": dict(sorted(purposes.items())),
        "by_identity_proof": dict(sorted(proofs.items())),
    }


def analyze(receipt: Path, source_receipt: Path, output: Path) -> None:
    documents = govinfo_documents(source_receipt)
    per_family = json.loads((source_receipt / "tables" / "per-family.json").read_text())
    by_id = {
        (family, document["id"]): document for family, entry in per_family.items() for document in entry["documents"]
    }
    report: dict[str, Any] = {
        "measured_at": datetime.now(UTC).date().isoformat(),
        "receipt": str(receipt),
        "source_receipt": str(source_receipt),
        "supersedes": "docs/research/pdf-family-rollup-yield-2026-09-20.json",
        "mods_route": f"{API}/packages/{{packageId}}[/granules/{{granuleId}}]/mods",
        "mods_kinds": sorted(MODS_KINDS),
        "requests": _request_counts(receipt),
        "families": {},
        "collection_mods_vocabulary": {},
        "collection_kinds_stated": {},
    }
    vocabulary: dict[str, Counter[str]] = {}
    kinds: dict[str, dict[str, int]] = {}
    for document in documents:
        retained = receipt / "mods" / f"{_safe(document.mods_key)}.xml"
        family = report["families"].setdefault(document.family, {"documents": []})
        row: dict[str, Any] = {
            "id": document.document_id,
            "package_id": document.package_id,
            "granule_id": document.granule_id,
            "collection": document.collection,
            "mods_key": document.mods_key,
            "mods_url": document.mods_url,
            "mods_retained": retained.exists(),
        }
        source = by_id.get((document.family, document.document_id))
        if source is None or not retained.exists():
            row["note"] = "no retained MODS" if not retained.exists() else "the rollup read no text for this document"
            family["documents"].append(row)
            continue
        facts = mods_facts(retained.read_bytes())
        vocabulary.setdefault(document.collection, Counter()).update(facts["element_census"])
        # How many records of this collection state each kind at all. One
        # record stating it does not make it a property of the collection:
        # seven of the eight activity reports state a ``bioGuideId`` and the
        # eighth states a ``congMember`` without one.
        stated_here = kinds.setdefault(
            document.collection, dict.fromkeys([*MODS_KINDS, *DOCUMENT_REFERENCE_ELEMENTS, "records"], 0)
        )
        stated_here["records"] += 1
        stated_here["collection_code"] = "/".join(facts["collection_code"]) or "none"
        for name, values in facts["stated"].items():
            stated_here[name] += 1 if values else 0
        for name in DOCUMENT_REFERENCE_ELEMENTS:
            stated_here[name] += 1 if facts["document_references"].get(name) else 0
        row["mods_sha256"] = facts["source_sha256"]
        row["mods_bytes"] = facts["source_byte_size"]
        row["mods_states"] = {name: len(values) for name, values in facts["stated"].items() if values}
        row["mods_document_references"] = {name: len(values) for name, values in facts["document_references"].items()}
        row["bill_natural_keys_stated"] = len(facts["bill_natural_keys"])
        row["law_natural_keys_stated"] = facts["law_natural_keys"]
        row["comparison"] = compare_document(_print_sets(source), facts)
        family["documents"].append(row)
    for name, family in report["families"].items():
        family["title"] = name
        family["restated"] = _restate(family["documents"])
    report["collection_mods_vocabulary"] = {
        collection: dict(sorted(counts.items())) for collection, counts in sorted(vocabulary.items())
    }
    report["collection_kinds_stated"] = {
        collection: dict(sorted(stated.items())) for collection, stated in sorted(kinds.items())
    }
    # The uncapped re-read is a separate phase because it costs minutes rather
    # than seconds, but its restated figures are the ones the report leads
    # with, so the committed sidecar carries them when that phase has run.
    uncapped_path = receipt / "uncapped.json"
    if uncapped_path.exists():
        uncapped_report = json.loads(uncapped_path.read_text())
        report["uncapped"] = {
            "restated": uncapped_report["restated"],
            # Wall-clock, so it moves between runs. It is carried here anyway
            # because the report quotes it, and a number the report quotes
            # belongs in the record the report is rendered from.
            "timings": uncapped_report["timings"],
            "pages_read": {
                family: sum(row["page_count"] for row in uncapped_report["documents"] if row["family"] == family)
                for family in sorted({row["family"] for row in uncapped_report["documents"]})
            },
            "per_document_bills": [
                {
                    "id": row["id"],
                    "pages": row["page_count"],
                    "print": row["comparison"]["bill_number"]["print_distinct"]
                    if isinstance(row["comparison"]["bill_number"]["print_distinct"], int)
                    else len(row["comparison"]["bill_number"]["print_distinct"]),
                    "mods": row["comparison"]["bill_number"]["mods_distinct"],
                    "print_only": len(row["comparison"]["bill_number"]["print_only"]),
                }
                for row in uncapped_report["documents"]
                if row["family"] == "house_activity"
            ],
        }
    (receipt / "recheck.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(_compact(report), indent=2, sort_keys=True) + "\n")
    print(json.dumps({name: family["restated"] for name, family in report["families"].items()}, indent=2))


def _restate(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per family and per rule: the print's yield restated against the MODS, with the MODS's own column.

    ``link_rows`` and ``distinct_values`` stay two different numbers, for the
    reason the rollup gives: one document citing one key is one row, and eight
    prints citing the same key are eight rows but one key.
    """
    read = [document for document in documents if document.get("comparison")]
    restated: dict[str, Any] = {"documents_with_mods": len(read)}
    for rule in JOIN_KEY_RULES:
        # ``.get``: a comparison read back from a receipt may carry only the
        # kinds that had a value, and a rule absent from every document is
        # already reported by its absence from the table.
        cells = [cell for document in read if (cell := document["comparison"].get(rule.name))]
        if not cells or not any(cell["print_distinct"] or cell["mods_distinct"] for cell in cells):
            continue
        print_union = {value for cell in cells for value in cell["print_distinct"]}
        mods_union = {value for cell in cells for value in cell["mods_values"]}
        restated[rule.name] = {
            # Two different facts, and conflating them is how a surviving-yield
            # table goes wrong: whether this tool reads the kind from a MODS at
            # all, and whether any record in *this* family actually stated it.
            # A CRPT MODS has a ``rin`` reader and states no RIN.
            "mods_reader_exists": cells[0]["mods_states_this_kind"],
            "mods_states_this_kind": bool(mods_union),
            "documents": sum(1 for cell in cells if cell["print_distinct"]),
            "documents_beyond_mods": sum(1 for cell in cells if cell["print_only"]),
            "print_link_rows": sum(len(cell["print_distinct"]) for cell in cells),
            "print_only_link_rows": sum(len(cell["print_only"]) for cell in cells),
            "print_distinct_values": len(print_union),
            # The rollup's own spelling of this number: the union of each
            # document's own print-only set. That is the right one for a
            # ``document_citations`` row, since a row is worth building only
            # where *that* document's MODS does not state the key.
            "print_only_distinct_values": len({value for cell in cells for value in cell["print_only"]}),
            # The family-wide reading of the same question: a key no MODS in
            # the family states anywhere. Lower wherever one document's MODS
            # states what another document only printed.
            "print_only_against_family_union": len(print_union - mods_union),
            "mods_link_rows": sum(cell["mods_distinct"] for cell in cells),
            "mods_distinct_values": len(mods_union),
            "mods_only_link_rows": sum(cell["mods_only"] for cell in cells),
        }
    restated["mods_document_reference_rows"] = sum(
        sum(document.get("mods_document_references", {}).values()) for document in read
    )
    return restated


def _compact(report: Mapping[str, Any]) -> dict[str, Any]:
    """The committed sidecar: every number the report cites, without the per-document key lists."""
    result = json.loads(json.dumps(report, default=str))
    for family in result["families"].values():
        for document in family["documents"]:
            comparison = document.get("comparison")
            document.pop("law_natural_keys_stated", None)
            if not comparison:
                continue
            document["comparison"] = {
                name: {
                    **{key: value for key, value in cell.items() if key != "mods_values"},
                    "print_distinct": len(cell["print_distinct"]),
                    "print_only_count": len(cell["print_only"]),
                    "print_only": cell["print_only"][:12],
                }
                for name, cell in comparison.items()
                if cell["print_distinct"] or cell["mods_distinct"]
            }
    return result


# --- the print side's own false positives --------------------------------------------

#: The Congress sitting when this was measured. A public-law or bill key naming
#: a later one cannot be a real citation, whatever the print appears to say.
CURRENT_CONGRESS = 119
#: Positive titles the publishers actually have. 54 U.S. Code titles, 50 CFR
#: titles, ~91 Federal Register volumes by 2026, ~610 U.S. Reports volumes,
#: ~140 Statutes at Large volumes. Each is an upper bound with slack, so a
#: flagged value is one no plausible reading rescues.
_RANGES: dict[str, tuple[int, int]] = {
    "usc_section": (1, 54),
    "cfr_section": (1, 50),
    "federal_register_cite": (1, 100),
    "us_reports_cite": (1, 610),
    "statutes_at_large": (1, 140),
}


def _leading_number(value: str, pattern: str) -> int | None:
    match = re.match(pattern, value)
    return int(match.group(1)) if match else None


def implausible(kind: str, value: str) -> str | None:
    """Why this canonical key cannot be the thing its rule names, or ``None``.

    The rollup measured its rules against *lookalikes* -- strings that match a
    pattern and are not the key. This is the mirror check it never ran, on the
    surviving yield only: a key that survives the MODS comparison is one a
    contract would actually be built on, so a false positive there is a row
    that would be published. It is deliberately conservative -- every bound is
    the publisher's real range with slack -- because the cost of flagging a
    real key is higher than the cost of carrying a suspect one into a note.
    """
    if kind == "public_law":
        congress = _leading_number(value, r"(\d+)-")
        if congress is not None and not 1 <= congress <= CURRENT_CONGRESS:
            return f"names Congress {congress}; the {CURRENT_CONGRESS}th is sitting"
    if kind == "bill_number":
        number = re.search(r"(\d+)$", value)
        if number and (number.group(1).startswith("0") or number.group(1) == "0"):
            return "a bill number is never zero-padded"
    if kind == "docket_number":
        year = _leading_number(value, r"[A-Z]+(\d{4})")
        if year is not None and not 1900 <= year <= 2026:
            return f"names docket year {year}"
    if kind in _RANGES:
        low, high = _RANGES[kind]
        first = _leading_number(value, r"(\d+)")
        if first is not None and not low <= first <= high:
            return f"leading number {first} is outside {low}-{high}"
    if kind == "dollar_amount" and (re.fullmatch(r"0+", value) or len(value) < 2):
        # Not a false positive -- ``$0`` is a real figure -- but not a key a
        # join can be built on either, so it is reported apart from the rest.
        return "not usable as a join key"
    return None


def _evidence(text: str, kind: str, value: str) -> str | None:
    """The first place in the print this canonical key was read from, with its context."""
    rule = next((candidate for candidate in JOIN_KEY_RULES if candidate.name == kind), None)
    if rule is None:
        return None
    for match in rule.compiled().finditer(text):
        raw = match.group(0)
        if rule.canonical(raw) != value:
            continue
        start, end = max(0, match.start() - 70), min(len(text), match.end() + 70)
        return " ".join(text[start:end].split())
    return None


def lossy_dollar_keys(text: str) -> dict[str, list[str]]:
    """Dollar keys behind which the print states more than one amount.

    ``dollar_amount``'s canonical reduces to alphanumerics, which erases the
    decimal separator, so ``$28.4 billion`` and ``$284 billion`` are one key.
    Every other rule's canonical erases only punctuation and case the two
    publishers spell differently -- ``P.L. 117-2`` and ``Public Law 117-2``
    are one law and collapsing them is the point -- so the check is applied
    here alone, and only where the raw spellings still differ once the
    currency sign, thousands separators and whitespace are removed.

    It runs against the yield in the deflating direction: a lossy key makes
    the distinct count *smaller* than the number of amounts the print states,
    and makes the key itself useless for a join.
    """
    spellings: dict[str, set[str]] = {}
    rule = next(candidate for candidate in JOIN_KEY_RULES if candidate.name == "dollar_amount")
    for match in rule.compiled().finditer(text):
        raw = " ".join(match.group(0).split())
        spellings.setdefault(rule.canonical(raw), set()).add(re.sub(r"[$,\s]|,$", "", raw))
    return {key: sorted(values) for key, values in spellings.items() if len(values) > 1}


def congress_blind_exposure(facts: Mapping[str, Any], printed: Sequence[str], package_id: str) -> list[str]:
    """Print bill keys the MODS dates to a Congress other than the package's own.

    This is exactly what the congress-blind comparison could hide: if a print
    names a bill of an earlier Congress, matching on ``type+number`` alone
    calls it stated while a ``natural_key`` match with the package's Congress
    imputed would not. Measuring it turns the caveat from a worry into a
    number.
    """
    match = re.search(r"-(\d{2,3})[a-z]", package_id)
    if match is None:
        return []
    congress = match.group(1)
    congresses: dict[str, set[str]] = {}
    for key in facts["bill_natural_keys"]:
        stated, kind, number = key.split("-", 2)
        congresses.setdefault(_alnum(f"{kind}{number}"), set()).add(stated)
    return sorted(value for value in printed if (stated := congresses.get(value)) and congress not in stated)


def sanity_flags(text: str, comparison: Mapping[str, Any]) -> dict[str, Any]:
    """Every surviving key this document contributes that cannot be what its rule names."""
    flagged: dict[str, list[dict[str, str]]] = {}
    for kind, cell in comparison.items():
        for value in cell["print_only"]:
            reason = implausible(kind, value)
            if reason is None:
                continue
            flagged.setdefault(kind, []).append(
                {"value": value, "reason": reason, "evidence": _evidence(text, kind, value) or ""}
            )
    lossy = lossy_dollar_keys(text)
    return {
        "flagged": flagged,
        "lossy_dollar_keys": len(lossy),
        "lossy_dollar_examples": {key: lossy[key] for key in sorted(lossy)[:5]},
    }


# --- the uncapped re-read ------------------------------------------------------------


def uncapped(receipt: Path, source_receipt: Path, families: Sequence[str]) -> None:
    """Re-read the retained PDFs with the 60-page cap removed, and compare again.

    The result this whole recheck turns on -- that a GovInfo print names no bill
    and no law its own MODS does not already state -- was measured on a read
    the rollup capped at 60 pages. A capped read can only *understate* what the
    print names, so "print-only is zero" could be an artifact of the cap rather
    than a fact about the document. This relaxes exactly that constraint: same
    rules, same MODS, every page of every retained PDF, no request at all (the
    bodies are in the rollup's own ``blobs/``).

    Cost is linear in pages and it is the whole reason this is a separate
    phase: the eight activity reports are 1,249 pages and the eight budget
    volumes 1,785, against 480 and 480 read before.
    """
    import time

    from spicy_docs.extraction import DocumentExtractor, NativeText
    from spicy_docs.extraction.gpo_normalize import normalize_gpo_pages
    from tools.analysis.pdf_family_rollup import RequestLog as RollupLog
    from tools.analysis.pdf_family_rollup import measure_keys

    rollup_log = RollupLog(source_receipt)
    rows: list[dict[str, Any]] = []
    for document in govinfo_documents(source_receipt):
        if families and document.family not in families:
            continue
        retained = receipt / "mods" / f"{_safe(document.mods_key)}.xml"
        digest = rollup_log.succeeded(document.url)
        if digest is None or not retained.exists():
            continue
        started = time.perf_counter()
        extractor = DocumentExtractor(NativeText(), tables=False)
        texts: list[str] = []
        page_count = 0
        results = extractor.extract(rollup_log.body(digest), media_type="application/pdf")
        try:
            for result in results:
                texts.append(result.text)
                page_count = result.metadata.get("page_count", page_count)
        finally:
            results.close()
        normalized, _cleanup = normalize_gpo_pages(tuple(texts))
        # The same rules the rollup ran, imported rather than restated; the
        # index argument is irrelevant here because the comparison below is
        # against the MODS, so an empty record is passed deliberately.
        whole = "\n".join(normalized)
        measured = measure_keys(whole, None)
        facts = mods_facts(retained.read_bytes())
        comparison = compare_document({name: found["distinct"] for name, found in measured["join_keys"].items()}, facts)
        # The false-positive pass runs on this read rather than in a phase of
        # its own: it needs the same text, and re-extracting 18,119 pages to
        # ask a second question of them would be the measurement paying twice.
        sanity = sanity_flags(whole, comparison)
        rows.append(
            {
                "id": document.document_id,
                "family": document.family,
                "mods_key": document.mods_key,
                "pages_read": len(texts),
                "page_count": page_count,
                "seconds": round(time.perf_counter() - started, 2),
                "mods_document_references": {
                    name: len(values) for name, values in facts["document_references"].items()
                },
                "comparison": comparison,
                "sanity": sanity,
                "congress_blind_exposure": congress_blind_exposure(
                    facts, comparison["bill_number"]["print_distinct"], document.package_id
                ),
            }
        )
        cell = comparison["bill_number"]
        law = comparison["public_law"]
        print(
            f"{document.document_id}: {len(texts)}/{page_count} pages, "
            f"bills print {len(cell['print_distinct'])} mods {cell['mods_distinct']} print-only {len(cell['print_only'])}, "
            f"laws print {len(law['print_distinct'])} mods {law['mods_distinct']} print-only {len(law['print_only'])}"
        )
    families_read = sorted({row["family"] for row in rows})
    summary = {family: _restate([row for row in rows if row["family"] == family]) for family in families_read}
    for family in families_read:
        summary[family]["sanity"] = _sanity_summary([row for row in rows if row["family"] == family])
    timings = {
        family: {
            "seconds": round(sum(row["seconds"] for row in rows if row["family"] == family), 2),
            "pages": sum(row["page_count"] for row in rows if row["family"] == family),
        }
        for family in families_read
    }
    for family, timing in timings.items():
        timing["ms_per_page"] = round(1000 * timing["seconds"] / timing["pages"], 2)
    per_document = sorted(1000 * row["seconds"] / row["page_count"] for row in rows if row["page_count"])
    timings["all"] = {
        "seconds": round(sum(row["seconds"] for row in rows), 2),
        "pages": sum(row["page_count"] for row in rows),
        "ms_per_page": round(1000 * sum(row["seconds"] for row in rows) / sum(row["page_count"] for row in rows), 2),
        "slowest_document_ms_per_page": round(per_document[-1], 1),
        "fastest_document_ms_per_page": round(per_document[0], 1),
    }
    (receipt / "uncapped.json").write_text(
        json.dumps({"documents": rows, "restated": summary, "timings": timings}, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"restated": summary, "timings": timings}, indent=2))


def _sanity_summary(documents: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per family: which surviving keys are false positives, and the restated count.

    The flagged set is a union across documents, the same way
    ``print_only_distinct_values`` is, so subtracting it from that number gives
    the count a contract would actually be built on.
    """
    flagged: dict[str, set[str]] = {}
    reasons: dict[str, dict[str, str]] = {}
    for document in documents:
        for kind, entries in document["sanity"]["flagged"].items():
            for entry in entries:
                flagged.setdefault(kind, set()).add(entry["value"])
                reasons.setdefault(kind, {})[entry["value"]] = entry["reason"]
    examples: dict[str, list[str]] = {}
    for document in documents:
        examples.update(document["sanity"]["lossy_dollar_examples"])
    exposure = sorted({value for document in documents for value in document["congress_blind_exposure"]})
    return {
        "flagged_distinct_values": {kind: len(values) for kind, values in sorted(flagged.items())},
        "flagged_values": {kind: sorted(values) for kind, values in sorted(flagged.items())},
        "flagged_reasons": {kind: dict(sorted(entries.items())) for kind, entries in sorted(reasons.items())},
        "lossy_dollar_keys": sum(document["sanity"]["lossy_dollar_keys"] for document in documents),
        "lossy_dollar_examples": {key: examples[key] for key in sorted(examples)[:5]},
        "congress_blind_exposure": exposure,
        "congress_blind_exposure_count": len(exposure),
    }


# --- the report's generated block ----------------------------------------------------

MARK_START = "<!-- generated by tools/analysis/pdf_yield_mods_recheck.py: start -->"
MARK_END = "<!-- generated by tools/analysis/pdf_yield_mods_recheck.py: end -->"

#: The order the surviving-yield table reads in: the keys a citation contract
#: joins on first, then the ones with no hosted target yet.
YIELD_ORDER: tuple[str, ...] = (
    "bill_number",
    "public_law",
    "usc_section",
    "statutes_at_large",
    "cfr_section",
    "federal_register_cite",
    "rin",
    "gao_product_id",
    "crs_report_id",
    "docket_number",
    "case_docket_number",
    "us_reports_cite",
    "committee_name",
    "bioguide_id",
    "dollar_amount",
    "fiscal_year",
)
_FAMILY_TITLES = {
    "house_activity": "Activity reports",
    "budget": "Budget",
    "senate_secretary": "SecSen",
}


def surviving(restated: Mapping[str, Any], kind: str) -> tuple[int, int]:
    """``(print-only distinct, flagged as impossible)`` for one family and kind."""
    cell = restated.get(kind)
    if not isinstance(cell, dict):
        return 0, 0
    flagged = restated.get("sanity", {}).get("flagged_distinct_values", {}).get(kind, 0)
    return cell["print_only_distinct_values"], flagged


def render_block(sidecar: Mapping[str, Any]) -> str:
    """The markdown between the markers, rendered from the sidecar alone.

    Every number the report leads with is here, so a report that drifts from
    its own measurement fails a test instead of being believed.
    """
    uncapped_report = sidecar["uncapped"]
    restated = uncapped_report["restated"]
    timings = uncapped_report["timings"]
    families = [name for name in ("house_activity", "budget", "senate_secretary") if name in restated]
    lines = [MARK_START, ""]
    lines.append(
        f"Measured {sidecar['measured_at']} from {sidecar['requests']['total']} keyed requests over "
        f"{len(sidecar['collection_kinds_stated'])} collections "
        f"({', '.join(f'`{name}`' for name in sidecar['collection_kinds_stated'])}). "
        f"The uncapped re-read covered {timings['all']['pages']:,} pages in "
        f"{timings['all']['seconds']:.0f} s, {timings['all']['ms_per_page']:.1f} ms/page "
        f"({timings['all']['fastest_document_ms_per_page']:.1f} to "
        f"{timings['all']['slowest_document_ms_per_page']:.1f} per document)."
    )
    lines.append("")
    lines.append("### Every bill each activity report names, against its own MODS")
    lines.append("")
    lines.append("| Report | Pages | Print, 60 pages | Print, all pages | MODS | Print-only |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    capped = {
        document["id"]: document["comparison"]["bill_number"]
        for document in sidecar["families"]["house_activity"]["documents"]
        if document.get("comparison")
    }
    for row in sorted(uncapped_report["per_document_bills"], key=lambda entry: entry["id"]):
        sampled = capped.get(row["id"], {})
        lines.append(
            f"| {row['id']} | {row['pages']} | {sampled.get('print_distinct', 0)} | "
            f"{row['print']} | {row['mods']} | **{row['print_only']}** |"
        )
    activity = restated["house_activity"]
    lines.append(
        f"| **Total** | {uncapped_report['pages_read']['house_activity']:,} | "
        f"{sidecar['families']['house_activity']['restated']['bill_number']['print_link_rows']:,} | "
        f"{activity['bill_number']['print_link_rows']:,} | "
        f"{activity['bill_number']['mods_link_rows']:,} | "
        f"**{activity['bill_number']['print_only_link_rows']}** |"
    )
    lines.append("")
    lines.append("### The surviving yield, after the false-positive pass")
    lines.append("")
    lines.append("Distinct print-only keys on the uncapped read, with the keys that cannot be")
    lines.append("what their rule names subtracted. A dash is a kind the print never stated.")
    lines.append("")
    lines.append("| Kind | MODS states it | " + " | ".join(_FAMILY_TITLES[name] for name in families) + " |")
    lines.append("| --- | --- |" + " --- |" * len(families))
    for kind in YIELD_ORDER:
        cells = []
        stated = []
        for name in families:
            total, flagged = surviving(restated[name], kind)
            cell = restated[name].get(kind)
            if isinstance(cell, dict):
                stated.append(_FAMILY_TITLES[name] if cell["mods_states_this_kind"] else "")
            if not total and not flagged:
                cells.append("—" if not isinstance(cell, dict) or not cell["mods_link_rows"] else "0")
                continue
            survives = total - flagged
            shown = f"**{survives:,}**" if survives else "0"
            cells.append(shown + (f" (−{flagged})" if flagged else ""))
        naming = ", ".join(name for name in stated if name) or "no"
        lines.append(f"| `{kind}` | {naming} | " + " | ".join(cells) + " |")
    lines.append("")
    for name in families:
        sanity = restated[name].get("sanity", {})
        flagged = sanity.get("flagged_values", {})
        reasons = sanity.get("flagged_reasons", {})
        if not flagged:
            lines.append(f"`{_FAMILY_TITLES[name]}`: nothing flagged.")
            continue
        parts = []
        for kind, values in flagged.items():
            shown = ", ".join(f"`{value}` ({reasons[kind][value]})" for value in values[:3])
            parts.append(f"{kind}: {shown}" + (f", and {len(values) - 3} more" if len(values) > 3 else ""))
        lines.append(f"`{_FAMILY_TITLES[name]}` flagged — " + "; ".join(parts) + ".")
        if sanity.get("lossy_dollar_keys"):
            lines.append(
                f"`{_FAMILY_TITLES[name]}` also carries {sanity['lossy_dollar_keys']} dollar keys behind which "
                "the print states more than one amount, because the canonical erases the decimal separator "
                f"(for example `{next(iter(sanity['lossy_dollar_examples']))}`)."
            )
    lines.append("")
    lines.append(MARK_END)
    return "\n".join(lines)


def render(sidecar_path: Path, report_path: Path) -> None:
    """Rewrite the report's generated block from the committed sidecar. No request, no PDF."""
    block = render_block(json.loads(sidecar_path.read_text()))
    report = report_path.read_text()
    start, end = report.find(MARK_START), report.find(MARK_END)
    if start < 0 or end < 0:
        raise RecheckError(f"{report_path} carries no generated-block markers")
    report_path.write_text(report[:start] + block + report[end + len(MARK_END) :])
    print(f"rendered {len(block)} characters into {report_path}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="phase", required=True)
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("--receipt", type=Path, required=True)
    fetch_parser.add_argument("--source-receipt", type=Path, required=True)
    fetch_parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    analyze_parser = sub.add_parser("analyze")
    analyze_parser.add_argument("--receipt", type=Path, required=True)
    analyze_parser.add_argument("--source-receipt", type=Path, required=True)
    analyze_parser.add_argument("--output", type=Path, required=True)
    uncapped_parser = sub.add_parser("uncapped")
    uncapped_parser.add_argument("--receipt", type=Path, required=True)
    uncapped_parser.add_argument("--source-receipt", type=Path, required=True)
    uncapped_parser.add_argument("--family", action="append", default=[])
    render_parser = sub.add_parser("render")
    render_parser.add_argument("--sidecar", type=Path, required=True)
    render_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.phase == "fetch":
        fetch(args.receipt.expanduser(), args.source_receipt.expanduser(), args.max_requests)
    elif args.phase == "uncapped":
        uncapped(args.receipt.expanduser(), args.source_receipt.expanduser(), args.family)
    elif args.phase == "render":
        render(args.sidecar.expanduser(), args.report.expanduser())
    else:
        analyze(args.receipt.expanduser(), args.source_receipt.expanduser(), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
