"""Admitted public-table locations and exact Parquet member reading."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from rulespec_artifacts import (
    ArtifactPin,
    LocalMemberSource,
    MemberSource,
    admit_artifact,
)

from spicy_docs.public_tables.format import (
    PublicTableError,
    _member_position,
)
from spicy_docs.public_tables.profiles import PublicTableProfile
from spicy_docs.public_tables.verify import (
    _validate_root,
    verify_public_table_admission,
)


class PublicTableArtifactLocation:
    """Bind admission and member reads to one exact artifact location.

    A local location admits and reads the same directory.  A remote location
    admits an exact distribution through its injected ``MemberSource`` and
    resolves data below bases whose final path is the admitted Rulespec
    artifact digest, written as ``sha256/<hex>``.
    """

    def __init__(
        self,
        *,
        source: MemberSource,
        expected_pin: ArtifactPin,
        local_root: Path | None = None,
        duckdb_base_uri: str | None = None,
    ) -> None:
        local = Path(local_root).absolute() if local_root is not None else None
        if (local is None) == (duckdb_base_uri is None):
            raise PublicTableError("public-table location must be exactly one local or remote artifact")
        self.source = source
        self.expected_pin = expected_pin
        self._local_root = local
        self._duckdb_base_uri = (
            _content_addressed_base(
                duckdb_base_uri,
                expected_pin=expected_pin,
            )
            if duckdb_base_uri is not None
            else None
        )

    @classmethod
    def local(
        cls,
        root: Path,
        *,
        expected_pin: ArtifactPin,
    ) -> PublicTableArtifactLocation:
        selected = Path(root).absolute()
        return cls(
            source=LocalMemberSource(selected),
            expected_pin=expected_pin,
            local_root=selected,
        )

    @classmethod
    def content_addressed_remote(
        cls,
        source: MemberSource,
        *,
        expected_pin: ArtifactPin,
        duckdb_base_uri: str,
    ) -> PublicTableArtifactLocation:
        return cls(
            source=source,
            expected_pin=expected_pin,
            duckdb_base_uri=duckdb_base_uri,
        )

    def duckdb_member(self, object_key: str) -> str:
        """One member's absolute local path or content-addressed DuckDB URI."""

        if self._local_root is not None:
            return str(self._local_member(object_key))
        assert self._duckdb_base_uri is not None
        return f"{self._duckdb_base_uri}/{quote(object_key, safe='/=._-')}"

    def _local_member(self, object_key: str) -> Path:
        assert self._local_root is not None
        path = (self._local_root / object_key).absolute()
        if not path.is_relative_to(self._local_root):
            raise PublicTableError("public-table member escapes its local artifact")
        return path


def _content_addressed_base(
    value: str,
    *,
    expected_pin: ArtifactPin,
) -> str:
    """Require a clean https or loopback base URI ending in the admitted ``sha256/<hex>`` digest."""

    selected = value.rstrip("/")
    parsed = urlparse(selected)
    scheme_allowed = parsed.scheme == "https"
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        scheme_allowed = True
    digest = expected_pin.artifact_digest
    digest_hex = digest.removeprefix("sha256:")
    path_parts = parsed.path.rstrip("/").split("/")
    if (
        not scheme_allowed
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or re.fullmatch(r"[0-9a-f]{64}", digest_hex) is None
        or path_parts[-2:] != ["sha256", digest_hex]
    ):
        raise PublicTableError("DuckDB base must be a clean content-addressed artifact URI")
    return selected


class PublicTableReader:
    """Admit one public table and expose its exact Parquet members."""

    def __init__(
        self,
        location: PublicTableArtifactLocation,
        *,
        profile: PublicTableProfile,
        accepted_verifier_implementation_ids: frozenset[str],
    ) -> None:
        if not accepted_verifier_implementation_ids:
            raise PublicTableError("at least one public-table verifier must be accepted")
        self._profile = profile
        self._location = location
        source = location.source
        self._artifact = admit_artifact(
            source,
            expected_pin=location.expected_pin,
            semantic_verifier=lambda artifact, source: verify_public_table_admission(
                artifact,
                source,
                profile=profile,
            ),
        )
        producer = self._artifact.root["producer"]
        if producer["verifierImplementationId"] not in accepted_verifier_implementation_ids:
            raise PublicTableError("public-table verifier implementation is not accepted")
        spec, members = _validate_root(self._artifact, source, profile=profile)
        self._members = tuple(
            sorted(
                members,
                key=lambda member: _member_position(str(member.object_key), profile=profile),
            )
        )
        source_input = self._artifact.root["inputs"][0]
        self.source_pin = ArtifactPin(
            logical_id=str(source_input["logicalId"]),
            artifact_digest=str(source_input["artifactDigest"]),
        )
        self.source_state_digest = str(spec["sourceStateDigest"])
        self.source_state_scope = str(spec["sourceStateScope"])

    @property
    def pin(self) -> ArtifactPin:
        return self._artifact.pin

    @property
    def table_name(self) -> str:
        return self._profile.table_name

    @property
    def columns(self) -> tuple[str, ...]:
        return self._profile.columns

    @property
    def object_keys(self) -> tuple[str, ...]:
        return tuple(str(member.object_key) for member in self._members)

    @property
    def duckdb_member_locations(self) -> tuple[str, ...]:
        return tuple(self._location.duckdb_member(object_key) for object_key in self.object_keys)

    def duckdb_relation(
        self,
        connection: Any,
    ) -> Any:
        """Return DuckDB's native Parquet relation over exact admitted members."""

        locations = list(self.duckdb_member_locations)
        if len(locations) != len(set(locations)) or any(not value for value in locations):
            raise PublicTableError("public-table member locations are empty or repeated")
        return connection.from_parquet(
            locations,
            hive_partitioning=bool(self._profile.partition_columns),
            union_by_name=False,
        )
