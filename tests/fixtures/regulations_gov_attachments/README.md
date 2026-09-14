# Regulations.gov attachment-host fixtures

Captured 2026-09-14 from `downloads.regulations.gov`, keyless, with the browser
User-Agent the host requires. These U.S. government responses are public domain.
Offline tests establish behavior for this shape; they do not establish coverage
or continuing live availability.

| Fixture | Request | Bytes | SHA-256 | Transformation |
| --- | --- | --- | --- | --- |
| `FAA-2016-6907-0001-content.pdf` | [https://downloads.regulations.gov/FAA-2016-6907-0001/content.pdf](https://downloads.regulations.gov/FAA-2016-6907-0001/content.pdf) | 2,620 | `f4494ea77d0f8a0ec0b6e7f64e20c6ffe6c53d3be47cd59245f42f74036a7fc0` | Complete, unchanged response. |

The file is kept whole rather than truncated to 2 KB because a prefix cannot
prove a digest, and this one is checkable three ways: the API declared
`size: 2620` for it in `../listings/regulations-gov-document-detail.json`, the
host returned exactly that many bytes, and the same digest was recorded
independently on 2026-09-05 in the pinned PDF floor population
(`corpora/supply-2026-09-02/receipts/pdf-floor-population-2026-09-05.json`,
where it is the smallest of 1,000 rows). Same bytes, two tools, nine days apart.

The host answers three ways and they are not interchangeable. A served file is
`200` with `application/pdf` and a `Content-Length` matching the declared size.
A rejected client is `403` with a 919-byte `text/html` page -- what
`spicy-docs-regulations-gov/1.0` received for this exact URL one request
earlier. A file that is not there is `403` with S3's 111-byte
`application/xml` `AccessDenied`. Only the first is a file, and neither `403`
establishes absence. The full bodies, headers and timings are in
`corpora/supply-2026-09-02/receipts/port-P05-regulations-gov-2026-09-14/`.
