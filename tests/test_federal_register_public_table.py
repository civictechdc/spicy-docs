"""Current Federal Register identity survives native-to-public publication."""

import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest
from rulespec_artifacts import ArtifactPin

pytest.importorskip("pyarrow.parquet")

from spicy_docs.cli.source_native import main
from spicy_docs.public_tables.api import PublicTableBuild, PublicTableError, PublicTablePublisher
from spicy_docs.public_tables.profiles import (
    FEDERAL_REGISTER_PUBLIC_TABLE,
    PublicTableProjectionError,
)
from spicy_docs.schemas.federal_register import FEDERAL_REGISTER_COLUMNS
from tests.releases.fixtures import IMPLEMENTATION_ID, _document, _publish, _reader, _stable_pages
from tests.test_public_table import _PUBLIC_PRODUCER, _public_reader, _source_row, _SourceStub


def test_cli_projects_current_native_identity_without_losing_reused_numbers(tmp_path: Path, capsys) -> None:
    scope = {"publishedFrom": "2000-01-14", "publishedThrough": "2000-01-18"}
    documents = [
        _document("00-111", publication_date="2000-01-14", title="Older rule"),
        _document("00-111", publication_date="2000-01-18", title="Later notice"),
    ]
    source = _publish(tmp_path, _stable_pages(*documents, window=scope), query_scope=scope)
    native = _reader(source.root, source.artifact.pin)
    assert [row["sourceRecordId"] for row in native.iter_records()] == ["00-111@2000-01-14", "00-111@2000-01-18"]
    destination = tmp_path / "public"
    assert (
        main(
            [
                "publish-public-table",
                "--table",
                "federal-register",
                "--source-release",
                str(source.root),
                "--source-blob-store",
                str(tmp_path / "blobs"),
                "--source-accepted-verifier-implementation-id",
                IMPLEMENTATION_ID,
                "--destination",
                str(destination),
                "--implementation-id",
                IMPLEMENTATION_ID,
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    pin = ArtifactPin(receipt["logicalId"], receipt["artifactDigest"])
    reader = _public_reader(destination, FEDERAL_REGISTER_PUBLIC_TABLE, pin)
    with duckdb.connect() as connection:
        rows = reader.duckdb_relation(connection).pl().to_dicts()
    assert reader.columns == FEDERAL_REGISTER_COLUMNS
    assert [(row["document_number"], row["publication_date"], row["title"]) for row in rows] == [
        ("00-111", "2000-01-14", "Older rule"),
        ("00-111", "2000-01-18", "Later notice"),
    ]
    spec = json.loads((destination / "artifact.json").read_bytes())["spec"]
    assert spec["primaryKey"] == ["document_number", "publication_date"]
    assert spec["projectionVersion"] == "1.1"


def test_current_projection_refuses_a_wrong_source_identity() -> None:
    profile = FEDERAL_REGISTER_PUBLIC_TABLE
    with pytest.raises(PublicTableProjectionError, match="source record identity"):
        profile.project(_source_row(profile, "2026-00001", _document()))


def test_compound_public_key_still_refuses_duplicate_pairs(tmp_path: Path) -> None:
    profile = FEDERAL_REGISTER_PUBLIC_TABLE
    row = _source_row(profile, "2026-00001@2026-08-25", _document())
    with pytest.raises(PublicTableError, match="repeats primary key"):
        PublicTablePublisher(profile).publish(
            _SourceStub(profile, [row, row]),
            build=PublicTableBuild(_PUBLIC_PRODUCER),
            destination=tmp_path / "public",
        )
    assert not (tmp_path / "public").exists()


def test_compound_key_encoding_preserves_column_boundaries() -> None:
    profile = FEDERAL_REGISTER_PUBLIC_TABLE
    assert profile.row_key({"document_number": "a@b", "publication_date": "c"}) != profile.row_key(
        {"document_number": "a", "publication_date": "b@c"}
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"primary_key": ()},
        {"primary_key": ("document_number", "document_number")},
        {"primary_key": ("document_number", "missing")},
        {"sort_columns": ("document_number",)},
        {"source_record_id": None},
    ],
)
def test_compound_key_requires_a_complete_explicit_profile(changes) -> None:
    with pytest.raises(PublicTableError):
        PublicTablePublisher(replace(FEDERAL_REGISTER_PUBLIC_TABLE, **changes))


def test_compound_key_requires_every_value() -> None:
    with pytest.raises(PublicTableProjectionError, match="primary key is empty"):
        FEDERAL_REGISTER_PUBLIC_TABLE.row_key({"document_number": "00-111", "publication_date": None})
