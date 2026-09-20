# Four retained PDF text controls

These are the complete normalized text strings from four fixed GovInfo PDFs
already retained in `cbo-routes-2026-09-20/`, derived without requests by
`extraction.body_text.rendition_text(..., rendition="pdf", media_type="application/pdf")`.
`sources.json` pins the source PDF, normalized text and located letter digest.
The test pins exact offsets into each text. The build receipt replays the
original PDFs through that same product path and checks these fixtures.

The House headings are single uppercase lines; the Senate heading starts
`VI.`. Contents entries retain dot leaders. The two newer attributions wrap
between `Congressional` and `Budget Office`. The two older signatures preserve
uppercase names. None of these fixtures includes raster extraction or cost
figures recovered from an image. Four fixed texts, 97,113 characters total,
keep the covers, contents and surrounding prose as false-positive controls.
