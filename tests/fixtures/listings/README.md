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
| `house-vote` | `GET house-vote/119/1?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (roll 240, `updateDate` 2025-09-09T18:53:19-04:00) and identical declared count (362) — sort ignored | 2026-09-19 |

`CongressListRoute.sort_honored` and `.window_honored` for both routes are set
from these four observations: `committee-bills` is `sort_honored=False,
window_honored=True`; `bill-actions` is `sort_honored=False,
window_honored=False`. Every other route's `window_honored` stays the
dataclass default (`True`), which is a carried-forward assumption from
`bill`/`crsreport`'s original, always-accepted contract, not a measurement —
see `sources/congress/listing.py`'s module docstring.

`house-vote`'s `sort_honored=False` was carried over from an indirect
inference (the sibling `house-vote/{c}/{session}/{roll}/members` route,
measured `sort ignored` in the legislative data map) until the direct probe
above replaced the inference with a measurement of the exact route this
package uses.

Fifth round, captured 2026-09-19 for the A5, A6, A7 and A10 list and detail
routes (`docs/research/closing-the-gaps-2026-09-19.md`; api.data.gov key as
`X-Api-Key`, list pages at `limit=3` except where the query itself narrows
to fewer rows). Each response's `request` echo block was checked
byte-for-byte against the key with `scrub_credential` before it was saved;
none of the twelve carried it.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `congress-committee-meeting-list.json` | GET https://api.congress.gov/v3/committee-meeting/119/house | 1,118 | `4465958620844652d282f2edb1c68c82c246f6ccfbedc5a0c3c16b3073a93ad6` | Complete, unchanged response; 3 of a declared 1,611. |
| `congress-committee-meeting-detail.json` | GET https://api.congress.gov/v3/committee-meeting/119/house/119565 | 31,002 | `ff5d18f60faa03557b2384032c627ca8f839d910a0c4627da882d587b281b134` | Complete, unchanged response; one record, chosen over two other captured event ids because it carries `relatedItems.bills` (the meeting->bill edge). |
| `congress-treaty-list.json` | GET https://api.congress.gov/v3/treaty/119 | 978 | `d1b33e8cbb8f7575f7e42bc53349bdde59672e4214016552c6dac0e22cdd9995` | Complete, unchanged response; the 119th Congress answers only 2 treaties, fewer than `limit=3`. |
| `congress-treaty-detail.json` | GET https://api.congress.gov/v3/treaty/119/2 | 2,288 | `dd485a871156da2b7131ef433dafda7712dd56998e0e74cfe57023b6fa69dcef` | Complete, unchanged response; the same treaty the legislative data map's `treaty->cdoc` edge resolved. |
| `congress-daily-congressional-record-list.json` | GET https://api.congress.gov/v3/daily-congressional-record | 1,318 | `85aa4fb9633e81a56863a9d064755d74dc8515c4b7dcbaa9aff69f6c1d0dddac` | Complete, unchanged response; 3 of a declared 5,869; captured bare (no volume) since the route's own bare listing is a supported, measured shape. |
| `congress-daily-congressional-record-detail.json` | GET https://api.congress.gov/v3/daily-congressional-record/172/148 | 2,076 | `c1f40d70becc51ae15b5fc6202754f81c718e848d80e5003a20b7e73dc78b541` | Complete, unchanged response. |
| `congress-house-communication-detail.json` | GET https://api.congress.gov/v3/house-communication/119/ec/4752 | 1,758 | `444e2e99526f5b1955f7bd8658f6b2981dbabaa95e0c9abc8de3a397c739c2a5` | Complete, unchanged response; the same EC 4752 record the legislative data map's `communication-typing`/`communication->committee`/`communication->federal-register`/`communication->requirement` edges resolved. |
| `congress-senate-communication-list.json` | GET https://api.congress.gov/v3/senate-communication/119 | 1,462 | `eb134534e308e27e730010e567f55b4d41874b203bfa3d84badb283b56e2e80e` | Complete, unchanged response; 3 of a declared 4,842. |
| `congress-senate-communication-detail.json` | GET https://api.congress.gov/v3/senate-communication/119/ec/4712 | 1,319 | `2ddfee041eb8566680d13c99b1e7a51703f68023fc04e7f067c12741f98a9d0d` | Complete, unchanged response; the same EC 4712 record the map's `senate-communication->committee` edge resolved. |
| `congress-house-requirement-list.json` | GET https://api.congress.gov/v3/house-requirement | 793 | `4ae32fd2772d0168874871e52e3adbbe9f71f60be230d9e2ae4d313c95ad5400` | Complete, unchanged response; 3 of a declared 3,226. |
| `congress-house-requirement-detail.json` | GET https://api.congress.gov/v3/house-requirement/8070 | 761 | `089f7d77eb02d82004e7edfb3c21d7d596c03abf21fe9aa76f1d21a9dd2dc494` | Complete, unchanged response; requirement 8070, the CRA requirement the map's `requirement->communications` edge and `communication->requirement` edge both name. |
| `congress-house-requirement-communications.json` | GET https://api.congress.gov/v3/house-requirement/8070/matching-communications | 1,286 | `098e062b5bfa7d8b62ced73b60783784399e6a5cedaff643fa6cc7b06eac91a3` | Complete, unchanged response; 3 of a declared 92,450. |

Congress.gov spells a detail record's row two different ways, both
confirmed live 2026-09-19: `house-communication`, `daily-congressional-record`,
`senate-communication` and `house-requirement` detail nest a single JSON
object under their records key (`{"houseCommunication": {...}}`), while
`treaty` detail nests a one-element array instead
(`{"treaty": [{...}]}`). `reading/paged_json.py`'s `_read_page` now reads
either shape as a one-row page with no declared count and no continuation
(a single Mapping under the records key is wrapped as a one-element list
before the existing list checks run), so every field a fixture record
carries reaches `CongressListingReader.records`/`.page` unchanged, the same
way a list route's rows do.

Sort and date-window support for every new list route was measured the same
way as the fourth round's `committee-bills`/`bill-actions`/`house-vote`
probes: a keyed request pair at `limit=3`, not saved as fixtures.

| Route | Asked | Came back | Date |
| --- | --- | --- | --- |
| `committee-meeting` | `GET committee-meeting/119/house?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (eventId 119569, `updateDate` 2026-09-18T21:34:11Z) and identical declared count (1,611) — sort ignored | 2026-09-19 |
| `treaty` | `GET treaty/119?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical order both times (treaty 2 first) and identical declared count (2) — sort ignored | 2026-09-19 |
| `daily-congressional-record` | `GET daily-congressional-record?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (volume 172 issue 148) and identical declared count (5,869) — sort ignored | 2026-09-19 |
| `senate-communication` | `GET senate-communication/119?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (EC 4712) and identical declared count (4,842) — sort ignored | 2026-09-19 |
| `house-requirement` | `GET house-requirement?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (requirement 12478) and identical declared count (3,226) — sort ignored | 2026-09-19 |
| `house-requirement-communications` | `GET house-requirement/8070/matching-communications?limit=3&sort=updateDate+desc` vs `...&sort=updateDate+asc` | Identical first record both times (EC 2, 112th) and identical declared count (92,450) — sort ignored | 2026-09-19 |
| `committee-meeting` | `GET committee-meeting/119/house?limit=1` vs `...&fromDateTime=2026-09-18T00:00:00Z` | Declared count 1,611 unfiltered vs 8 with the one-day window — window honored | 2026-09-19 |
| `treaty` | `GET treaty?limit=1` vs `...&fromDateTime=2026-09-18T00:00:00Z` | Declared count 786 unfiltered vs 0 with the one-day window — window honored | 2026-09-19 |
| `daily-congressional-record` | `GET daily-congressional-record?limit=1` vs `...&fromDateTime=2026-09-18T00:00:00Z` | Declared count 5,869 both times, unchanged — window ignored | 2026-09-19 |
| `senate-communication` | `GET senate-communication/119?limit=1` vs `...&fromDateTime=2026-09-18T00:00:00Z` | Declared count 4,842 both times, unchanged — window ignored | 2026-09-19 |

`CongressListRoute.sort_honored` is `False` for all twelve new routes: the
six list routes above are measured (the pairs immediately above), and the
six `*-detail` routes are `False` by construction — a detail route answers
one record, not a list, so there is nothing to reorder. `window_honored` is
measured `True` for `committee-meeting` and `treaty`, measured `False` for
`daily-congressional-record` and `senate-communication`, and `False` by
construction for the same six detail routes. `house-requirement` and
`house-requirement-communications` keep the dataclass default
(`window_honored=True`), a carried-forward assumption, not a measurement —
consistent with `nomination`/`hearing`/`committee-report`/
`house-communication`/`house-vote` above, and noted here rather than spending
two more requests on a route whose every record already shares one frozen
`updateDate` (2021-11-05, see the third-round note above and Table A in
`docs/research/legislative-data-map-2026-09-18.md`).

Two more requests (not saved as fixtures) confirmed the bare-collection
design `optional_params` states: `GET committee-meeting?limit=1` answered a
declared count of 18,133, matching Table A's total for the route with no
`congress`/`chamber` at all, and `GET senate-communication?limit=1` answered
175,597, matching Table A's total the same way. `treaty` and
`daily-congressional-record`'s bare shape is confirmed by the window-probe
and list-fixture requests above, which already omitted `congress`/`volume`.

This round used 38 keyed requests, two over the 36-request plan: the first
two (`house-communication/119/ec/4752`, checked once to confirm the records
key before a save-to-disk helper existed, then re-fetched to print the full
record) were spent without saving bytes, so a third, saved request was
needed to capture `congress-house-communication-detail.json` with genuine,
verifiable wire bytes rather than reconstructing the file from a
`json.dumps` of the second request's console output. Every other route's
fixture, sort probe and window probe above cost exactly the one request its
row states.
