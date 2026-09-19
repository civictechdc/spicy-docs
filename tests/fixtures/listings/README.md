# Publisher list-page fixtures

Captured 2026-09-14 for the SpicyRegs fetcher merge, keyed pages with the
api.data.gov key sent only as `X-Api-Key`. These U.S. government responses are
public domain. Offline tests establish behavior for these shapes; they do not
establish coverage or continuing live availability. A declared count is the
publisher's statement for that query on that day.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `congress-bill-list.json` | [https://api.congress.gov/v3/bill](https://api.congress.gov/v3/bill?format=json&limit=2&sort=updateDate+desc) | 2,124 | `04330a045f6a6a390caa35330595220f83120f59a9a473786ef9d3bed993e9db` | Complete, unchanged response. |
| `congress-crsreport-list.json` | [https://api.congress.gov/v3/crsreport](https://api.congress.gov/v3/crsreport?format=json&limit=2&sort=updateDate+desc) | 1,057 | `789e5cc59088c99d346edc39d985885ed820f416d8d18bc11502034937c67c3c` | Complete, unchanged response. |
| `govinfo-published-cfr.json` | [https://api.govinfo.gov/published/2025-01-01/2025-01-31](https://api.govinfo.gov/published/2025-01-01/2025-01-31?offsetMark=*&pageSize=2&collection=CFR) | 701 | `812aad43c6741776ca6791a29ceaf507706c3e45f2e729c687b8438923a4bc9e` | Complete, unchanged response. |
| `govinfo-package-granules.json` | [https://api.govinfo.gov/packages/CFR-2025-title1-vol1/granules](https://api.govinfo.gov/packages/CFR-2025-title1-vol1/granules?offsetMark=*&pageSize=2) | 792 | `abcec8690f74d6741050e6dd505b59783cd9b9f4367bd5167dba54fe2a18d4ed` | Complete, unchanged response. |
| `gao-reports-rss.xml` | [https://www.gao.gov/rss/reports.xml](https://www.gao.gov/rss/reports.xml) | 7,088 | `47c972ab137badd153cc61fdb0da783a16fff1be451e5bad6f242a285f230ec6` | Channel header and the first 2 of 25 items; full response 104,663 bytes, SHA-256 `55657a8676877dd1b1dbc4263e1732e08e47903edd7e64da32494ce410b8b19f`. |

Headers, rate limits and the complete feed are in
`corpora/supply-2026-09-02/receipts/spicyregs-merge-probes-2026-09-14/`.
Congress.gov continuations carry an unencoded space in `sort=updateDate desc`;
GovInfo continuations carry an opaque `offsetMark`.

Second round, captured 2026-09-14 for the remaining routes (USAspending, LDA and CourtListener keyless; FCC with the api.data.gov key; SAM with the SAM.gov key, both as `X-Api-Key`):

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `usaspending-recipient-p1.json` | POST https://api.usaspending.gov/api/v2/recipient/ | 486 | `3aaffd9ee5377797ba5f17477513c6579b11d62d29efd0ba2f021b40e8937a56` | Complete, unchanged response to the POST body `{limit:2,page:1,order:desc,sort:amount,award_type:all}`. |
| `fcc-ecfs-proceedings.json` | GET https://publicapi.fcc.gov/ecfs/proceedings | 3,294 | `1f2016cd1b884d4a5bd93046ca2c4ba45daa57fa67e2ec7fe4cddf5eb2e80b48` | Complete, unchanged response. |
| `fcc-ecfs-filings.json` | GET https://publicapi.fcc.gov/ecfs/filings | 8,949 | `15d020330b9fa0c46e7878685d5f9ed2c764c003ece30f26aff678c8f668252c` | Complete, unchanged response. |
| `lda-filings-p1.json` | GET https://lda.gov/api/v1/filings/ | 6,595 | `59fe769447226fd443ade1523c86b47bc0cfc9d1f5ae7cc02be51409b1076945` | Complete, unchanged response. |
| `courtlistener-search-recap.json` | GET https://www.courtlistener.com/api/rest/v4/search/ | 51,424 | `325359abda001d8bf57682e2bca882d8374c6f37326c1129fb1bd1641a7adeeb` | Complete, unchanged response; 20 results. |
| `courtlistener-search-opinions.json` | GET https://www.courtlistener.com/api/rest/v4/search/ | 48,099 | `4b1df8c2611e95dc1ad8460d29b94602f1b65d02d0bac900b337698bdb147b59` | Complete, unchanged response; 20 results. |
| `sam-entities-p1.json` | GET https://api.sam.gov/entity-information/v4/entities | 14,826 | `7acdb03875789da24a7b06522ba9eb4d9c008261d39832fb4c3e246ae2f93b56` | Complete, unchanged response; the publisher's links carry an `api_key=REPLACE_WITH_API_KEY` placeholder. |

Third round, captured 2026-09-14 for the keyed regulations.gov API v4 document
routes (api.data.gov key as `X-Api-Key`; the attachment host takes no key):

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `regulations-gov-documents-p1.json` | GET https://api.regulations.gov/v4/documents | 9,029 | `abead3878398e785614750bc31e523641406f2aebad24edb2425bc3629b06c22` | Complete, unchanged response to `filter[postedDate][ge]=2026-09-02&filter[postedDate][le]=2026-09-02&page[size]=5&page[number]=1&sort=postedDate`; 5 of a declared 191. |
| `regulations-gov-document-detail.json` | GET https://api.regulations.gov/v4/documents/FAA-2016-6907-0001 | 2,826 | `245080749e578addcb37cef2970a3cae639ff79baad30919dc920e7b1a614fa3` | Complete, unchanged response. |
| `regulations-gov-attachments.json` | GET https://api.regulations.gov/v4/documents/FAA-2016-6907-0001/attachments | 1,479 | `089d4a805739474abd68a87ca19878a428c2144ca842ca435b739d19574b21ed` | Complete, unchanged response; two attachments, the second withheld with `fileFormats: null`. |

The list pages carry no `links` object: the two top-level keys are `data` and
`meta`, and the continuation is `meta.hasNextPage` with the current
`meta.pageNumber`. `page[size]` is 5 to 250 and `page[number]` at most 40, all
three quoted from the publisher's own HTTP 400 bodies. `meta.totalElements` is
the query's size, not what a walk can reach: one query declared 57,383 while
`totalPages` stayed at 40 for both `page[size]=250` and `page[size]=100`.
Headers, the refused 400/403/404 bodies and the rate-limit readings are in
`corpora/supply-2026-09-02/receipts/port-P05-regulations-gov-2026-09-14/`.

Fourth round, captured 2026-09-19 for the Phase 4 table-driven Congress.gov
routes (BillTrax port; api.data.gov key as `X-Api-Key`, first page of the
119th Congress list at `limit=3` except the routes with their own path
identity). Each response's `request` echo block was checked byte-for-byte
against the key with `scrub_credential` before it was written; none of the
eight carried it. `congress-house-vote-list.json` was added the same day,
closing the `house-vote` gap the table-contract design
(`docs/research/table-contracts-2026-09-19.md` §2.1) named.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `congress-amendment-list.json` | GET https://api.congress.gov/v3/amendment/119 | 1,301 | `5c851d224057f1d9ebb602f52e771f233aa853e73693fdb626d5f752d6e8aafb` | Complete, unchanged response; 3 of a declared 7,066. |
| `congress-committee-bills-list.json` | GET https://api.congress.gov/v3/committee/house/hsju00/bills | 1,691 | `eb6d81a422ca2b065ad8164b7398137b309900ae4645ee2fb8c78549ce5b6568` | Complete, unchanged response; 3 of a declared 41,822. |
| `congress-bill-actions-list.json` | GET https://api.congress.gov/v3/bill/119/hr/1/actions | 1,308 | `2696de6d3c8f861f36f130cb92390c2202ec597916e5c3b26dadb98824ddbc1f` | Complete, unchanged response; 3 of a declared 59. |
| `congress-nomination-list.json` | GET https://api.congress.gov/v3/nomination/119 | 2,960 | `e41a87e3087a7e5291c28d6c7ffec53ca4f9feaa924a4a4112e658d923696f16` | Complete, unchanged response; 3 of a declared 2,208. |
| `congress-hearing-list.json` | GET https://api.congress.gov/v3/hearing/119 | 1,001 | `4e601ff5e3854dbcdb482bc5f742e83d974674c8a4a287417c6c9e48a98e767b` | Complete, unchanged response; 3 of a declared 971. |
| `congress-committee-report-list.json` | GET https://api.congress.gov/v3/committee-report/119 | 1,411 | `8fc218474c4638bc644ed52252f247223f061f6381e51803cea9c953c9a07fd7` | Complete, unchanged response; 3 of a declared 950. |
| `congress-house-communication-list.json` | GET https://api.congress.gov/v3/house-communication/119 | 1,407 | `307ae75d21d9a01d2eedabcd1c5871966a2a16e0d13b306325e22396891a088f` | Complete, unchanged response; 3 of a declared 4,975. |
| `congress-house-vote-list.json` | GET https://api.congress.gov/v3/house-vote/119/1?limit=3 | 2,264 | `e27d5fa9fd8ce95926fdb3d4871d87cce629bdd51f97645bcf8c5f984efd9989` | Complete, unchanged response; 3 of a declared 362. |

`congress-committee-bills-list.json` contradicts the naive reading of "records
key `bills`": the publisher nests the array inside a `committee-bills` wrapper
object alongside its own `count` and `url`, not at the top level the way
every other route here answers. `CongressListRoute.records_key` for that
route is the tuple `("committee-bills", "bills")`; `reading/paged_json.py`
reads a tuple records key the same way it already reads
`count_path`/`next_path`. The other six of the original seven matched the
brief's flat top-level keys exactly (`actions`, `nominations`, `hearings`,
`reports`, `houseCommunications`); `house-vote`'s `houseRollCallVotes` does
too.

`committee-bills` and `bill-actions` initially carried `sort_honored=False`
and `window_honored` unset as dataclass defaults rather than measurements.
Probed live 2026-09-19, not saved as fixtures (each is a `limit=1` request,
not a captured page): four observations, one per route per axis.

| Route | Asked | Came back | Date |
| --- | --- | --- | --- |
| `committee-bills` | `GET committee/house/hsju00/bills?limit=1&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (`bill 110/hconres/30`, `updateDate` 2015-12-07T16:53:38Z) — sort ignored | 2026-09-19 |
| `committee-bills` | `GET committee/house/hsju00/bills?limit=1` vs `...&fromDateTime=2026-09-18T00:00:00Z` | Declared count 41,822 unfiltered vs 9 with the one-day window — window honored | 2026-09-19 |
| `bill-actions` | `GET bill/119/hr/1/actions?limit=1&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (`actionCode` E40000, `actionDate` 2025-07-04) — sort ignored | 2026-09-19 |
| `bill-actions` | `GET bill/119/hr/1/actions?limit=1` vs `...&fromDateTime=2026-09-18T00:00:00Z` | Declared count 59 both times, unchanged — window ignored | 2026-09-19 |

`CongressListRoute.sort_honored` and `.window_honored` for both routes are set
from these four observations: `committee-bills` is `sort_honored=False,
window_honored=True`; `bill-actions` is `sort_honored=False,
window_honored=False`. Every other route's `window_honored` stays the
dataclass default (`True`), which is a carried-forward assumption from
`bill`/`crsreport`'s original, always-accepted contract, not a measurement —
see `sources/congress/listing.py`'s module docstring.
