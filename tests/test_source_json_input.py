"""Raw source parsing retains strict numeric and duplicate-key behavior."""

import pytest

from spicy_docs.sources.json_input import load_integer_json


class SourceError(ValueError):
    pass


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (b'{"a": 1, "a": 2}', "repeats field 'a'"),
        (b'{"outer": {"a": 1, "a": 2}}', "repeats field 'a'"),
        (b'{"a": 1.25}', "unsupported float '1.25'"),
        (b'{"a": NaN}', "unsupported float 'NaN'"),
        (b'{"a": Infinity}', "unsupported float 'Infinity'"),
        (b'{"a": -Infinity}', "unsupported float '-Infinity'"),
        (b"\xff", "invalid Example JSON"),
        (b"{", "invalid Example JSON"),
    ],
)
def test_ambiguous_or_unsupported_json_raises_the_source_error(raw: bytes, message: str) -> None:
    with pytest.raises(SourceError, match=message):
        load_integer_json(raw, source="Example", error_type=SourceError)


def test_source_values_and_container_shape_are_left_to_the_caller() -> None:
    raw = b'[null, true, false, 42, "text", {"a": 1}]'
    assert load_integer_json(raw, source="Example", error_type=SourceError) == [None, True, False, 42, "text", {"a": 1}]


def test_public_table_number_diagnostic_remains_source_specific() -> None:
    with pytest.raises(SourceError, match="public-table JSON contains unsupported number '1.5'"):
        load_integer_json(b"1.5", source="public-table", error_type=SourceError, number_label="number")
