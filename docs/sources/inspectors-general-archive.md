# Read archived inspector-general report metadata

`parse_inspector_general_report` reads retained metadata produced by
[`unitedstates/inspectors-general`](https://github.com/unitedstates/inspectors-general)
and used by the [`unitedstates/reports`](https://github.com/unitedstates/reports)
archive. It preserves the complete record, including unknown fields, and separates
source-declared file links from the metadata capture.

```python
from pathlib import Path
from spicy_docs.sources.agency_reports.inspectors_general import parse_inspector_general_report

result = parse_inspector_general_report(
    Path("report.json").read_bytes(),
    url="https://raw.githubusercontent.com/unitedstates/reports/779b991b33e317eaa118985834618e67e3cc35c2/inspectors-general/cia/2007/2004-7601-IG/report.json",
)
assert result["record"]["year"] == 2016
assert result["record"]["published_on"] == "2007-07-16"
```

The metadata URL identifies the retained input; `source` records its SHA-256 and
byte length. `record` retains every parsed field, `assets` lists the declared
report URL and file type, and `links` retains inspector, landing, and summary
page URLs. A source can declare an unreleased report with a landing page and no
file. No network request occurs during parsing.

Archive path year, metadata `year`, and `published_on` can differ. The example
above is a real upstream record, and all values survive. Select archived
`report.pdf` or other members from a retained archive listing rather than
reconstructing a directory from metadata. A declared origin URL can itself point
to another archive; keep that assertion distinct from the downloaded file's URL.

The reader refuses duplicate JSON keys, malformed inputs, invalid required field
shapes, and metadata exceeding the caller's byte bound. Tests use exact bounded
metadata fixtures plus malformed and unreleased controls. The dated workspace
review records replay over the inspected archive. This reader adds historical
input support alongside [Oversight.gov HTML](agency-reports.md); it does not
establish collection completeness, acquire linked originals, or publish a release.
