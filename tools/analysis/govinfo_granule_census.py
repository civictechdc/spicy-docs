#!/usr/bin/env python3
"""Enumerate govinfo's granule ids per Federal Register issue and diff ours against them.

GPO's granule ids are derived from the printed FR Doc colophon, and that
colophon carries a composition defect: on some printed pages the space between
the number and "Filed" was lost, so ``95-8641`` was filed at GPO as granule
``95-8641-Filed``. Every route keyed on the bare number then 404s. RefSpec found
that specimen on 2026-08-31 by a four-route probe; the overseer re-found it on
2026-09-05 by listing the issue package. Two routes, one mechanism.

This measures the population rather than guessing at it. A package listing
returns EVERY granule for an issue in one call (138 for FR-1995-04-10), so one
request per issue enumerates the whole corpus of ids -- no need to know in
advance which documents are broken, which is the part nobody can know.

WHAT THIS CANNOT SEE, stated because a census that reports agreement with its
own assumptions is not a measurement:

* Matching is exact string equality, deliberately. Any normalisation (splitting
  a trailing "Filed") would decide the very question being asked, and RefSpec's
  pilot attestation recorded ``reverse_substitution: forbidden`` -- for
  ``E5-2394`` the fused spelling is the only live identifier, so a "repair"
  destroys that case while fixing ``95-8641``. Unmatched is reported, never
  resolved.
* Unmatched is reported in BOTH directions and neither direction alone is "the
  defect count". Granules include non-documents (the Reader Aids section is
  served under an internal placeholder id), and our corpus may legitimately
  hold a document for a date whose granule GPO files differently or not at all.
* An issue that 404s or errors is recorded as such and excluded from the rates,
  because a failed listing is missing evidence, not evidence of zero mismatches.

The active route reads keyless issue MODS XML. It never accepts or sends an API key.

Resumable by design: results are appended per issue as JSONL and an existing
output file is read first, so a run interrupted at hour two resumes rather than
re-spending the quota.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

import httpx

from spicy_docs.source_native import ROLE_RECORDS
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

# Shared capped exponential backoff with full jitter; this tool decides which
# status and transport errors are retryable.
from spicy_docs.transport.retry import retry_http

MANIFEST_PATH: tuple[str, str] = ("manifests", "source-native.json")
#: The KEYLESS enumeration route, and the complete one. Measured 2026-09-05:
#: the keyed api.govinfo.gov granules endpoint returned ZERO granules for 33 of
#: 58 sampled 1994 issues while reporting HTTP 200 and its own declared count of
#: 0 -- so it looked like a clean answer and was missing metadata. mods.xml
#: returned all 105 granules for FR-1994-01-03, where the keyed route returned
#: none. The patchy route was also the one that spent the credential.
MODS_URL = "https://www.govinfo.gov/metadata/pkg/FR-{date}/mods.xml"
USER_AGENT = "spicy-docs-govinfo-granule-census/1.0"
MODS_NS = {"m": "http://www.loc.gov/mods/v3"}


def _granules_from_mods(xml: bytes) -> list[tuple[str, str | None]]:
    """Every granule of an issue, as (accessId, FR Doc No.).

    Written against a saved sample rather than a description of the format,
    which is why it does not look like the description: ``accessId`` is an
    element under ``extension`` in the MODS namespace, not an
    ``identifier[@type='accessId']``. An XPath built from the prose found 105
    constituents and zero ids.

    BOTH values are returned on purpose. ``accessId`` is GPO's own granule id
    and is what a content URL is keyed on, so it is what a fetch 404s against
    -- it carries the printed-colophon fusion (``95-8641-Filed``). The
    ``FR Doc No.`` identifier is the parsed number. Keying the census on the
    parsed number would compare our document numbers against document numbers
    and agree with itself; the defect only shows against the accessId.
    """
    root = ElementTree.fromstring(xml)
    out: list[tuple[str, str | None]] = []
    for item in root.findall(".//m:relatedItem[@type='constituent']", MODS_NS):
        access = next(
            (e.text.strip() for e in item.iter() if e.tag == "{http://www.loc.gov/mods/v3}accessId" and e.text),
            None,
        )
        if access is None:
            continue
        frdoc = next(
            (e.text.strip() for e in item.findall("m:identifier[@type='FR Doc No.']", MODS_NS) if e.text),
            None,
        )
        out.append((access, frdoc))
    return out


class _RetryableStatus(httpx.HTTPStatusError):
    """A 429 or 5xx worth retrying, as distinct from a 404 that is an answer."""


class CredentialRefusedError(RuntimeError):
    """A 401 or 403 aborts the run instead of being recorded and passed over.

    The enumeration route was verified keyless. If the publisher starts
    answering 401 or 403, the premise that this census spends no credential has
    failed, and the only safe response is to stop and say so. Recording it as a
    per-issue failure and continuing would walk all 1,502 issues collecting
    refusals, and -- worse -- would hide a change of terms behind a column of
    zeros that reads like coverage.

    Never retry these and never fall back to sending a key. A run authorized on
    "this spends nothing" must not quietly become a run that spends something.
    """


def _our_numbers_by_date(release_root: Path, blob_store: Path) -> dict[str, set[str]]:
    store = LocalSourceNativeBlobStore(blob_store, create=False)
    members = json.loads(release_root.joinpath(*MANIFEST_PATH).read_text())["members"]
    by_date: dict[str, set[str]] = collections.defaultdict(set)
    for member in (m for m in members if m["role"] == ROLE_RECORDS):
        with store.open(member["blobRef"]) as handle:
            for line in handle:
                record = json.loads(line)["record"]
                by_date[record["publication_date"]].add(record["document_number"])
    return dict(by_date)


def _fetch_mods(client: httpx.Client, date: str) -> bytes:
    def _attempt() -> bytes:
        response = client.get(MODS_URL.format(date=date))
        if response.status_code in (401, 403):
            raise CredentialRefusedError(
                f"govinfo answered {response.status_code} for FR-{date}: this route is "
                "supposed to need no credential. Stopping rather than continuing or "
                "sending a key."
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableStatus("retryable govinfo response", request=response.request, response=response)
        response.raise_for_status()
        return response.content

    return retry_http(_attempt, retryable=(httpx.RequestError, _RetryableStatus))


def _granule_ids(client: httpx.Client, date: str) -> tuple[list[str], int, int | None]:
    """Every granule id for one issue, from the issue's MODS record.

    One request, no pagination: a MODS package record lists every constituent
    in a single document, which is the other reason this route beats the keyed
    granules endpoint it replaced -- that one paged, and paging was where a
    short read could masquerade as a complete answer.

    Returns ids, calls spent, and the declared count. The declared count is the
    constituent count from the same document, so unlike the keyed route it
    cannot report "0 of 0" for an issue whose metadata is simply absent: a
    missing record is a 404 and is recorded as a failure, not as an empty
    success.
    """
    xml = _fetch_mods(client, date)
    granules = _granules_from_mods(xml)
    ids = [access for access, _frdoc in granules]
    return ids, 1, len(ids)


def _release_digest(release_root: Path) -> str:
    """The pinned identity of the corpus a row's counts were computed against.

    Every row carries this. Without it a resumed file can silently mix two
    corpora: on 2026-09-05 a resume ran against the pre-composite release while
    rows 1-391 had been computed against composite-2, and the 483 recovered
    documents -- 364 of them pre-2000 -- would have surfaced as "govinfo has it,
    we do not", inflating the column whose real signal is single digits.

    A single date cannot detect that swap. 1994-01-03 holds 105 documents in
    BOTH releases; only 380 of 8,170 dates differ at all. The digest is checked
    instead of the counts for exactly that reason.
    """
    artifact = json.loads((release_root / "artifact.json").read_text())
    digest = artifact.get("artifactDigest")
    if not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise SystemExit(f"{release_root}/artifact.json carries no usable artifactDigest")
    return digest


def _guard_resume_release(output: Path, digest: str) -> None:
    """Append only when every existing row names this exact source release."""
    if not output.exists():
        return
    for line in output.read_text().splitlines():
        if not line.strip():
            continue
        found = json.loads(line).get("sourceReleaseDigest")
        if found is None:
            raise SystemExit(f"{output} contains a row without sourceReleaseDigest; start a fresh output file.")
        if found != digest:
            raise SystemExit(
                f"{output} holds rows from {found} and this run's release is {digest}. "
                "Resuming would mix two corpora in one file."
            )


def _resume_state(output: Path) -> tuple[set[str], set[str]]:
    """Split what is already recorded into settled issues and ones to retry.

    Resume used to treat every recorded date as done, which is right for a
    listing and wrong for a failure: an outage writes `listing-failed` rows, and
    skipping them makes a transient 502 permanent in the census. Nine such rows
    were written on 2026-09-05 when govinfo's backend went down mid-run, and
    without this they would never be revisited.

    Only a complete listing settles a date. `listing-failed` and
    `listing-incomplete` are both returned for retry -- the second because a
    short read is exactly the case the status exists to mark as untrustworthy.

    The file stays append-only, and the LAST row for a date is the current one.
    A superseded failure is kept rather than rewritten, so the census carries
    the evidence that an issue once failed and what it answered when it did.
    """

    listed: set[str] = set()
    retry: set[str] = set()
    if not output.exists():
        return listed, retry
    for line in output.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        date = row["publicationDate"]
        if row.get("status") == "listed":
            listed.add(date)
            retry.discard(date)
        else:
            retry.add(date)
            listed.discard(date)
    return listed, retry


def census(
    release_root: Path,
    blob_store: Path,
    output: Path,
    *,
    through: str,
    min_interval_seconds: float,
    transport: httpx.BaseTransport | None = None,
) -> int:
    release_digest = _release_digest(release_root)
    _guard_resume_release(output, release_digest)
    by_date = _our_numbers_by_date(release_root, blob_store)
    dates = sorted(d for d in by_date if d <= through)
    print(f"corpus: {release_root.name} {release_digest}", file=sys.stderr)
    done, retry = _resume_state(output)
    if output.exists():
        print(
            f"resuming: {len(done):,} issues listed, {len(retry):,} to retry",
            file=sys.stderr,
        )

    todo = [d for d in dates if d not in done]
    print(f"{len(dates):,} issues in scope, {len(todo):,} to fetch", file=sys.stderr)

    with (
        httpx.Client(
            headers={"Accept": "application/xml", "User-Agent": USER_AGENT},
            timeout=httpx.Timeout(60.0, connect=30.0),
            follow_redirects=True,
            transport=transport,
        ) as client,
        output.open("a") as sink,
    ):
        last = 0.0
        for index, date in enumerate(todo, start=1):
            wait = min_interval_seconds - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            last = time.monotonic()
            ours = by_date[date]
            try:
                ids, calls, declared = _granule_ids(client, date)
            except httpx.HTTPStatusError as error:
                row = {
                    "publicationDate": date,
                    "sourceReleaseDigest": release_digest,
                    "status": "listing-failed",
                    "httpStatus": error.response.status_code,
                    "ourDocumentCount": len(ours),
                }
            else:
                granules = set(ids)
                complete = declared is None or len(ids) >= declared
                row = {
                    "publicationDate": date,
                    "sourceReleaseDigest": release_digest,
                    # A listing that returned fewer granules than the issue
                    # declares is evidence we truncated, not evidence of a
                    # mismatch; keep it out of the rates.
                    "status": "listed" if complete else "listing-incomplete",
                    "apiCalls": calls,
                    "ourDocumentCount": len(ours),
                    "granuleCount": len(granules),
                    "granuleCountDeclaredBySource": declared,
                    "matched": len(ours & granules),
                    "ourNumbersUnmatched": sorted(ours - granules),
                    "granulesUnmatched": sorted(granules - ours),
                }
            sink.write(json.dumps(row, sort_keys=True) + "\n")
            sink.flush()
            if index % 25 == 0 or index == len(todo):
                print(f"  {index:,}/{len(todo):,} issues", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--blob-store", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="JSONL, appended, resumable")
    parser.add_argument(
        "--through",
        default="1999-12-31",
        help="Last publication date to enumerate. Default limits this diagnostic to pre-2000 "
        "issues; supply a later date to include more issues.",
    )
    parser.add_argument(
        "--min-interval-seconds",
        type=float,
        default=3.7,
        help="Floor between requests. Default paces this keyless MODS diagnostic; "
        "measure the concurrency you intend to run before raising it.",
    )
    args = parser.parse_args(argv)
    return census(
        args.release_root,
        args.blob_store,
        args.output,
        through=args.through,
        min_interval_seconds=args.min_interval_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
