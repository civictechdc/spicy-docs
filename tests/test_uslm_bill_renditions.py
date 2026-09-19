"""Pin the five-package USLM bill-rendition measurement (gap B7's proof).

``tests/fixtures/govinfo_bills/uslm-renditions-2026-09-19.json`` records every
BILLS package in the 2026-09-19 text-versions census sample that offers a
United States Legislative Markup rendition, each fetched through
``GovInfoBodyAcquirer.acquire(package, prefer=("uslm",))`` and derived through
``body_text`` -- facts only, no bytes. This test re-derives what the retained
bytes still prove (the ``BILLS-119hconres11enr`` fixture in the same
directory), pins the census reconciliation the measurement corrects, and
checks the JSON's own arithmetic, so none of it drifts silently.
"""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from spicy_docs.extraction.body_text import rendition_text

FIXTURES = Path(__file__).parent / "fixtures" / "govinfo_bills"
PIN = json.loads((FIXTURES / "uslm-renditions-2026-09-19.json").read_text())
RETAINED = (FIXTURES / "uslm-119hconres11enr.xml").read_bytes()
CENSUS = json.loads((Path(__file__).parents[1] / "docs/research/billtrax-raw-data-2026-09-19.json").read_text())

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
IN_SCOPE = {
    "BILLS-119hconres11enr",
    "BILLS-119hr6644enr",
    "BILLS-119hr7147enr",
    "BILLS-119hr7148enr",
    "BILLS-119s4138enr",
}
USLM_NAMESPACE = "http://schemas.gpo.gov/xml/uslm"


def _packages() -> dict[str, dict]:
    return {row["package_id"]: row for row in PIN["packages"]}


def test_every_in_scope_package_is_pinned_exactly_once():
    assert set(_packages()) == IN_SCOPE
    assert len(PIN["packages"]) == len(IN_SCOPE)


def test_reconciliation_arithmetic_holds():
    counts = PIN["census_reconciliation"]
    assert counts["distinct_uslm_entries"] == 9
    assert (
        counts["bills_packages_in_scope"] + counts["plaw_collection_uslm_entries_out_of_scope"]
        == counts["distinct_uslm_entries"]
    )
    assert counts["bills_packages_in_scope"] == len(IN_SCOPE)


def test_each_row_states_the_reading_facts_the_grammar_and_derivation_claim():
    """Every pinned rendition is `application/xml` in the USLM namespace, read
    by the markup-reader branch, from a package whose MODS also offered XML --
    the measured ground for 'a second structured rendition' and for XML's top
    slot in the sealed order."""
    for row in PIN["packages"]:
        assert row["root_namespace"] == USLM_NAMESPACE, row["package_id"]
        assert row["media_type"] == row["content_type"] == "application/xml", row["package_id"]
        assert row["derivation"] == "markup-reader", row["package_id"]
        assert "xml" in row["offered_formats"], row["package_id"]
        assert row["text_line_count"] > 0, row["package_id"]
        assert _HEX64.fullmatch(row["sha256"]), row["package_id"]


def test_roots_vary_by_bill_type_as_documented():
    roots = {pkg: row["root_localname"] for pkg, row in _packages().items()}
    assert roots["BILLS-119hconres11enr"] == "resolution"
    for hr in IN_SCOPE - {"BILLS-119hconres11enr"}:
        assert roots[hr] == "bill", hr


def test_hconres11enr_row_rederives_from_the_retained_fixture_bytes():
    """The one package whose bytes are committed must still match its pin, so
    the fixture and the measurement cannot drift apart silently."""
    row = _packages()["BILLS-119hconres11enr"]
    root = ET.fromstring(RETAINED)
    derived = rendition_text(RETAINED, rendition="uslm", media_type="application/xml")
    assert hashlib.sha256(RETAINED).hexdigest() == row["sha256"]
    assert len(RETAINED) == row["byte_size"]
    assert root.tag.rpartition("}")[2] == row["root_localname"] == "resolution"
    assert root.tag.lstrip("{").partition("}")[0] == row["root_namespace"]
    assert derived.derivation == row["derivation"]
    assert len(derived.text.splitlines()) == row["text_line_count"]


def test_the_corrected_census_still_states_the_double_counted_aggregate():
    """The census file's own aggregate is the number this measurement corrects
    (10 USLM of 240, each sampled bill counted once per pinning code). If the
    file is ever regenerated with different numbers, the reconciliation above
    must be re-run rather than silently inherited."""
    counts = CENSUS["sources"]["textVersionsVocabulary"]["formatTypeCounts"]
    assert counts["United States Legislative Markup"] == 10
    assert sum(counts.values()) == 240
    codes = CENSUS["sources"]["textVersionsVocabulary"]["codes"]
    assert codes["enr"]["sample"] == "BILLS-119hconres11enr.xml"
    assert codes["rds"]["sample"] == "BILLS-119hconres11rds.xml"
