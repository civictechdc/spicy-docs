# Synthetic Federal Register XML

`document.xml` is an authored example, not a publisher capture. Its document
number and filing text exercise XML identity checks; the requested URL supplies
the publication date. No redactions were made.

Run `examples/federal_register_body.py` to retain the exact XML. Its
`--case html-fallback` demonstration uses the neighboring GovInfo fixtures and
an authored XML 404 response. Both cases run offline.
