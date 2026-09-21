"""Ordered bulk dictionaries retain the source cells that justify each name.

Pins omitted cell and row-end handling with exact text evidence, and refusals
for missing, duplicate, ambiguous, incomplete, multi-table, bad-digest and
unclosed definitions.
"""

import hashlib
from html import unescape

import pytest

from spicy_docs.sources.fec.bulk_dictionary import parse_bulk_dictionary

HEADER = "<tr><td><strong>Column name</strong></td><td>Field name</td><td>Position</td><td>Null</td></tr>"


def _read(body):
    """Read a dictionary fixture through the parser."""
    raw = body.encode()
    return raw, parse_bulk_dictionary(raw, sha256="sha256:" + hashlib.sha256(raw).hexdigest())


def test_omitted_cell_and_row_ends_preserve_spelling_blank_cells_and_exact_text_evidence():
    """Omitted cell and row ends preserve publisher spelling, blank cells and exact text evidence."""
    html = "<table><tr><td>Unrelated</td></tr></table><table>" + HEADER
    html += "<tr><td> CAND_ID \r\n<td>Candidate identification<td>1<td>N"
    html += "<tr><td>Offsets_To_Leagal_Accounting<td>Costs &amp; refunds<td>2<td></table>"
    raw, result = _read(html)
    assert result["table_locator"]["table_ordinal"] == 1
    assert [field["name"] for field in result["fields"]] == ["CAND_ID", "Offsets_To_Leagal_Accounting"]
    assert [field["position"] for field in result["fields"]] == [1, 2]
    assert result["fields"][0]["cells"][0]["text"] == " CAND_ID \r\n"
    assert result["fields"][1]["cells"][3]["text"] == ""
    for field in result["fields"]:
        for cell in field["cells"]:
            for fragment in cell["fragments"]:
                source = raw[fragment["byte_start"] : fragment["byte_end"]].decode()
                assert (source if fragment["is_literal"] else unescape(source)) == fragment["text"]


@pytest.mark.parametrize(
    "rows",
    [
        "<tr><td>A<td>Name<td>2<td>N",
        "<tr><td>A<td>Name<td>1<td>N<tr><td>B<td>Name<td>1<td>N",
        "<tr><td>A<td>Name<td>1<td>N<tr><td>A<td>Name<td>2<td>N",
        "<tr><td> <td>Name<td>1<td>N",
        "<tr><td>A<td>Name<td>one<td>N",
        "<tr><td>A<td>Name<td>1",
        "<tr><td colspan='2'>A<td>1<td>N",
        "",
    ],
)
def test_missing_duplicate_ambiguous_and_incomplete_definitions_refuse(rows):
    """Missing, duplicate, ambiguous and incomplete definitions are refused."""
    with pytest.raises(ValueError):
        _read("<table>" + HEADER + rows + "</table>")


def test_two_matching_tables_bad_digest_and_unclosed_table_refuse():
    """Two matching tables, a bad digest and an unclosed table are refused."""
    table = "<table>" + HEADER + "<tr><td>A<td>Name<td>1<td>N</table>"
    with pytest.raises(ValueError, match="exactly one"):
        _read(table + table)
    with pytest.raises(ValueError, match="digest"):
        parse_bulk_dictionary(table.encode(), sha256="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="not closed"):
        _read(table.removesuffix("</table>"))
