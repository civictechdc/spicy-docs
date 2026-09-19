# Agency-report-block fixtures

`crpt-119hrpt105.txt`, `crpt-113hrpt135.txt` and `crpt-113srpt77.txt` are the
text `report_blocks.parse_agency_blocks` reads, not the PDFs themselves. They
are the repo's own extraction output -- `spicy_docs.extraction.api.DocumentExtractor(NativeText())`
over `pymupdf==1.28.2`, one page's `.text` per line joined with `"\n"` -- run
against three real committee reports fetched keyless from GovInfo on
2026-09-19. These U.S. government documents are public domain. Offline tests
establish behavior for these shapes; they do not establish coverage or
continuing live availability.

Byte counts, SHA-256 values, page counts and provenance for every fixture are
in `sources.json`, read by `tests/test_report_blocks.py::test_retained_fixture_pins`
(shared with the FOIA/Oversight fixtures above). `sourcePdfSha256`/`sourcePdfBytes`
are the original PDF `curl` fetched from the `url` column; `extractedWith` names
the extraction call; `complete: false` fixtures additionally give the full
(untruncated) extracted text's own character count and SHA-256, so the excerpt
below can be checked against its source even though that full text is not
committed.

| Fixture | Package | Pages | PDF bytes | Extracted text | Fixture bytes | Reduction |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `crpt-119hrpt105.txt` | [CRPT-119hrpt105](https://www.govinfo.gov/content/pkg/CRPT-119hrpt105/pdf/CRPT-119hrpt105.pdf) | 3 | 199,803 | 7,113 chars | 7,140 | None -- complete extracted text. |
| `crpt-113hrpt135.txt` | [CRPT-113hrpt135](https://www.govinfo.gov/content/pkg/CRPT-113hrpt135/pdf/CRPT-113hrpt135.pdf) | 229 | 3,233,438 | 513,773 chars | 72,466 | Two ranges of the full extracted text, `[0:60000]` and `[471565:483565]`, joined by one plain-text line stating the omitted range (`[omitted: characters 60000-471565 ...]`, itself not a valid header line -- it contains lowercase text). The second range holds the one measured hyphen-line-wrap header fragment (`hyphenWrapFragmentHeaders: 1` in `docs/research/billtrax-raw-data-2026-09-19.json`); the first holds the report's front matter and its first real `DEPARTMENT OF THE ARMY` section. |
| `crpt-113srpt77.txt` | [CRPT-113srpt77](https://www.govinfo.gov/content/pkg/CRPT-113srpt77/pdf/CRPT-113srpt77.pdf) | 190 | 531,055 | 615,326 chars | 180,900 | First 180,000 characters of the full extracted text (`[0:180000]`); front matter through multiple `DEPARTMENT OF HOMELAND SECURITY`/`OFFICE OF ...` sections. This report measured zero hyphen-wrap fragments, so no excerpt needs to reach further in to find one. |

These are the same three packages `docs/research/billtrax-raw-data-2026-09-19.md`
§6 measured (fetched there with `pdf-parse`-equivalent decoding; re-fetched
here and re-extracted with this repo's own pymupdf-based `extraction` module
rather than reusing that document's numbers). PDF byte sizes match that
document's table exactly (199,803 / 3,233,438 / 531,055) and `crpt-119hrpt105`'s
PDF SHA-256 matches its recorded `sourcePdfSha256` from that same measurement,
confirming it is the identical file. Extracted-text character counts are close
to but not identical to that document's pdf-parse-based counts (7,113 vs
7,116; 513,773 vs 514,002; 615,326 vs 615,516) -- a different PDF text-extraction
library, not a different document.
