# Retained inspector-general metadata fixtures

Exact metadata bytes from `unitedstates/reports` at commit
`779b991b33e317eaa118985834618e67e3cc35c2`, retrieved 2026-09-28:

- `ccr-report.json`: `inspectors-general/ccr/2012/OIG-USCCR-12-1/report.json`
- `cia-report.json`: `inspectors-general/cia/2007/2004-7601-IG/report.json`

The CIA file intentionally keeps archive year 2007, publication date 2007-07-16,
and metadata year 2016. The archive is a community source; its metadata fields
are assertions, and its original-document URLs can point to another archive.
These fixtures include metadata only. No source document is fetched by the tests.
