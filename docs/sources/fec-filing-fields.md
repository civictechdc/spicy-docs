# Label retained FEC filing fields

`spicy_docs.sources.fec.layouts` exposes literal field definitions from pinned
official electronic and paper workbooks. The core package reads compact JSON;
it needs no spreadsheet library or network access. Select a dictionary once and
reuse it with the existing positional filing reader.

```python
from spicy_docs.sources.fec.layouts import (
    filing_layouts,
    filing_layout,
    map_filing_fields,
)

choices = filing_layouts()  # Exact family/version/form/row selectors.
layout = filing_layout(family="electronic", version="8.5", form="Sch C1")
# `record` comes from filing_records; `header` is its first result.
mapped = map_filing_fields(
    record,
    layout=layout,
    format_version=header["format_version"],
)
```

Choose the layout using source evidence. This API does not infer compatibility
from record prefixes, amendments, field counts or similar version numbers.
It preserves the native record type and separately supplied header version;
`field_mapping.selection` says `caller-selected`. For example, dictionary form
`Sch C1` can describe a raw `SC1/10` record, and historical `SH5` describes `H5`.
Those examples do not authorize a general prefix-matching rule.

## Select the dictionary exactly

| Dictionary | Selector spelling | Evidence retained |
| --- | --- | --- |
| Electronic all-version headers | `family="electronic"`, literal versions such as `v3`, `v5.3`, `v8.4`; form from the source row | Labels in physical column order, source sheet/row/cells, workbook digest and archive member. |
| Electronic specification | `family="electronic"`, `version="8.5"`; literal tab such as `Sch A` or `Text` | Labels, specification columns, sheet notes and the complete summary of changes. |
| Paper all-version headers | `family="paper"`, literal versions such as `v3.3`; source-row form | Paper field positions, kept separate from electronic formats. A raw `P3.3` header is not rewritten. |

`filing_layouts()` lists the packaged selectors. `filing_layout()` returns an
independent copy; modifying it cannot change later lookups. Unknown selectors
raise `KeyError`. Version strings such as `v3`, `3.00`, `5.00` and `v5.0` are
distinct. Amendment suffixes are not stripped. A new format needs its own evidence.

The historical dictionary repeats electronic `v6.4/F3S` with different fields.
Selection refuses until the caller specifies `row=7` or `row=8`. Both source
observations remain available. Duplicate labels and incorrectly repeated printed
ordinals also survive; physical column position supplies the field index.

The specification retains sheets for forms its summary says are excluded.
Worksheet presence therefore establishes a dictionary observation, not acceptance
of that record type. `layout["source"]["notes"]` retains the complete change
summary without guessing joins from inconsistent form spellings. Sheet-specific
notes remain in `layout["notes"]`.

Each field definition contains `label` and its worksheet `cell`. Specification
fields also retain the other source columns, starting at column C, in
`specification`: type, requirement, sample, value reference, rule reference and
form association where present. These are descriptive source values, not applied
validation rules. Formula-based header labels use the publisher's cached value
and retain an unevaluated `formula`; OpenPyXL expands shared formula references
during generation. The API does not recalculate formulas or claim caches are fresh.
Exact workbook XML remains recoverable through the source digest and cell.

## Preserve values and bodies

`map_filing_fields(record, *, layout, format_version, max_fields=10_000)` accepts
`kind="record"` output from `filing_records`. It copies the input members and adds
the declared version and `field_mapping`; it rejects input members that would
collide with those output names. Header and bracketed-text observations stay on
their existing reader paths.

| Added output | Meaning |
| --- | --- |
| `field_mapping.layout` | Selected family/version/form/row, source cells and workbook pin. Full dictionary notes stay in the separately retrieved layout. |
| `field_mapping.annotations` | Ordered positions with `presence` of `value`, `body` or `absent`, plus label/cell definitions where supplied. Unknown extra positions have `definition=null`. |
| `field_mapping.width` | `short`, `equal` or `extra_fields` compared with the selected dictionary. Equal width does not establish compatibility. |

Values remain in the original positional `fields` mapping. Empty strings, zeros,
numeric spellings and unknown codes are unchanged. Body fields remain in
`embedded_bodies`; annotations add no body text. Missing trailing positions differ
from present blank values. Every observed position must occur exactly once across
values and body references. The mapper rejects inconsistent positions or exceeded
field bounds and preserves unknown input members.

Lookup indexes the finite catalog once. Mapping takes linear work in the selected
layout, record fields and copied input bytes. It neither scans the registry nor
opens the original per record. Fetch a layout outside the record loop; retain its
notes and source definitions once. Mapped rows contain compact label/cell
annotations rather than repeated examples and specification rules.

## Rebuild and qualify

The [generator](../../tools/build_fec_layouts.py) reads the pinned workbook fixtures:

```sh
uv run --frozen --with openpyxl==3.1.5 python tools/build_fec_layouts.py
```

OpenPyXL is a development-only dependency. It resolves workbook relationships;
sheet IDs must not be treated as worksheet filenames. The independent test reader
compares packaged layout membership, positions, labels and formulas with native
XLSX XML. Known-answer cases cover shifted fields, duplicate ordinals, ambiguous
rows, excluded forms, absent/blank/extra values, bodies and input bounds.

[Qualification records](</Users/mikewolfd/Work/corpora/supply-2026-09-02/receipts/fec-filing-fields-2026-09-15/README.md>)
pin the retained real-record replay, checks and installed package. They cover the
selected source frame, not all historical filings or today's accepted formats.
Financial interpretation, amendment views, dataset backfills and additional
immutable release profiles remain separate work.
