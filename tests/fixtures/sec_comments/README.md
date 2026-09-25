# SEC comments fixtures

Captured 2026-09-24 from `www.sec.gov` with the declared fair-access user
agent shape (`spicy-docs-sec-comments/1.0 (…; contact: …)`) at one request per
second, well under sec.gov's ten-per-second ceiling. That day's rule-page probe
sent the reserved placeholder mailbox (`probe-record.json` in its receipt); a
live acquirer now refuses the placeholder. Offline tests establish behavior for these shapes; they do not establish
coverage or continuing live availability.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `rulemaking-index.html` | [/rules-regulations/rulemaking-activity](https://www.sec.gov/rules-regulations/rulemaking-activity) | 10,246 | `460f6ec0e0e3de783d96da3eaf084a25993c1b83e7eccdbae9eac8245b218602` | The `cols-4` table verbatim with 4 of 48 rows — the numbered proposal (`S7-2026-33`), the slug row with an empty file-number cell (`33-11438`), a final `S7-` rule (`S7-11-23`, carrying its `View Related Activity` search link) and a multi-release rule whose status link is a descriptive slug (`S7-04-23`) — then the pagination nav trimmed to its current item (`?page=0`), one numbered item and its next-page link. Complete response 247,278 bytes, SHA-256 `e4a16b8e6f8710384ed075309150500c8f9b036c17010f1ed72da783b3cf3d94`. |
| `rulemaking-index-terminal.html` | same route, `?page=1` shape | 5,557 | `31f854f4a400a6dae5ee82cc7960f4f57c85876a5f63a38af4f6cb974b02c493` | The first 2 rows of the same capture under a constructed terminal pager: a previous link to `?page=0` and the current item `?page=1`, no next. The live pager's terminal-page HTML was not separately captured; this nav states the same shape its next-page items do. |
| `comment-listing.html` | [/comments/s7-11-23/s71123.htm](https://www.sec.gov/comments/s7-11-23/s71123.htm) | 10,092 | `9f766977daebdb0c2ab4d6bfbce9a8b3a2ba3f001dce3c7741498d5fc002afdc` | The `h1`, the three-row letter-type table (`s71123-typea.htm`, `-typeb.htm`, `-typec.pdf`) and the comments table with 5 of 30 rows — four PDFs (one a `Meeting with SEC Officials` memorandum) and the one `.html` comment (`Cory`) — then the nav verbatim (current `?page=0`, next `?page=1`). The exposed filter form and page chrome were removed. Complete response 103,711 bytes, SHA-256 `0b264caf0f2f2b4c75dd600f5e7afb077b004d793d894e3c3499f257a9e8d920`. |
| `comment-listing-terminal.html` | [/comments/s7-11-23/s71123.htm?page=3](https://www.sec.gov/comments/s7-11-23/s71123.htm?page=3) | 6,846 | `e5cffb5553087f61bf042337795c2bb6424ae06855be5450304459d67c7eec8b` | The same reductions from the real terminal page (13 rows; no next link anywhere in it) with 4 rows kept: three single-number `s71123-542242.htm`-shape files and one two-number `.htm`. Its pager was re-paged to current `?page=1` so this fixture pair walks from `comment-listing.html`'s own next link; the current item's shape is the live one. Complete response 85,241 bytes, SHA-256 `4215474722b042ef70dbc04ab6dd6df4da74f6dcdba434fb6b05640c5448fe668`. |
| `comment-letter-type-a.htm` | [/comments/s7-11-23/s71123-typea.htm](https://www.sec.gov/comments/s7-11-23/s71123-typea.htm) | 728 | `6e16e64b416fdf3a04b2e7bca33b9de18cb315db3b93d4632495969315d824d3` | Head and title through the `Letter Type A` heading, then the first 600 bytes of the letter body. The title states `File No. S7-11-23`, the identity witness an HTML file must carry. Complete response 7,492 bytes, SHA-256 `5a97ae4fe9746e6a38ae35c6d2b6b402a46921890b701d8b6c4406ac4e3471c4`. |
| `comment-file.html` | [/comments/s7-11-23/s71123-420279-1002982.html](https://www.sec.gov/comments/s7-11-23/s71123-420279-1002982.html) | 949 | `91191d11069c88d97a76fd1927281c9521b0428e8ccaa9ad125f921ccfb12504` | Head, the `Subject: File No. S7-11-23 / From: Cory` heading verbatim, and the first 800 bytes of the comment text. Complete response 13,162 bytes, SHA-256 `c3ff96fba7f6f865168f9653af75403414578ac4adc0442de9c940125c72cf83`, `content-type: text/html`. |
| `comment-file.pdf.head` | [/comments/s7-11-23/s71123-279699-683202.pdf](https://www.sec.gov/comments/s7-11-23/s71123-279699-683202.pdf) | 1,024 | `e2996337ed0288ae59addb674c8fa094bdb311e3740172b02974b37e8b3f8270` | **First 1,024 bytes only** (a Range GET), so an incomplete capture is what this file is: a real `%PDF-1.6` header and the linearization dictionary whose `/L 84116` states the complete file's length. The complete 84,116-byte body was never fetched; tests reconstruct one by padding to that stated length. |

## What the probes established on 2026-09-24

- The rulemaking index paginates with `?page=N` (29 pages that day; a
  `rel="next"` anchor ends at the last). Thirty rows to a page on the listing.
- The `S7-11-23` per-rule page states its file number, release numbers and
  FR citations through Drupal `field--name-` statement fields (`File Number`,
  `Release Number`, `Document Citation` labels), and one citation in prose
  (the extension block's `at 90 FR 2837` sentence). The live page reuses the
  `field-release-number` template for `Title` fields, so the reader honors
  the field's label, not the machine name alone.
- **SRO rule pages remain unmeasured.** The retained index states no `sr-` rows on its
  default view, its `year=2017` filter, or its `search=sr-nasdaq` view
  (which is not the `cols-4` table), and the guessed routes
  `/rules-regulations/2026/09/sr-nasdaq-2026-001`,
  `/rules-regulations/sro-rule-filings`, `/rules-regulations/sro` and
  `/rules/sro` all answered 404. Those guessed routes do not establish whether SRO
  rule pages or comments exist. The response evidence is in the probe receipt
  (`sec-comments-rule-page-probe-2026-09-24/sro-negative-evidence.json`).
- `s71123-typea.htm` is a **letter-type document** — the form letter many
  commenters submitted — not a continuation page. Continuation is the
  `?page=N` query; no `-1.htm` grammar exists on this route.
- The `S7-11-23` per-rule page
  ([/rules-regulations/2025/06/s7-11-23](https://www.sec.gov/rules-regulations/2025/06/s7-11-23))
  links the comment listing as
  `https://www.sec.gov/comments/s7-11-23/s71123.htm`, byte-identical to the
  grammar `comment_index_url` builds.
- A guessed `/comments/34-103980/34103980.htm` answered 404 (the Drupal 404
  page). That response is an observation about the guessed locator, not
  discovery and not absence of comments.
- `/comments/` itself answers 200 with `Index No Browsing`: no directory
  enumeration; the rulemaking index is the supported discovery entry point.
- Comment files carry no charset on `text/html` and state their docket in
  their own words (`File No. S7-11-23`); the one PDF probed was linearized.

## Join fixtures (2026-09-24, offline)

The join (`src/spicy_docs/sources/sec_comments/join.py`) connects the SEC
pages above with two retained corpora from
`/Users/mikewolfd/Work/corpora/supply-2026-09-02/`, and the tests run it
end-to-end over these bounded rows. The regulations.gov document attributes and Federal Register release
records were retained by the Mirrulations mirror and the `fr-full-1994-2026`
release respectively.

| Fixture | Source | Trim |
| --- | --- | --- |
| `mirror-sec-documents.jsonl` | 5 retained regulations.gov SEC document envelopes, verbatim field values, from `campaign/regs-documents-SEC` source-native blobs `sha256:0092cfc7…`, `sha256:3861bca6…`, `sha256:5a55a017…`, `sha256:c1446957…` | Each row keeps the envelope (`fieldDiagnostics`, `schemaDigest`, `schemaName`, `schemaVersion`, `scopeId`, `sourceRecordId`) and `record.data.{type,id}` verbatim, plus the `attributes` subset the join reads: `frDocNum`, `docketId`, `title`, `documentType`, `postedDate`. Dropped verbatim fields: `fileFormats`, `links`, `relationships`, the remaining null `attributes`. Original-line SHA-256 per row (in order `SEC-2005-0010-0001`, `SEC-2010-0055-0001`, `SEC-2025-1268-0001`, `SEC-2025-0062-0001`, `SEC-2023-0740-0001`): `8ac9bf77…`, `174ed7d6…`, `a24c0756…`, `0eeb5f2e…`, `f3b781ae…`. |
| `federal-register-documents.jsonl` | 5 real Federal Register release records (`releases/fr-full-1994-2026`, `source-native-records` role) for the documents the mirror rows derive to: `2023-15200`, `2010-239`, `2024-31178`, `05-18895`, `2025-12016` | Each row keeps `record.{document_number, volume, start_page, end_page, publication_date, docket_ids, title, type, agencies}` verbatim (`agencies` added 2026-09-25 from the same source lines: the join indexes SEC-agency records only). The first three name `File No. S7-11-23` and the S7-11-23 release chain (`Release No. 34-97877` / `34-102022` / `34-103320`); `2010-239` exercises the mirror's zero-padded `frDocNum` (`2010-00239`); `05-18895` the two-digit-year spelling. Original-line SHA-256 per row: `fee2e01d…`, `844f2ab7…`, `3540e241…`, `6c883b65…`, `0481af2f…`. |
| `rule-page.html` | [/rules-regulations/2025/06/s7-11-23](https://www.sec.gov/rules-regulations/2025/06/s7-11-23); 3,036 bytes, SHA-256 `67907dbe46be5144b8bb9c8372179d931158c0e5de64cd2df03afc5c43d6dc1e` | **Live capture, 2026-09-24.** The complete response (73,533 bytes, SHA-256 `dfd8ac768648928ba5bf31bcc252422b60b5660f84578bdbea6b1c9eef2e6b56`) trimmed by `tools/analysis/sec_comments_rule_page_probe.py --emit-fixture` to the nodes `parse_rule_page` reads, each verbatim: the `h1` title, the `field--name-field-file-number` / `-release-number` / `-document-citation` statement divs the `-compliance-date` div whose sentence states the `90 FR 2837` citation and the `-comments-received` div that states the listing URL — wrapped in a synthesized HTML envelope. The trim drops the page chrome, navigation and resources; two `field-release-number` fields whose label is `Title` (the live page reuses that template for titles) remain verbatim but do not become release-number statements because the reader honors the field label. |
| `rule-page-full.html` | The same request; 73,533 bytes, SHA-256 `dfd8ac768648928ba5bf31bcc252422b60b5660f84578bdbea6b1c9eef2e6b56` | **The complete response, unmodified**, copied from receipt `sec-comments-rule-page-probe-2026-09-24/rules-regulations_2025_06_s7-11-23.html`. Kept so the tests prove the trim against the real page: `--emit-fixture` on it reproduces `rule-page.html` byte for byte, and both parse equal. |


## Complete incremental PDF regression (2026-09-25 UTC)

`comment-file-incremental.pdf` is the exact 69,393-byte response from
[s71123-518235-1491262.pdf](https://www.sec.gov/comments/s7-11-23/s71123-518235-1491262.pdf).
SHA-256: `39b8736b6cbd98b2cca828176562afdb1380da53d51a631b3469991e36fefcd4`. It retains an original `/L 65314`
linearization hint and an appended revision ending at byte 69,393; the final
`startxref` points to its appended cross-reference stream. The complete response
and listing are pinned in
`scraper-completion-2026-09-24T235248Z/fcc-sec/sec-full/`.
The mismatch is valid: ISO 32000-1 table F.1 requires treating such a file as
ordinary PDF. Tests also reject incomplete appended revisions and the original
truncated first-page fixture.

## Publisher-stated discovery regression (2026-09-25 UTC)

The delivery campaign selected the following rule URLs directly from its
retained rulemaking index (`sha256:00921f3b51fc81f3e9fbbf7f2e57c37612c44a06b015e82f7230173c4751ba44`).
Every request used the declared SEC agent and one-second pacing. Full captures,
timestamps, methods, response metadata and full/trimmed parser parity are in
`scraper-delivery-2026-09-25T003133Z/sec/`.

| Fixture | Source and retained evidence | Transformation |
| --- | --- | --- |
| `rule-page-slug.html` | [Electronic Submission rule page](https://www.sec.gov/rules-regulations/2025/09/electronic-submission-certain-material-under-securities-exchange-act-1934-amendments-regarding-focus); full 75,572 bytes, SHA-256 `f7878db02ce79f33b61f564bd2485a4df06e33e92caf1eadf6c66d351f302a3c`; fixture 3,566 bytes, SHA-256 `90867235b1119b5f0ef6e9ddd3943e540f37fc63e0078ee6788d493b026be1ad` | The probe tool retains the title and marked fields verbatim, including `field-comments-received`. The descriptive slug page states `/comments/s7-08-23/s70823.htm`. Its full and trimmed parses are equal. |
| `rule-page-no-listing.html` | [Modernization of Delegations rule page](https://www.sec.gov/rules-regulations/2026/07/modernization-delegations-authority-commission-staff); full 65,640 bytes, SHA-256 `983ecc1811b4688b96087f708cfff5ea56c8f47edf0c8d5b1cf6a4ca93c7b5cc`; fixture 473 bytes, SHA-256 `6e15e8de95f653ebd2246ddbb4b408dc85b83952feca50e63bcfbebaa27ed16e` | The same verbatim-node trim. Neither its full nor trimmed page states a file number or received-comments link; the release is `33-11431`. This qualifies the no-link observation, not absence of comments. |
| `comment-listing-case.html` | [S7-08-23 listing](https://www.sec.gov/comments/s7-08-23/s70823.htm); full 100,289 bytes, SHA-256 `4564977a51ebffc747dddf233f5b7df4d5e799e8f6e5118c9088349233f566b5`; fixture 4,504 bytes, SHA-256 `f7eaa022ccd9e5f8d26ecfec2e3e7b2bd3e8d09ddf9233a485c69dd0b4f28b87` | Verbatim title, section table, first comment row and pager in a synthetic HTML wrapper; other comment rows removed. The retained row states `/comments/S7-08-23/s70823-810619-2468353.pdf`. Docket comparison ignores case while file acquisition preserves this exact URL. The row, section and pager parse equal their full-response counterparts. |
