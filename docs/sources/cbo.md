# CBO cost estimates

Capture CBO's per-Congress cost-estimate feeds — exact bytes, CBO's own
spellings, and the publication link each item states. One route answers
keyless; the routes the publisher advertises for the feed and for the estimate
documents are behind a bot wall, and this module records that refusal by name
rather than pretending the route works.

## What answers, and what does not

| Route | Answered 2026-09-14 | Credential |
| --- | --- | --- |
| `https://www.cbo.gov/rss/{congress}congress-cost-estimates.xml` | `200`, `text/xml`, 420–560 KB | none |
| `https://www.cbo.gov/cost-estimates/xml` | `403` DataDome challenge | none exists |
| `https://www.cbo.gov/publication/<id>` (the link every item states) | `403` DataDome challenge | none exists |
| An estimate PDF under `/system/files/` or `/sites/default/files/` | `403` DataDome challenge | none exists |

The wall is not user-agent gating — a current Chrome UA gets the identical
refusal — and it is not a cookie round-trip: presenting the `datadome` cookie
the wall itself set changes nothing. `CboChallengeError` names it. It is
deliberately *not* a `CredentialRefusedError`: this family holds no credential,
so a `403` here is a bot wall, not a key being rejected. The shared client
refuses `401`/`403` before reading a body, so no challenge bytes reach the
caller through this route; the pinned challenge bodies are in the receipt below.

## Read the document shape correctly

A per-Congress feed is **not RSS 2.0** and has no channel header. It is CBO's
own XML: a `<response>` root whose children are `<item key="N">` elements
carrying exactly five fields.

```xml
<?xml version="1.0"?>
<response><item key="0"><Title>S. 4429, Connected Vehicle Security Act of 2026</Title>
<Date>Fri, 11 Sep 2026 16:47:00 -0400</Date>
<Link>https://www.cbo.gov/publication/62720</Link>
<Description>As ordered reported by the Senate Committee …</Description>
<Bill_Number>S. 4429</Bill_Number></item></response>
```

- `key` must equal the item's 0-based position in document order.
- `Title`, `Date` and `Link` must be non-empty. `Link` must match
  `https://www.cbo.gov/publication/<digits>` exactly and be unique in the feed;
  it supplies `publication_id`.
- `Description` and `Bill_Number` may be empty, which is a real value —
  procedural items such as the weekly House suspension-calendar notices publish
  `<Bill_Number></Bill_Number>` — and reads as `None`, not as drift.
- Surrounding whitespace is trimmed. Interior text, including CBO's own line
  breaks inside `Description`, stays verbatim, as do `&#x2019;`-style
  references once resolved.
- **An unknown child element refuses the whole feed.** There are no Topic
  labels, budget-function codes, UMRA mandate flags or PAYGO flags in these
  bytes. Those fields appear only in RefSpec's `cbo-cost-estimates-mini.xml`,
  which that module's docstring states is a structural reconstruction of the
  walled feed, not a capture. Refusing an unknown field means the day CBO
  publishes one it is visible instead of silently dropped.

A feed is an observation, never a catalog. It is also not a recent-items
window: a per-Congress file is that Congress to date — the 119th spans
2025-01-10 to 2026-09-11 — ordered newest first. Over a 41-day gap it behaved
as append-only (below). A Congress with no file answers `404` with a Drupal
HTML page: requested-empty, not absence of the route.

## Use the route

Install the `acquisition` extra. No key, no env variable.

```python
from spicy_docs.sources.cbo import CboAcquirer, CboBudget

budget = CboBudget(max_requests=3, max_bytes=4 * 1024**2, timeout_seconds=60, min_request_interval_seconds=1.5)
with CboAcquirer(budget=budget) as cbo:
    result = cbo.acquire_per_congress_feed(119)
    print(len(result.feed.items), result.capture.sha256)
    for item in result.feed.items[:3]:
        print(item.key, item.publication_id, item.bill_number, item.date, item.title)
```

`result.capture` carries the exact bytes, both URLs, status, time and digest;
retain `capture.body`. `result.feed` is a reading of those bytes, not evidence.
`acquire_cost_estimates_feed()` reads the advertised feed with the same parser,
so a `200` that is not this shape is refused with its bytes attached — today it
raises `CboChallengeError`.

`acquire_estimate_document(url)` captures one estimate PDF and proves its
identity three ways: `Content-Type: application/pdf`, the `%PDF-` magic bytes,
and a final URL equal to the locator. The locator must be an
`https://www.cbo.gov/…​.pdf` URL with no query. **No keyless route states one**
— the feed's `<Link>` is a publication page, not a PDF — so a caller supplies
it from a channel that can pass the wall. Without such a channel the estimate
documents are unavailable, and no amount of retrying changes that.

## Evidence

Reduced pinned bytes with digests: [`tests/fixtures/cbo/README.md`](../../tests/fixtures/cbo/README.md).
Full feeds, headers, wall probes, and the cross-capture measurement:
`corpora/supply-2026-09-02/receipts/port-P06-cbo-2026-09-14/`.

The parser is qualified against five real captures — the 116th, 117th, 118th
and 119th Congresses on 2026-09-14, plus RefSpec's 119th from 2026-08-04 —
totalling 6,233 items, every one of which satisfies every rule above.

| Congress | Captured | Bytes | Items |
| --- | --- | --- | --- |
| 116 | 2026-09-14 | 439,228 | 1,259 |
| 117 | 2026-09-14 | 420,685 | 1,191 |
| 118 | 2026-09-14 | 560,335 | 1,533 |
| 119 | 2026-09-14 | 431,257 | 1,192 |
| 119 | 2026-08-04 | 375,365 | 1,058 |

Across those 41 days all 1,058 items of the earlier 119th capture are still
present and byte-identical in every field, with 134 added and none removed or
edited. That cross-check uses two independently captured files, so it can
disagree with itself; a single-file consistency check could not.

Parsing streams rather than building a tree. Measured on the 118th Congress
feed, the largest real capture: median 5.8 ms streaming against 5.6 ms for a
full tree — the same, within noise — with peak allocation 961 KiB against
2,195 KiB.

RefSpec's [`cbo_topic_codes.py`](../../../RefSpec/src/refspec/registry/cbo_topic_codes.py)
keeps the vocabulary reading of this publisher; this module is the acquisition.

## Change and check

Owner: [`cbo.py`](../../src/spicy_docs/sources/cbo.py).

```sh
uv run --frozen pytest -q tests/test_cbo.py
```

The qualification tests read the receipt directory outside this repository and
skip when it is absent; re-pin before trusting a run in which they skipped.
There is no PDF fixture on purpose — no publisher PDF is obtainable keyless, so
the tests build minimal PDF bytes inline rather than shipping bytes that are
not CBO's beside bytes that are.
