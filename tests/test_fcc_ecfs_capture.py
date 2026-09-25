"""The FCC operator path replays pinned pages and keeps durable, verified document outcomes."""

import json
from datetime import date as Date

import pytest

from spicy_docs.sources import walled_fetch as walled_fetch_module
from spicy_docs.sources.fcc_ecfs_attachments import (
    FccEcfsDocumentAcquirer,
    FccEcfsDocumentBudget,
    FccEcfsDocumentError,
)
from spicy_docs.sources.fcc_ecfs_capture import FccCaptureJournal, retained_body
from spicy_docs.sources.walled_fetch import RungOutcome, Transport, WalledFetchResult
from spicy_docs.transport.credentials import CredentialRefusedError
from tests.test_fcc_ecfs_filings import Publisher
from tools.analysis.fcc_ecfs_backfill import backfill, load_resume, main

KEY = "source-secret-123456789"
SHELL = b'<!doctype html><div id="root"></div>'


def body_for(url):
    return f"A source-authored text file served at {url}.\n".encode()


def answer(url, body=None, *, content_type="text/plain", final_url=None):
    return WalledFetchResult(
        body_for(url) if body is None else body, 200, content_type, final_url or url, Transport.DIRECT, None, None
    )


def filing(identity="123", *, files=2, day="2026-01-01"):
    return {
        "id_submission": identity,
        "date_received": f"{day}T12:00:00Z",
        "date_submission": f"{day}T12:00:00Z",
        "express_comment": 0,
        "documents": [
            {"src": f"https://www.fcc.gov/ecfs/document/{identity}/{index}", "filename": f"comment-{index}.txt"}
            for index in range(1, files + 1)
        ],
    }


def byte_url(identity, index):
    return f"https://www.fcc.gov/ecfs/documents/{identity}/{index}"


def journal_rows(output):
    return [json.loads(line) for line in (output / "documents.jsonl").read_text().splitlines()]


def run(output, *, rows=None, response=None, until=Date(2026, 1, 1), **kwargs):
    publisher = Publisher([filing(), filing("456", files=0)] if rows is None else rows)
    documents = []

    def ladder(url, *, before_request, **_):
        # One scripted ladder answer per document, charged like any attempt.
        before_request()
        documents.append(url)
        return (response or answer)(url)

    client = FccEcfsDocumentAcquirer(budget=FccEcfsDocumentBudget(3, 1024, 10, 0))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(walled_fetch_module, "walled_fetch", ladder)
        offline = walled_fetch_module.ProxyFetchers(zyte="offline", firecrawl="offline")
        patch.setattr(walled_fetch_module.ProxyFetchers, "from_environment", classmethod(lambda _cls: offline))
        code = backfill(
            since=Date(2026, 1, 1),
            until=until,
            output=output,
            api_key=KEY,
            min_interval_seconds=0,
            pause_seconds=0,
            transport=publisher,
            capture_documents=True,
            document_acquirer=client,
            **kwargs,
        )
    return code, [str(call.url) for call in publisher.calls], documents


def test_interrupted_capture_resumes_only_outstanding_files_and_retains_parent_evidence(tmp_path):
    code, pages, documents = run(tmp_path, max_document_attempts=1)
    assert code == 1 and len(pages) == len(documents) == 1
    assert journal_rows(tmp_path)[-1]["outcomes"] == {"captured": 1, "not-requested": 1}
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and documents == [byte_url("123", 2)]
    summary = journal_rows(tmp_path)[-1]
    assert summary["outcomes"] == {"captured": 2}
    assert summary["reusedDocuments"] == 1 and summary["filingsWithoutDocuments"] == 1
    captured = [row for row in journal_rows(tmp_path) if row["kind"] == "document"]
    assert len(captured) == 2 and captured[0]["runId"] != captured[1]["runId"]
    windows = load_resume(tmp_path / "resume.jsonl")
    for row in captured:
        source = row["source"]
        assert windows[(source["start"], source["end"])]["sha256"] == source["sha256"]
        pinned = (tmp_path / f"filings-{source['start']}-{source['end']}.jsonl").read_text().splitlines()
        assert json.loads(pinned[source["line"]]) == filing()
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and not documents
    assert journal_rows(tmp_path)[-1]["reusedDocuments"] == 2


def test_larger_filing_page_replays_on_resume(tmp_path):
    code, pages, documents = run(tmp_path, per_page=5000)
    assert code == 0 and len(pages) == 1 and "limit=5000" in pages[0]
    assert len(documents) == 2
    assert run(tmp_path, per_page=5000) == (0, [], [])


@pytest.mark.parametrize("damage", ["delete", "corrupt"])
def test_only_the_damaged_document_is_reacquired_into_a_new_store(tmp_path, damage):
    assert run(tmp_path)[0] == 0
    first = next(row for row in journal_rows(tmp_path) if row["kind"] == "document")
    old = next((tmp_path / "captures" / first["capture"]["runId"]).rglob(first["capture"]["sha256"][7:]))
    if damage == "delete":
        old.unlink()
    else:
        old.write_bytes(b"!" + old.read_bytes()[1:])
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and documents == [byte_url("123", 1)]
    if damage == "corrupt":
        assert old.read_bytes().startswith(b"!"), "the damaged evidence stays in its original store"
    assert run(tmp_path)[1:] == ([], [])


def test_missing_page_reacquires_discovery_but_reuses_document_captures(tmp_path, capsys):
    assert run(tmp_path)[0] == 0
    state = next(iter(load_resume(tmp_path / "resume.jsonl").values()))
    page = state["pages"][0]
    next((tmp_path / "captures" / page["runId"]).rglob(page["sha256"][7:])).unlink()
    # A capture dry run counts settled windows the way execution will.
    plan = ["--since", "2026-01-01", "--until", "2026-01-01", "--output", str(tmp_path)]
    assert main(plan) == 0 and "1 already settled" in capsys.readouterr().out
    assert main([*plan, "--capture-documents"]) == 0 and "0 already settled" in capsys.readouterr().out
    code, pages, documents = run(tmp_path)
    assert code == 0 and len(pages) == 1 and not documents


def test_failed_file_retries_and_does_not_erase_an_earlier_success(tmp_path):
    def fail_second(url):
        if url.endswith("/2"):
            raise FccEcfsDocumentError("temporary transport failure")
        return answer(url)

    assert run(tmp_path, response=fail_second)[0] == 1
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and documents == [byte_url("123", 2)]
    assert journal_rows(tmp_path)[-1]["outcomes"] == {"captured": 2}


@pytest.mark.parametrize(
    "kind,refusal",
    [
        ("redirected", lambda url: answer(url, final_url=url + "?moved")),
        ("spa-shell", lambda url: answer(url, SHELL, content_type="text/html")),
    ],
)
def test_a_per_document_refusal_is_recorded_and_later_files_are_still_captured(tmp_path, kind, refusal):
    rows = [filing(files=3)]

    def first_refuses(url):
        return refusal(url) if url.endswith("/1") else answer(url)

    code, pages, documents = run(tmp_path, rows=rows, response=first_refuses)
    assert code == 1 and documents == [byte_url("123", index) for index in (1, 2, 3)]
    assert journal_rows(tmp_path)[-1]["outcomes"] == {"refused": 1, "captured": 2}
    refused = next(row for row in journal_rows(tmp_path) if row.get("status") == "refused")
    assert refused["refusalKind"] == kind
    assert retained_body(tmp_path, refused["refusal"]) == refusal(byte_url("123", 1)).body
    code, pages, documents = run(tmp_path, rows=rows, response=first_refuses)
    assert code == 1 and not pages and documents == [byte_url("123", 1)]


def test_a_host_wide_refusal_still_aborts_before_the_next_file(tmp_path):
    wall = b"You don't have permission to access this server."

    def walled(url):
        raise walled_fetch_module._exhausted(url, (RungOutcome(Transport.DIRECT, "wall"),), wall)

    code, _, documents = run(tmp_path, response=walled)
    assert code == 2 and len(documents) == 1
    refused = journal_rows(tmp_path)[-2]
    assert refused["refusalKind"] == "client-rejected" and retained_body(tmp_path, refused["refusal"]) == wall


def test_credential_refusal_aborts_before_next_file_and_is_scrubbed_before_truncation(tmp_path):
    def refused(_):
        raise CredentialRefusedError("x" * 1980 + KEY + " https://source.test/?api_key=another-secret")

    code, _, documents = run(tmp_path, response=refused)
    assert code == 2 and len(documents) == 1
    journal = (tmp_path / "documents.jsonl").read_text()
    assert KEY not in journal and KEY[:15] not in journal and "another-secret" not in journal
    assert not journal_rows(tmp_path)[-1]["complete"]
    assert run(tmp_path)[0] == 0


def test_serialized_row_scrubbing_catches_nested_unknown_query_credentials(tmp_path):
    with FccCaptureJournal(tmp_path, secrets=(KEY,)) as journal:
        journal.emit({"kind": "test", "nested": {"value": KEY, "url": "https://source.test/?api_key=other-secret"}})
    text = (tmp_path / "documents.jsonl").read_text()
    assert KEY not in text and "other-secret" not in text


def test_scrubbing_happens_before_json_escaping_and_covers_dictionary_keys(tmp_path):
    secret = 'quoted"secret\\with-backslash'
    with FccCaptureJournal(tmp_path, secrets=(secret,)) as journal:
        journal.emit({"kind": "test", "nested": {secret: [secret]}})
    assert journal_rows(tmp_path)[-1]["nested"] == {"<redacted>": ["<redacted>"]}


def test_a_quoted_credential_url_leaves_every_row_readable(tmp_path):
    message = 'refused {"url": "https://source.test/?api_key=abc123"}'
    with FccCaptureJournal(tmp_path) as journal:
        journal.emit({"kind": "test", "message": message})
    assert journal_rows(tmp_path)[-1]["message"] == message.replace("abc123", "<redacted>")
    with FccCaptureJournal(tmp_path):
        pass  # the next run reads every committed row


def test_a_row_whose_serialization_still_carries_a_credential_is_not_written(tmp_path):
    # The field pass scrubs text; a numeric leaf reaches the serialized row unscrubbed.
    with FccCaptureJournal(tmp_path, secrets=("12345678901",)) as journal:
        before = (tmp_path / "documents.jsonl").read_bytes()
        with pytest.raises(ValueError, match="kept a credential"):
            journal.emit({"kind": "test", "count": 12345678901})
        assert (tmp_path / "documents.jsonl").read_bytes() == before


@pytest.mark.parametrize("reverse", [False, True])
def test_filing_without_documents_counts_the_union_of_its_observations(tmp_path, reverse):
    # Adjacent windows each observe the filing, once without files and once with one.
    first, second = (0, 1) if not reverse else (1, 0)
    rows = [filing(files=first, day="2026-01-01"), filing(files=second, day="2026-01-02")]
    code, _, documents = run(tmp_path, rows=rows, until=Date(2026, 1, 2), slice_days=1)
    assert code == 0 and len(documents) == 1
    summary = journal_rows(tmp_path)[-1]
    assert summary["filings"] == 1 and summary["filingsWithoutDocuments"] == 0


@pytest.mark.parametrize("damage", ["scope", "method", "status", "terminal"])
def test_resume_rechecks_request_scope_and_continuation_from_exact_pages(tmp_path, damage):
    assert run(tmp_path)[0] == 0
    state = next(iter(load_resume(tmp_path / "resume.jsonl").values()))
    page = state["pages"][0]
    if damage == "scope":
        page["requestedUrl"] = page["requestedUrl"].replace("2026-", "2025-")
        page["resolvedUrl"] = page["requestedUrl"]
    elif damage == "terminal":
        # A full page requires another page, even when a forged receipt says
        # it was terminal. The exact body contains two rows.
        page["requestedUrl"] = page["requestedUrl"].replace("limit=1000", "limit=2")
        page["resolvedUrl"] = page["requestedUrl"]
    elif damage == "method":
        page["method"] = "POST"
    else:
        page["status"] = 403
    with (tmp_path / "resume.jsonl").open("a") as sink:
        sink.write(json.dumps(state) + "\n")
    code, pages, documents = run(tmp_path)
    assert code == 0 and len(pages) == 1 and not documents


def test_a_truncated_final_journal_row_is_preserved_and_valid_successes_resume(tmp_path):
    assert run(tmp_path, max_document_attempts=1)[0] == 1
    with (tmp_path / "documents.jsonl").open("ab") as sink:
        sink.write(b'{"kind":"document","key":')
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and len(documents) == 1
    assert next(tmp_path.glob("documents-interrupted-*.partial")).read_bytes() == b'{"kind":"document","key":'


def test_interrupted_window_checkpoint_does_not_prevent_document_resume(tmp_path):
    assert run(tmp_path, max_document_attempts=1)[0] == 1
    with (tmp_path / "resume.jsonl").open("ab") as sink:
        sink.write(b'{"start":"2026-01-01"')
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and len(documents) == 1
    assert next(tmp_path.glob("resume-interrupted-*.partial")).read_bytes() == b'{"start":"2026-01-01"'


def test_reflected_credential_is_never_retained_as_file_bytes(tmp_path):
    code, _, documents = run(tmp_path, response=lambda url: answer(url, KEY.encode()))
    assert code == 2 and len(documents) == 1
    assert all(KEY.encode() not in path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())


def test_empty_and_unavailable_are_explicit_outcomes_and_unavailable_retries(tmp_path):
    def outcome(url):
        return WalledFetchResult(
            b"", 404 if url.endswith("/2") else 200, "text/plain", url, Transport.DIRECT, None, None
        )

    assert run(tmp_path, response=outcome)[0] == 0
    assert journal_rows(tmp_path)[-1]["outcomes"] == {"requested-empty": 1, "unavailable": 1}
    code, pages, documents = run(tmp_path)
    assert code == 0 and not pages and documents == [byte_url("123", 2)]


def test_malformed_declarations_cannot_mark_capture_complete(tmp_path):
    row = filing()
    row["documents"][0]["src"] = "https://unexpected.test/document"
    code, _, documents = run(tmp_path, rows=[row])
    assert code == 1 and not documents
    assert journal_rows(tmp_path)[-1]["invalidFilings"] == 1
