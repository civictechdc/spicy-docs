#!/usr/bin/env python3
"""Compare Federal Register document numbers with GovInfo granule ids by issue.

Read each issue's keyless MODS XML and append results to resumable JSONL. This
route never accepts or sends an API key; 401/403 aborts the run.

Interpretation rules:
- Compare exact strings. Printed colophons can fuse a number with "Filed", as
  in 95-8641-Filed. Normalizing would hide the mismatch; for E5-2394, the fused
  spelling is the only live identifier.
- Report unmatched ids in both directions. Neither count alone measures defects:
  granules include non-documents such as Reader Aids, and filing dates may differ.
- Record failed listings and exclude them from rates. Missing evidence does not
  establish zero mismatches.

Each output row pins the source release digest so resume cannot mix corpora.
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
#: Keyless MODS lists issue constituents. The keyed granules endpoint can
#: return HTTP 200 with zero results for populated issues (FR-1994-01-03).
MODS_URL = "https://www.govinfo.gov/metadata/pkg/FR-{date}/mods.xml"
USER_AGENT = "spicy-docs-govinfo-granule-census/1.0"
MODS_NS = {"m": "http://www.loc.gov/mods/v3"}


def _granules_from_mods(xml: bytes) -> list[tuple[str, str | None]]:
    """Return each granule as (accessId, FR Doc No.).

    accessId is an element under extension in the MODS namespace, not an identifier
    attribute. It keys content URLs and can retain colophon fusion such as
    95-8641-Filed. FR Doc No. is the parsed number; comparing that alone would hide
    the identifier mismatch this census measures.
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
    """Abort on 401/403 because the route's keyless premise no longer holds.

    Never retry or fall back to a key. Continuing would record refusals as apparent
    coverage; sending a key would change the run's authorized credential use.
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
    """Return granule ids, one call spent, and their count from one issue's MODS XML.

    MODS supplies all constituents without pagination. A missing MODS record returns
    404 and becomes a failed listing, rather than the keyed endpoint's empty success.
    """
    xml = _fetch_mods(client, date)
    granules = _granules_from_mods(xml)
    ids = [access for access, _frdoc in granules]
    return ids, 1, len(ids)


def _release_digest(release_root: Path) -> str:
    """Read the source release identity attached to every census row.

    Resume compares digests to prevent mixed corpora. Equal counts on a sampled
    date cannot prove two releases contain the same documents.
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
    """Return settled issues and issues to retry, using the latest row per date.

    Only status=listed settles an issue. Retry failures and incomplete listings;
    keep superseded rows in the append-only file as evidence of earlier answers.
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
