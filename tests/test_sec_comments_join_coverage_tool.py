"""SEC coverage receipts count actual mirror documents and retain the Federal Register chain independently."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

from spicy_docs.releases.format import ROLE_RECORDS
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tools.analysis import sec_comments_join_coverage as tool

FIXTURES = Path(__file__).parent / "fixtures" / "sec_comments"


def release(root, store, rows):
    body = b"".join(json.dumps(row).encode() + b"\n" for row in rows)
    digest = "sha256:" + hashlib.sha256(body).hexdigest()
    store.put_blob(digest, len(body), [body])
    path = root.joinpath(*tool.MANIFEST)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"members": [{"role": ROLE_RECORDS, "blobRef": digest}]}))
    return root


def mirror(identity, number, *, title="No matching title", posted="2026-01-01"):
    return {
        "record": {
            "data": {
                "id": identity,
                "attributes": {
                    "frDocNum": number,
                    "title": title,
                    "postedDate": posted,
                    "documentType": "Rule",
                },
            }
        }
    }


def run_report(tmp_path, monkeypatch, mirrors, fr_rows):
    store = LocalSourceNativeBlobStore(tmp_path / "blobs")
    sec = release(tmp_path / "sec", store, mirrors)
    fr = release(tmp_path / "fr", store, fr_rows)
    receipts = tmp_path / "receipts"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sec_comments_join_coverage",
            "--sec-release",
            str(sec),
            "--fr-release",
            str(fr),
            "--blob-store",
            str(store.root),
            "--receipts",
            str(receipts),
        ],
    )
    tool.main()
    report = json.loads((receipts / "sec-comments-join-coverage-with-fallbacks.jsonl").read_text())
    for pin in report["inputs"]:
        assert pin["sha256"] == hashlib.sha256(Path(pin["path"]).read_bytes()).hexdigest()
    return report


def fr_rows():
    return [json.loads(line) for line in (FIXTURES / "federal-register-documents.jsonl").read_text().splitlines()]


def test_unreadable_numbers_are_not_counted_as_resolved_and_duplicates_count_as_documents(tmp_path, monkeypatch):
    records = fr_rows()
    mirrors = [
        mirror("a", "2023-15200"),
        mirror("b", "2023-15200"),
        mirror("c", "not-a-number"),
        mirror("d", "2026-99999"),
        mirror("e", None),
    ]
    report = run_report(tmp_path, monkeypatch, mirrors, records[:1])
    coverage = report["coverage"]
    assert coverage["joinableViaFrDocNumDocuments"] == 2
    assert coverage["frDocNumResolvedFraction"] == 0.5
    assert coverage["totalJoinableDocuments"] == 2
    assert report["secDocuments"]["frDocNumUnreadable"] == 1
    assert report["fallbacks"]["unresolvedFrDocNumDocuments"]["total"] == 2


def test_sample_chain_includes_fr_records_absent_from_the_mirror(tmp_path, monkeypatch):
    report = run_report(tmp_path, monkeypatch, [mirror("a", "2023-15200")], fr_rows())
    chain = report["coverage"]["sampleChain"]["S7-11-23"]
    assert [entry["documentNumber"] for entry in chain] == ["2023-15200", "2024-31178", "2025-12016"]
    assert [entry["citation"] for entry in chain] == ["88 FR 45836", "90 FR 2790", "90 FR 27990"]


def test_fallback_resolves_missing_and_unreadable_numbers_without_inflating_primary_coverage(tmp_path, monkeypatch):
    records = fr_rows()[:1]
    title = records[0]["record"]["title"]
    mirrors = [
        mirror("a", None, title=title, posted="2023-07-18"),
        mirror("b", "not-a-number", title=title, posted="2023-07-18"),
    ]
    report = run_report(tmp_path, monkeypatch, mirrors, records)
    assert report["coverage"]["joinableViaFrDocNumDocuments"] == 0
    assert report["coverage"]["fallbackResolvedDocuments"] == 2
    assert report["coverage"]["totalJoinableDocuments"] == 2


def test_link_counts_come_from_the_join_and_the_raw_census_counts_what_it_cannot_read(tmp_path, monkeypatch):
    rows = fr_rows()[:3]  # the S7-11-23 chain: proposal, adoption, extension
    # The release misspells some raw names; its own agency slug still names the SEC.
    rows[1]["record"]["agencies"] = [
        {"raw_name": "SECURITIES AND EXCHANGE COMMISISON", "slug": "securities-and-exchange-commission"}
    ]
    # A statement outside the join's grammar is counted by its shape, never silently dropped.
    rows[2]["record"]["docket_ids"] = ["Release No. SAB 102"]
    epa = {"document_number": "2026-00001", "volume": 91, "start_page": 1000, "agencies": [{"raw_name": "EPA"}]}
    mirrors = [
        mirror("a", "2023-15200"),
        mirror("b", "2024-31178"),
        mirror("c", "2025-12016"),
        mirror("d", "2026-00001"),
    ]
    report = run_report(tmp_path, monkeypatch, mirrors, [*rows, {"record": epa}])
    coverage = report["coverage"]
    assert coverage["joinableViaFrDocNumDocuments"] == coverage["linkedByCitation"] == 3
    assert coverage["frDocNumResolvedOnlyOutsideSec"] == ["2026-00001"]
    assert coverage["linkedByReleaseNumber"] == coverage["linkedByFileNumber"] == 2
    assert [link["mirrorDocumentId"] for link in coverage["sampleChain"]["links"]] == ["a", "b"]
    census = report["federalRegister"]
    assert census["secAgencyRecords"] == 3 and census["statementSpellings"]["release:Release No."] == 3
    assert census["statementsTheJoinReadsNothingFrom"] == {'release:["Release No. SAB N"]': 1}


@pytest.mark.parametrize("start_page,linked,unspellable", [(632, 1, 0), (1_234_567, 0, 1)])
def test_a_sub_1000_page_joins_and_a_citation_the_grammar_cannot_spell_is_counted(
    tmp_path, monkeypatch, start_page, linked, unspellable
):
    records = fr_rows()[:1]
    records[0]["record"]["start_page"] = start_page
    report = run_report(tmp_path, monkeypatch, [mirror("a", "2023-15200")], records)
    assert report["coverage"]["linkedByCitation"] == linked
    assert report["coverage"]["citationsOutsideTheJoinGrammar"] == unspellable


def test_fr_number_without_a_volume_and_page_is_not_a_citation(tmp_path, monkeypatch):
    records = fr_rows()[:1]
    records[0]["record"]["start_page"] = None
    report = run_report(tmp_path, monkeypatch, [mirror("a", "2023-15200")], records)
    assert report["coverage"]["frDocNumResolvedToCitation"] == 0
    assert report["coverage"]["joinableViaFrDocNumDocuments"] == 0
