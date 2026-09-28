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
  feed's own `<Link>` states, so the two join. **Except the 112th and 113th**,
  whose BILLSTATUS states no estimate; their rows come from this feed
  ([below](#the-112th-113th-estimates-come-from-this-feed)).
- **The letter text is reprinted verbatim in the bill's committee report**, for
  the 883 of 1,368 scored bills of the 118th (64.5%) that have one;
  `committee_reports` carries its span.
- **The summary cost card is a raster** in every rendition, so no figure is
  published by either table.

See [the routes measurement](../research/cbo-cost-estimate-routes-2026-09-20.md)
and [what landed](../research/cbo-cost-estimates-build-2026-09-20.md). This
feed remains the route to CBO's *own* spelling of the measure, which no GovInfo
route states.

## The 112th-113th estimates come from this feed

GovInfo's BILLSTATUS states no `<cboCostEstimates>` item for the 112th or
113th Congress: none in 12,299 and 10,637 documents of every bill type (one
113th document, H.R. 4200, has an empty element), where the 111th's state
2,156 items in 902 documents. So those Congresses' `cbo_cost_estimates` rows
are built from this feed, `source` `cbo_feed`
(`interpretation.bill_family.build_cbo_feed_cost_estimates`).

Congress.gov's bill record is not a second route. Its 112th-113th lists are
this feed regrouped by `Bill_Number`: the same instants, titles and texts, the
feed's wrong numbers followed (112 H.R. 1707 lists CBO's estimate of S. 1707),
and nothing for an item whose `Bill_Number` is empty. A keyed reader for it
was built and sampled (56 requests, 2026-09-28) and removed when the
independent review showed this; the branch history keeps it.

**Which bill an item names.** `feed_item_bills(congress, bill_number)` reads a
`Bill_Number` as a measure type's abbreviation words, each ended by a period, a
space or both, then the number, in the feed's own Congress. Every form in the
108th-119th feeds is that shape: `H.R. 8`, `S. 2241`, `H. J. Res. 48`,
`H.J.Res. 124`, `S.J.Res. 44`, `H.Con.Res. 103`, `H.R.681`, `S.  1591`,
`H.r. 4679`. No item names more than one bill. Anything else refuses with
`CboFeedBillError`, field `bill_number` and its shape: a bare number (117th
`700`), an amendment (116th `S.A. 948`), trailing text (119th `H.R. 7529,`) or
a list. Where `Bill_Number` is empty, `title_bills(congress, title)` takes the
citation the title leads with, in the same grammar written capitalized
(`H.R. 4402, Critical Minerals Policy Act of 2012`). A title that leads with
prose names no bill (`Sequester Replacement Reconciliation Act`,
`Public Law 112-8, ...`). Anything ambiguous refuses with field `title`: a
second citation of another bill (`two-citations`), a citation after the start
(`not-at-start`, the 119th's `... in Title IV of H.R. 1`) or an abbreviation and
number that is no bill type (`unknown-form`). A title is never read where
`Bill_Number` states a value. `cbo_feed_bills(feed, congress)` maps a whole
feed, marks each bill `found_by` `bill_number` or `title`, and counts the items
that name none and every refusal.

| Congress | Items | Bills | By `Bill_Number` | By title only | Items named by title | Unnamed | Refused |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 112 | 944 | 813 | 769 | 44 | 61 | 31 | 0 |
| 113 | 1,117 | 988 | 851 | 137 | 170 | 16 | 0 |

**The rows.** One row per bill and publication, through the same fold and
shaper as the BILLSTATUS route: 913 for the 112th and 1,101 for the 113th, with
no refusal. `pub_date` is the item's `Date` as the same instant in UTC, spelled
as BILLSTATUS spells it (`feed_item_pub_date`; Congress.gov lists that spelling
for all 43 sampled items). `description` is the item's text with the
surrounding whitespace this package's parser trims; the feed itself ends many
descriptions with a newline. A bill's items are ordered oldest first, because
the feed runs newest first and its order within one `Date` changes between
captures. The report citations are the bill's own BILLSTATUS
`<committeeReports>`, which the host passes in; a bill it passes none for
publishes NULL there. If BILLSTATUS and the feed ever state one bill and
publication, `merge_cbo_cost_estimates` keeps the BILLSTATUS row.

**A wrong number stays visible.** Every row, on either route, carries
`title_bill_id`: the bill its own title leads with. Over the 108th-119th
(2026-09-28) it differs from `bill_id` on 5 BILLSTATUS rows and 5 feed rows,
and there `bill_id` is wrong: 112 H.R. 1707 for S. 1707, 115 S. 2416 for S.
2461, 117 S. 2671 for S. 2761, 119 H.R. 648 for H.R. 658 and 119 H.R. 5201 for
H.R. 5021 on the feed, the last four on BILLSTATUS too, and 114 H.R. 3347 for
H.R. 3447 on BILLSTATUS alone, whose feed item states 3447. A wrong Congress is
not seen: the 112th feed files P.L. 111-322 under H.R. 3082, the 111th
Congress's number.

Receipts, with the feeds' bytes and every script:
`~/Work/corpora/fork-execution-2026-09-21/cbo-112-113/` (`feeds/`,
`title-bill/title-bill.json`).

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

Owner: [`cbo.py`](../../src/spicy_docs/sources/cbo.py); the rows are shaped in
[`bill_family.py`](../../src/spicy_docs/interpretation/bill_family.py).

```sh
uv run --frozen pytest -q tests/test_cbo.py tests/test_cost_estimate_tables.py
```

The qualification tests read the receipt directory outside this repository and
skip when it is absent; re-pin before trusting a run in which they skipped.
There is no PDF fixture on purpose — no publisher PDF is obtainable keyless, so
the tests build minimal PDF bytes inline rather than shipping bytes that are
not CBO's beside bytes that are.
