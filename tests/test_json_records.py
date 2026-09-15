"""Frozen source parsers qualify decoded values, exact slices, and named refusals."""

import json
import math
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path

import pytest

from spicy_docs.sources import json_input
from spicy_docs.sources.json_input import read_json_records
from tests import json_record_ranges_oracle as old_records
from tests import source_json_input_oracle as old_loaders

FIXTURES = Path(__file__).parent / "fixtures"


class SourceError(ValueError):
    pass


def read(raw, **options):
    return read_json_records(
        raw,
        source="Example",
        error_type=SourceError,
        **{"number_policy": "finite-float", "max_bytes": 64 * 1024**2, "max_nodes": 1_000_000, **options},
    )


def outcome(operation):
    try:
        value = operation()
        return ("value", repr(value))
    except (ValueError, InvalidOperation, RecursionError) as error:
        return ("error", type(error), str(error), type(error.__cause__), str(error.__cause__))


@pytest.mark.parametrize("error_type", [ValueError, SourceError])
@pytest.mark.parametrize("loader", ["load_integer_json", "load_decimal_json", "load_finite_json", "load_bounded_json"])
@pytest.mark.parametrize(
    "raw",
    [
        b' {"unknown":[null,true,false,-0,9007199254740993,"\\ud800"]} ',
        b"1.25",
        b"1e0",
        b"1e-9999",
        b"1e9999",
        b"1e999999999999999999999999",
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b"1" * 5000,
        b'{"a":1,"\\u0061":2}',
        b'{"nested":{"a":1,"a":2}}',
        b"[1,]",
        b"[1 2]",
        b"[",
        b"",
        b" \t\r\n",
        b"null tail",
        b"\xff",
        b"\xef\xbb\xbf[]",
        b"[" * 1500 + b"0" + b"]" * 1500,
    ],
)
def test_existing_loader_values_exceptions_messages_and_causes_match_frozen_source(raw, loader, error_type):
    options = {"source": "Example", "error_type": error_type}
    if loader == "load_bounded_json":
        options.update(number_policy="finite-float", max_bytes=10_000)
    assert outcome(lambda: getattr(json_input, loader)(raw, **options)) == outcome(
        lambda: getattr(old_loaders, loader)(raw, **options)
    )


@pytest.mark.parametrize("policy", ["integer", "decimal", "finite-float"])
@pytest.mark.parametrize("setting", ["max_bytes", "max_nodes", "max_depth"])
@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 1])
def test_existing_bounded_loader_limits_retain_diagnostics(policy, setting, limit):
    options = {"source": "Example", "error_type": SourceError, "number_policy": policy, "max_bytes": 100}
    options[setting] = limit
    assert outcome(lambda: json_input.load_bounded_json(b'[0,{"a":[1]}]', **options)) == outcome(
        lambda: old_loaders.load_bounded_json(b'[0,{"a":[1]}]', **options)
    )


@pytest.mark.parametrize(
    "text",
    [
        ' \t\r\n[ {"é":"☃\\n", "number":1.00e+2}, "𝄞", -0, true, null, [1,2], {} ]\r\n',
        ' ["\\ud83d\\ude00", "\\ud800", "\\udfff", {"\\ud800":"fact"}] ',
        ' ["brackets [], commas, and escaped \\"quotes\\"", "é"] ',
        ' {"z":1,"a":9007199254740993} ',
        ' "é𝄞" ',
        " null ",
        " false ",
        " -0.0 ",
        " 1.2500E+1 ",
        " 1e-9999 ",
        " [] ",
        " [ [ ] ] ",
    ],
)
def test_source_values_and_exact_character_byte_ranges_match_frozen_record_oracle(text):
    raw = text.encode("utf-8")
    result = read(raw)
    assert repr(result.value) == repr(old_records.strict_json_value(text))
    assert tuple((span.char_start, span.char_end) for span in result.records) == old_records.record_char_ranges(text)
    for span in result.records:
        assert raw[span.byte_start : span.byte_end] == text[span.char_start : span.char_end].encode("utf-8")
        assert span.byte_start == len(text[: span.char_start].encode("utf-8"))
        assert span.byte_end == len(text[: span.char_end].encode("utf-8"))


@pytest.mark.parametrize(
    "filename",
    [
        "federal_register_reference/fr-agencies-2026-08-15.json",
        "federal_register_topics/federal-register-topics-2026-08-03.json",
        "cfr_metadata/ecfr-agencies.json",
        "fec/keyset.json",
    ],
)
def test_complete_retained_sources_match_frozen_value_and_every_record_slice(filename):
    raw = (FIXTURES / filename).read_bytes()
    text = raw.decode("utf-8")
    result = read(raw)
    assert result.value == old_records.strict_json_value(text)
    expected = old_records.record_char_ranges(text)
    assert tuple((span.char_start, span.char_end) for span in result.records) == expected
    for span, (start, end) in zip(result.records, expected, strict=True):
        assert raw[span.byte_start : span.byte_end] == text[start:end].encode("utf-8")


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b" \t\r\n",
        b"[",
        b"[1",
        b"[1,",
        b"[1,]",
        b"[,1]",
        b"[1,,2]",
        b"[1 2]",
        b"[[]] tail",
        b"[] []",
        b"{}tail",
        b"truefalse",
        b"01",
        b"[01]",
        b"[1e]",
        b'{"a":1,"\\u0061":2}',
        b'[0,{"x":1,"x":2}]',
        b"[NaN]",
        b"[Infinity]",
        b"[-Infinity]",
        b'"unterminated',
        b'"control\x00"',
        b"\xff",
        b"\xef\xbb\xbf[]",
        b'"\xed\xa0\x80"',
    ],
)
def test_malformed_ambiguous_and_undecodable_documents_never_return_partial_records(raw):
    with pytest.raises(SourceError):
        read(raw)


@pytest.mark.parametrize("raw", [b"1e9999", b"-1e9999", b"[0,1e9999]"])
def test_finite_overflow_is_an_explicit_correction_to_old_docspec_acceptance(raw):
    old = old_records.strict_json_value(raw.decode())
    assert math.isinf(old[-1] if isinstance(old, list) else old)
    with pytest.raises(SourceError, match="unsupported number"):
        read(raw)


def test_number_policy_retains_source_spelling_and_exposes_selected_value_type():
    raw = b"[1.00e+2, -0.0, 1e-9999]"
    result = read(raw, number_policy="decimal")
    assert result.value == [Decimal("1.00e+2"), Decimal("-0.0"), Decimal("1e-9999")]
    assert [raw[span.byte_start : span.byte_end] for span in result.records] == [b"1.00e+2", b"-0.0", b"1e-9999"]
    assert read(b"[9007199254740993,-0]", number_policy="integer").value == [9007199254740993, 0]
    with pytest.raises(SourceError, match="unsupported float"):
        read(b"[1e0]", number_policy="integer")
    with pytest.raises(SourceError, match="number policy"):
        read(b"0", number_policy="automatic")


@pytest.mark.parametrize("raw,policy", [(b"1" * 5000, "integer"), (b"1e999999999999999999999999", "decimal")])
def test_decoder_numeric_limits_are_source_refusals(raw, policy):
    with pytest.raises(SourceError, match="decoder limits"):
        read(raw, number_policy=policy)


@pytest.mark.parametrize("setting", ["max_bytes", "max_nodes", "max_depth"])
@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_all_limits_validate_even_for_empty_record_set(setting, limit):
    with pytest.raises(SourceError, match=setting):
        read(b"[]", **{setting: limit})


def test_cumulative_nodes_count_root_and_unknown_children_at_the_exact_boundary():
    raw = b'[0,{"unknown":[1]}]'
    assert read(raw, max_nodes=5, max_depth=3).value == [0, {"unknown": [1]}]
    for limits in ({"max_nodes": 4}, {"max_depth": 2}, {"max_bytes": len(raw) - 1}):
        with pytest.raises(SourceError):
            read(raw, **limits)
    assert read(b"[]", max_nodes=1).records == ()
    assert read(b"0", max_nodes=1).value == 0
    assert read(b"[0]", max_nodes=2, max_depth=1).value == [0]
    with pytest.raises(SourceError):
        read(b"[0]", max_nodes=1)
    with pytest.raises(SourceError):
        read(b"[" * 1500 + b"0" + b"]" * 1500)


def test_array_records_decode_once_and_byte_conversion_visits_disjoint_source_slices(monkeypatch):
    decoded_starts, encoded_slices = [], []
    original_decoder = json.JSONDecoder

    class CountingDecoder(original_decoder):
        def raw_decode(self, text, idx=0):
            decoded_starts.append(idx)
            return super().raw_decode(text, idx)

    class SourceText(str):
        def __getitem__(self, key):
            value = super().__getitem__(key)
            if not isinstance(key, slice):
                return value

            class SourceSlice(str):
                def encode(self, *args, **kwargs):
                    encoded_slices.append((key.start, key.stop))
                    return super().encode(*args, **kwargs)

            return SourceSlice(value)

    class SourceBytes(bytes):
        def decode(self, *args, **kwargs):
            return SourceText(super().decode(*args, **kwargs))

    monkeypatch.setattr(json_input.json, "JSONDecoder", CountingDecoder)
    raw = SourceBytes(' ["é", {"snow":"☃"}, [1,2]] '.encode())
    result = read(raw)
    assert decoded_starts == [span.char_start for span in result.records]
    assert len(encoded_slices) == 2 * len(result.records)
    assert encoded_slices[0][0] == 0
    assert all(left[1] == right[0] for left, right in pairwise(encoded_slices))
    assert encoded_slices[-1][1] == result.records[-1].char_end
