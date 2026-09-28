# CBO cost-estimate fixtures

Captured 2026-09-14, keyless, `User-Agent: spicy-docs-cbo-feed/1.0`,
`Accept-Encoding: identity`. These U.S. government responses are public domain.
Offline tests establish behavior for these shapes; they do not establish
coverage or continuing live availability. A feed is what CBO listed at that
moment, never a catalog.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `cbo-119congress-cost-estimates.xml` | [https://www.cbo.gov/rss/119congress-cost-estimates.xml](https://www.cbo.gov/rss/119congress-cost-estimates.xml) | 903 | `bc65c5a6caba2113c0044b1952aee70b269ddb55629fe5f67513315d420025f5` | XML declaration and `<response>` root with the first 2 of 1,192 items, then `</response>\n`; full response 431,257 bytes, SHA-256 `ff9e1610421cb9df077e7116b7c9a209b6d645fc1c6d03ba522361f9ae02376d`. |
| `cbo-112congress-cost-estimates.excerpt.xml` | [https://www.cbo.gov/rss/112congress-cost-estimates.xml](https://www.cbo.gov/rss/112congress-cost-estimates.xml), fetched keyless 2026-09-28 | 3,439 | `74ed346679e52735ae9076b3b5dd8ce20cf91eb6b027fc94b0209fbc3ae21a79` | The XML declaration, `<response>` root and 10 of the 944 items, each verbatim but for its `key`, renumbered 0-9 in document order (the parser requires a key equal to the position); full response 355,637 bytes, SHA-256 `806da5f90c980ee17dba23f432d38090b141782c60d5a0c136f143ab88a61535`. The items: 43626 (Bill_Number H.R. 1707, title S. 1707), 43585 (empty Bill_Number, title H.R. 4402), S. 3240's three (one titled "... Under Title I of S. 3240"), 43234 (empty Bill_Number, no citation), S. 1065's two (42930 dated 2012-01-18 and 43482 dated 2012-01-01, so oldest first is not publication-id order), 22098 (empty Bill_Number, title Public Law 112-8) and 22065 (Bill_Number H.R. 3082, title P.L. 111-322). Cut by `every-congress/cut_112_excerpt.py` in the receipt, which first reproduces the eight-item cut byte for byte. |
| `cbo-110congress-cost-estimates.excerpt.xml` | [https://www.cbo.gov/rss/110congress-cost-estimates.xml](https://www.cbo.gov/rss/110congress-cost-estimates.xml), fetched keyless 2026-09-28 | 354 | `19cca09dc308dd815d776917b131d099ed84b9a0754ab0ba1cef7837948f6d7f` | The XML declaration, `<response>` root and 1 of the 1,483 items, verbatim but for its `key` (0): 19115, empty Bill_Number, title "Public Law 110-50 Passport Backlog Reduction Act of 2007". Full response 572,089 bytes, SHA-256 `c92c081c63bb5d4be403fe0f187ab377bc8610cdba90813f469147e713fb9641`. |
| `cbo-datadome-challenge.html` | [https://www.cbo.gov/cost-estimates/xml](https://www.cbo.gov/cost-estimates/xml) | 767 | `47893cb4d9117b662eb765f8914c919c9bed0907b11fac94361fc7434e381f9d` | Complete, unchanged HTTP 403 response body. |

The feed has **no channel header**: CBO's per-Congress document is a
`<response>` root of `<item key="N">` elements, not RSS 2.0. The two retained
items are the two that matter for the parser: item 0 is a procedural notice
with an empty `<Bill_Number></Bill_Number>`, and item 1 carries a
`<Description>` with CBO's own interior line breaks and trailing newline.

`cbo-datadome-challenge.html` is the bot wall in front of
`/cost-estimates/xml`, `/publication/<id>` and every PDF path. Its byte count
is 767 on every observation but its SHA-256 differs per response — the body
embeds a per-response nonce — so the digest above pins this capture only, and
no test may assert it.

**There is no PDF fixture, deliberately.** No CBO estimate PDF is reachable
without solving the bot wall (the feed states no PDF locator, and the
publication page and both file tiers answer 403), so shipping a fabricated
PDF here would put bytes that are not the publisher's beside bytes that are.
`tests/test_cbo.py` builds minimal PDF bytes inline instead, and says so.

Headers, the four full per-Congress feeds, the wall probes and the
cross-capture measurement are in
`corpora/supply-2026-09-02/receipts/port-P06-cbo-2026-09-14/`.
