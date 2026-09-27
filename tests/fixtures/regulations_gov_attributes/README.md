Four Regulations.gov API detail records (`data` objects), as DocSpec's `catalogue` capture holds them
(pin `sha256:2200b5e6…`, supplied 2026-09-02), extracted by DocSpec `a93ecd4`'s
`tools/export_regulations_attributes.py extract`:

- `documents.json`:
  - `CFTC-2026-0925-0001`: topics, an effective date, `withinCommentPeriod`;
  - `EPA-HQ-OW-2008-0465-1709`: authors and an author date;
  - `DOT-OST-2000-8082-0016`: a government submitter's stated contact fields.
- `dockets.json`: `DOS-2026-0760`, with keywords and an effective date.

No record states both authors and topics: of 1,943,106 documents, 217,308 state authors and 85,110 topics, and
none states both.
