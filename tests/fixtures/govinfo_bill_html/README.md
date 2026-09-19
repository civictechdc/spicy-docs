# GovInfo bill `htm` bodies: the two print conventions the rules depend on

**Complete, unchanged publisher responses.** Nothing was reduced, reformatted
or redacted; these are the bytes GovInfo served. They are U.S. government
documents in the public domain.

Retrieved with unauthenticated `GET` on 2026-09-19 through
`tools.analysis.bill_html_xml_gap`'s `KeylessProbe`, at the keyless locator
`sources.govinfo.bodies.package_body_locator(id, "htm")` derives, with the
publisher's HTTP-200 error page refused on both witnesses.

| Fixture | Publisher URL | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `BILLS-113s2113rs.htm` | <https://www.govinfo.gov/content/pkg/BILLS-113s2113rs/html/BILLS-113s2113rs.htm> | 18,091 | `8edf42039fc61cb6a9dd7b0e5bfc53e012ed610588a3d916b0e62becae54b9a7` |
| `BILLS-113hjres72fph.htm` | <https://www.govinfo.gov/content/pkg/BILLS-113hjres72fph/html/BILLS-113hjres72fph.htm> | 3,603 | `17e88256e57f6a571052447b0560c034718f9d816067eaf2048e7af2d94d136d` |

## Why these two

`tests/test_bill_html_xml_gap_tool.py` pins most rules against *constructed*
print samples, which prove what a rule does with a shape but establish nothing
about what GPO actually serves. These two carry the conventions that claim is
most load-bearing for, on real bytes:

- **`BILLS-113s2113rs.htm`** — a reported bill carrying a committee substitute.
  Its superseded text is wrapped in GPO's `<DELETED>` markers, which arrive as
  **text** because the `htm` rendition escapes them (`&lt;DELETED&gt;`), and
  which sit *outside* the wrapped provision's own indentation
  (`<DELETED>    (a) Amendment.--`). That convention is **not** an element the
  bill DTD declares — the schema declares `deleted-phrase` and a `changed`
  attribute taking `deleted`, neither of which is this marker — so it is a
  corpus inference, and it is the one rule with no publisher documentation
  behind it. It is also unexercised by the held-out draw, which contains no
  two-body document. Both are reasons for it to be pinned to real bytes here.
  The document's XML carries two `<legis-body>` elements; its HTML prints five
  struck headings and three live ones.
- **`BILLS-113hjres72fph.htm`** — a continuing resolution whose general
  provisions are set as GPO's run-in `    Sec. 101.` at the body indent rather
  than the uppercase `SEC. 101.` at column 0. Reading only the uppercase form
  loses every appropriations bill and continuing resolution outright; on the
  tuning corpus 39 of 104 headings take this form.

Selected because they are the smallest complete bodies in the measured corpus
carrying each convention, and because each is a shape a reader can check by
eye. Between them they are 21,694 bytes.

## What these fixtures cannot establish

Two documents. They show that GPO spelled these two conventions this way on
2026-09-19; they do not establish how often either appears, nor that the
publisher will keep spelling them so — which is exactly why
`bill_html_xml_gap.struck_expected` asserts a lower bound rather than trusting
the marker, and why the research document states the convention as an
inference. Neither carries a table of contents, so the contents-list rules stay
unpinned here and unscored in the measurement's title-level form.

The full measurement's corpus, receipts and digests live outside this
repository in
`~/Work/corpora/supply-2026-09-02/receipts/bill-html-xml-gap-2026-09-19/`; see
[the research document](../../../docs/research/bill-html-xml-gap-2026-09-19.md).
