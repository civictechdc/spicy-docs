# Historical statute metadata

`spicy_docs.sources.historical_statutes` reads retained community metadata from
the unitedstates Legisworks and Nabors projects. It adds early statute-to-bill
evidence that the official U.S. Code classification reader does not supply.
The caller provides exact bytes and a full Git commit, and retains the bytes
beside the returned SHA-256 and source URL. The commit identifies the requested
snapshot; the parser does not independently authenticate that acquisition.

```python
from spicy_docs.sources.historical_statutes import parse_legisworks_volume, parse_nabors_table

volume = parse_legisworks_volume(yaml_bytes, volume=16, commit=legisworks_commit)
crosswalk = parse_nabors_table(csv_bytes, commit=nabors_commit)
```

Install `spicy-docs[yaml]` for Legisworks. Nabors parsing uses the standard
library. Both APIs preserve every source field, record order and duplicates.
The result's `records` contain `source_record_index` and `fields`; Legisworks
also supplies the source-documented `pdf_url`. Those links do not establish
downloaded PDF contents. Nabors also supplies physical CSV line coordinates.
Nabors rows with a source `ERROR` marker or the wrong cell count remain visible
with `status="unmapped"`, literal `cells`, and `fields=None`. Callers must check
that status before attempting an association; a successful file read does not
mean every transcribed row supplies usable coordinates.

Use the source record index with its input digest as observation identity.
Several statutes can start on one printed page, and early bill numbers can
repeat across sessions. A page match supplies candidates, not a single law.
Keep fractional identifiers, missing values, and every candidate. In particular,
do not fill Nabors's blank Congress cells by guessing from neighboring rows.
American Memory's separate document printings can add context after an explicit
association check; these readers do not assert those links.

These are community transcriptions with source-specific limitations. Legisworks
documents missing original scan pages. Nabors describes an incomplete digitization
of a research table; this reader handles table facts, not the book's prose.
The fixture provenance under `tests/fixtures/historical_statutes/` records the
bounded source excerpts used in offline checks. The workspace's unitedstates
validation report records the larger pinned-file pilot.
