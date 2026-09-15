# Federal Register reference data

Use these readers for retained publisher agency lists, documented codes and type
facets. They require only the core wheel. Per-document metadata already belongs
to the [Federal Register document reader](federal-register.md).

```python
from spicy_docs.sources.federal_register.reference_data import (
    read_fr_agencies,
    read_fr_documented_enums,
    read_fr_type_facets,
)

roster = read_fr_agencies(agencies_bytes)
for agency in roster.records:
    print(agency.source_path, agency.agency_id, agency.name, agency.parent_id)

documented = read_fr_documented_enums(documentation_bytes)
for enum in documented.enums:
    print(enum.schema_name, enum.source_path, enum.values)

facets = read_fr_type_facets(facets_bytes)
```

| Input | Source fields retained | Caller decisions |
| --- | --- | --- |
| `/api/v1/agencies` | Ordered agency IDs, names, URLs, parent/child values, full raw rows including logos | Required field set, unique IDs/slugs, valid graph links, accepted URL hosts |
| `/api/v1/documentation.json` | Direct and array-item enums under `components.schemas`, literal values/order, raw schemas and full root | Which documented sets matter, code grammar, comparisons with other captures |
| `/api/v1/documents/facets/type` | Ordered codes, names, counts and full raw rows | Whether codes match a separately captured enum and counts are usable |

Each result includes the exact input SHA-256 and byte count. Row and enum paths
identify positions in the decoded JSON; they are not original-byte spans. Enum
tuple indexes are zero-based source ordinals. Keep original bytes for replay.

Known fields must have the expected JSON types. Empty strings, empty lists,
unknown fields, duplicate row IDs, unresolved relationships and unrecognized code
values remain observations. A negative integer count is captured as stated; a
caller may reject it. These readers do not declare a roster complete or turn a
source slug into a stable concept identifier.

All JSON uses UTF-8, unique object keys, Python integers and finite binary floats.
Original bytes preserve numeric spelling and any precision lost by float decoding.
Duplicate keys, nonfinite numbers and malformed known fields refuse. Defaults
bound input to 16 MiB, 500,000 JSON values and depth 64, including unknown fields.
The decoder materializes that bounded input; these are not streaming JSON readers.

The retained August 2026 documentation contains 11 enum sets. Its `info.version`
is an empty string. Its Topic enum has 7,772 entries, while the earlier
[topics capture](federal-register-topics.md) has 7,767 rows. Different dates and
source shapes do not establish a crosswalk. RefSpec owns that comparison.

The three reference readers accept supplied bytes; they perform no acquisition
or storage. The topics module separately provides explicit bounded acquisition.
