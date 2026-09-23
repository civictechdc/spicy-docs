# Regulations.gov through Mirrulations

Capture documents, dockets, or comments from the anonymous Mirrulations S3 mirror.
Each release retains exact objects in deterministic ZIP packs.
`complete-snapshot` covers the enumerated mirror scope, not all Regulations.gov
records or history.

## Scope and evidence

The [CLI](../cli.md#publish) requires dates and named agencies:

| Collection | Scope date | Selection version |
| --- | --- | --- |
| Documents | `postedDate` | `modifyDate`, then `postedDate` as fallback |
| Dockets | `modifyDate` | `modifyDate` |
| Comments | `postedDate` | `modifyDate` |

- An object's S3 path, collection, agency, and body identity must agree.
  Refetch filename suffixes do not create new identities.
- Documents with null or unusable posted dates remain excluded evidence.
  Dockets and comments require their respective scope dates.
- Each query acquires the full named agency/collection listing, then selects
  dates from object bodies. Shorter windows repeat those reads.
- The exact reader lists keys in order, pins each GET to its listed ETag, and
  checks metadata and byte length. Changed or missing objects abort enumeration.
  Processed-key omission is available only in the [raw reader](raw-readers.md#mirrulations).
- Object pins do not freeze the live listing at one upstream instant.
- Packs start at zero, remain contiguous per agency, and end with a terminal
  pack. Agencies and keys remain ordered and distinct.
- Publication and replay recompute inclusion from exact saved bodies and check
  it against manifests and results; editing an `included` flag cannot change
  membership silently.

## Selection preserves source differences

All profiles use `data.id`. Timestamps become UTC only for comparison; records
retain source timestamps. A non-null version wins over null.

Read a calendar day with `regulations_gov_day`, never the UTC prefix: the
publisher closes a comment window at 11:59:59 PM Eastern (`03:59:59Z` or
`04:59:59Z`), so the prefix is a day late on every deadline, while a bare
`T00:00:00Z` is a date-only value that keeps its date. `regulations_gov_instant`
gives the Eastern-clock instant, or None for a date-only value. The measurement
and receipt are in `spicy_docs.sources.regulations_gov.dates`.

| Collection | Repeated winning version |
| --- | --- |
| Documents | Identical canonical records collapse. If only `openForComment` or `withinCommentPeriod` differs, the last-listed observation wins. Other differences refuse publication. |
| Dockets | Identical canonical records collapse; differences refuse publication. |
| Comments | Every repeated identity/version refuses publication, including identical records and null versions. |

The two document fields can change without a new source version. Tie comparison
omits only those fields; the selected record digest includes both, and evidence
retains every observation. See [source-specific rules](../decisions.md#similar-sources-can-need-different-rules).

Closed classifiers refuse unknown fields, malformed identity, wrong agency, and
ambiguous versions. Renditions preserve attachment locators and metadata; they
contain no downloaded attachment. Stream admitted records or export the matching
public table, retaining the source release and blob store for original JSON.

Policy `1.2` pins rendition typing: publisher media types or known aliases take
precedence, then the final URL path extension supplies a known type. Queries,
fragments and parent directory names do not supply an extension. JSON becomes
`application/json`; unknown types remain `application/octet-stream`. All three
profiles share this policy version; dockets still state no renditions. Current
readers refuse earlier policies. The raw record schemas remain `1.0`.

## Change and check

[`sources/regulations_gov/`](../../src/spicy_docs/sources/regulations_gov/) owns
this behavior: `definitions.py` declarations, `validation.py` checks,
`records.py` classification/versions, `schemas.py` shapes, `scope.py` membership,
`evidence.py` decoding, `acquisition.py` capture, and `profile.py` composition.

```sh
uv run --frozen pytest -q tests/regulations_gov/ tests/test_mirrulations_reader.py
```

Cover excluded objects, refetches, null dates, changed metadata, missing terminal
packs, drift, and ties. Include replay for key/body identity and enumeration
changes; schema checks alone cannot prove either.
