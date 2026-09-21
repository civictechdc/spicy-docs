"""Raw source JSON parsing keeps strict numeric and duplicate-key behavior.

load_integer_json and load_finite_json refuse duplicate keys and non-finite numbers through the caller's error
type, number policies are explicit, and whole-document byte, node, and depth limits refuse before enumerating
children."""

from decimal import Decimal

import pytest

from spicy_docs.reading.json_input import load_bounded_json, load_finite_json, load_integer_json


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


@pytest.mark.parametrize("raw", [b"NaN", b"Infinity", b"-Infinity", b"1e9999", b"-1e9999", b'{"x":1,"x":2}'])
def test_finite_float_policy_refuses_nonfinite_and_duplicate_keys(raw):
    with pytest.raises(SourceError):
        load_finite_json(raw, source="Example", error_type=SourceError)


def test_number_policies_are_explicit_and_preserve_expected_types():
    def read(raw, policy):
        return load_bounded_json(raw, source="Example", error_type=SourceError, number_policy=policy, max_bytes=100)

    assert read(b"9007199254740993", "integer") == 9007199254740993
    assert read(b"1.1", "decimal") == Decimal("1.1")
    assert type(read(b"1.1", "decimal")) is Decimal
    assert type(read(b"1.1", "finite-float")) is float
    with pytest.raises(SourceError):
        read(b"1.1", "integer")
    with pytest.raises(SourceError):
        read(b"1", "automatic")


@pytest.mark.parametrize(
    "raw,limits",
    [
        (b"{}", {"max_bytes": 1}),
        (b'{"unknown":[1,2]}', {"max_nodes": 3}),
        (b'{"unknown":[1]}', {"max_depth": 1}),
        (b"1", {"max_nodes": True}),
        (b"1", {"max_depth": 0}),
        (b"", {}),
        (b'"ok"'.decode().encode("utf-16"), {}),
        (b"[" * 1500 + b"0" + b"]" * 1500, {}),
        (b"1" * 5000, {}),
    ],
)
def test_whole_document_limits_and_decoder_errors_use_source_error(raw, limits):
    options = {"max_bytes": 10_000, **limits}
    with pytest.raises(SourceError):
        load_bounded_json(raw, source="Example", error_type=SourceError, number_policy="finite-float", **options)


def test_decimal_decoder_limit_uses_source_error():
    with pytest.raises(SourceError):
        load_bounded_json(
            b"1e999999999999999999999999",
            source="Example",
            error_type=SourceError,
            number_policy="decimal",
            max_bytes=100,
        )


def test_node_budget_refuses_before_enumerating_wide_children(monkeypatch):
    from spicy_docs.reading import json_input

    class WideArray(list):
        def __iter__(self):
            raise AssertionError("node limit must be checked before queuing children")

    monkeypatch.setattr(json_input, "load_finite_json", lambda *args, **kwargs: WideArray([0] * 100))
    with pytest.raises(SourceError, match="max_nodes"):
        load_bounded_json(
            b"[]", source="Example", error_type=SourceError, number_policy="finite-float", max_bytes=100, max_nodes=10
        )
