"""Retained Regulations.gov comment value in the source-native product.

Pins raw-field preservation, newest-version selection with a refused tie, fail-closed schema drift, ASCII-sorted
distinct records, and the CLI/import boundary."""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from rulespec_artifacts import LocalMemberSource, Producer

from spicy_docs.cli.source_native import main as source_native_main
from spicy_docs.source_native import (
    SourceNativeReleaseBuild,
    SourceNativeReleaseError,
    SourceNativeReleasePublisher,
    SourceNativeReleaseReader,
    verify_source_native_release,
)
from spicy_docs.source_native.profiles import REGULATIONS_GOV_COMMENT_PROFILE
from spicy_docs.source_native.regulations_gov import (
    COMMENT_COLLECTION,
    COMMENT_SOURCE_SYSTEM_ID,
    RegulationsGovSourceError,
    classify_comment,
    comment_rendition_rows,
    comment_source_issued_version,
    iter_regulations_gov_comment_pages,
)
from spicy_docs.storage.blobs import LocalSourceNativeBlobStore

_IMPLEMENTATION_ID = "git+https://example.test/spicy-docs@" + "a" * 40
_PRODUCER = Producer(
    product="spicy-docs",
    implementation_id=_IMPLEMENTATION_ID,
    verifier_id="urn:spicy-regs:source-native-release-verifier",
    verifier_version="2.0",
    verifier_implementation_id=_IMPLEMENTATION_ID,
)


def _completed_at() -> datetime:
    return datetime(2026, 8, 25, 0, 0, 1, tzinfo=UTC)


def _comment(
    identity: str = "EPA-2026-0001-0001",
    *,
    modify_date: str | None = "2026-08-25T01:02:03Z",
    body: str = "Exact public comment",
) -> dict[str, Any]:
    return {
        "data": {
            "attributes": {
                "agencyId": "EPA",
                "comment": body,
                "commentOn": "source-object",
                "commentOnDocumentId": "EPA-2026-0001-0000",
                "displayProperties": [{"label": "Page Count", "name": "pageCount", "tooltip": None}],
                "docketId": "EPA-2026-0001",
                "documentType": "Public Submission",
                "duplicateComments": 0,
                "fileFormats": [
                    {
                        "fileUrl": f"https://downloads.regulations.gov/{identity}/comment.txt",
                        "format": "txt",
                        "size": 42,
                    }
                ],
                "modifyDate": modify_date,
                "openForComment": False,
                "pageCount": 1,
                "postedDate": "2026-08-24T04:00:00Z",
                "trackingNbr": "tracking-1",
                "withdrawn": False,
            },
            "id": identity,
            "links": {"self": f"https://api.regulations.gov/v4/comments/{identity}"},
            "relationships": {
                "attachments": {
                    "data": [{"id": f"{identity}-attachment", "type": "attachments"}],
                    "links": {
                        "related": f"https://api.regulations.gov/v4/comments/{identity}/attachments",
                        "self": f"https://api.regulations.gov/v4/comments/{identity}/relationships/attachments",
                    },
                }
            },
            "type": COMMENT_COLLECTION,
        },
        "included": [
            {
                "attributes": {
                    "agencyNote": None,
                    "authors": ["Exact source author"],
                    "docAbstract": None,
                    "docOrder": 1,
                    "fileFormats": [
                        {
                            "fileUrl": f"https://downloads.regulations.gov/{identity}/attachment.pdf",
                            "format": "pdf",
                            "size": 123,
                        }
                    ],
                    "modifyDate": "2026-08-24T05:00:00Z",
                    "publication": None,
                    "restrictReason": None,
                    "restrictReasonType": None,
                    "title": "Exact attachment title",
                },
                "id": f"{identity}-attachment",
                "type": "attachments",
            }
        ],
    }


@dataclass(frozen=True, slots=True)
class _Object:
    key: str
    etag: str
    version_id: str | None
    content: bytes


class _Reader:
    def __init__(self, objects: list[_Object]) -> None:
        self.objects = objects

    def iter_source_objects(self, *, max_bytes: int) -> Iterator[_Object]:
        assert max_bytes == 16 * 1024 * 1024
        yield from self.objects


def _object(
    identity: str,
    *,
    tag: str,
    record: dict[str, Any] | None = None,
) -> _Object:
    content = json.dumps(
        record or _comment(identity),
        indent=2,
    ).encode()
    return _Object(
        key=(f"raw-data/EPA/EPA-2026-0001/text-{tag}/comments/{identity}.json"),
        etag=f'"{tag}-etag"',
        version_id=f"{tag}-version",
        content=content,
    )


def _scope() -> dict[str, object]:
    return {
        "agencies": ["EPA"],
        "postedFrom": "2026-08-24",
        "postedThrough": "2026-08-24",
    }


def _publish(tmp_path: Path, objects: list[_Object], name: str = "comments"):
    return SourceNativeReleasePublisher(
        REGULATIONS_GOV_COMMENT_PROFILE,
        blob_store=LocalSourceNativeBlobStore(tmp_path / "blobs"),
        clock=_completed_at,
    ).publish(
        iter_regulations_gov_comment_pages(
            lambda agency: (
                _Reader(sorted(objects, key=lambda item: item.key)) if agency == "EPA" else pytest.fail(agency)
            ),
            query_scope=_scope(),
        ),
        build=SourceNativeReleaseBuild(
            query_scope=_scope(),
            producer=_PRODUCER,
            started_at="2026-08-25T00:00:00Z",
        ),
        destination=tmp_path / name,
    )


def _reader(root: Path, pin) -> SourceNativeReleaseReader:
    return SourceNativeReleaseReader(
        LocalMemberSource(root),
        blob_source=LocalSourceNativeBlobStore(root.parent / "blobs"),
        profile=REGULATIONS_GOV_COMMENT_PROFILE,
        expected_pin=pin,
        accepted_verifier_implementation_ids=frozenset({_IMPLEMENTATION_ID}),
    )


def test_comment_raw_fields_and_every_attachment_rendition_are_preserved() -> None:
    """The raw comment passes through unshaped, its modifyDate is its issued version, and the
    comment's and the attachment's file formats each yield a rendition row."""
    raw = _comment()

    assert classify_comment(raw) == raw
    assert comment_source_issued_version(raw) == "2026-08-25T01:02:03Z"
    rows = comment_rendition_rows(raw)
    assert [row["sourceField"] for row in rows] == [
        "data.attributes.fileFormats[0]",
        "included[0].attributes.fileFormats[0]",
    ]
    assert [row["mediaType"] for row in rows] == ["text/plain", "application/pdf"]
    assert [row["expectedByteSize"] for row in rows] == [42, 123]


def test_comment_json_types_survive_publication_and_retained_replay(tmp_path: Path) -> None:
    """JSON and unknown-format attachments publish and replay byte-equal with media types
    assigned, under acquisition policy 1.3, and the release verifies."""
    raw = _comment()
    raw["data"]["attributes"]["fileFormats"] = [
        {"fileUrl": "https://example.test/data.json#table", "format": None},
        {"fileUrl": "https://example.test/path.xml/child", "format": None},
    ]
    raw["included"][0]["attributes"]["fileFormats"] = [
        {"fileUrl": "https://example.test/download", "format": "JSON"},
    ]
    published = _publish(tmp_path, [_object("EPA-2026-0001-0001", tag="json", record=raw)])
    reader = _reader(published.root, published.artifact.pin)
    assert next(iter(reader.iter_records()))["record"] == raw
    rows = {row["sourceField"]: row for row in reader.iter_renditions()}
    assert rows["data.attributes.fileFormats[0]"]["mediaType"] == "application/json"
    assert rows["data.attributes.fileFormats[1]"]["mediaType"] == "application/octet-stream"
    assert rows["included[0].attributes.fileFormats[0]"]["mediaType"] == "application/json"
    assert reader.collection_outcome["acquisitionPolicyVersion"] == "1.3"
    verify_source_native_release(
        published.artifact,
        LocalMemberSource(published.root),
        profile=REGULATIONS_GOV_COMMENT_PROFILE,
        blob_source=LocalSourceNativeBlobStore(tmp_path / "blobs"),
    )


def test_complete_enumeration_selects_newest_comment_version_and_counts_discard(
    tmp_path: Path,
) -> None:
    """Two observations of one comment publish only the newest, and the receipt counts both
    discovered and the one discarded observation."""
    identity = "EPA-2026-0001-0001"
    older = _comment(identity, modify_date="2026-08-24T10:00:00Z", body="older")
    newer = _comment(identity, modify_date="2026-08-25T10:00:00Z", body="newer")
    published = _publish(
        tmp_path,
        [
            _object(identity, tag="older", record=older),
            _object(identity, tag="newer", record=newer),
        ],
    )
    reader = _reader(published.root, published.artifact.pin)

    assert reader.source_system_id == COMMENT_SOURCE_SYSTEM_ID
    assert reader.source_state_scope == "complete-snapshot"
    assert [row["record"]["data"]["attributes"]["comment"] for row in reader.iter_records()] == ["newer"]
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert receipt["discoveredRecordCount"] == 2
    assert receipt["inputObservationCount"] == 2
    assert receipt["publishedRecordCount"] == 1
    assert receipt["discardedObservationCount"] == 1
    assert receipt["acquisitionEvidenceCount"] == 1
    assert not (published.root / "evidence").exists()


def test_nonnull_modify_date_wins_and_single_null_version_remains_valid(
    tmp_path: Path,
) -> None:
    """A dated modifyDate outranks a null one, and a comment whose only version is null still publishes."""
    identity = "EPA-2026-0001-0001"
    null_version = _comment(identity, modify_date=None, body="null")
    exact_version = _comment(identity, modify_date="2026-08-25T10:00:00Z", body="dated")
    published = _publish(
        tmp_path,
        [
            _object(identity, tag="null", record=null_version),
            _object(identity, tag="dated", record=exact_version),
        ],
    )
    rows = list(_reader(published.root, published.artifact.pin).iter_records())
    assert rows[0]["record"]["data"]["attributes"]["comment"] == "dated"

    only_null = _publish(
        tmp_path,
        [
            _object(
                "EPA-2026-0001-0002",
                tag="only-null",
                record=_comment(
                    "EPA-2026-0001-0002",
                    modify_date=None,
                ),
            )
        ],
        name="only-null",
    )
    null_rows = list(_reader(only_null.root, only_null.artifact.pin).iter_records())
    assert null_rows[0]["record"]["data"]["attributes"]["modifyDate"] is None


@pytest.mark.parametrize(
    ("first_version", "second_version", "first_body", "second_body"),
    [
        ("2026-08-25T10:00:00Z", "2026-08-25T06:00:00-04:00", "first", "second"),
        (None, None, "first null", "second null"),
        ("2026-08-25T10:00:00Z", "2026-08-25T10:00:00Z", "first", "second"),
    ],
)
def test_differing_comments_at_one_normalized_version_refuse_a_tie(
    tmp_path: Path,
    first_version: str | None,
    second_version: str | None,
    first_body: str,
    second_body: str,
) -> None:
    """Differing comments at one normalized instant -- an offset spelling, two nulls, or the
    same string twice -- refuse the release with a source-version tie."""
    identity = "EPA-2026-0001-0001"
    first = _comment(identity, modify_date=first_version, body=first_body)
    second = _comment(identity, modify_date=second_version, body=second_body)

    with pytest.raises(SourceNativeReleaseError, match="source-version tie"):
        _publish(
            tmp_path,
            [
                _object(identity, tag="first", record=first),
                _object(identity, tag="second", record=second),
            ],
        )


def test_identical_comments_at_one_version_are_one_observation(tmp_path: Path) -> None:
    """Mirrulations refetch files ``<id>(1).json``: 23 such ties among ACF comments, all byte-identical."""
    identity = "EPA-2026-0001-0001"
    record = _comment(identity, modify_date="2026-08-25T10:00:00Z", body="identical")
    published = _publish(
        tmp_path,
        [_object(identity, tag="first", record=record), _object(identity, tag="second", record=record)],
    )
    rows = list(_reader(published.root, published.artifact.pin).iter_records())
    assert [row["record"]["data"]["attributes"]["comment"] for row in rows] == ["identical"]
    receipt = json.loads((published.root / "receipts/publication.json").read_bytes())
    assert (receipt["publishedRecordCount"], receipt["discardedObservationCount"]) == (1, 1)


@pytest.mark.parametrize("location", ["comment", "attachment"])
def test_comment_schema_drift_fails_closed(location: str) -> None:
    """An unrecognized field, on the comment or its attachment, fails closed naming the field."""
    raw = deepcopy(_comment())
    if location == "comment":
        raw["data"]["attributes"]["newSourceField"] = "unclassified"
    else:
        raw["included"][0]["attributes"]["newSourceField"] = "unclassified"

    with pytest.raises(RegulationsGovSourceError, match="unclassified"):
        classify_comment(raw)


def test_comment_release_records_are_ascii_sorted_and_distinct(tmp_path: Path) -> None:
    """Published records come out ASCII-sorted and distinct however their objects arrived."""
    objects = [
        _object("EPA-2026-0001-0003", tag="z"),
        _object("EPA-2026-0001-0001", tag="x"),
        _object("EPA-2026-0001-0002", tag="y"),
    ]
    published = _publish(tmp_path, list(reversed(objects)))

    identities = [row["sourceRecordId"] for row in _reader(published.root, published.artifact.pin).iter_records()]
    assert identities == sorted(set(identities))


def test_comment_profile_is_available_through_the_single_injected_cli(
    tmp_path: Path,
) -> None:
    """The CLI publishes the comment release through one injected reader and asks only for the
    comments collection."""
    release = tmp_path / "cli-comments"
    output = StringIO()
    observed_collections: list[str] = []

    def read(agency: str, collection: str) -> _Reader:
        assert agency == "EPA"
        observed_collections.append(collection)
        return _Reader([_object("EPA-2026-0001-0001", tag="cli")])

    instants = iter(
        [
            datetime.fromisoformat("2026-08-25T00:00:00+00:00"),
            datetime.fromisoformat("2026-08-25T00:00:01+00:00"),
        ]
    )
    exit_code = source_native_main(
        [
            "publish",
            "--source",
            "regulations-comments",
            "--since",
            "2026-08-24",
            "--until",
            "2026-08-24",
            "--agency",
            "EPA",
            "--destination",
            str(release),
            "--blob-store",
            str(tmp_path / "blobs"),
            "--implementation-id",
            _IMPLEMENTATION_ID,
        ],
        read_regulations=read,
        clock=lambda: next(instants),
        stdout=output,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert observed_collections == [COMMENT_COLLECTION]
    assert json.loads(output.getvalue())["source"] == "regulations-comments"


def test_comment_source_native_boundary_has_no_sibling_product_imports() -> None:
    """No releases, regulations_gov or source-native module imports a sibling product's package
    (docspec, refspec, spicysearch)."""
    repository = Path(__file__).resolve().parents[1]
    imported: set[str] = set()
    for relative in (
        *repository.glob("src/spicy_docs/releases/*.py"),
        *repository.glob("src/spicy_docs/sources/regulations_gov/*.py"),
        *repository.glob("src/spicy_docs/source_native/*.py"),
        *repository.glob("src/spicy_docs/source_native_*.py"),
        *repository.glob("src/spicy_docs/*_source_native.py"),
    ):
        tree = ast.parse((repository / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)

    assert not {name for name in imported if name.startswith(("docspec", "refspec", "spicysearch"))}
