# Choose a PDF extraction approach

Keep several extraction choices and select them for the source, document family,
page content and required output. The strongest option for native prose need not
be the strongest option for a scanned form in the same PDF.

The [machine-readable choice catalog](pdf-extraction-choices.json) saves named
options, tested settings, useful combinations, limits and evidence references.
The catalog is documentation data, not executable configuration. The
[unified extraction API](pdf-extraction-api.md) implements the selected PyMuPDF,
RapidOCR, Apple Vision, LightOnOCR, GLM-OCR and Gemini choices, including native
plus regions and multi-turn Gemini. Their catalog entries name the corresponding
strategy and optional extras. Other converters remain saved research choices.
DocSpec retains its document and representation lifecycle; source defaults remain
caller-selected.

## Main choices

These are candidates supported by selected FEC experiments, not universal quality
rankings. A proposed use on another source still needs source-specific checks.

| Choice | Suitable starting point | What the experiments showed | Main limitation |
| --- | --- | --- | --- |
| `native-pymupdf` | Digital prose, legal opinions, letters and stamps available as native text | Useful native text and word/line coordinates; recovered some overlays the pypdf baseline missed | Searchable headers do not prove searchable bodies; raster and vector lettering may be absent |
| `native-poppler` | Native text when a command-line backend fits; optional layout-preserving whitespace | Comparable selected native content to PyMuPDF | Whitespace is not a verified table or field mapping |
| `ocr-rapidocr` | Scanned prose and supplementary image text; portable local OCR | Useful text, boxes and confidence without an API call | Can drop whole lines, negations, decimals and checkbox states |
| `ocr-apple-vision` | Local OCR on macOS | Strong selected text recovery; keep Apple's OCR as a distinct choice | macOS-specific; financial values and reading order still had errors; not an Apple generative model |
| `ocr-lighton` | Local full-page extraction of prose, metadata and forms | Strongest new local candidate in the configuration comparison; preserved selected checkbox states and distinct refunds | Monetary notation, year/column binding, signature presence and a drawn counter still failed; preserve HTML value attributes |
| `vision-gemini` | Dense forms, mixed pages, scans and vector lettering that need visual interpretation | Stronger selected form relationships than ordinary OCR | Amount, due-date, blank-cell and unchecked-box errors remain |
| `vision-multiturn-summary` | Difficult pages needing full-page context and systematic close inspection | Full page, overlapping strips with summaries, then final JSON was the strongest candidate in the sequential pilot | A final table still lost column structure; retains full history and costs more; further-evaluation gate is not production qualification |
| `native-region-ocr` | Native prose with bounded image text such as a logo or stamp | Recovered the Elias logo while preserving the native sentence full-page OCR dropped | Another letter's footer URL was corrupted; region coverage and ordering need checking |
| `native-region-vision` | Native prose plus selected image text, or a visually complex region | Strongest result in the regional pilot; economical supplementation of mixed prose | Unchecked-box, monetary and table errors remain; manual cropping lost a drawn page counter; automatic-selection gate failed |
| `docling-json` | Workflows that need structured document output, tables and intermediate page cells | Retaining parsed pages and all content layers recovered otherwise discarded text | Recognition, layout classification and export can each lose different content; tables were not reliably correct |

For native and OCR observations retain the coordinates, not only joined text.
For model outputs retain the original response as well as the derived body.
Markdown is a useful view; its appearance does not establish source fidelity.
The catalog's evidence entries link each choice to its retained settings, inputs,
outputs, assessments and run receipts.

## Additional choices worth keeping

| Choice | Why retain it | Current evidence limit |
| --- | --- | --- |
| `docling-vlm-gemini` | Remote vision inside an existing Docling workflow | Better form output than the tested local VLM, but serialization merged a blank due-date boundary; retain raw VLM output |
| `marker-llm` | Marker workflows whose particular layout processors benefit from LLM correction | Repaired selected loan fields; failed to recover another form's financial labels despite extra calls; a conditional candidate |
| `liteparse` | Another structured local parser when its JSON annotations/fields fit the consumer | JSON preserved more checked content than Markdown; remaining identifier/date and form errors |
| `vision-openai-mini`, `vision-openai` | Provider/model alternatives for future source-class comparisons | Tested GPT-5.4 mini and GPT-5.5 preserved many anchors but changed financial amounts; neither was established as better overall |
| `ocr-tesseract` | A conventional local baseline or an existing Tesseract installation | The tested PSM 3 configuration produced form noise and lost decimals/checkboxes; other languages and modes need evaluation |
| `searchable-pdf-ocrmypdf` | A derived searchable PDF and OCR sidecar are required outputs | Skip, redo and force strategies have different tradeoffs; force can replace correct native values with mistakes |
| `native-query-pdfquery` | Positioned native elements must be queried by known geometry | Queryable XML is useful; no OCR capability, and default resorting had excessive repeated box comparisons |
| `vision-multiview` | Full page and overlapping strips in one request | Cheaper than sequential inspection, but lost more selected amounts, column relationships and checkbox information |
| `vision-multiturn-records` | Detailed intermediate observations and summaries are useful for inspection | Tied running summaries on critical page-failure count, cost more, repeated an incorrect payment and produced invalid source IDs |
| `ocr-glm` | A local specialist providing a separate table observation | `Table Recognition:` preserved the difficult FEC summary's central table where text mode flattened it | One exposed diagnostic; outside-table content omitted, debt-plan cents and vendor selection still failed |
| `mineru-configurations` | Research or an existing MinerU workflow needing layout and intermediate JSON | Saved pipeline, language, table, hybrid and image-analysis configurations; JSON retains content omitted by Markdown | Narrow images can bypass recognition; the diagnostic gate override recovered amounts without repairing all relationships |

The current DocSpec `LazyPypdfExtractor` remains an existing native-text baseline;
these saved alternatives do not remove it. PDFium, pdfplumber and
PyMuPDF4LLM with OCR disabled remain available comparison baselines in the original
experiment archive. Their tested configurations did not demonstrate a recall gain
over the smaller alternatives that would make them main choices here.

Keep the remaining research too. The catalog links the complete earlier
dispositions rather than copying every backend and package inventory. Stock
Marker balanced had an operational grammar failure; its compatibility diagnostic
is not stock behavior. Tested GraniteDocling MLX, Paddle and Unstructured
configurations did not establish a reason to prefer them on these FEC pages.
The later MinerU configuration sweep explains several remaining losses: export
can discard recognized furniture, small-image filtering can skip amounts, and
image interpretation can invent relationships. Keep those configurations as
research choices, with the private gate override clearly distinguished from a
supported option. LightOnOCR and GLM-OCR are separate open-weight candidates;
olmOCR-2 and DeepSeek-OCR-2 remain researched but untested in this round.
Unexecuted hosted options, including Mistral OCR, Document AI, Azure Document
Intelligence, Textract, LlamaParse and Datalab hosted extraction, remain research
candidates, with no quality verdict. A failed mode does not reject its whole
product family, and an unavailable credential does not measure model quality.

## Select by source and page, with an explicit override

Treat a source's known document family as a starting preference. Also inspect
how each page stores visible content and which relationships must survive.

| Source/document example | Choices to compare first | Preserve and check |
| --- | --- | --- |
| FEC legal opinion or another source's complete digital prose | Native PyMuPDF; Poppler alternative | Footnotes, negations, received stamps, links and page identity |
| FEC law-firm letter with a raster logo/footer | Native plus region OCR or region vision | Native prose unchanged outside regions; names, URLs, stamps and unselected visual text |
| Scanned correspondence from any source | RapidOCR; Apple Vision on macOS; LightOnOCR or full-page vision when needed | Complete sentences, dates, names, signature presence and reading order |
| Financial summaries, filled forms and checkboxes | Official structured rendition when equivalent; otherwise sequential vision with summaries, compared with LightOnOCR and a separate GLM table observation | Labels, columns, empty versus zero, checked versus unchecked, distinct transactions and conflicting amounts |
| Reports requiring structured hierarchy or table exports | Docling JSON; LiteParse; conditional Docling VLM or Marker LLM | Raw recognition and intermediate structure as well as export; furniture and picture text |
| Known native form geometry | Native coordinates; PDFQuery only if querying adds value | Positional field mapping and layout/version drift; this extraction use still needs qualification |
| Blank or purely decorative page | Native/empty representation after source inspection | No invented body; absence of native text alone cannot identify this case |

The API supports explicit page overrides and region selections within a document
strategy. The caller resolves any source-family preference before constructing the
extractor and retains the selection reason. Results record the strategy and backend
settings. The catalog's illustrative configuration is not parsed by the runtime;
`automatic_selection` remains false.

Do not switch an entire PDF merely because one page needs OCR. Do not treat
nonempty native text, a low raster fraction, agreement among models, or a successful
parser exit as evidence of completeness. The tested automatic page routers and
the latest manual-region gate did not meet their no-regression criteria.

The sequential candidate sees the full page, three overlapping strips from top to
bottom, and the full page again before producing JSON. It retains every earlier
image and answer, including provider continuation signatures. Its summaries were
not always cumulative; the experiment does not support keeping only the latest
summary. Detailed intermediate transcriptions remain a choice, but did not improve
the overall result over summaries in this test. The API now constrains source IDs to supplied images and validates final JSON.
Explicit table-cell output remains a further experiment: current final JSON can
still contain tables as Markdown within transcription strings.

The later local comparison supports testing a specialist on the part it handles
well. GLM's table prompt preserved the central summary table, while LightOn kept
more complete page content. Their combination has not been tested. Keep both
observations separately traceable, then check explicit table cells against the
source. Gemini's prior multi-turn result remains the strongest complete-page
candidate on these selected cases; it does not establish a ceiling for a local
specialist. The local experiment used exposed development pages and community
MLX bf16 conversions, with no new holdout or production-throughput test.

## Settings and evidence that travel with a choice

- Record source bytes/digest, original page number, rendition identity, page
  rotation, region rectangle, render resolution, coordinate convention and every
  transform back to the original page.
- Retain native text/boxes, raw OCR text/boxes/confidence, raw model responses,
  structured JSON and any derived display text separately. Keep competing amounts
  as disagreements; do not merge or vote them into a source fact.
- Pin the engine/package/model revision, effective options, prompt and prompt
  digest. The catalog records historical tested settings; later versions and
  different parameter combinations are not automatically qualified.
- For Docling, retain `generate_parsed_pages=True` output, full JSON, page/picture
  images and raw VLM output where applicable. Choose export content layers and
  picture traversal deliberately; a serializer can remove a distinction the raw
  response retained.
- For MinerU, retain all content-list fields, middle/model JSON and image crops;
  header and footnote loss in Markdown can be an export decision. For LightOn,
  preserve meaningful HTML attributes: tested refund amounts occur in `input`
  value attributes. Resolve generated image references against retained files;
  a filename emitted by a model is not evidence that the image was saved.
- Keep OCR language, rendering, full-page versus regional scope, provider/model,
  prompt and output limits configurable at the processor boundary. Tested choices
  are explicit configurations; the catalog does not claim every combination ran.
- Account for detection, rendering, all model calls, retries and reconciliation.
  Small crops can add requests and take longer. Reuse acquired bytes and retained
  observations; add a thin optional backend only when its source class benefits.

The full-page input-fusion experiment did not establish an overall benefit from
always feeding native text, OCR text and images to the LLM. Preserve that as an
experimental variant in the archive, rather than making all three mandatory.
Prefer official XML/JSON/XHTML and native bulk records when they carry the required
content. PDF extraction supplies additional document evidence, not replacement
financial authority.

## Retained experiments

The JSON catalog resolves evidence paths under
`~/Work/corpora/supply-2026-09-02/receipts/`. Those large local captures are not
bundled with SpicyDocs. Each referenced report is pinned by SHA-256 in the catalog;
its neighboring files retain actual versions, requests, failures and inputs.

| Evidence ID | What it preserves |
| --- | --- |
| `comparison` | Original native/OCR/converter/provider comparison and all alternative dispositions |
| `hybrid` | Docling settings, parsed-page/export retention, local/remote VLM, Marker modes and request crossover |
| `layout` | PDFQuery, layout detectors and manually assigned page types |
| `routing` | Automatic page-router failures on additional documents |
| `fusion` | Full-page image/native/OCR input ablation |
| `regions` | Native-preserving regional OCR/vision, controls, costs and failed automatic-selection gate |
| `multiturn` | Full page and covering strips, running summaries versus detailed observations, final JSON, stage traces, costs and a passed gate for further evaluation of summaries |
| `open_models` | MinerU configuration sweep, GLM text/table prompts, LightOnOCR, adaptive repeats, image-size diagnostic, raw exports/intermediates and local cost accounting |

The reusable result is this set of choices and their limits. Automatic routing,
general historical-scan coverage, multilingual extraction, cross-page tables,
handwriting and production throughput remain unqualified. Evaluate a newly
selected source class before making one of these choices its default.
