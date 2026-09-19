"""Pin gap B6's corpus-validation aggregates against the committed JSON.

``tests/fixtures/gpo_pdf_text/corpus-2026-09-19.json`` is the per-document
record of a 42-document run over ``extraction.body_text``'s PDF branch --
the "Corpus validation" section in ``docs/extraction-gpo.md`` restates its
table and its aggregate numbers in prose. This test re-derives those
aggregates from the committed JSON so the two never drift apart silently,
without holding or fetching a single byte of any PDF: the JSON carries only
each document's URL, sha256 and measured counts (see that file's own
``method`` field for exactly what was run and how).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parents[1] / "fixtures/gpo_pdf_text/corpus-2026-09-19.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _load() -> list[dict]:
    return json.loads(FIXTURE.read_text())["documents"]


def test_corpus_has_forty_two_documents_spanning_both_congresses():
    documents = _load()
    assert len(documents) == 42
    kinds = {d["kind"] for d in documents}
    assert kinds == {"bill", "report", "record"}
    bills = [d for d in documents if d["kind"] == "bill"]
    reports = [d for d in documents if d["kind"] == "report"]
    records = [d for d in documents if d["kind"] == "record"]
    assert len(bills) == 36
    assert len(reports) == 5
    assert len(records) == 1
    congresses = {d["congress"] for d in bills}
    assert congresses == {113, 119}
    assert sum(1 for d in bills if d["congress"] == 113) == 6
    assert sum(1 for d in bills if d["congress"] == 119) == 30


def test_corpus_spans_every_named_print_stage():
    """The task-named stages (ih, is, rh, rs, eh, es, enr, rfs, pcs, ats)
    plus every other stage the sealed vocabulary in
    ``sources/congress/bill_versions.py`` names as measured in the 119th
    BILLS census that this corpus happens to also carry."""
    stages = {d["stage"] for d in _load() if d["kind"] == "bill"}
    named = {"ih", "is", "rh", "rs", "eh", "es", "enr", "rfs", "pcs", "ats"}
    assert named <= stages


def test_layout_verdict_matches_every_stage_expectation():
    """Every non-enrolled bill stage (not just ih/is/rh/rs -- the fixture
    also carries eh/es/rfs/pcs/ats/rds/cps/eas/eah/rfh/rhuc, all measured
    True the same way) is line-numbered; every enrolled bill, every
    committee report, and the Congressional Record issue are not. Zero
    disagreements across all 42 documents, pinned -- this is what two rule
    fixes in ``gpo_normalize._layout_verdict`` (see that function's own
    docstring) bought: both were false negatives this same corpus caught
    before the fix. Each document must match exactly one of the three
    branches below; a document matching none (an unexpected kind or a bill
    stage this test has not accounted for) fails the test outright rather
    than silently skipping both assertions the earlier, narrower version of
    this loop made possible."""
    documents = _load()
    for doc in documents:
        if doc["kind"] in ("record", "report") or (doc["kind"] == "bill" and doc["stage"] == "enr"):
            assert doc["line_numbers"] is False, doc["package"]
        elif doc["kind"] == "bill":
            assert doc["line_numbers"] is True, doc["package"]
        else:
            pytest.fail(
                f"document matched no branch: kind={doc['kind']!r} "
                f"stage={doc.get('stage')!r} package={doc.get('package')!r}"
            )


def test_no_gutter_digits_leak_and_no_footer_survives_on_any_document():
    documents = _load()
    assert sum(d["gutter_digits_leaked"] for d in documents) == 0
    assert sum(d["footers_left"] for d in documents) == 0


def test_hyphen_rejoin_residual_false_positive_rate():
    """89,337 merge operations, 70,054 resulting words checked, 1,232 not a
    known word (1.76%) -- the number ``docs/extraction-gpo.md``'s "Corpus
    validation" section states and characterizes (sampled and read on the
    page: a real compound's own hyphen coinciding with the print-wrap point,
    or a proper noun / modern compound the system dictionary lacks -- not a
    parsing defect)."""
    documents = _load()
    total_rejoins = sum(d["hyphen_rejoin_count"] for d in documents)
    total_words = sum(d["rejoined_word_count"] for d in documents)
    total_false = sum(d["false_rejoin_count"] for d in documents)
    assert total_rejoins == 89_337
    assert total_words == 70_054
    assert total_false == 1_232
    assert round(total_false / total_words, 4) == 0.0176


def test_reused_fixture_documents_carry_no_url_or_bytes():
    """A document reused from an already-committed fixture was never
    re-fetched this run; its provenance is the fixture file itself, not a
    URL or a sha256 of bytes this run captured."""
    documents = _load()
    reused = [d for d in documents if d["reused_fixture"]]
    assert len(reused) == 4
    for doc in reused:
        assert doc["url"] is None
        assert doc["sha256"] is None
        assert doc["byte_size"] is None


def test_every_fresh_document_states_a_govinfo_url_and_a_sha256_digest():
    documents = _load()
    fresh = [d for d in documents if not d["reused_fixture"]]
    assert len(fresh) == 38
    for doc in fresh:
        assert doc["url"].startswith("https://www.govinfo.gov/") or doc["url"].startswith("https://api.govinfo.gov/")
        assert doc["package"] in doc["url"]
        assert _HEX64.match(doc["sha256"])
        assert isinstance(doc["byte_size"], int) and doc["byte_size"] > 0


def test_no_bytes_or_credentials_committed_in_the_corpus_json():
    """Boy-scout guard for the rule stated in the task and in
    ``AGENTS.md``: the fixture carries per-document measurements and
    provenance, never PDF bytes and never a credential."""
    raw = FIXTURE.read_text()
    assert "%PDF" not in raw
    for needle in ("api_key", "API_GOV", "X-Api-Key", "Authorization", "Bearer "):
        assert needle not in raw
