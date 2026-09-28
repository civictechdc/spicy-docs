"""YAML evidence parsing refuses silent data loss and preserves literal dates."""

import datetime
import sys

import pytest

from spicy_docs.reading.yaml_input import load_bounded_yaml


def load(body, **kwargs):
    return load_bounded_yaml(body, source="fixture", error_type=ValueError, max_bytes=4096, **kwargs)


def test_dates_stay_literal_without_changing_other_yaml_users():
    import yaml

    assert load(b"date: 2026-09-28\nrescinded: true\ncongress: 119") == {
        "date": "2026-09-28",
        "rescinded": True,
        "congress": 119,
    }
    assert yaml.safe_load("date: 2026-09-28")["date"] == datetime.date(2026, 9, 28)


@pytest.mark.parametrize(
    "body",
    [
        b"a: 1\na: 2",
        b"true: x\n1: y",
        b"a: &r [x]\nb: *r",
        b"a: &r [*r]",
        b"a: {<<: {b: 1}}",
        b"? [a, b]\n: c",
        b"!!python/object:unknown {}",
        b"a: [",
        b"---\na: 1\n---\na: 2",
        b"\xff",
    ],
)
def test_ambiguous_or_unsupported_yaml_refuses(body):
    with pytest.raises(ValueError):
        load(body)


def test_node_depth_and_payload_bounds():
    with pytest.raises(ValueError, match="bounds"):
        load(b"[1, 2]", max_nodes=2)
    with pytest.raises(ValueError, match="bounds"):
        load(b"[[[1]]]", max_depth=2)
    with pytest.raises(ValueError, match="byte bound"):
        load(b"x" * 4097)


@pytest.mark.parametrize(
    "body",
    [b"date: !!timestamp 2026-09-28", b"blob: !!binary aGk=", b"s: !!set {a: null}", b"o: !!omap [{a: 1}]"],
)
def test_explicit_tags_cannot_bring_back_constructed_dates_or_non_json_values(body):
    with pytest.raises(ValueError, match="not supported YAML"):
        load(body)


def test_aliases_are_named_as_aliases():
    with pytest.raises(ValueError, match="aliases"):
        load(b"a: &r [x]\nb: *r")


def test_missing_parser_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "yaml", None)
    with pytest.raises(ValueError, match=r"spicy-docs\[yaml\]"):
        load(b"a: 1")


@pytest.mark.parametrize("body", [b"unknown: {0xA: numeric, '10': string}", b"unknown: {42: value}"])
def test_nested_mapping_keys_cannot_change_when_encoded_as_json(body):
    """Unknown nested keys remain strings; YAML numeric decoding cannot cause later JSON data loss."""
    with pytest.raises(ValueError, match="string mapping keys"):
        load(body)
