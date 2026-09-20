# The CBO cost-estimate capability, measured on the bytes it was built from

**2026-09-20.** Measured, offline, through the product code. **Zero requests**
(a cap of 10 keyed GovInfo requests was stated before the run and none was
spent). Receipt:
`~/Work/corpora/supply-2026-09-02/receipts/cbo-cost-estimates-build-2026-09-20/`
— `measure.py`, its `measurement.json`, and the input pins.

This is the build of [the routes measurement](cbo-cost-estimate-routes-2026-09-20.md)'s
recommendation. That note found the index CBO's own walled site denies us is
keyless in GovInfo's BILLSTATUS bulk zips, and that the letter text is
reprinted in the committee report for the reported subset. This note says what
landed and re-derives every number it claims from the bytes that receipt
already retained.

## Inputs, pinned

| Input | Digest | Extent |
| --- | --- | --- |
| `BILLSTATUS-118-hr.zip` | `8e7ca7da…dba98` | 10,564 bills, 35.5 MB |
| `BILLSTATUS-118-s.zip` | `269261c0…e399c` | 5,649 bills, 14.4 MB |
| 17 `CRPT` htm bodies | logged in `../cbo-routes-2026-09-20/requests.jsonl` | 6 KB to 411 KB each |

```sh
cd ~/Work/spicy-stack/spicy-docs
R=~/Work/corpora/supply-2026-09-02/receipts/cbo-cost-estimates-build-2026-09-20
uv run --frozen python $R/measure.py
```

The script aborts rather than measuring if a retained blob's bytes do not hash
to the name it is stored under.

## Step zero: what the family already had

Nothing. `parse_bill_status` read neither `<cboCostEstimates>` nor
`<committeeReports>`; `TABLE_CONTRACTS` had no column, and `docs/tables.md` no
occurrence, of `cbo`. So the index side is a **new table**, not appended
columns on `congress_bills` — the choice the owner's do-not-recreate rule
turns on, made by looking rather than by assuming.

## The index reproduces, every count

Every one of the 16,213 files in both zips is parsed through
`sources.congress.bill_status.parse_bill_status` — not the subset whose bytes
contain the element, which would have made the first row below a restatement
of the filter rather than a measurement.

| | Measured here | The routes note |
| --- | ---: | ---: |
| Bills in both zips | **16,213** | 16,213 |
| Bills stating `<cboCostEstimates>` | **1,368** | 1,368 |
| `<item>` rows stated | **1,468** | 1,468 |
| Distinct publication ids (**union** across both zips) | **1,431** | 1,431 |
| Self-closing / empty elements | **0** | 0 |
| Absent elements | **14,845** | — |
| Unexpected block shapes | **0** | — |
| Urls outside the measured `/publication/{id}` shape | **0** | 0 of 1,468 |

Per zip: `118/hr` 10,564 bills, 973 with the element, 1,062 items, 1,035 ids;
`118/s` 5,649 bills, 395, 406, 396. The id total is taken as a **union, never
a sum**, because a publication can score bills of two types; none here does,
and it is still re-derived as a union rather than left as an assumption.

**Published rows: 1,431, every one keying uniquely** on
`(bill_id, publication_id)` through `CBO_COST_ESTIMATES.checked`.

The first build measurement hard-coded `empty_elements` to zero whenever
any bill had estimates. It could not detect an empty element. This rerun
counts the product reader's explicit outcomes and first tests a synthetic zip
containing populated, absent, empty and unexpected blocks. Restoring the old
hard-coded expression fails that control. The retained zips still measure
zero empty blocks; this is now an observation the measurement can disprove.
The sidecar records all four control bills separately from the corpus counts.

### The 37 rows the identity would have dropped

1,468 items become 1,431 rows. The 37 are the publisher stating one
publication twice on one bill. **Nine of those 37 disagree**, and every one of
the nine disagrees in `title` alone — CBO re-spelling the measure's title.
Four are capitalisation ("Human rights" to "Human Rights", "reform Act" to
"Reform Act"), three are an ampersand escaped once or twice, one is a doubled
space, one renames the Act ("Mobilization Act (FEMA)" to "Mobilization
Accountability (FEMA)") and one corrects a year ("Act of 2022" to "2023").
`pubDate`, `url` and `description` agree on all 37.

So the fold is lossless by construction: `restatements_json` carries every
later item that differs, with only the differing fields, and is `[]` on the
other 1,459 rows.

### One publisher quirk the build found

`<committeeReports>` writes a part citation **without a space after the
comma** — all thirteen measured are `H. Rept. 118-167,Part 2`. The first
pattern written here demanded the space and read all twelve occurrences in the
scored set as unparsed; corrected, **0 of 910 citations are unparsed**. Shapes:
`H. Rept. N-N` 649, `S. Rept. N-N` 249, the part form 12.

### The text route's ceiling, from the index alone

| | Bills with an estimate | Of those, with a committee report | Share |
| --- | ---: | ---: | ---: |
| `118/hr` | 973 | 655 | 67.3% |
| `118/s` | 395 | 228 | 57.7% |
| **Both** | **1,368** | **883** | **64.5%** |

Reproduced exactly. This is `COUNT(DISTINCT bill_id) WHERE
report_citation_count > 0` over the published rows, so the ceiling is a
property a consumer reads off one row rather than a number in a document.

**It is an upper bound in both directions.** A report citation does not mean
the report reproduced the estimate — the routes probe found the estimate
absent from 3 of 13 reported bills whose index named one — and a citation can
name a report for a different stage than the one the estimate scores.

**61 of the 1,368 scored bills carry more than one estimate, and 28 of those
also carry a report.** That is the measurement that decided where the letter
columns live: one reprinted letter could not be attributed to one of several
estimates on those 28 bills without guessing.

## The text side reproduces, and the gate holds

All 17 retained bodies, through `extraction.body_text.rendition_text` and then
`interpretation.cbo_estimates.read_cbo_estimate`.

| Signal | Measured here | The routes note |
| --- | ---: | ---: |
| Bodies read | **17** | 17 |
| Cover recital declares the estimate | **7** | 7 |
| A CBO heading appears | **11** | 10 |
| Heading present, recital absent | **4** | 3, plus `CRPT-118hrpt111` named separately |
| Declared letters located end to end | **7 of 7** | — |
| …ending at the Director's attribution | **6** | — |
| …ending at the next heading in the same series | **1** | — |
| Declared letters naming a signatory | **6 of 7** | 6 of 7 |
| The publisher's own reason read | **4** | 4 (3 + `hrpt111`) |

**The heading count is 11, not 10, and that is the point.** The routes note
measured 10 with five committee-specific patterns and said in its own "what
could not be established" that the set was a floor, naming `CRPT-118hrpt111`'s
`C. Cost Estimate Prepared by the Congressional Budget Office` as the one it
missed. This build's vocabulary has that spelling, so it finds 11. **The
vocabulary is still a floor** — it is only ever used to locate a span the
recital has already declared, and it never decides whether an estimate is
there.

The four heading-without-recital reports are exactly the four that say why:
`CRPT-118hrpt18` and `-118hrpt21` ("was not available"), `-118hrpt58` and
`-118hrpt111` ("requested but not received"). Each one's reason paragraph comes
back whole, with its span. That is requested-empty with the publisher's own
reason, not a NULL.

### Two false positives the recital gate refuses

`CRPT-118srpt99` — a Senate Budget Committee activity report accompanying no
bill — states `Director, Congressional Budget Office.` in a **witness list**
and `Washington, DC, March 1, 2023.` on the committee's **own** letter of
transmittal. Both markers would read as a CBO letter under a signature or
dateline gate. The recital is absent, so the rule reports no letter. (The
routes note's `director_signature_present: 7` counted that body; its looser
detector is what the gate exists to replace.)

### No letter date, and why that is not a shortfall

**0 of 17 bodies carries a CBO letterhead dateline**, inside a located span or
anywhere else. No pattern is written for a form nothing retained has shown.
It is also unnecessary: the estimate's date is CBO's own `pubDate`, already
published on `cbo_cost_estimates.pub_date`, so re-deriving it from prose would
recreate what the index states. One retained body whose reprint carries the
letterhead would add the rule.

### Why no `document_citations` row

Across all 17 bodies there is **one** `cbo.gov` locator — a footnote in
`CRPT-118hrpt930` to an unrelated 2018 CBO infrastructure study — **zero**
`/publication/{id}` pages, and **zero** locators inside any located letter. A
citation row's identity includes `target_key`; the print states none to carry.

## The committed fixtures are faithful

Each of the seven excerpts in `tests/fixtures/cbo_estimates/` was run against
the whole body it was cut from: **7 of 7 agree** on the recital decision, the
heading rule, the end rule, the signatory, the absence rule and the letter's
character length. Without that check, every pinned number in
`tests/test_cbo_estimates.py` would be a statement about the cut rather than
about the publisher.

## What landed

| | |
| --- | --- |
| `congress_bills` | One appended nullable `cbo_cost_estimates_outcome` column; unread, populated and requested-empty shapes survive without estimate rows |
| `cbo_cost_estimates` | 16 columns, keyed `(bill_id, publication_id)`, filled in the bill family's one pass from the same BILLSTATUS document as its other four tables |
| `committee_reports` | 13 appended columns: the recital's answer, the print's own bill key, the heading, the letter's span, digest, end rule and signatory, and the publisher's reason |
| `interpretation/cbo_estimates.py` | the named, versioned rule, with each pattern's reason and its rejects beside it |
| `sources/congress/bill_status.py` | reads `<cboCostEstimates>` and `<committeeReports>`, under both the live and the guide's spellings |

## What this does not establish

- **No count here is a CBO production rate.** The element is never emitted
  empty, so a bill without it is *either* never scored *or* not yet linked, and
  nothing in this route tells the two apart. Every row is requested-empty
  evidence about one bill.
- **One Congress, one capture.** 16,213 bills of the 118th's House and Senate,
  read from two zips downloaded on one day. Nothing here speaks to another
  Congress, to resolutions, or to whether the zips still say this.
- **Seventeen bodies is a sample**, drawn by the routes probe from GovInfo's
  own `published` listing — not from anything CBO states, so the text counts
  cannot agree with themselves, but they are still 17 documents.
- **The heading vocabulary is a floor** and will stay one. It is used only to
  locate a span the recital declared; a report whose heading it misses
  publishes `report_states_estimate = true` with a NULL span, which is visible
  as a shortfall rather than as an absence.
- **The summary cost card is still a raster** in both renditions, and no
  figure is extracted from it. The routes note's step 4 — run the extraction
  API over those embedded 1320-px images and report a recovered-figure rate —
  is **not attempted here** and no contract claims to carry cost numbers.
- **The ~35% of scored bills with no report have no text route at all**, and
  neither does any current-year estimate. The index row still carries the
  bill, the stage, the date and the locator; the figures are absent and
  recorded as absent.
- **Nothing was re-probed.** Every `www.cbo.gov` finding in the routes note is
  one request on one day, and this build made none.
