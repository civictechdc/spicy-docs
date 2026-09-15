"""Legal offsets and audit pages retain source identity, scope and raw evidence.

AO/AF fixtures are complete retained publisher queries. Audit success and all
multi-page cases here are synthetic; the real audit page proves refusal only.
"""

import copy
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from rulespec_artifacts import LocalMemberSource

from spicy_docs.source_native import SourceNativeReleaseBuild, SourceNativeReleasePublisher, SourceNativeReleaseReader
from spicy_docs.source_native_profiles import FEC_AUDIT_QUERY_PROFILE, FEC_LEGAL_QUERY_PROFILE
from spicy_docs.sources.fec.audit_profile import audit_query_scope, iter_retained_audit_pages
from spicy_docs.sources.fec.legal_profile import iter_retained_legal_pages, legal_query_scope
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore
from tests.releases.fixtures import IMPLEMENTATION_ID, PRODUCER
from tests.test_fec_release import _inputs as synthetic_inputs

FIXTURES = Path(__file__).parent / "fixtures/fec"
LEGAL_URL = "https://api.open.fec.gov/v1/legal/search/?type=murs&hits_returned=1"
AUDIT_URL = "https://api.open.fec.gov/v1/audit-case/?cycle=2022&per_page=1"
INTERFACES = {
    "legal": (FEC_LEGAL_QUERY_PROFILE, legal_query_scope, iter_retained_legal_pages),
    "audit": (FEC_AUDIT_QUERY_PROFILE, audit_query_scope, iter_retained_audit_pages),
}


def _capture(raw, url):
    return {
        "requestUrl": url,
        "observedAt": "2026-09-15T03:00:00Z",
        "responseSha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "byteSize": len(raw),
    }


def _legal_inputs(tmp_path, *, records=None, selected="murs", size=1, change=None):
    if records is None:
        records = [{"doc_id": "mur_2", "type": selected}, {"doc_id": "mur_1", "type": selected}]
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    captures, originals = [], []
    for offset in range(0, max(1, len(records)), size):
        value = {
            selected: records[offset : offset + size],
            "total_" + selected: len(records),
            "total_all": len(records),
        }
        if change is not None:
            change(value, offset)
        raw = json.dumps(value, indent=2).encode()
        url = LEGAL_URL.replace("type=murs", "type=" + selected).replace("hits_returned=1", f"hits_returned={size}")
        if offset:
            url += f"&from_hit={offset}"
        capture = _capture(raw, url)
        blobs.put_blob(capture["responseSha256"], len(raw), (raw,))
        captures.append(capture)
        originals.append(raw)
    return captures, originals, blobs


def _audit_inputs(tmp_path, *, records=None, change=None):
    captures, originals, blobs = synthetic_inputs(
        tmp_path,
        records=records
        if records is not None
        else [{"audit_case_id": "2", "audit_id": 9}, {"audit_case_id": "1", "audit_id": 9}],
        response_change=change,
    )
    for index, capture in enumerate(captures):
        capture["requestUrl"] = capture["resolvedUrl"] = AUDIT_URL + (f"&page={index + 1}" if index else "")
    return captures, originals, blobs


def _publish(tmp_path, family, captures, blobs, *, pages=None):
    profile, scope, iterate = INTERFACES[family]
    output = LocalSourceNativeBlobStore(tmp_path / "output-blobs")
    published = SourceNativeReleasePublisher(
        profile, blob_store=output, clock=lambda: datetime(2026, 9, 15, 4, tzinfo=UTC)
    ).publish(
        iterate(captures, blob_source=blobs) if pages is None else pages,
        build=SourceNativeReleaseBuild(
            query_scope=scope(captures), producer=PRODUCER, started_at="2026-09-15T03:00:00Z"
        ),
        destination=tmp_path / "release",
    )
    return SourceNativeReleaseReader(
        LocalMemberSource(published.root),
        blob_source=output,
        profile=profile,
        expected_pin=published.artifact.pin,
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )


def _at(value, pointer):
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _assert_source_reconstruction(reader, originals, captures):
    """Compare with the raw source independently of the production record splitter."""
    raw_by_url = dict(zip((capture["requestUrl"] for capture in captures), originals, strict=True))
    for wrapped in reader.iter_records():
        row = wrapped["record"]
        source = json.loads(raw_by_url[row["capture"]["requestUrl"]], parse_float=str)
        expected = _at(source, row["source_pointer"])
        rebuilt = copy.deepcopy(row["metadata"])
        for body in row["embedded_bodies"]:
            pointer = body["source_pointer"]
            assert pointer.startswith(row["source_pointer"] + "/")
            text = _at(source, pointer)
            assert isinstance(text, str) and len(text) == body["characters"]
            relative = pointer[len(row["source_pointer"]) :]
            parent, _, token = relative.rpartition("/")
            _at(rebuilt, parent)[token.replace("~1", "/").replace("~0", "~")] = text
        assert rebuilt == expected
    retained = set()
    for evidence in reader.iter_record_evidence():
        with ZipFile(BytesIO(reader.read_evidence(evidence["evidenceBlobRef"]))) as archive:
            retained.add(archive.read("response.json"))
    if retained:
        assert retained == set(originals)
    assert reader.collection_outcome["requestedScope"] == {"captures": captures}
    assert reader.collection_outcome["sourceStateScope"] == "observed-crawl"
    assert list(reader.iter_renditions()) == []


@pytest.mark.parametrize(
    "selected", json.loads((FIXTURES / "legal/sources.json").read_bytes()), ids=lambda row: row["file"]
)
def test_retained_legal_queries_preserve_every_field_and_exact_evidence(tmp_path, selected):
    raw = (FIXTURES / "legal" / selected["file"]).read_bytes()
    capture = selected["capture"]
    assert capture["responseSha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert capture["byteSize"] == len(raw)
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    blobs.put_blob(capture["responseSha256"], len(raw), (raw,))
    reader = _publish(tmp_path, "legal", [capture], blobs)
    _assert_source_reconstruction(reader, [raw], [capture])
    group = next(key for key in json.loads(raw) if not key.startswith("total_"))
    assert {row["sourceRecordId"] for row in reader.iter_records()} == {row["doc_id"] for row in json.loads(raw)[group]}


@pytest.mark.parametrize(
    "selected,identity",
    [
        ("murs", "mur_1"),
        ("advisory_opinions", "advisory_opinions_2025-01"),
        ("admin_fines", "af_4855"),
        ("adrs", "adr_1203"),
    ],
)
def test_legal_types_preserve_native_case_id_and_nested_signal(tmp_path, selected, identity):
    row = {
        "doc_id": identity,
        "type": selected,
        "no": "01",
        "summary": "Source summary",
        "documents": [
            {"document_id": 1, "doc_order_id": 2, "text": "Full body", "url": "/files/legal/example.pdf"},
            {"document_id": 2, "doc_order_id": 2},
        ],
        "citations": [{"text": "52 U.S.C. 30101", "unknown": None}],
        "commission_votes": [{"action": "First action"}, {"action": "First action"}],
        "dispositions": [{"penalty": 12.50, "payment_amount": None, "payment_status": "Paid In Full"}],
        "extension": {"a/b~c": {"body": "Second body"}, "empty": []},
    }
    captures, raw, blobs = _legal_inputs(tmp_path, records=[row], selected=selected)
    reader = _publish(tmp_path, "legal", captures, blobs)
    _assert_source_reconstruction(reader, raw, captures)
    (wrapped,) = reader.iter_records()
    assert wrapped["sourceRecordId"] == identity
    value = wrapped["record"]
    assert len(value["embedded_bodies"]) == 2
    assert value["metadata"]["citations"][0]["text"] == "52 U.S.C. 30101"
    assert value["assets"][0]["url"] == "https://www.fec.gov/files/legal/example.pdf"


def test_offset_chain_keeps_unsorted_native_ids_and_exact_continuation(tmp_path):
    captures, raw, blobs = _legal_inputs(tmp_path)
    reader = _publish(tmp_path, "legal", captures, blobs)
    _assert_source_reconstruction(reader, raw, captures)
    assert {row["sourceRecordId"] for row in reader.iter_records()} == {"mur_1", "mur_2"}


@pytest.mark.parametrize("family,inputs", [("legal", _legal_inputs), ("audit", _audit_inputs)])
def test_complete_empty_query_retains_requested_scope(tmp_path, family, inputs):
    captures, _, blobs = inputs(tmp_path, records=[])
    reader = _publish(tmp_path, family, captures, blobs)
    assert list(reader.iter_records()) == []
    assert reader.collection_outcome["recordOutcome"] == "empty"
    assert reader.collection_outcome["requestedScope"] == {"captures": captures}
    assert reader.collection_outcome["acquisitionEvidenceCount"] == 1


@pytest.mark.parametrize("identity", [None, 1, "", " \n"])
def test_legal_identity_is_required(tmp_path, identity):
    captures, _, blobs = _legal_inputs(tmp_path, records=[{"doc_id": identity, "type": "murs"}])
    with pytest.raises(ValueError, match="doc_id"):
        _publish(tmp_path, "legal", captures, blobs)


@pytest.mark.parametrize(
    "change",
    [
        lambda value, offset: value.update(total_all=99),
        lambda value, offset: value.update(total_murs=True),
        lambda value, offset: value.update(total_murs=0, total_all=0),
        lambda value, offset: value.update(murs=[]),
        lambda value, offset: value.update(error="denied"),
        lambda value, offset: value["murs"][0].update(type="adrs"),
        lambda value, offset: value.update(adrs=[{"doc_id": "adr_1", "type": "adrs"}], total_adrs=1),
    ],
)
def test_legal_counts_groups_and_refusals_cannot_publish(tmp_path, change):
    captures, _, blobs = _legal_inputs(tmp_path, records=[{"doc_id": "mur_1", "type": "murs"}], change=change)
    with pytest.raises(ValueError):
        _publish(tmp_path, "legal", captures, blobs)
    assert not (tmp_path / "release").exists()


def test_omitted_selected_empty_group_is_not_an_empty_answer(tmp_path):
    def change(value, offset):
        del value["murs"]
        value.update(adrs=[], total_adrs=0)

    captures, _, blobs = _legal_inputs(tmp_path, records=[], change=change)
    with pytest.raises(ValueError, match="selected result group"):
        _publish(tmp_path, "legal", captures, blobs)


def test_declared_total_cannot_change_across_legal_pages(tmp_path):
    def change(value, offset):
        if offset:
            value.update(murs=[], total_murs=1, total_all=1)

    captures, _, blobs = _legal_inputs(tmp_path, change=change)
    with pytest.raises(ValueError, match="count or page inventory changed"):
        _publish(tmp_path, "legal", captures, blobs)


@pytest.mark.parametrize(
    "query",
    [
        "type=murs",
        "type=murs&hits_returned=0",
        "type=murs&hits_returned=201",
        "type=murs&hits_returned=x",
        "type=murs&hits_returned=1&from_hit=x",
        "type=murs&hits_returned=2&from_hit=1",
        "type=murs&hits_returned=1&from_hit=-1",
        "type=murs&hits_returned=1&from_hit=0&from_hit=0",
        "type=murs&hits_returned=1&hits_returned=1",
        "type=murs&type=adrs&hits_returned=1",
        "type=statutes&hits_returned=1",
        "type=rulemakings&hits_returned=1",
        "type=murs&hits_returned=1&page=1",
        "type=murs&hits_returned=1&per_page=1",
        "type=murs&hits_returned=1&last_id=1",
    ],
)
def test_legal_controls_require_one_supported_type_and_exact_offset(tmp_path, query):
    capture = _capture(b"{}", LEGAL_URL.split("?")[0] + "?" + query)
    with pytest.raises(ValueError):
        legal_query_scope([capture])


def test_legal_maximum_size_and_explicit_zero_offset_are_supported(tmp_path):
    records = [{"doc_id": f"mur_{i}", "type": "murs"} for i in range(200)]
    captures, _, blobs = _legal_inputs(tmp_path, records=records, size=200)
    captures[0]["requestUrl"] += "&from_hit=0"
    assert len(list(_publish(tmp_path, "legal", captures, blobs).iter_records())) == 200


@pytest.mark.parametrize(
    "family,inputs,identity",
    [("legal", _legal_inputs, {"doc_id": "mur_1", "type": "murs"}), ("audit", _audit_inputs, {"audit_case_id": "1"})],
)
def test_duplicate_source_id_refuses_instead_of_collapsing(tmp_path, family, inputs, identity):
    captures, _, blobs = inputs(tmp_path, records=[identity, identity])
    with pytest.raises(ValueError, match="repeats"):
        _publish(tmp_path, family, captures, blobs)


@pytest.mark.parametrize("family,inputs", [("legal", _legal_inputs), ("audit", _audit_inputs)])
def test_missing_page_and_shrunk_capture_inventory_refuse(tmp_path, family, inputs):
    captures, _, blobs = inputs(tmp_path)
    pages = list(INTERFACES[family][2](captures, blob_source=blobs))
    with pytest.raises(ValueError, match="terminal"):
        _publish(tmp_path, family, captures, blobs, pages=pages[:-1])
    with pytest.raises(ValueError, match="continuation"):
        _publish(tmp_path, family, captures[:-1], blobs, pages=pages[:-1])
    assert not (tmp_path / "release").exists()


def test_audit_identity_is_case_id_and_categories_remain_nested(tmp_path):
    raw = json.loads((FIXTURES / "audit.json").read_bytes())
    # Explicitly synthetic success built from the retained row shape, not a source census.
    records = [raw["results"][0], {**raw["results"][0], "audit_case_id": "2287"}]
    captures, raw, blobs = _audit_inputs(tmp_path, records=records)
    reader = _publish(tmp_path, "audit", captures, blobs)
    _assert_source_reconstruction(reader, raw, captures)
    rows = {row["sourceRecordId"]: row["record"]["metadata"] for row in reader.iter_records()}
    assert set(rows) == {"2286", "2287"}
    assert rows["2286"]["audit_id"] == rows["2287"]["audit_id"] == 806
    assert rows["2286"]["primary_category_list"][0]["sub_category_list"][0]["sub_category_id"] == "0"


@pytest.mark.parametrize("identity", [None, 123, "", "x", "123\n", True])
def test_audit_native_case_identity_refuses_invalid_values(tmp_path, identity):
    captures, _, blobs = _audit_inputs(tmp_path, records=[{"audit_case_id": identity, "audit_id": 123}])
    with pytest.raises(ValueError, match="audit_case_id"):
        _publish(tmp_path, "audit", captures, blobs)


def test_retained_partial_audit_listing_cannot_publish(tmp_path):
    raw = (FIXTURES / "audit.json").read_bytes()
    # Synthetic credential-free descriptor; the original source bytes/counts are unchanged.
    capture = _capture(raw, "https://api.open.fec.gov/v1/audit-case/?per_page=1")
    blobs = LocalSourceNativeBlobStore(tmp_path / "originals")
    blobs.put_blob(capture["responseSha256"], len(raw), (raw,))
    with pytest.raises(ValueError, match="continuation"):
        _publish(tmp_path, "audit", [capture], blobs)
    assert not (tmp_path / "release").exists()


def test_audit_estimated_empty_is_not_complete(tmp_path):
    captures, _, blobs = _audit_inputs(
        tmp_path, records=[], change=lambda value: value["pagination"].update(is_count_exact=False)
    )
    with pytest.raises(ValueError, match="exact nonnegative publisher count"):
        _publish(tmp_path, "audit", captures, blobs)


def test_trailing_empty_legal_capture_is_not_part_of_the_declared_query(tmp_path):
    captures, originals, blobs = _legal_inputs(tmp_path)
    extra = json.loads(originals[-1])
    extra["murs"] = []
    raw = json.dumps(extra).encode()
    capture = _capture(raw, LEGAL_URL + "&from_hit=2")
    blobs.put_blob(capture["responseSha256"], len(raw), (raw,))
    with pytest.raises(ValueError, match="continuation"):
        _publish(tmp_path, "legal", [*captures, capture], blobs)
