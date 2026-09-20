# Hearing-to-bill link fixtures

Four publisher records retained by the
[hearing-to-bill linkage measurement](../../../docs/research/hearing-bill-linkage-2026-09-20.md)
(receipt `corpora/supply-2026-09-02/receipts/hearing-bill-linkage-2026-09-20/`,
198 requests, all HTTP 200). **Nothing here was re-fetched**: every byte comes
from that receipt's `responses/`, and the three MODS records are reduced by the
rule stated below. These U.S. government documents are public domain.

Offline tests establish behavior for these four records on the day they were
captured; they establish neither coverage nor continuing live availability.

| Fixture | What it is | Publisher bytes | Publisher SHA-256 | Fixture bytes | Fixture SHA-256 |
| --- | --- | ---: | --- | ---: | --- |
| `mods-CHRG-118hhrg52385.excerpt.xml` | **reduced**: `api.govinfo.gov/packages/CHRG-118hhrg52385/mods`, keyed with `X-Api-Key` (receipt `responses/p1-mods-CHRG-118hhrg52385.xml`) | 19,079 | `072ac972844bfe31ba74581ed0a18729f2e8866e574e903ac64c3b58806ec612` | 11,644 | `94dfcded879ddb4d9885c2bf36e5da40343a3a7d733d84b945286cfd7937c589` |
| `mods-CHRG-118hhrg56198.excerpt.xml` | **reduced**: `api.govinfo.gov/packages/CHRG-118hhrg56198/mods`, keyed (receipt `responses/p1-mods-CHRG-118hhrg56198.xml`) | 41,655 | `53dd47b44e5df31072125ebb777498a0f046a9845576ba1aa688d359fab9ff64` | 28,285 | `07356e4d83d7a9bc75761ccc98965e897b1760a184cb09cf7bce23281c7b5ecb` |
| `mods-CHRG-118shrg56403.excerpt.xml` | **reduced**: `api.govinfo.gov/packages/CHRG-118shrg56403/mods`, keyed (receipt `responses/p2b-mods-CHRG-118shrg56403.xml`) | 20,138 | `4bbb9f119099ab0689a0477afc637619e2e3dfbe0c0ce081edefd4cb0ad22b09` | 20,022 | `2ddd680b0a3a3038e937cc1912d5e93972a0406366401ac1eeb3d8b9d1ab364a` |
| `meeting-115955.xml` | **verbatim**: docs.house.gov's per-event meeting XML for event 115955, keyless (receipt `responses/p1-meeting-115955.xml`) | 16,568 | `928a1497cefa978a75a929473d23a445e34322e3402f1fbe871e92755ea10320` | 16,568 | `928a1497cefa978a75a929473d23a445e34322e3402f1fbe871e92755ea10320` |

The credential travelled only in the `X-Api-Key` request header, on a client
dedicated to the keyed hosts; docs.house.gov was fetched by a second client
carrying no credential, so a redirect between them could not pick one up. The
receipt's own `verify_credentials.py` re-scanned all 197 retained responses
offline and found none.

## The MODS reduction, stated exactly

Everything before the first `<relatedItem>`, then `</mods>`. Nothing inside the
kept span was rewritten. What is dropped is the per-granule constituent
records, which `validate_package_mods` does not read: it reads the **root's
own** `extension` children, the same boundary `_mods_bills`, `_mods_committees`
and `_mods_held_date` draw. The kept span therefore carries everything the
reader under test looks at — every root-level `<bill>` with its `context`, the
`<congCommittee>` and the `<heldDate>` — and the same reduction rule the
[document-citation fixtures](../document_citations/README.md) already use.

The meeting XML is **not** reduced: at 16,568 bytes it is inside the fixture
bound whole, and cutting elements out of the record under test would change
what the reader sees.

## What each record is here to establish

- **`CHRG-118hhrg56198`** is the one-to-many case the whole design rests on:
  its MODS names **12 `COVER` bills** (and 17 `BODY` ones), so a scalar
  `hearing_transcripts.bill_id` would have to pick one of twelve. Held
  2024-06-12 by `hsvr00`. Its `COVER` list is also the set that three
  independent sources agreed with, set-equal, in `cover-agreement.json`.
- **`CHRG-118hhrg52385`** pairs with `meeting-115955.xml`: the same hearing
  from both sides. The MODS states **8 `COVER` bills** and the agenda states
  **9 `BR` documents of which 8 resolve**, and the two disagree in both
  directions — the cover names `118-hr-1450`, which the agenda does not, and
  the agenda names `118-hr-2997`, which the cover does not and which
  Congress.gov records as heard a month later. Keeping both sources as rows is
  what makes that disagreement readable.
- **`meeting-115955.xml`** carries the refusal case: one `BR` document whose
  `<legis-num>` is empty, whose file is `BILLS-118pih-ForestServiceFlexibleHousi.pdf`
  and whose description reads `H.R. _____ (Rep. Neguse)` — a discussion draft
  with no number. It is refused with a stated reason rather than guessed at.
  Its other eight `BR` documents spell the type in both places (`HR 188`
  beside `BILLS-118HR188ih.pdf`), so the **type-less** spelling some
  committees post — `<legis-num>226</legis-num>` beside `BILLS-118226ih.pdf`,
  which the community scraper defaults to `hr` — is not in this record. That
  path is exercised from a short constructed record inlined in
  `tests/test_hearing_bill_links.py`, which costs less than a second 22 KB
  publisher file for one branch.
- **`CHRG-118shrg56403`** is a Senate hearing whose MODS states **no bill in
  any context**, so the cover rule produces nothing. 3 of 3 sampled Senate
  hearings were like this and Congress.gov states one to two bills for each, so
  the silence is this publisher's and not the hearing's. Three is not a rule:
  the Senate census is the open measurement.

## The rendition identity, re-derivable here

`meeting-115955.xml`'s digest above is the digest of **both** retained copies:
the ASP.NET `__doPostBack` download the page offers
(`responses/p1-meeting-115955.xml`) and the static keyless GET at
`https://docs.house.gov/meetings/II/II10/20230523/115955/HHRG-118-II10-20230523.xml`
(`responses/p1b-static-115955.xml`). That is the 2-of-2 byte-identity behind
`house_meeting_xml_locator`, and it was checked by digest rather than by status
because this publisher serves its own pages at HTTP 200.
