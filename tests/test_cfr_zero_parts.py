"""Part zero is published and fits the existing Rulespec identifier space.

The oracle ``old_cfr_part`` is the check copied from RefSpec 566df1d4; zero-part
support is the named change. Publisher fixtures prove the new reader mints
``:0`` without inventing a different part, while every other part form must
still agree with the copied check.

Ported with :mod:`spicy_docs.interpretation.iri_minting` from RefSpec
``tests/test_cfr_zero_parts.py`` at RefSpec ``4a680c81``, with its fixture
``tests/fixtures/cfr-zero-parts.json`` byte-identical under
``fixtures/interpretation/``; only the import and fixture paths and ``ruff
format``'s layout changed. The fixture's ``source.path`` values name the eCFR
title XML in the RefSpec checkout it was cut from; its ``url`` and ``sha256``
locate that XML anywhere.
"""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from spicy_docs.interpretation import iri_minting as minting

CASES = json.loads((Path(__file__).parent / "fixtures/interpretation/cfr-zero-parts.json").read_text())["cases"]


def old_cfr_part(value):
    # Copied from 566df1d4; the unchanged input/positive-integer helpers are shared.
    text = minting._stated(value).lower()
    match = re.fullmatch(r"([0-9]+)([a-z]?)", text)
    if match is None:
        return None
    number = minting._positive_integer(match[1])
    return None if number is None else f"{number}{match[2]}"


@pytest.mark.parametrize("case", CASES, ids=lambda case: str(case["title"]))
@pytest.mark.parametrize("part", [0, "0", "00", " 000 "])
def test_publisher_part_zero_mints_without_inventing_a_different_part(case, part):
    """A publisher ``PART 0`` head mints ``urn:rkaf:us:cfr:<title>:0`` and extends the first section, where the copied
    check refuses it."""

    assert case["head"].startswith("PART 0")
    assert 'N="0" TYPE="PART"' in case["opening_and_head"]
    with patch.object(minting, "_cfr_part", old_cfr_part):
        assert minting.mint_cfr_iri(case["title"], part) is None
    minted = minting.mint_cfr_iri(case["title"], part)
    assert minted.iri == f"urn:rkaf:us:cfr:{case['title']}:0"
    assert minting.IDENTIFIER_SPACES[minted.scheme].fullmatch(minted.iri)
    if case["first_section"] is not None:
        suffix = case["first_section"]["number"].removeprefix("0.")
        assert minting.mint_cfr_iri(case["title"], part, suffix).iri == minted.iri + "." + suffix


@pytest.mark.parametrize(
    "value",
    [None, "", " ", "-0", "0.0", "0/1", "0-1", "0aa", "٠", "０", True, "1", 1, "01", " 15a ", "016A", "101-1", "16a3"],
)
def test_other_part_forms_agree_with_the_copied_check(value):
    """Every non-zero part form, including Unicode digits, booleans and separators, keeps the copied verdict."""

    assert minting._cfr_part(value) == old_cfr_part(value)


@pytest.mark.parametrize("value", ["0a", "000A"])
def test_zero_stem_letter_follows_the_existing_space_without_an_issuance_claim(value):
    """``0a`` stays inside the existing identifier space even though it makes no claim that the part was issued."""

    assert old_cfr_part(value) is None
    assert minting.mint_cfr_iri(16, value).iri == "urn:rkaf:us:cfr:16:0a"


@pytest.mark.parametrize("title", [0, "00", -1, 51, None, "٠"])
def test_title_validation_is_still_independent_of_zero_part_support(title):
    """Invalid titles are refused whatever the zero-part change did."""

    assert minting.mint_cfr_iri(title, "0") is None
