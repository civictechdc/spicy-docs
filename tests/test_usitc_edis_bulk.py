"""A retained EDIS index binds every ZIP PDF to expected source attachment metadata."""

import hashlib
import io
import warnings
import zipfile
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from spicy_docs.sources.usitc_edis import AttachmentRecord, UsitcEdisSourceError, inspect_bulk_archive

INDEX = (Path(__file__).parent / "fixtures/usitc_edis/bulk-index-894762.html").read_bytes()
NAMES = ("894762-0-2620262.pdf", "894762-1-2620275.pdf")
PDFS = (b"%PDF-1.6\nsynthetic-one\n%%EOF\n", b"%PDF-1.5\nsynthetic-two\n%%EOF\n")
EXPECTED = tuple(
    AttachmentRecord(attachment_id, 894762, None, len(body), None, None, None, None)
    for attachment_id, body in zip((2620262, 2620275), PDFS, strict=True)
)


def archive(index=INDEX, *, members=None, compression=zipfile.ZIP_DEFLATED):
    output = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(output, "w", compression) as bundle:
        warnings.simplefilter("ignore", UserWarning)  # Duplicate-member fixtures are deliberate.
        for name, body in zip(NAMES, PDFS, strict=True) if members is None else members:
            bundle.writestr(name, body)
        if index is not None:
            bundle.writestr("index.html", index)
    return output.getvalue()


def inspect(body, *, expected=EXPECTED, **kwargs):
    return inspect_bulk_archive(io.BytesIO(body), byte_size=len(body), expected_attachments=expected, **kwargs)


def test_complete_archive_keeps_exact_index_columns_links_and_shared_inventory():
    body = archive()
    stream = io.BytesIO(body)
    result = inspect_bulk_archive(stream, byte_size=len(body), expected_attachments=EXPECTED)
    assert not stream.closed
    assert result.index_bytes == INDEX
    assert result.index_member_ordinal == 2
    assert [(row.document_id, row.attachment_id) for row in result.rows] == [(894762, 2620262), (894762, 2620275)]
    assert [row.member_name for row in result.rows] == list(NAMES)
    assert [row.file_label for row in result.rows] == ["894762-2620262.pdf", "894762-2620275.pdf"]
    assert [row.pdf_version for row in result.rows] == ["1.6", "1.5"]
    fields = dict(result.rows[0].fields)
    assert fields["DOCUMENT DATE"] == "09/15/2026 12:00 AM"
    assert fields["INVESTIGATION"] == "337-1458 - Violation"
    assert fields["ATTACHMENT TITLE"] == "1458 Order No. 42 Granting Joint Motion for an EOT"
    for row, pdf in zip(result.rows, PDFS, strict=True):
        member = result.inventory["members"][row.member_ordinal]
        assert member["name"] == row.member_name and member["crcVerified"]
        assert member["byteSize"] == len(pdf)
        assert member["sha256"] == "sha256:" + hashlib.sha256(pdf).hexdigest()
    index_member = result.inventory["members"][result.index_member_ordinal]
    assert index_member["sha256"] == "sha256:887d2184b9c27872d32df49ab4b3ea0ce4d4a9eb77279fe9697fbdf57bd3e8ca"


def test_additional_index_columns_survive_without_interpreting_them():
    index = INDEX.replace(b"<th>SECURITY</th>", b"<th>SECURITY</th><th>OTHER SOURCE FIELD</th>")
    index = index.replace(b"<td>Public</td>", b"<td>Public</td><td>A &amp; B</td>")
    result = inspect(archive(index))
    assert dict(result.rows[0].fields)["OTHER SOURCE FIELD"] == "A & B"


@pytest.mark.parametrize(
    "members,index,reason",
    [
        ([(NAMES[0], PDFS[0])], INDEX, "missing PDF member"),
        ([*zip(NAMES, PDFS), ("894762-2-2620276.pdf", PDFS[0])], INDEX, "unindexed PDF"),
        ([*zip(NAMES, PDFS), (NAMES[0], PDFS[0])], INDEX, "repeats a member name"),
        (list(zip(NAMES, PDFS)), None, "omitted index.html"),
        ([*zip(NAMES, PDFS), ("../escape.pdf", PDFS[0])], INDEX, "unsafe member"),
        ([*zip(NAMES, PDFS), ("folder/", b"")], INDEX, "unsafe member"),
    ],
)
def test_missing_extra_duplicate_or_unsafe_members_refuse(members, index, reason):
    with pytest.raises(UsitcEdisSourceError, match=reason):
        inspect(archive(index, members=members))


@pytest.mark.parametrize(
    "old,new,reason",
    [
        (b"href='894762-0-2620262.pdf'", b"href='../894762-0-2620262.pdf'", "unsafe or missing"),
        (b"href='894762-0-2620262.pdf'", b"href='https://edis.usitc.gov/file.pdf'", "unsafe or missing"),
        (b">894762-2620262.pdf<", b">894762-2620275.pdf<", "identities disagree"),
        (b"<td>894762</td>", b"<td>894763</td>", "identities disagree"),
        (b"<td>Public</td>", b"<td>Confidential</td>", "not Public"),
        (b"<th>SECURITY</th>", b"<th>UNKNOWN</th>", "columns are missing"),
        (b"<th>SECURITY</th>", b"<th>DOCUMENT ID</th>", "columns are missing or ambiguous"),
        (b"</table>", b"", "complete table"),
    ],
)
def test_index_scope_security_and_shape_are_proved(old, new, reason):
    with pytest.raises(UsitcEdisSourceError, match=reason):
        inspect(archive(INDEX.replace(old, new, 1)))


def test_duplicate_index_attachment_refuses_even_when_member_names_differ():
    first_row = INDEX.split(b"<tr>")[2].split(b"</tr>")[0]
    first_row = first_row.replace(b"894762-0-2620262.pdf", b"894762-2-2620262.pdf")
    index = INDEX.replace(b"</table>", b"<tr>" + first_row + b"</tr></table>")
    with pytest.raises(UsitcEdisSourceError, match="repeats an attachment"):
        inspect(archive(index, members=[*zip(NAMES, PDFS), ("894762-2-2620262.pdf", PDFS[0])]))


@pytest.mark.parametrize(
    "expected,reason",
    [
        (EXPECTED[:1], "unexpected attachment"),
        ((*EXPECTED, replace(EXPECTED[0], id=2620276)), "omitted expected attachments"),
        ((*EXPECTED, EXPECTED[0]), "expected attachment identity repeats"),
        ((replace(EXPECTED[0], file_size=12345), EXPECTED[1]), "size differs"),
        ((replace(EXPECTED[0], id=0), EXPECTED[1]), "positive integers"),
        ((replace(EXPECTED[0], document_id=True), EXPECTED[1]), "positive integers"),
        ((), "must not be empty"),
    ],
)
def test_expected_metadata_must_match_exact_attachment_set(expected, reason):
    with pytest.raises(UsitcEdisSourceError, match=reason):
        inspect(archive(), expected=expected)


def test_absent_declared_size_does_not_discard_the_observed_member_size():
    result = inspect(archive(), expected=tuple(replace(row, file_size=None) for row in EXPECTED))
    assert result.inventory["members"][0]["byteSize"] == len(PDFS[0])


@pytest.mark.parametrize("replacement", [b"not a PDF", b"%PDF-1.6\n%%EOF" + b"x" * 2048])
def test_pdf_format_and_actual_final_window_are_checked(replacement):
    body = archive(members=[(NAMES[0], replacement), (NAMES[1], PDFS[1])])
    expected = (replace(EXPECTED[0], file_size=len(replacement)), EXPECTED[1])
    with pytest.raises(UsitcEdisSourceError, match="%PDF- magic|PDF trailer"):
        inspect(body, expected=expected)


def test_unix_symlink_refuses_even_when_its_payload_looks_like_a_pdf():
    info = zipfile.ZipInfo(NAMES[0])
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with pytest.raises(UsitcEdisSourceError, match="unsafe member"):
        inspect(archive(members=[(info, PDFS[0]), (NAMES[1], PDFS[1])]))


@pytest.mark.parametrize("damage", ["crc", "truncated"])
def test_invalid_archive_refuses_through_shared_inventory(damage):
    body = archive(compression=zipfile.ZIP_STORED)
    body = body.replace(b"synthetic-one", b"corrupted-one") if damage == "crc" else body[:-9]
    with pytest.raises(UsitcEdisSourceError, match="CRC|end record"):
        inspect(body)


def test_invalid_deflate_payload_is_a_source_refusal():
    body = bytearray(archive())
    # The first local header is intact; corrupt only the DEFLATE block type.
    # BTYPE=3 is reserved, so the shared bounded inflater raises zlib.error.
    payload = 30 + int.from_bytes(body[26:28], "little") + int.from_bytes(body[28:30], "little")
    body[payload] |= 0b110
    with pytest.raises(UsitcEdisSourceError, match="could not be read") as refused:
        inspect(bytes(body))
    assert isinstance(refused.value.__cause__, zlib.error)


@pytest.mark.parametrize(
    "limit", ["byte_size", "max_entries", "max_decoded_bytes", "max_metadata_bytes", "max_index_bytes"]
)
@pytest.mark.parametrize("value", [0, -1, True])
def test_invalid_bounds_refuse_before_any_nonseekable_read(limit, value):
    class Unreadable:
        def seekable(self):
            pytest.fail("invalid bounds must refuse before examining the stream")

        def read(self, size=-1):
            pytest.fail("invalid bounds must refuse before a stream read")

    options = {"byte_size": 1, limit: value}
    with pytest.raises(UsitcEdisSourceError, match="positive integer"):
        inspect_bulk_archive(Unreadable(), expected_attachments=EXPECTED, **options)


@pytest.mark.parametrize("delta", [-1, 1])
def test_seekable_original_must_match_its_pinned_size(delta):
    body = archive()
    with pytest.raises(UsitcEdisSourceError, match="selected byte size"):
        inspect_bulk_archive(io.BytesIO(body), byte_size=len(body) + delta, expected_attachments=EXPECTED)


@pytest.mark.parametrize(
    "limits,reason",
    [
        ({"max_entries": 2}, "entry count"),
        ({"max_decoded_bytes": 100}, "decoded size"),
        ({"max_index_bytes": 100}, "max_index_bytes"),
        ({"max_metadata_bytes": 100}, "metadata read"),
    ],
)
def test_caller_bounds_apply_to_archive_and_index(limits, reason):
    with pytest.raises(UsitcEdisSourceError, match=reason):
        inspect(archive(), **limits)


def test_nonseekable_input_spools_once_and_every_member_is_read_in_one_pass(monkeypatch):
    """The inventory's CRC pass also yields the index and PDF edges; no member is decoded twice."""
    large_pdf = b"%PDF-1.7\n" + b"x" * (3 * 64 * 1024) + b"\n%%EOF\n"
    body = archive(members=[(NAMES[0], large_pdf), (NAMES[1], PDFS[1])], compression=zipfile.ZIP_STORED)

    class Nonseekable(io.BytesIO):
        def __init__(self, body):
            super().__init__(body)
            self.requests = []

        def seekable(self):
            return False

        def read(self, size=-1):
            assert 0 < size <= 64 * 1024
            self.requests.append(size)
            return super().read(size)

    monkeypatch.setattr(zipfile.ZipExtFile, "read", lambda *_a, **_k: pytest.fail("a member was decoded a second time"))
    stream = Nonseekable(body)
    expected = (replace(EXPECTED[0], file_size=len(large_pdf)), EXPECTED[1])
    result = inspect_bulk_archive(stream, byte_size=len(body), expected_attachments=expected)
    assert result.rows[0].pdf_version == "1.7" and result.index_bytes == INDEX
    assert stream.tell() == len(body) and not stream.closed
    assert len(stream.requests) >= 4
