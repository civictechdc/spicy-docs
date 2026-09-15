# Read embedded PDF page text

Use `PypdfReader` when a consumer needs pypdf's original page strings. Install
`spicy-docs[pdf-pypdf]`; this extra adds pypdf without a renderer, OCR engine, or
model. Importing and configuring the reader loads none of those packages.

```python
from pathlib import Path

from spicy_docs.extraction.pypdf import PypdfReader

source = Path("document.pdf").read_bytes()
with PypdfReader().open(source) as document:
    print(document.backend_version, document.page_count, document.is_encrypted)
    for number in range(1, document.page_count + 1):
        text = document.read_page(number)
        print(number, repr(text))
```

`read_page` uses one-based page numbers and returns the backend's exact `str` or
`None`. It preserves blank pages and whitespace. The caller chooses separators,
text folding, retained evidence, and whether a failed page aborts the document.
Use the [PDF and image extraction API](pdf-extraction-api.md) for page geometry,
native text blocks, rendering, or an explicitly selected OCR/model backend.

| Input or outcome | Behavior |
| --- | --- |
| `password=None` (default) | Refuse every encrypted PDF, including one readable with an empty password. |
| `password=""` or another string | Explicitly try that password. The document still reports `is_encrypted=True` after successful decryption. |
| `expected_backend_version="6.14.2"` in the reader constructor | Require that installed version and the matching loaded module before opening the PDF. The result reports the actual backend version. |
| Invalid or over-limit input | Raise `ValueError` before loading pypdf. The default input limit is 64 MiB; select `max_input_bytes` explicitly to change it. |
| Missing backend or unreadable PDF | Raise `PdfReadError`, derived from the existing `ExtractionError`. |
| Encryption refusal | Raise `PdfEncryptedError`, a `PdfReadError` subtype. |
| Page extraction failure | Raise `PdfPageError` with its one-based `.page` and the original exception in `.__cause__`. Other pages remain available while the context is open. |

The context owns the byte stream and pypdf reader and closes them on exit,
including after a caller error. A closed document cannot read pages. The reader
does not retain passwords, write files, fetch sources, or retry extraction.

The byte limit bounds accepted input, not PDF decompression, extraction time, or
output size. Applications own execution limits. Empty extracted text means
pypdf supplied no text; it does not prove a visually blank page. pypdf can also
recover from malformed structures, so this reader is not a PDF conformance
validator. Source bytes remain the evidence for future extraction.

Qualification uses pypdf 6.14.2, the complete retained
[FAA fixture](../tests/fixtures/regulations_gov_attachments/README.md), and generated
valid PDFs with blank, whitespace, encrypted, and damaged-page controls. Consumer
tests separately check their formatting and error policies. RefSpec's PDF
geometry/font visitors remain separate from this page-string API.
