# GAO report-file fixtures

Captured 2026-09-14 from `files.gao.gov` with a plain HTTP client and no
credential; that host takes none. These U.S. government responses are public
domain. Offline tests establish behavior for these shapes; they do not
establish coverage or continuing live availability.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `gao-26-107693-index.html` | [https://files.gao.gov/reports/GAO-26-107693/index.html](https://files.gao.gov/reports/GAO-26-107693/index.html) | 6,657 | `d1915f230bb4665e77c3745505411df6432e46a98281b37fb09d7fa56ebede90` | Three byte ranges of the response, joined by two comments that state the removals: `0-415` (doctype, meta, title), `82592-88564` (`</head>` through the report-PDF anchor, including both product-page links), `419830-419991` (the closing tags). Full response 419,991 bytes, SHA-256 `f2a1436278dad1541d72d510e745ba993ff92ef4b61506988f5aa6e840e69271`, `Content-Type: text/html`. |
| `gao-26-107693-pdf-head.bin` | [https://files.gao.gov/assets/gao-26-107693.pdf](https://files.gao.gov/assets/gao-26-107693.pdf) | 2,048 | `7e88c789c500ae57f3ead7eaae384990c1908037739d6273bb7f512562a5bfc5` | First 2,048 bytes only. Full response 5,020,419 bytes, SHA-256 `c970457a529f7bff7eac420bbe0e82e96b3f5907cbf2e00ff8aa95bd3b1543fe`, `Content-Type: application/octet-stream`. The reduction is the point: it carries the publisher's real `%PDF-1.7` header and, being truncated, must be refused. |
| `files-access-denied.xml` | [https://files.gao.gov/reports/GAO-99-999999/index.html](https://files.gao.gov/reports/GAO-99-999999/index.html) | 263 | `333c9fd200b3b8dca5e316599c253cbfa6aa9b55f9f2ec700e9b4d60b8efd03d` | Complete, unchanged `403` body for a product that does not exist. |

No complete PDF is committed: the publisher's report bodies run from hundreds
of kilobytes to megabytes. Transport behavior is exercised on a minimal
synthetic PDF declared in `tests/test_gao_files.py`, which is labeled there as
synthetic and proves nothing about GAO.

`files-access-denied.xml` is the answer this host gives for an object it does
not have. It is the same `AccessDenied` document it returns for a path spelled
with the wrong case, differing only in the request identifiers, so a `403` here
never establishes absence.

Headers, every probe, and the parser run over the four complete retained index
bodies are in
`corpora/supply-2026-09-02/receipts/port-P04-gao-files-2026-09-14/`.
