# PDF-only measurement across spicy-docs's corpus

Status: measured 2026-09-19, read-only, about twenty bounded requests; nothing changed in any repository.

**Followed by the yield measurement**, 2026-09-20: what these families would
actually contribute as hosted tables, family by family, against what each
publisher's index already states —
[pdf-family-rollup-yield-2026-09-20.md](pdf-family-rollup-yield-2026-09-20.md).
It confirms CBO as blocked (refused even through a paid proxy), finds the House
committee activity reports to be the densest join surface in the corpus, and
finds CRS's bills-discussed already present in the Congress.gov index.

Read-only measurement. Repo: `../../spicy-docs` (main), no files
modified. Corpus enumerated from `docs/source-workflows.md` (both tables), `docs/README.md`'s
"Work on a source" list, every file under `docs/sources/*.md`, and the body-carrying rows of
`docs/research/legislative-data-map-2026-09-18.md` Tables A-D. Renditions are read from the docs
first; where the docs didn't state them, they were measured today with bounded probes through the
repo's own readers (`uv run --frozen python -`, `read_api_key(Path(".env"), "API_GOV")` sent as an
`X-Api-Key` header only, no bare `curl` against keyed routes). New live probes run today: 2 GovInfo
BILLS packages x 2 candidates each (1990s, 2005 eras; ~9 requests), 1 CRS report metadata + 2 file
fetches, 3 GAO file fetches, 3 CourtListener endpoint checks — about 20 requests total, under the
40-request bound.

Verdict legend: **PDF-only** (no other rendition of the body exists or is reachable) ·
**PDF-primary** (PDF is offered plus a real text/markup alternative) · **structured**
(xml/json/html/csv is the native or preferred rendition; PDF is absent or secondary) ·
**metadata-only** (the family supplies no document body at all, only records/links about one).

## Part 1 — Families this repo documents and/or implements (`docs/sources/*.md`)

| Family | Body renditions the publisher offers | Source of fact | Verdict |
| --- | --- | --- | --- |
| GovInfo committee reports (`CRPT`) | `htm`, `pdf` | `docs/sources/govinfo-bodies.md`, measured 2026-09-19 (`CRPT-119hrpt1`) | PDF-primary |
| GovInfo hearing transcripts (`CHRG`) | `htm`, `pdf` (46.6 MB) | same, `CHRG-119hhrg64242` | PDF-primary |
| GovInfo congressional documents (`CDOC`) | `htm`, `pdf` | same, `CDOC-119tdoc2` | PDF-primary |
| GovInfo Congressional Directory (`CDIR`) | `pdf` (18.3 MB), `txt` | same, `CDIR-2026-02-20` | PDF-primary |
| GovInfo Congressional Record (`CREC`) | `pdf` only — no `xml`/`htm`/`txt` offered | same, `CREC-2026-01-02`; MODS states PDF alone, four PDF summary links | **PDF-only** |
| GovInfo bill text (`BILLS`), 2025-era | `htm`, `xml`, `pdf` (+ USLM at a moved address) | same, `BILLS-119hr1enr` | structured |
| GovInfo bill text (`BILLS`), 2005-era | `htm`, `pdf` — **no `xml`** | measured today: `GovInfoBodyAcquirer.acquire("BILLS-109s256enr"/"BILLS-109hr1268enr", prefer=("xml","htm","txt","pdf"))` → `offered=('htm','pdf')` both | PDF-primary |
| GovInfo bill text (`BILLS`), 1990s-era | `htm`, `pdf` — **no `xml`** | measured today: `BILLS-103hr1enr`/`BILLS-103hr1ih` → `offered=('htm','pdf')` both | PDF-primary |
| Federal Register documents | `body-xml` (publisher `full_text_xml_url`), `body-html`, `html`, `pdf` link; the dedicated body acquirer only ever fetches `xml`/`html`/`txt` — **PDF is never a body-acquirer format** | `docs/sources/federal-register.md`, `federal-register-body-sources.md` | structured |
| CFR / eCFR (title, section, annual, bulk) | `xml`/`xhtml` is the body route; annual MODS separately advertises PDF for ~400 of 401 constituents, and "some structural nodes offer only PDF" at the sub-part level | `docs/sources/cfr.md`, `govinfo-metadata.md` | structured (footnote: some CFR constituent nodes are PDF-only within the metadata inventory) |
| Unified Agenda edition | `xml` (reginfo.gov `REGINFO_RIN_DATA`) | `docs/sources/unified-agenda.md` | structured |
| U.S. Code (title/corpus zip, annual archive, Popular Name Tool, Table III) | `xml` (USLM), annual archive `xhtml`, Popular Name Tool/Table III `html` | `docs/sources/uscode.md` | structured |
| Public laws & statute compilations (USLM) | `xml` | `docs/sources/uslm-laws.md` | structured |
| Regulations.gov documents/comments (Mirrulations + API attachments) | Publisher-declared `fileFormats[]`/`attachments_json[].formats[]`: PDF plus a real non-PDF alternative on the same item | Real fixture `tests/fixtures/listings/regulations-gov-attachments.json` (`FAA-2016-6907-0001`: `docx` **and** `pdf` on one attachment); public-comments `attachments_json` shape in `tests/test_spicy_regs_public_tables_source_native.py` (`pdf`+`txt` on one comment, `json`/`octet-stream` on another) | PDF-primary |
| CRS report files | Publisher `formats[]` states **both** `PDF` and `HTML`, but only PDF is actually servable to a plain keyless client | measured today: `api.congress.gov/v3/crsreport/IF12853` → `formats: [{PDF,…IF12853.10.pdf},{HTML,…IF12853.html}]`; live fetch of the PDF → `200 application/pdf` (409,240 B); identical client on the HTML URL → **403**. `docs/sources/crs-files.md` documents and implements only the PDF route. | **PDF-only in practice** (publisher states an HTML alternative that this client cannot reach) |
| GAO reports (product page + files) | `pdf` (every product), `-highlights.pdf` (most), and an `index.html` "online report" for a majority | `docs/sources/gao-files.md` (47/47 pdf, 27/47 highlights, 26/47 html index, 2026-08-22); reconfirmed live today for `gao-26-107693`: PDF 200 (5,020,419 B), highlights PDF 200 (818,614 B), `index.html` 200 `text/html` (419,991 B) | PDF-primary |
| CBO cost estimates | Feed `<Link>` is an HTML publication *page*, never a PDF locator; the estimate PDF itself has **no keyless route at all** (`www.cbo.gov` DataDome-walled on every path probed, with and without browser headers) | `docs/sources/cbo.md`, measured 2026-09-14 | **PDF-only** (and presently unreachable keyless) |
| Supreme Court slip opinions | Index states one PDF link per opinion; no other rendition stated | `docs/sources/supreme-court.md` | **PDF-only** |
| FCC ECFS filings | Mixed at the filing level: an "express comment" carries its text **inline in the JSON** (`text_data`, no attachment at all); a formal filing attaches a PDF (`documents[].filename`) | `tests/fixtures/listings/fcc-ecfs-filings.json` (2 filings: 1 inline-text-only, 1 with one `.pdf` attachment; extension count `{pdf: 1}`) | structured/mixed (not PDF-only — roughly half the sampled filings carry no PDF at all) |
| CourtListener opinions | Keyless `search` route states `download_url` (PDF) + `local_path` (cached PDF) only; the full `html`/`plain_text`/`xml_harvard` fields live on the opinion/cluster **detail** routes, which this environment cannot reach | measured today: `courtlistener.com/api/rest/v4/search/?type=o` → 200 (public); `.../clusters/{id}/` and `.../opinions/{id}/` → **401**, no CourtListener token in `.env`; this repo has no CourtListener body-fetch module at all, only `bulk.py` (CSV dump) and the search listing | PDF confirmed keyless; text alternative stated by the publisher's schema but **not verified in this environment** (no credential) |
| Agency reports — FOIA annual XML | `xml` (NIEM FOIA exchange 1.02/1.03) | `docs/sources/agency-reports.md`; fixtures `tests/fixtures/agency_reports/foia-fec-2010.xml`, `foia-fec-2025.xml` | structured |
| Agency reports — Oversight.gov evaluation pages | `html` (full report description + recommendation tables in-page) | same; fixture `tests/fixtures/agency_reports/oversight-data-act.html` (44,102 B) | structured |
| Appropriations committee press releases | RSS 2.0 channel/item; House item `description` is HTML | `docs/sources/press-releases.md` | structured |
| Roll-call votes (House Clerk EVS, Senate LIS) | `xml` | `docs/sources/congress-votes.md` | structured |
| FEC official data (bulk, OpenFEC JSON, sitemaps, link discovery) | Mixed by design: bulk master files, native `.fec` delimited filings, CSV, XML `legal/` listings, JSON, plus linked PDFs (`pdf_url`) and HTML (`html_url`, gated behind `allow_html=True`) | `docs/sources/fec.md`, `fec-rows.md` (`format="fec"`/`"delimited"`) | structured/mixed |

**Correction, 2026-09-19 (gap B3):** the CRS row's single 403 was one flaky sample, not the route's
behavior — an eight-request re-probe got HTML 200s on both reports tried, so `crs_files.py` now prefers
HTML and falls back to PDF only on a refusal (`docs/sources/crs-files.md`).

### Metadata-only families in this repo (no document body at all)

Congress bills status (BILLSTATUS XML — bill *metadata*, not the bill's legislative text; the text
itself is the `BILLS` row above), Congress bulk status zips, Congress.gov/GovInfo/GAO/LDA/
CourtListener/SAM/USAspending/FCC list pages (`listings.md`), GovInfo MODS (`govinfo-metadata.md`)
and PREMIS (`govinfo-premis.md`), the community legislators crosswalk JSON (`legislators.md`),
eCFR agency roster / Archives subject index (`cfr-roster-index.md`), eCFR authority-note reader
(`ecfr-authority.md`, a derived reader over already-acquired CFR XML), the BILLSTATUS guide-table
reader (`billstatus-guide.md`, a static GitHub Markdown reference, not a multi-rendition source),
and the agency-report-block splitter (`agency-report-blocks.md`, a downstream parser over already-
extracted PDF text, not an acquisition family).

## Part 2 — Legislative-data-map candidates that carry a body (Tables A-D)

Only rows where the map states or samples a rendition; unmeasured candidates (JCT, House LDA
filings, Senate financial disclosure, PLUM report, GAO legal/restricted reports, EveryCRSReport,
House Rules Committee, House floor summary) are omitted rather than guessed at.

| Family | Body renditions | Source | Verdict |
| --- | --- | --- | --- |
| Statutes at Large (`bulkdata/STATUTE`) | `xml`, one per volume | Table B | structured |
| Government Manual (`bulkdata/GOVMAN`) | "clean org XML" | Table B | structured |
| House Rules and Manual (`bulkdata/HMAN`) | "clean XML" | Table B | structured |
| House committee activity reports (search over `HRPT`; CHA) | "end-of-Congress PDF cadence" | Table B (`rejected`) | **PDF-only** |
| House/Senate per-vote XML, MemberData.xml, members.xml, Senate `cvc`/contact XML, LIS nomination feeds, House committee/floor weekly XML+RSS, Senate hearings/session calendar | All sampled as XML (root element stated per row) | Table C | structured |
| House Statement of Disbursements | CSV since 2016 | Table C (`candidate`) | structured |
| Report of the Secretary of the Senate | "PDF since 2011" — publisher's table itself calls this **"PDF-only; revisit if XML or CSV appears"** | Table C (`rejected`) | **PDF-only** |
| House Clerk disclosures (financial, travel, mass comms, post-employment) | "search-site PDFs" | Table C (`rejected`) | **PDF-only** |
| President's Budget Appendix, agency CBJs | "PDF-heavy; OMB non-compliant on format" | Table C (`rejected`) | PDF-primary/near-PDF-only (doc hedges "heavy," not "only") |
| CISA `.gov` domain registry | CSV | Table C (`candidate`) | structured |
| Agency uploaded-report PDFs (BillTrax upload channel) | PDF | Table D (`port 5`) | **PDF-only** |

## Summary

- **PDF-only families: 8** — GovInfo Congressional Record (`CREC`) package bodies; CBO cost-estimate
  documents (also currently unreachable keyless, DataDome-walled); Supreme Court slip opinions;
  CRS report files (publisher states an HTML alternative, but it 403s to a plain client — only PDF
  is practically fetchable); House committee activity reports (CHA); the Report of the Secretary of
  the Senate; House Clerk disclosure search-site PDFs; BillTrax's agency-uploaded-report PDF channel.
  Parsers for all eight must stay on the PDF-extraction path (PyMuPDF/`DocumentExtractor`), not a
  markup reader.
- **PDF-primary-with-text-alternative: 7** — GovInfo committee reports (`CRPT`), hearings (`CHRG`),
  congressional documents (`CDOC`), Congressional Directory (`CDIR`), 2005- and 1990s-era `BILLS`
  packages (htm+pdf, no xml — measured today), regulations.gov/Mirrulations attachments (real
  fixture shows docx+pdf and pdf+txt pairs), and GAO reports (pdf always, `-highlights.pdf` on most,
  a full HTML "online report" on roughly half — reconfirmed live today).
- **Structured (xml/json/html/csv as the native or preferred rendition): the majority of the
  corpus** — Federal Register, CFR/eCFR, Unified Agenda, U.S. Code, USLM public laws/statute
  compilations, Statutes at Large/GOVMAN/HMAN bulkdata, roll-call vote XML, FOIA annual XML,
  Oversight.gov HTML, press-release RSS/HTML, FEC's native `.fec`/CSV/XML/JSON mix, and the whole
  Table C publisher-XML family (per-vote, member, committee, nomination, calendar files).
- **Ambiguous/unresolved today**: FCC ECFS filings mix inline JSON text with occasional PDF
  attachments (not PDF-only — about half the sampled filings carry no PDF at all); CourtListener
  opinions are PDF-confirmed keyless (`download_url`) but the publisher's own `html`/`plain_text`
  fields sit behind a detail/cluster route that answered 401 in this environment (no CourtListener
  token in `.env`), so the text alternative is documented by the publisher's schema but not
  independently verified here.
- **Metadata-only (no body at all): the largest remaining group** — BILLSTATUS bill metadata, every
  publisher list/search route (`listings.md`), GovInfo MODS/PREMIS, the legislators crosswalk JSON,
  the eCFR roster/subject-index readers, and the BILLSTATUS guide-table reader.
