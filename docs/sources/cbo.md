# CBO cost estimates

Capture CBO's per-Congress cost-estimate feeds — exact bytes, CBO's own
spellings, and the publication link each item states. One route answers
keyless; the routes the publisher advertises for the feed and for the estimate
documents are behind a bot wall, and this module records that refusal by name
rather than pretending the route works.

## The index and the text are reachable without this route

The wall below still stands over every `cbo.gov` document path, and nothing on
this page has changed. What has changed is that the estimates themselves no
longer depend on it:

- **The index is keyless in GovInfo's BILLSTATUS bulk zips.**
  `<cboCostEstimates>` carries the `pubDate`, `title`, `url` and stage
  `description` of every estimate, two requests per Congress and type.
  `cbo_cost_estimates` hosts it ([tables](../tables.md#the-cbo-cost-estimate-is-an-index-here-and-a-span-there)),
  and the `publication_id` it parses out of each url is the same key this
  feed's own `<Link>` states, so the two join.
- **The letter text is reprinted verbatim in the bill's committee report**, for
  the 883 of 1,368 scored bills of the 118th (64.5%) that have one;
  `committee_reports` carries its span.
- **The summary cost card is a raster** in every rendition, so no figure is
  published by either table.

See [the routes measurement](../research/cbo-cost-estimate-routes-2026-09-20.md)
and [what landed](../research/cbo-cost-estimates-build-2026-09-20.md). This
feed remains the route to CBO's *own* spelling of the measure, which no GovInfo
route states.

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
so a `403` here is a bot wall, not a key being rejected. Because the route is
keyless the shared client retains the refusal body, so the wall's own answer
reaches the caller on `CboChallengeError.refused_response`; its digest still
cannot be pinned, because the challenge carries a per-response nonce (767 bytes
one way, 770 another, on the same day).

### There is no keyless route to an estimate document

Re-probed on 2026-09-14 with a complete browser-like request — Chrome 140 user
agent, `Accept`, `Accept-Language`, `Referer`, `Upgrade-Insecure-Requests` and
the three `Sec-Fetch-*` headers — every document path answered the identical
`403`, 767 bytes, `server: DataDome`, `x-datadome: protected`:

| Requested with a full browser-like header set | Answered |
| --- | --- |
| `https://www.cbo.gov/system/files/2020-07/HR1957directspending.pdf` | `403`, 767 B, DataDome |
| `https://www.cbo.gov/cost-estimates/xml` | `403`, 767 B, DataDome |
| `https://www.cbo.gov/publication/62720` | `403`, 767 B, DataDome |
| `https://www.cbo.gov/rss/119congress-cost-estimates.xml` (control) | `200`, 431,257 B, no `x-datadome` |

The control matters: the same client, same headers, same second — so the headers
are not what is refused, and the wall is path-scoped rather than client-scoped.
The 767 bytes are a JavaScript challenge (`Please enable JS`, a DataDome `dd`
blob with a per-response `cid`); passing it means executing that script, which
no header set can do, and this module does not try.

Nor is there another host to ask. CBO's own retained markup names only
`www.cbo.gov` paths for its assets — `/system/files/*`, `/sites/default/files/*`,
`/themes/custom/*`, `/modules/contrib/*` — plus social and analytics hosts and
`js.datadome.co`. No CDN, no `files`/`static` host, and the feed's `<Link>` is a
publication *page*, never a PDF locator. The only unwalled paths observed are
`/rss/{congress}congress-cost-estimates.xml` and `/sites/default/files/css/*`.

**So the estimate documents have no keyless route, and a browser-backed
transport is the only path.** `CboAcquirer` already takes one: inject a
`transport` — [`transport/zyte.py`](../../src/spicy_docs/transport/zyte.py) is
that shape over the [`sources/zyte.py`](../../src/spicy_docs/sources/zyte.py)
adapter — and the locator grammar, the byte bounds and the three identity
proofs below apply unchanged.

**Measured 2026-09-20: the proxy did not get past this wall either.** With a
`ZYTE_TOKEN`, nine walled URLs — eight `/publication/{id}` pages the feed
itself stated, and one `/system/files/*.pdf` — were requested through Zyte,
eleven attempts in all, two of them repeated in `browserHtml` mode. **No
estimate document was obtained.** What those eleven failures are matters: 3
carry Zyte's own `/download/temporary-error` slug, and the other 8 are a bare
provider HTTP 520 — the proxy's transport failing, which by this repository's
own rule cannot establish a publisher's answer. So the measurement says this
proxy could not fetch these paths; it does **not** say CBO refused the proxy.
The direct `403`s above remain the evidence that CBO itself refuses. The control matters as much as the refusals: the *unwalled*
`/rss/119congress-cost-estimates.xml` fetched through the same proxy, in the
same session, returned 432,572 bytes with digest `910aab10…`, byte-identical to
the keyless capture — so the transport works and the wall is path-scoped, not a
wiring fault. The receipt is
`corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20/`; the
earlier finding stands unchanged, that the default transport cannot reach a
document, on four paths, on two days, with and without browser headers.

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

**`index` is where an item sat in that capture, not a handle on the item.** Two
captures of the 119th feed nine hours apart on 2026-09-14 hold the same 1,192
items, byte-identical in all five fields of every one, both strictly newest-first
— and differ in 76 positions, every one of them a swap inside a run of items
sharing one `Date`. The order within a `Date` is not stable, so a changed digest
on this feed is not evidence the feed changed, and only `publication_id`
identifies an item across captures.

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
both the locator and a `transport` that can pass the wall. Without such a
transport the estimate documents are unavailable, and no amount of retrying or
of adding headers changes that.

## Evidence

Reduced pinned bytes with digests: [`tests/fixtures/cbo/README.md`](../../tests/fixtures/cbo/README.md).
Full feeds, headers, wall probes, and the cross-capture measurement:
`corpora/supply-2026-09-02/receipts/port-P06-cbo-2026-09-14/`. The browser-header
probes, the control, and the second 119th-Congress capture:
`corpora/supply-2026-09-02/receipts/publisher-questions-2026-09-14/q3-cbo-bot-wall/`.
One request per URL: the `403`s do not establish that the wall is permanent or
global, and the `200` does not establish a reliable route.

The parser is qualified against six real captures — the 116th, 117th, 118th and
119th Congresses on 2026-09-14, the 119th again nine hours later, plus RefSpec's
119th from 2026-08-04 — totalling 7,425 items, every one of which satisfies every
rule above.

| Congress | Captured | Bytes | Items |
| --- | --- | --- | --- |
| 116 | 2026-09-14 13:27Z | 439,228 | 1,259 |
| 117 | 2026-09-14 13:24Z | 420,685 | 1,191 |
| 118 | 2026-09-14 13:24Z | 560,335 | 1,533 |
| 119 | 2026-09-14 13:15Z | 431,257 | 1,192 |
| 119 | 2026-09-14 22:03Z | 431,257 | 1,192 |
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
