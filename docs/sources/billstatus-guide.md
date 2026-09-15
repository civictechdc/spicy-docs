# Read BILLSTATUS guide code tables

`spicy_docs.sources.congress.billstatus_codes.read_billstatus_guide` reads retained
UTF-8 Markdown bytes. It returns the publisher's bill-type sentence and four
tables, with exact source text, line numbers and byte spans.

| Source section | Captured observations |
| --- | --- |
| 1.1 | Introductory bill-type descriptions, retained separately. |
| 2.1, `billType` | Every comma-list value, including repeated or empty values. |
| 2.1, `version` | The publisher's explanation of the XML format version. |
| 3 | Action codes and descriptions, including the complete pre-table courtesy disclaimer. |
| 4 | Action-type values and their explanatory context. |
| 5 | Summary version codes, chambers and descriptions. |
| 6 | Title-type codes and descriptions. |

```python
from spicy_docs.sources.congress.billstatus_codes import read_billstatus_guide

guide = read_billstatus_guide(retained_markdown)
for table in guide.tables:
    for row in table.rows:
        print(table.section_number, [cell.value for cell in row.cells])
```

Each cell keeps its raw source spelling alongside a value with surrounding
whitespace and one enclosing Markdown bold pair removed. Table headings, headers,
separators, rows and pre-table prose retain their original text. Byte ends are
exclusive; line numbers are one-based. Replay spans against the original bytes
and the returned `input_sha256` and `input_bytes`.

The retained guide's section 2.1 lists `H`, while section 1.1 says `House Bill
(HR)`. The current BILLSTATUS XML fixture states `bill/type=HR` and
`version=3.0.0`. These are separate source observations. This reader does not
reconcile them or change bill acquisition/listing identifiers. The guide's
`version` explanation is not a guide release identifier; the input digest pins
the actual guide read.

Unknown codes, repeated codes, unfamiliar chambers and empty cells survive.
Missing sections remain absent; repeated sections remain separate. Malformed
tables, multiple separated tables within one selected section and escaped pipes
refuse explicitly. This is a reader for the publisher's literal layout, not a
general Markdown renderer. Input bytes, rows/values and columns are bounded.

RefSpec chooses which observations form its reviewed code sets, checks its exact
snapshot and counts, and assigns record codes. It also decides whether a list is
open or closed. SpicyDocs retains the publisher's disclaimer without converting
it into an assignment rule. This reader fetches and publishes nothing.

The exact retained guide and its capture pin are in
`tests/fixtures/billstatus_codes/`. The source is the
[GPO BILLSTATUS guide](https://github.com/usgpo/bill-status/blob/master/BILLSTATUS-XML_User_User-Guide.md).
