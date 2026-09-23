# Capture the OLRC classification tables

For the current Congress the Office of the Law Revision Counsel publishes one
"Table of Classifications for Public Laws" per session — which Code sections
each new public law touched — in two orders, linked from one index page. This
is the per-Congress view of the same facts [Table III](uscode.md) holds per
act: where Table III answers "what did the 1955 Food Additives Amendment do to
the Code", the classification table answers "what did Public Law 119-75 do",
the day the law is enacted, years before Table III reaches it. Both are
keyless, and both are captured with the same bounded-evidence machinery.

| Route | Answered 2026-09-19 | Credential |
| --- | --- | --- |
| `classification/tables.shtml` — the index of the current Congress's session tables | 39,140 bytes | none |
| `classification/tbl{c}{pl\|cd}_{1st\|2nd}.htm` — one session, by public law or by Code citation | 115,140 bytes (583 rows) | none |

## What the readers prove, from the page itself

`spicy_docs.sources.uscode.classification` refuses any page that cannot
establish its own identity before a single row is read:

- **The index proves its title** (`UNITED STATES CODE CLASSIFICATION TABLES`),
  then lists every `tbl` href in page order. Zero table links is a refusal,
  not an empty fact — the index has linked four tables since it was first
  measured.
- **Each table states its Congress and session in its caption**
  (`119th Congress, 2nd Session`), the laws it covers (`Public Law 119-70 and
  Public Laws 119-74 through 119-110`, expanded by the reader to all 38
  numbers), and a prepared date. A page for another session — or a challenge
  page served with status 200 — is refused by name. Every row's own law
  number must carry that same Congress.
- **The rows are a fixed-width `<PRE>` block, not an HTML table.** The column
  offsets are read from the page's own header line, never assumed: on
  2026-09-19 all 583 data lines of the 2nd-session table sliced at those
  offsets with none left over.
- **Column 3 is the publisher's action vocabulary, kept verbatim** (`nt`,
  `new`, `nt new`, `nt [tbl]`, `prec`, `repealed`, `gen amd`, `omitted`, ...);
  the blank the legend reads as "amended" is kept as NULL, and the reading
  stays the consumer's.
- **The Statutes at Large column is two facts**: the printed text (one page,
  or a span such as `637, 638`) and, where the row links the statviewer, the
  link's own volume and page (573 of 583 rows on the measured day).
- **The two orders hold the same rows.** Both 2nd-session pages parsed to the
  same 583-row multiset on 2026-09-19, and one row appears twice in each — so
  `law_code_sections` keys a row on its position (`seq`), not its content.
- **Zero rows refuses**, the way an empty `<PRE>` block is the shape of a
  cut-off page, not of a session that classified nothing.

## Capture one source

From the checkout, install acquisition dependencies with
`uv sync --frozen --extra acquisition`. Each output directory must be new.

```sh
uv run --frozen python - <<'PY'
from spicy_docs.sources.uscode.acquisition import UsCodeAcquirer, UsCodeAcquisitionBudget

budget = UsCodeAcquisitionBudget(2, 1 << 20, 60, 1)
with UsCodeAcquirer(budget=budget) as source:
    index = source.acquire_classification_index()
    table = source.acquire_classification_table(119, 2)
print(table.result.congress, table.result.session, len(table.result.records))
PY
```

Each capture retains the original bytes, their digest, the resolved URL and
the timing, beside the parsed result. The row bound defaults to 65,536 rows;
a page that states more than `max_rows` refuses rather than truncating
silently.

## Where the rows land

`classification.records` shapes into the `law_code_sections` table
(`schemas/law_tables.py`): one row per line of the page, keyed
`(congress, session, seq)` — see [Tables](../tables.md). The Table III reader
(`parse_table3_page`, same package) shapes into `table3_records`, the
per-act view keyed `(act_key, seq)`; its page proves the act, the Congress
and the Statutes at Large volume back, which is the register's Table III
proof. The measured captures and their whole-page counts are in
`corpora/supply-2026-09-02/receipts/olrc-classification-2026-09-19/`.

Both tables keep the section as printed (`4980D`, `1400Z-1`) and append
`usc_section_key`, its lower-cased, dash-folded join key (`4980d`,
`1400z-1`). Case carries no identity in the Code, and 142 of the 814 lettered
rows in the retained 119th-Congress table (captured 2026-09-19) print a
capital; see
[the decision](../decisions.md#us-code-section-join-keys-are-lower-cased-on-both-sides).
