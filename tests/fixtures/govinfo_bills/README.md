# GovInfo bill parser samples

Retrieved from GovInfo with unauthenticated GET on 2026-09-12. These U.S.
government documents are public domain. Offline tests establish behavior for
these shapes; they do not establish coverage or continuing live availability.

| Fixture | Publisher response | Changes |
| --- | --- | --- |
| `status-119hr6028.xml` | [119 HR 6028 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr6028.xml) | Omitted unrelated fields, retained two actions and two subjects, shortened each summary to its first HTML paragraph, reformatted XML. Both offered text versions remain. |
| `text-119hr6028eh.xml` | [119 HR 6028 EH XML](https://www.govinfo.gov/content/pkg/BILLS-119hr6028eh/xml/BILLS-119hr6028eh.xml) | Retained identity fields and first section, omitted other content, reformatted XML. External DOCTYPE retained. |
| `text-119hr6028ih.xml` | [119 HR 6028 IH XML](https://www.govinfo.gov/content/pkg/BILLS-119hr6028ih/xml/BILLS-119hr6028ih.xml) | Same reduction; preserves the introduced version and its root stage. |
| `text-119s5enr.xml` | [119 S 5 ENR XML](https://www.govinfo.gov/content/pkg/BILLS-119s5enr/xml/BILLS-119s5enr.xml) | Same reduction; preserves spelled-out Congress and title without Congress number. |
| `text-119hjres25enr.xml` | [119 HJRES 25 ENR XML](https://www.govinfo.gov/content/pkg/BILLS-119hjres25enr/xml/BILLS-119hjres25enr.xml) | Complete, unchanged 2,751-byte response. |
| `status-119s5.xml` | [119 S 5 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119s5.xml) | Retrieved with unauthenticated GET on 2026-09-19: `200`, `content-type: text/xml`, 269,519 bytes, SHA-256 `060213ff9909c0d5683d586fc7b9b4150c1c5a1d46b5bdb99ada5c49c89dc5eb`, publisher Last-Modified 2026-07-30 18:58:58 GMT. Reduced: kept 5 of 39 actions in publisher order and dropped `relatedBills`, `cosponsors`, `subjects`, `summaries`, `titles`, `amendments` and `textVersions`; reformatted XML. Retained elements are unchanged publisher bytes. |
| `status-119hr300.xml` | [119 HR 300 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr300.xml) | Retrieved with unauthenticated GET on 2026-09-19: `200`, `content-type: text/xml`, 6,855 bytes live, SHA-256 `fed90a2cdb9fb962825376322b33225fca5e0419ef82691ec3a0d510dc596f24`, publisher Last-Modified 2026-07-30 18:44:05 GMT. Reduced: dropped `<constitutionalAuthorityStatementText>`; every other element is unchanged publisher bytes. Added to cover `<titles>` and `<relatedBills>`: no other fixture in this directory carries `<relatedBills>` at all (`status-119s5.xml` had it stripped when reduced, see above), and this is the smallest live bill found carrying both. |
| `mods-119hconres11enr.xml` | [`packages/BILLS-119hconres11enr/mods`](https://api.govinfo.gov/packages/BILLS-119hconres11enr/mods), keyed with `X-Api-Key` | Complete, unchanged 5,727-byte response, SHA-256 `1ea18296309270fdceccf631f8b74ed58ad09a0b4df691e3c0de61a33f15ece1`. Retrieved 2026-09-19. |
| `uslm-119hconres11enr.xml` | [USLM rendition](https://www.govinfo.gov/content/pkg/BILLS-119hconres11enr/uslm/BILLS-119hconres11enr.xml), keyless | Complete, unchanged 3,113-byte response, SHA-256 `a0e2847ee6883b64c881053c781ce0a289e25e59be7b812fcd7fbab5f2e9f5ff`, `content-type: application/xml`. Retrieved 2026-09-19. |

## Separate cosponsor list regression (2026-09-21)

`status-118hr1-cosponsors.xml` is reduced from retained native member
`BILLSTATUS-118hr1.xml` in the 118th House BILLSTATUS ZIP. The source has one
sponsor and 49 separately listed cosponsors. The fixture keeps the root version,
bill identity/title, complete sponsor block and complete cosponsor block; all
other bill fields were removed and ElementTree reserialized the XML. It does
not establish completeness for any removed field.

- Original member: 366,226 bytes, SHA-256
  `15066cb9262d8f5fadc73a411e4c8e8df65536e0f56b0068702ee2660986adce`.
- Retained archive: `receipts/cbo-routes-2026-09-20/blobs/8e7ca7dab50a7b9b977f021ec1b3231f8fedf82c33494553857b892fadfdba98`
  under `~/Work/corpora/supply-2026-09-02/`.
- Fixture: 20,699 bytes, SHA-256
  `e3b9123c9582fb46d950869d9fe51536d883b303649ffcde6780087872655be0`.
- The full two-archive source comparison and corrected local outputs are in
  `receipts/legislative-release-candidate-2026-09-21/`.

The regression first reproduced a shaped count of zero instead of 49. The
parser now reads `<cosponsors>` independently of `<sponsors>`.

## The USLM bill rendition (B7)

`BILLS-119hconres11enr` is the package `docs/research/billtrax-raw-data-2026-09-19.md`
§7 names as the one version its 240-format-entry sample matched by file name
to a real package: the enrolled H. Con. Res. 11. The sample's "ten `United
States Legislative Markup` format entries out of 240" counted each sampled
bill once per version code that pinned it; deduplicated, the sample's 20
distinct bills carry 188 format entries, 9 of them USLM -- the five BILLS
enrolled packages measured below plus four PLAW-collection entries
(`PLAW-119publN_uslm.xml`, the "Public Law" version on a bill's `/text`
endpoint), which are `sources/govinfo/uslm.py`'s territory, not the BILLS
grammar's. The recount and the per-package pins live in
`uslm-renditions-2026-09-19.json` (below). Its MODS states HTML,
PDF, XML and USLM renditions, all four at the standard
`content/pkg/{id}/{folder}/{id}.{extension}` addresses; the USLM one adds
`PACKAGE_BODY_FORMATS["uslm"]` (folder `uslm`, extension `xml`).

The USLM body's root is `<resolution>` in the `http://schemas.gpo.gov/xml/uslm`
namespace -- the same namespace GPO's PLAW/COMPS USLM uses, but a different
root than either of `sources/govinfo/uslm.py`'s two fixed roots (`pLaw`,
`statuteCompilation`), and a root that varies by bill type where PLAW and
COMPS each have exactly one. `uslm.py`'s grammar validates identity against a
`PublicLawSelection`/`StatuteCompilationSelection` keyed to one fixed root
each; a bill has no such selection type to validate against here, and its own
root varies (`bill`, `resolution`, `jointResolution`, and so on by bill type),
so `uslm.py`'s grammar does not apply. `extraction/body_text.py` reads it
through the same generic markup-reader branch as a BILLS `xml` body instead --
measured on all five packages (`uslm-renditions-2026-09-19.json`): this
fixture yields 42 elements, 31 element-boundary line breaks and 32
whitespace-only pretty-print lines, the per-rule counts being measured on this
one retained fixture, and every package's own text is recovered in order (see
`RENDITION_DERIVATIONS["uslm"]` and `docs/sources/govinfo-bodies.md`).

## The five-package USLM measurement (`uslm-renditions-2026-09-19.json`)

Every BILLS package in the 2026-09-19 text-versions sample that offers a USLM
rendition, each fetched through `GovInfoBodyAcquirer.acquire(package,
prefer=("uslm",))` and derived through `body_text` exactly as a caller would
(2026-09-19; corpus receipt `uslm-bill-rendition-2026-09-19`; 8 keyed + 4
keyless requests for the four packages not already retained here). The JSON
carries, per package, the root element, media type, byte count, SHA-256,
derivation and derived-text line count -- facts only, no bytes.
`BILLS-119hconres11enr`'s row is re-derived offline from this directory's
retained fixture (the test re-derives it again on every run); the other four
packages' bytes were not retained, so their rows are pins, not re-derivable
inputs. `tests/test_uslm_bill_renditions.py` pins the JSON against the
retained fixture and against the census file's own aggregate.

`status-119s5.xml` is the only enacted bill here, and it is the one that
carries `<laws>` and `<recordedVotes>`: the Laken Riley Act, Public Law 119-1.
The five retained actions are the two that became law (`36000` `BecameLaw` and
`E30000` `President`, both 2025-01-29), the House passage action carrying a
`clerk.house.gov` recorded vote, the Senate passage action carrying a
`senate.gov` one, and the introduction. It has **no** `<committees>` element,
which is the publisher's ordinary answer for a measure that took no committee
action — the guide says so at the `<committees>` entry — so committee parsing
is covered by `status-119hres10.xml` and `status-119hres1376.xml`, which carry
real ones. No `<recordedVote>` in this file states `fullActionName`, matching
the actions-route measurement in
[the raw-data study](../../../docs/research/billtrax-raw-data-2026-09-19.md).

Full response SHA-256 values, before reduction:

```text
status-119hr6028 190296c4c420dd547ffdf5835352a8830e901d729729eaab432a9e6a65ff9aa7
text-119hr6028eh 89f7d7a3a1f3fe28bc5227099662d8819ba674c70ccb258edba16ada7d3fc21d
text-119hr6028ih 6cf3e83e9ef2788fadfc205ecd081f12f2306742528e4f9d4eac6047c7555ff5
```

Complete response bytes, hashes, and HTTP receipts remain outside the repository
in the `bill-parser-probe-2026-09-12` corpus receipt directory.

## Bulk archive members

Complete, unchanged members of
[`BILLSTATUS-119-hres.zip`](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hres/BILLSTATUS-119-hres.zip)
(3,934,575 bytes, SHA-256
`fe82a63f30b55086556ba4192eef973eadc91cbb94186f471f84af1f0354506a`,
`content-type: application/zip`, publisher Last-Modified 2026-09-18 20:26:06
GMT), retrieved with unauthenticated GET on 2026-09-19. The three carry the
shapes `read_bulk_status_archive` has to read; the tests build their own small
zip from them, so the archive under test is exactly these bytes. Each one was
also fetched from its own single-file locator on the same day and is
byte-identical there, so the zip member and the published file are one object.

| Fixture | Archive member | Bytes | SHA-256 | Why it is here |
| --- | --- | --- | --- | --- |
| `status-119hres1376.xml` | `BILLSTATUS-119hres1376.xml` | 5,230 | `46700c14cde7b16178df2f63373ea0b75b24343c9be6afcfebee5a7166f0999a` | The current common shape: one summary whose `<text>` is a direct child. |
| `status-119hres10.xml` | `BILLSTATUS-119hres10.xml` | 8,109 | `b820f778ba01657db0f1013ffa0541da4e97365e725a8762b6f053b2267c8175` | Its summary states `<text>` inside a `<cdata>` element; 984 of 12,938 measured files do. |
| `status-119hres214.xml` | `BILLSTATUS-119hres214.xml` | 6,181 | `d4ffc66661530ca10370fc0893e52c18b0c841cdd3d4667494ba6d12f438c49d` | An action item states `actionCode` and `sourceSystem` with no `<text>`; 7 of 12,938 do. |

Both shapes are [decision 4, measured](../../../docs/sources/congress-bulk-status.md#decision-4-measured).
The whole-zip measurement, its per-type counts and the H.R. and S.Res. zips it
also covers stay outside the repository.

## Bulk folder listing

`listing-119hres.json` is a reduced copy of the keyless
[`bulkdata/json/BILLSTATUS/119/hres`](https://www.govinfo.gov/bulkdata/json/BILLSTATUS/119/hres)
listing, retrieved with unauthenticated GET and `Accept: application/json` on
2026-09-19: `200`, `content-type: application/json`, 569,986 bytes live,
SHA-256 `c2841f003c4833e35c9062470b36851da67f17f4dca5c420c3b29ff4b02214e0`,
1,567 entries. Reduced to 4 of those entries, in the publisher's own order,
byte-identical to the live response: the folder's own zip entry and the same
three archive members documented above (`status-119hres10.xml`,
`status-119hres214.xml`, `status-119hres1376.xml`), found here as their own
listing rows. Every other entry -- 1,563 more `BILLSTATUS-119hres*.xml` rows
in the same shape -- is omitted; nothing here was reworded or reformatted.

The kept zip entry (`BILLSTATUS-119-hres.zip`, `formattedLastModifiedTime`
`18-Sep-2026 20:26`, `size` 3,934,575) names the same instant and byte count
as the zip fixture above, confirmed the same day: `18-Sep-2026 20:26:06 GMT`
to the minute and the identical byte count. The three kept XML rows'
`size` fields (8,109, 6,181, 5,230) also agree with the archive members'
own byte counts above, member and listing row describing one object twice.

The module's own sidecar measurement,
[`legislative-data-map-2026-09-18.json`](../../../docs/research/legislative-data-map-2026-09-18.json)
(`govinfo.bulkdata.BILLSTATUS.currentCongress.types.hres`), captured this same
folder's zip a day earlier at 3,933,064 bytes, `zipModified` `18-Sep-2026
16:20` -- a different instant and a different byte count from this fixture's,
because GovInfo rebuilds the zip through the day (the module docstring records
the same behavior for H.R.: 31,656,886 bytes one morning, 31,658,670 that
afternoon). The sidecar is evidence that the listing states the same two facts
the zip's own HTTP `Last-Modified`/`Content-Length` state, not a source of
this fixture's rows.

## Printing order and section identity (2026-09-26)

Native bytes for two defects spicy-regs' 2026-09-26 qualification found in its
published bill family (receipt
`fork-execution-2026-09-21/drift-qualification-2026-09-26/bills-citations/`
under `~/Work/corpora`): 119 HR 983's dateless enrolled printing was diffed
into its introduced text, and 119 HR 5334's enrolled and 119 HR 9022's
reported printings each carry two sections the old `bill_sections` identity
could not tell apart. Each whole printing's digest equals the
`bill_versions.sha256` spicy-regs published for it (generation `5990abbb…`),
and each reduced printing's source digest does too. A reduction cuts whole elements and
leaves every other byte as served. All were read keyless from GovInfo on
2026-09-26 (UTC).

| Fixture | Bytes | SHA-256 | Publisher response and changes |
| --- | --- | --- | --- |
| `status-119hr983.xml` | 21,021 | `434f32c57fad34538e1409ba9dcbf21fae62b1189303df230602ecae56913008` | [119 HR 983 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr983.xml), complete and unchanged. Its `Enrolled Bill` item has `<date/>` and is listed first; the `Public Law` item comes last. |
| `text-119hr983ih.xml` | 5,685 | `efb81403638be325bb68a53f1fc024331a7ab83b7d95a9d7b5e7a5efaeb5b3d9` | [BILLS-119hr983ih XML](https://www.govinfo.gov/content/pkg/BILLS-119hr983ih/xml/BILLS-119hr983ih.xml), complete and unchanged. |
| `text-119hr983eh.xml` | 5,433 | `e7677f36f1fc09d8fe182f7f972887e3244567b2286821753c5e436e77902060` | [BILLS-119hr983eh XML](https://www.govinfo.gov/content/pkg/BILLS-119hr983eh/xml/BILLS-119hr983eh.xml), complete and unchanged. |
| `text-119hr983rfs.xml` | 5,609 | `a0e5c4a6c0b989ca30ef583daef74dedd83ae5a37de6bbcc2968998b007e0e26` | [BILLS-119hr983rfs XML](https://www.govinfo.gov/content/pkg/BILLS-119hr983rfs/xml/BILLS-119hr983rfs.xml), complete and unchanged. |
| `text-119hr983enr.xml` | 5,544 | `b95447fdcbe46553d563f2a656e32f4b3a9861b92e4d75e57ba0812c5eb3a12a` | [BILLS-119hr983enr XML](https://www.govinfo.gov/content/pkg/BILLS-119hr983enr/xml/BILLS-119hr983enr.xml), complete and unchanged; the enrolled printing and the law's body. |
| `status-119hr5334.xml` | 4,440 | `064612eb7f2a7d2c0e13445627f70d4ad20b80ff665aed715574ddd0d71b41aa` | [119 HR 5334 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr5334.xml) (108,169 bytes, `6c942ee61f174e587f964acebc70e8b611095c4be4edeab235654f90d4e21f29`). Reduced: the top-level `constitutionalAuthorityStatementText`, `committees`, `committeeReports`, `relatedBills`, `actions`, `cosponsors`, `cboCostEstimates`, `subjects`, `summaries`, `titles` and `amendments` elements are cut; `textVersions` is byte-identical. |
| `text-119hr5334ih.xml` | 4,346 | `c456aa223105d0b36d54c9817d09d516bf55556679043abda30559201f1b85ea` | [BILLS-119hr5334ih XML](https://www.govinfo.gov/content/pkg/BILLS-119hr5334ih/xml/BILLS-119hr5334ih.xml), complete and unchanged. |
| `text-119hr5334enr.xml` | 9,478 | `e71e46d361aab11f9d7ad6863dd90c558f007eb38a09e540f08c06179c7e2dbd` | [BILLS-119hr5334enr XML](https://www.govinfo.gov/content/pkg/BILLS-119hr5334enr/xml/BILLS-119hr5334enr.xml) (113,233 bytes, `50bf7a3c48fc607dee1cc800389c0e5afd682474aa3c399e2aa1e363d6096ca2`). Reduced: Division A's two `title` elements (`H42DEB9C…`, `H751A661…`) are cut, keeping Division A's and Division B's `Sec. 1` (`H7962367…`, `H99FFDB5…`), which share the match path `sec. 1`: seqs 3 and 6 here, 3 and 80 in the whole printing. |
| `status-119hr9022.xml` | 23,866 | `9bbca5ad13200b0c3ac548b4f1fddce0cb9ce1299639f7e20a3b8b0620515583` | [119 HR 9022 BILLSTATUS](https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119hr9022.xml), complete and unchanged (publisher Last-Modified 2026-07-24 10:24:25 GMT). |
| `text-119hr9022rh.xml` | 9,288 | `b0952d9eb609fb31393117d27ba72c966ec03ca558fd1b5ff20e4d3b77b7667b` | [BILLS-119hr9022rh XML](https://www.govinfo.gov/content/pkg/BILLS-119hr9022rh/xml/BILLS-119hr9022rh.xml) (124,422 bytes, `fc82dbe573754a737e74e6489262dd423bdb9d1e17d8b6203456c77e6c1f135b`). Reduced: every `title` but Title III is cut, and within Title III every child but its `enum`, `header`, the `ENERGY PROGRAMS` major heading, the `Title 17 Innovative Technology Loan Guarantee Program` intermediate heading and the two `appropriations-small` paragraphs under it (`HA2B9AE2…`, `HF8CCDC6…`), which share that heading's match path: seqs 4 and 5 here, 68 and 69 in the whole printing. |
