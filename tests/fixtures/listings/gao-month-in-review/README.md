# GAO Month in Review and Annual Index fixtures

Captured 2026-09-28 through Zyte (`httpResponseBody`, the publisher's own bytes)
because `www.gao.gov` refuses plain clients. These U.S. government pages are
public domain. Every file is the complete, unchanged response body, so the
parser meets the whole page, including the navigation, the "Jump To" list and
the footer outside `<main>`. Offline tests establish behavior for these shapes;
they do not establish coverage or continuing live availability.

| Fixture | Request | Captured | Bytes | SHA-256 | Zyte request id |
| --- | --- | --- | --- | --- | --- |
| `2026-08-page-0.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2026/August](https://www.gao.gov/reports-testimonies/month-in-review/2026/August) | 2026-09-28T17:01:33Z | 72,996 | `5db78fb10a27eb8868cfcc0214b9cd08f2b9324ff9676bcefa01757f2eb8af15` | `d26fe11a56f2ebf404b1c47331f891d6` |
| `2026-08-page-1.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2026/August?page=1](https://www.gao.gov/reports-testimonies/month-in-review/2026/August?page=1) | 2026-09-28T17:02:10Z | 73,334 | `9a87e3bdace67018aee8321abfb347e3c9db1f635505dceeee79f11777a44090` | `77d3ca9d71f8ee477278ef2aee672a70` |
| `2026-08-page-2.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2026/August?page=2](https://www.gao.gov/reports-testimonies/month-in-review/2026/August?page=2) | 2026-09-28T17:02:12Z | 74,023 | `3e2fbb6582e5d4b7554737d9fb512ff6b14e888f6580c4eaaf6ff0ce81eb1515` | `be35db698af78a560ff268e858ed45dc` |
| `2026-08-page-3.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2026/August?page=3](https://www.gao.gov/reports-testimonies/month-in-review/2026/August?page=3) | 2026-09-28T17:02:13Z | 72,006 | `91c8ae7970a293a66eee0cad10f0539b168543280822350dc9125d32c9f346de` | `53f5eb0a05d234130eae6a7c4af95e47` |
| `2025-page-49.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2025?page=49](https://www.gao.gov/reports-testimonies/month-in-review/2025?page=49) | 2026-09-28T17:03:22Z | 45,014 | `a3ff94f28285e5dd4302aeae7785ee128aeaf64ed0a907ff82b0ee36f8302fde` | `f4fb6270434bbc467a0273f4764239b5` |
| `2009-page-0.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2009](https://www.gao.gov/reports-testimonies/month-in-review/2009) | 2026-09-28T17:03:55Z | 75,400 | `b23887c36bebc81b9ac2e70a0b27d1b771e6393c3cb55c1809e6c376c6ad135f` | `b308e80e4509bdb0cf750e98f49a6cb9` |
| `2011-page-64.html` | [https://www.gao.gov/reports-testimonies/month-in-review/2011?page=64](https://www.gao.gov/reports-testimonies/month-in-review/2011?page=64) | 2026-09-28T21:06:53Z | 73,669 | `bade6e45b51777f820dd0d8fdcb62176465ca8e3894d3999f083322d820de85a` | (retained as refused evidence by the parallel backfill walk; no request id is kept for a refusal) |

The four August pages are one whole month: 100 teasers naming 73 distinct
numbers, 33 `GAO-26-` products and 40 B-numbered legal decisions, several
decisions naming more than one B-number in one teaser. `2025-page-49.html` is a
year's last page (two teasers, an overflow pager with no "Last" link);
`2009-page-0.html` is the oldest year probed, with the older product-number
forms (`GAO-09-NNN`, `-NNNT`, `-NNNR`, `-NNSP`). `2011-page-64.html` holds the first
teaser seen with an empty product-number field: an Antideficiency Act report,
linked as `/products/p00459`, which the backfill walk first refused.

The request ledger, `robots.txt`, and the other probes of that day are in
`corpora/mcp-chaos-2026-09-28/gao-sitemap/` (`requests.jsonl`, `raw/`).
