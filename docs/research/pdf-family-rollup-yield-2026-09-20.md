# What the PDF-only families would add as hosted tables

Status: measured 2026-09-20. Read-only, ten families, 118 logged requests;
nothing published, no contract built. Sidecar:
[`pdf-family-rollup-yield-2026-09-20.json`](pdf-family-rollup-yield-2026-09-20.json).
Receipt: `~/Work/corpora/supply-2026-09-02/receipts/pdf-family-rollup-yield-2026-09-20/`.
Tool: `tools/analysis/pdf_family_rollup.py`, two phases, both through
`uv run --frozen`.

The [PDF-only census](pdf-only-corpus-2026-09-19.md) named which families have
no rendition but a PDF. This measures what hosting them would be *worth*, under
the two rules the owner set:

1. **Data that already exists is not recreated from the PDF.** So each family is
   measured twice — once against its index or API record, once against its
   documents — and only the difference counts. "Already exists" is measured, not
   assumed: the same extraction rule is read off the index record and both sides
   are reduced to one canonical key before comparison, so Congress.gov's
   `{"type": "HR", "number": 7806}` and the print's `H.R. 7806` are one fact.
2. **Nothing of value that only the PDF holds may be left uncaptured**, where
   value means join keys to the [32 hosted tables](../tables.md) and structured
   content a consumer would otherwise re-read the PDF for.

## The verdict, per family

| Family | Documents read | Verdict | What only the PDF supplies | What the index already supplies |
| --- | --- | --- | --- | --- |
| **House committee activity reports** (GovInfo `CRPT`) | 8/8 | **Host as a contract** — the highest-yield family in the corpus | 940 distinct bill numbers, 67 public laws and 124 of 125 committee names, **none of them stated by the index** | `packageId`, `title`, `dateIssued`, `lastModified`, `congress` — and nothing else |
| **Report of the Secretary of the Senate** (GovInfo `CDOC`) | 8/8 | **Host as a contract** — a cost/expenditure table, not prose | 396 ruled tables in 480 sampled pages (median 5 rows × 10 columns), 2,004 distinct dollar figures, 30 public laws | The senate.gov page states a link and a label (`Full Report`, `Part I`, `Part II`) — two fields |
| **GAO reports** | 8/8 | **Host as a contract** — recommendations and cross-product citations | Recommendation sections in 5/8, *Matters for Congressional Consideration* in 1/8, 44 of the 45 distinct GAO product ids it cites are other products, 25 ruled tables | `product_id`, `title`, `link`, `guid`, `pub_date`, and a `description` that is the "What GAO Found" abstract |
| **Agency uploaded-report PDFs** (measured on Oversight.gov) | 8/8 | **Host as a contract**, but a narrow one | Recommendation sections in 6/8, 57 ruled tables, 17 fiscal years, 6 CFR cites | An unusually rich record: agency reviewed, components, report number, report type, date issued, external entity, **number of recommendations**, questioned costs, funds for better use |
| **Budget justifications** (GovInfo `BUDGET`) | 8/8 | **Host as a contract** — account tables, with a caveat | 727 distinct dollar figures, 91 U.S. Code cites, 77 public laws, 71 ruled tables, appropriation-account headings in 4/8 | `packageId`, `title` (`Appendix`, `Analytical Perspectives`, …), `dateIssued` — nothing below volume level |
| **House Clerk disclosures** | 7/8 | **Host as a contract** — but a form-extraction one, not a citation one | 56 ruled tables in 45 pages (asset/transaction grids), 102 distinct dollar figures | The yearly index states `DocID`, `Year`, `FilingType`, `FilingDate`, `Prefix`, `First`, `Last`, `Suffix`, `StateDst` — the filer and the filing, none of the content |
| **Supreme Court slip opinions** | 8/8 | **Evidence-only for citations; host the body** | 209 distinct U.S. Reports cites, 22 U.S. Code cites, 14 Statutes at Large cites, syllabus/held markers in 8/8 | The term index already states release number, date, docket, case name, **holding**, authoring Justice and citation |
| **CourtListener opinions** | 8/8 | **Evidence-only** | Nothing of its own. Every one of its 8 `download_url`s is a supremecourt.gov slip PDF, and 7 of the 8 are the same files the row above sampled (the two differ only by which revision token each route named) | 33 fields including `citation`, `docketNumber`, `dateFiled`, `judge`, `panel_names`, `syllabus`, `posture`, `procedural_history`, `scdb_id`, `lexisCite`, `neutralCite` |
| **CRS report files** | 8/8 | **Evidence-only for join keys; host the body** | 44 of 52 cited CRS report ids (report→report, which the index never states); 183 dollar figures; 22 U.S. Code cites | **Every bill the print discusses.** 0 of 36 distinct bills and 1 of 34 distinct public laws across the eight reports are absent from `relatedMaterials` |
| **CBO cost estimates** | **0/8** | **Blocked** — not obtainable, even through a paid proxy | Unknown, and it stays unknown | `Title`, `Date`, `Link` (a publication *page*), `Description`, `Bill_Number` |

## The three the owner named

### CBO's cost table: blocked, and the proxy does not change that

The census recorded CBO's documents as DataDome-walled with no keyless route.
Measured again today with a `ZYTE_TOKEN`: **nine walled URLs, eleven attempts,
two modes, all refused** with Zyte's own `/download/temporary-error`. Eight of
those nine were `/publication/{id}` pages the feed itself stated; the ninth was
a `/system/files/*.pdf` the earlier probe had named.

The control is what makes that a finding rather than a broken run: the same
proxy, the same session, fetched CBO's *unwalled* `/rss/119congress-cost-estimates.xml`
and returned 432,572 bytes with digest `910aab10…` — byte-identical to the
keyless capture taken minutes earlier. The transport works; the wall is
path-scoped and Zyte's own downloader is inside it.

So the highest-value candidate in the corpus cannot be built at all. What
survives is what the feed already gives, and that is not nothing: today's
capture of the 119th Congress holds 1,196 items, **1,140 of them naming a bill**
in `Bill_Number`, which resolves to a `congress_bills` row by the map's own
measured `cbo→bill` edge. A
`bill ↔ cost-estimate` link table is buildable today from the feed alone, with
no estimate document and no cost figures in it. Everything past that waits on a
route.

### CRS's bills-discussed: already exists — do not recreate it

This is the clearest application of rule 1 in the corpus, and it goes the other
way from what the census implied. Across the eight sampled reports the prints
name 36 distinct bills; `api.congress.gov/v3/crsreport/{id}`'s
`relatedMaterials[]` already states **every one of them**. Public laws: 34
distinct in the prints, 33 already stated, 1 new.

| Report | Bills in the PDF | Stated by the index | New | Laws in the PDF | New |
| --- | --- | --- | --- | --- | --- |
| IN12709 | 0 | 0 | 0 | 0 | 0 |
| IF12853 | 0 | 0 | 0 | 9 | 1 |
| IF13314 | 2 | 2 | 0 | 3 | 0 |
| R49351 | 5 | 5 | 0 | 2 | 0 |
| IN12576 | 1 | 1 | 0 | 1 | 0 |
| IN12418 | 3 | 3 | 0 | 4 | 0 |
| R49355 | 23 | 23 | 0 | 14 | 0 |
| IF12760 | 2 | 2 | 0 | 1 | 0 |

This result is the one the build order turns on, so it was re-derived with the
constraint relaxed and a different method: `crs-overlap-cross-check.py` in the
receipt reads `relatedMaterials[].type` and `.number` as **named fields**
rather than by pattern over rendered text, and agrees exactly. Extracting bills
from CRS PDF prose would be a keyed-route re-derivation of a keyed route's own
field, and it would be worse — a regex over print can drop a line-wrapped
`H.R.\n5509`, which `relatedMaterials` cannot.

What CRS PDFs *do* hold that nothing else does is the **report→report graph**:
52 distinct CRS report ids cited across the eight prints, 44 of them absent
from the citing report's index record. That is a real edge and it has no other
source; `relatedMaterials` covers laws and bills, never sibling reports.

### Opinions: CourtListener already carries the citations

Say it plainly, because it decides two families at once. CourtListener's own
record carries what a citation contract would be built to produce — `citation`,
`lexisCite`, `neutralCite`, `docketNumber`, `dateFiled`, `judge`, `panel_names`,
`syllabus`, `posture`, `procedural_history`, `scdb_id`, `sibling_ids` — and its
`download_url` for a Supreme Court opinion is the supremecourt.gov slip PDF
itself. There is no second acquisition to do and no metadata to re-derive.

What the slip PDF supplies that no index does is therefore exactly two things.

**The slip-opinion window before ingestion.** All eight sampled clusters carry
`citation: []`; the Court's own index gives `609/2` for all eight, which is a
preliminary-print volume placeholder, not a citation. Between a decision and its
ingestion — which for the newest of these is days and for the oldest in the
sample is months — the PDF is the only complete record of the opinion that
exists, and the Court's index is a *live render*: two captures 2.5 minutes apart
disagreed about 24 of 72 rows' links, and a link's trailing token is a revision
id. Capturing the PDF in that window is worth doing for the bytes, not for
fields.

**The body text**, and the citations inside it — 209 distinct U.S. Reports
cites, 22 U.S. Code cites, 14 Statutes at Large cites across eight opinions,
none of them in either index. CourtListener's `citation` field names how this
opinion is cited; it never names what this opinion cites. That opinion-to-
opinion edge is real yield, and it belongs in the shared
`document_citations` table rather than in an opinion-specific contract.

Everything else about an opinion is already hosted somewhere. A slip opinion
carries **no ruled table at all** (0 across 335 sampled pages), so there is no
table contract here, and the structure that does exist — syllabus, per curiam,
concurrence, dissent, found in 8 of 8 — is what the
[slip-opinion capture profile](document-capture-schema-2026-09-19.md) already
reads.

## Join-key yield

Each cell is `documents stating the key / documents read` and then
**`distinct values the index does not state`**`/distinct values found`. Blank
means zero. The bolded number is the yield: what hosting the PDF would add that
the publisher's own record does not already give.

| Key | Join target | CRS | GAO | SCOTUS | CourtL. | Activity | SecSen | Clerk | Budget | Upload |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bill_number` | `congress_bills.bill_id` | 6/8 · **0**/36 | 1/8 · **1**/1 | 2/8 · **4**/4 | 2/8 · **4**/4 | 8/8 · **940**/940 | | | 2/8 · **4**/4 | |
| `public_law` | `laws (congress, law_type, number)` | 7/8 · **1**/34 | | | | 8/8 · **67**/67 | 8/8 · **30**/30 | | 4/8 · **77**/77 | |
| `statutes_at_large` | `laws.statutes_at_large_cite` | | 7/8 · **11**/12 | 5/8 · **14**/14 | 5/8 · **13**/13 | 1/8 · **2**/2 | | | 1/8 · **6**/6 | |
| `usc_section` | `law_code_sections` | 3/8 · **22**/22 | 5/8 · **27**/28 | 6/8 · **19**/22 | 6/8 · **14**/14 | 6/8 · **15**/15 | 8/8 · **16**/16 | | 4/8 · **91**/91 | 4/8 · **5**/5 |
| `cfr_section` | CFR sections (host-side) | 3/8 · **17**/17 | 4/8 · **9**/9 | 2/8 · **4**/4 | 2/8 · **4**/4 | | | | 1/8 · **3**/3 | 5/8 · **6**/6 |
| `federal_register_cite` | `federal_register.document_number` | | 2/8 · **7**/7 | 4/8 · **7**/7 | 5/8 · **8**/8 | 1/8 · **1**/1 | | | | |
| `rin` | `federal_register.regulation_id_numbers_json` | | | | | 1/8 · **1**/1 | | | | |
| `gao_product_id` | GAO product id (`gao/files.py` key) | 1/8 · **3**/3 | 8/8 · **44**/45 | | | 1/8 · **2**/2 | | | | 2/8 · **4**/4 |
| `crs_report_id` | Congress.gov `crsreport` id | 8/8 · **44**/52 | | | | | | | 1/8 · **1**/1 | |
| `bioguide_id` | `members.bioguide_id` | | | | | | | | | |
| `docket_number` | `dockets.docket_id` | | | | | 1/8 · **1**/1 | | | | |
| `case_docket_number` | CourtListener docket | | 3/8 · **7**/7 | 6/8 · **9**/9 | 6/8 · **8**/8 | | | | | |
| `us_reports_cite` | CourtListener opinion citation | | | 8/8 · **209**/209 | 8/8 · **222**/222 | | | | | |
| `committee_name` | `committees.system_code` (by lookup) | 2/8 · **8**/8 | 6/8 · **8**/8 | | | 8/8 · **124**/125 | | 7/7 · **7**/7 | 2/8 · **14**/14 | |
| `dollar_amount` | no hosted target yet | 8/8 · **183**/183 | 6/8 · **265**/273 | 3/8 · **25**/25 | 3/8 · **25**/25 | 6/8 · **46**/46 | 8/8 · **2004**/2004 | 7/7 · **102**/102 | 6/8 · **727**/727 | 4/8 · **57**/60 |
| `fiscal_year` | no hosted target yet | 7/8 · **14**/16 | 5/8 · **23**/26 | | | 8/8 · **15**/15 | 8/8 · **35**/35 | | 6/8 · **58**/58 | 6/8 · **17**/17 |

Two results stand out and neither is where the census pointed.

**`bioguide_id` is zero everywhere.** No print in any family states a bioguide
id; every member reference is a printed name. A member join from any of these
families has to go through the `members` crosswalk by name, which is
interpretation, not acquisition — so no `document → member` contract should be
proposed on this evidence.

**The House committee activity reports are the corpus's densest join surface**:
940 distinct bill numbers, 67 public laws and 124 new committee names across eight
prints, with a publisher index that states seven fields and none of that. One
report is a whole Congress of one committee's legislative activity, and the
only place it exists in structured form is this PDF.

## Structured content

| Family | Ruled tables observed | Documents with one | Geometry (rows × cols, min/median/max) | Other structure |
| --- | --- | --- | --- | --- |
| Secretary of the Senate | 396 | 8/8 | 3/5/11 × 7/10/10 | — |
| Budget | 71 | 6/8 | 1/3/52 × 2/10/15 | appropriation-account headings 4/8, cost-table markers 2/8 |
| Agency upload (Oversight) | 57 | 7/8 | 1/4/53 × 2/4/18 | recommendation sections 6/8 |
| House Clerk | 56 | 7/8 | 2/10/23 × 2/6/8 | — |
| GAO | 25 | 8/8 | 1/8/18 × 2/3/6 | recommendations 5/8, Matters for Congress 1/8 |
| CRS | 11 | 2/8 | 2/14/59 × 3/3/3 | recommendations 2/8 |
| Slip opinions / CourtListener | 0 | 0/8 | — | syllabus or "Held" 8/8 |
| House activity reports | 0 | 0/8 | — | — |
| CBO | not measurable | — | — | — |

Two of these are negative results worth as much as the positive ones. **A slip
opinion has no ruled table at all** — its structure is the opinion division the
[slip-opinion profile](document-capture-schema-2026-09-19.md) already reads, not
a grid. And **a committee activity report has none either**: it is a long
bill-by-bill list in prose, so the contract for it is a citation contract, never
a table contract.

Table geometry is PyMuPDF's `find_tables()` through
`DocumentExtractor(..., tables=True)`, so it finds a table only where the print
carries a ruled grid, and reports one row per ruled band. The Senate's
expenditure volumes are the best case in the corpus: consistently 5–6 rows of
9–10 columns, which is a printed account block with its own ruling.

## The extraction rule per join key

Each rule below is what a `document_citations` builder would run. Every one was
measured on the sample and each carries the lookalikes it must reject; the
measurement asserts the rejection, so a rule that widened into prose shows up as
a failing check rather than as a high presence rate. All 16 rules pass; the full
patterns are in the sidecar's `join_key_rules`.

| Key | Rule, in words | Rejects (checked) |
| --- | --- | --- |
| `bill_number` | chamber designator, a `.` or space, then 1–5 digits, not preceded by `U.` or a letter | `HR974` (a GPO running head), `S4601` (a Record locator), `600 U. S. 183`, `ANALYSIS. 12` |
| `public_law` | `Public Law` or `P.L.`, optional `No.`, then `congress-number` | `Public Lands`, `P.L. Smith`, `Pub L` |
| `statutes_at_large` | `N Stat. N` | `Stat. of the Union`, `12 State 45` |
| `usc_section` | title, `U.S.C.`, optional `§`, then a section | `U.S. Code of conduct`, `42 USC for` |
| `cfr_section` | title, `C.F.R.`, optional `part`/`§`, then a part | `CFR is the`, `40 CRF 60` |
| `federal_register_cite` | volume, `Fed. Reg.`, page | `Fed. Reg. of the`, `88 Federal agencies` |
| `rin` | `RIN nnnn-XXnn`, the data map's own measured shape | `RIN of the`, `RIN 1234` |
| `gao_product_id` | `GAO-YY-NNNNN` with an optional suffix | `GAO reported`, `GAO-2026` |
| `crs_report_id` | a CRS series prefix and 4–6 digits, no separator | `R 1234`, `RL-31312` |
| `bioguide_id` | letter and six digits | `A 000375`, `AB000375` |
| `docket_number` | agency acronym, year, sequence | `FAA 2016 6907`, `ABC-16-0001` |
| `case_docket_number` | `No. YY-NNNN` — any federal case, not only a Supreme Court one | `No. 25`, `Number 24-1001` |
| `us_reports_cite` | volume, `U. S.`, page | `U.S. Government`, `600 US 1` |
| `committee_name` | `Committee on [the] <Title Case>` | `committee on the matter`, `Committee of the Whole` |

**Two of these rules were wrong until the sample corrected them, and that is the
argument for measuring before building.** The first `bill_number` rule scored
the slip-opinion sample at a 100% bill rate — because `600 U. S. 183` contains
`S. 183`. The same rule read the GPO running head `HR974` as a bill, which is
why GPO print artifacts now come off through
[`extraction/gpo_normalize.py`](../extraction-gpo.md) before any text rule runs.
Its own evidence gate is worth reporting: it stripped GPO footers from 8 of the
71 documents read — all eight committee activity reports — and fired on none of
the other 63, including the eight Secretary of the Senate volumes, which are
GovInfo prints from the same collection family. The gate is reading the page,
not the host. A `recommendation_list` marker built
from `We recommend that` alone found GAO recommendations in 1 of 8 reports; the
publisher's actual heading is *Recommendations for Executive Action*, and with
it the rate is 5 of 8.

## The contract shape this points at

One link table in the `fr_docket_links` shape — one row per (document, cited
key), sorted by target so a `WHERE target_key = ?` prunes row groups:

| Column | Meaning |
| --- | --- |
| `document_key` | The family's own natural key: `packageId` for GovInfo, `product_id` for GAO, CRS `id` + version, the Clerk's `DocID`, the slip opinion's file stem |
| `document_family` | Which of the families above, so one table serves all of them |
| `cite_kind` | The rule name above: `bill_number`, `public_law`, `usc_section`, … |
| `target_key` | The canonical key, in the hosted table's own spelling: `hr3633`, `119-21`, `26 U.S.C. 1` |
| `target_table` | `congress_bills`, `laws`, `law_code_sections`, `federal_register`, … |
| `evidence_page`, `evidence_line`, `evidence_text` | Where in the print it was read, from the same evidence blocks the capture profiles are built on |
| `rule_version` | So a re-extraction under a corrected rule is attributable, the way `prompt_version` is |

Every document in every family partitions cleanly into those evidence blocks:
the line assembly `reconstruction.evidence.evidence_from_pages` — the half that
every PDF capture profile shares — ran over one document per family and
round-tripped in all nine, 55 to 750 blocks each.

**No seventh capture profile was written.** What a family-specific profile adds
over the shared line assembly is a *grammar* — which lines are a heading, a
recommendation, a cost row — and choosing that grammar is the contract build
this measurement is meant to inform, not part of measuring it. The slip-opinion
profile remains the PDF-text worked example, and today's independent capture of
`25pdf/26a274_l537.pdf` is byte-identical to the one pinned there on 2026-09-19
(`7c14a9d1…`, 66,165 bytes), which is a route-stability result in its own right.

## What Zyte answered and what it did not

| Route | Census said | Direct, today | Through Zyte, today |
| --- | --- | --- | --- |
| CRS HTML (`congress.gov/crs_external_products/*/HTML/*.html`) | 403 to a plain client, corrected 2026-09-19 to flaky | `200 text/html`, 2 of 2 reports | `200 text/html`, 2 of 2, **byte-identical to the direct capture** (`5e20a65f…`, `154a5492…`) |
| CBO `/publication/{id}` | 403 DataDome | not attempted (the census established it twice) | **refused**, 8 URLs + 2 repeats in `browserHtml`, `/download/temporary-error` |
| CBO `/system/files/*.pdf` | 403 DataDome | not attempted | **refused**, `/download/temporary-error` |
| CBO `/rss/{c}congress-cost-estimates.xml` (control) | 200 keyless | `200`, 432,572 B | `200`, 432,572 B, **same digest** `910aab10…` |

The controls are the point. Two byte-identical pairs, on two publishers, say the
proxy returns the publisher's own bytes rather than a rendering — so the CBO
refusals are the wall answering, not the transport failing. The CRS "wall" did
not reproduce on either route; two successes do not establish a reliable route
any more than one does, and `crs_files.py`'s existing HTML-then-PDF fallback
stays the right shape.

The transport that made this possible is new:
[`transport/zyte.py`](../../src/spicy_docs/transport/zyte.py), an
`httpx.BaseTransport` over the existing `sources/zyte.py` fetcher, so any
acquirer that already takes an injected transport can be pointed through the
proxy without a second HTTP client. Its rules — one provider call per request,
no credential to the publisher, a `ZyteProxyRecord` on every response naming the
request id, the mode and the proxy — are recorded in
[decisions.md](../decisions.md#the-shared-zyte-transport-lives-in-spicy-docs-and-records-that-a-capture-was-proxied).

## Request counts

| Class | Requests | Bound | Notes |
| --- | --- | --- | --- |
| Keyless | 91 | none set | Ten hosts: `files.gao.gov`, `www.gao.gov`, `www.congress.gov`, `www.govinfo.gov`, `www.supremecourt.gov`, `www.courtlistener.com`, `www.senate.gov`, `disclosures-clerk.house.gov`, `www.oversight.gov`, `www.cbo.gov` |
| Keyed (`API_GOV`, header only) | 13 | 20 | Two hosts: 9 `api.congress.gov` `crsreport`, 4 `api.govinfo.gov` `published` |
| Zyte | 14 logged, 17 made | 30 | 3 provider calls predate the probe's failure logging and were re-run identically; every row the report cites is in `requests.jsonl` |
| **Total** | **118 logged** | | |

## Complexity

Linear per document in its pages. Extraction yields one page at a time and each
rule scans each page's text once, so a family of `D` documents with `P` pages
costs `O(D·P·C·K)` for `K` fixed rules. Measured with `tables=True` on all 71
documents: **10 to 166 ms per page**, and the spread is content, not size — the
Budget Appendix's dense ruled pages cost 166 ms/page against 22 ms/page for the
Senate volumes at the same 60-page depth. `find_tables()` is the only
superlinear step and it is per page and bounded there; nothing in this
measurement is superlinear in the corpus.

The one quadratic step is in the measurement's own index rendering, not in any
proposed contract: every ordered pair of a record's values is offered so a
two-field key is readable whatever order it was serialized in, which is O(k²) in
one record's field count — a handful, bounded by the publisher's schema.

## What this measurement cannot see

- **It reads at most 60 pages of a document.** That truncates the Secretary of
  the Senate volumes (1,259–3,018 pages), the Budget Appendix (1,340), seven of
  eight activity reports and four slip opinions. Every count above is therefore
  a floor on the document, not a total.
- **The "beyond the index" counts are a floor** for a second reason: the index
  side is rendered generously on purpose, so it can only look like the publisher
  states *more* than it does.
- **Eight documents per family is a sample, not coverage**, and every family's
  eight are the newest available, which biases toward current formatting.
- **One capture does not establish a route.** The CBO refusals are one day.
- **The agency-upload family has no publisher at all.** Its index record is
  Oversight.gov's, the nearest public analogue with one; a BillTrax upload has
  no index record, so for that channel *every* column in the table above is
  yield, and the Oversight numbers are the conservative reading.

## Recommended build order

1. **`document_citations`, the one shared link contract, built first on the
   House committee activity reports.** Densest yield in the corpus (940 bills,
   67 laws, 124 committees across eight prints), a publisher index that states
   none of it, keyless GovInfo documents, one keyed request per 100 packages to
   discover them, and no table extraction needed — it is a citation contract
   over prose. It also exercises `bill_number`, `public_law`, `committee_name`
   and the GPO normalizer together on the family where all four matter.
2. **Extend `document_citations` to GAO and the slip opinions**, which add the
   `gao_product_id` report→report edge (44 of 45 cites are other products) and
   the `us_reports_cite` opinion→opinion edge (209 distinct cites, and
   CourtListener's `citation` field covers the *cited* opinion, never the
   citing one's references).
3. **`crs_report_citations`, and nothing else from CRS.** The bills and laws are
   already in `relatedMaterials`; the report→report graph is not, and has no
   other source.
4. **`senate_expenditures`, a real table contract**, off the Secretary of the
   Senate volumes: 396 ruled tables in 480 sampled pages, a consistent 5–6 × 9–10
   geometry, and a two-field index record that states nothing about the content.
   This is the best ruled-table target in the corpus and it is keyless.
5. **`gao_recommendations`** — a list contract, not a citation one, over the
   *Recommendations for Executive Action* and *Matters for Congressional
   Consideration* sections. Worth doing after (2) because it needs a section
   grammar, which means the first family-specific capture profile.
6. **Budget account tables and House Clerk disclosure grids**, in that order.
   Both are real table yield; both need a page-level section grammar before the
   rows mean anything, and the Clerk's grids are a form-extraction problem
   rather than a citation one.
7. **CBO: build the feed-only `bill ↔ cost_estimate` link table now, and stop
   there.** The document has no route. Re-probe when CBO changes hosts or when
   a route other than `www.cbo.gov` appears; do not spend on the proxy again
   without new evidence, because the one measurement that would have justified
   it has been made and it came back negative.
8. **Do not build**: a `document → member` contract from any of these families
   (no print states a bioguide id), or a CRS bills-discussed extractor (rule 1).
