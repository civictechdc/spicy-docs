"""One table contract, and the five value helpers every ``shape_*`` goes through.

``schemas/`` is a leaf: nothing here imports ``sources``, ``interpretation``,
pyarrow or DeltaTrack, so spicy-regs can import a column tuple without pulling
an HTTP client, a model client or a git dependency
(``docs/research/table-contracts-2026-09-19.md`` §1).  Everything a shaper
needs that would require one of those -- a referral vocabulary, a prompt frame,
a version-kind label -- arrives as an argument, named by the caller that owns
it.

``spicy_regs_public_tables.py``'s four module constants describe one table
well.  Twenty tables need one record, because every generic thing the layer
does -- proving identity is unique, proving every column is described,
generating spicy-regs's schema dict -- is then one loop rather than twenty
hand-written pairs.  :class:`TableContract` is still data and pure functions.

Shapers return a :data:`Row`: every value is a string or ``None``, because
spicy-regs publishes these as all-VARCHAR Parquet read through a DuckDB view.
A typed value is spelled exactly once, here, so ``True`` cannot reach one table
as ``"true"`` and another as ``"True"``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

#: One published row: the contract's columns, each already a string or NULL.
type Row = dict[str, str | None]

#: The separator a joined column uses.  ASCII unit separator, not a comma: a
#: committee name, a reason code and a referral signal can all contain a comma,
#: and the placement study names that collision on ``match_path`` specifically.
UNIT_SEPARATOR = "\x1f"

_SNAKE_CASE = re.compile(r"[a-z][a-z0-9_]*")


class TableContractError(ValueError):
    """A contract or a row does not satisfy the contract it claims."""


def text(value: object) -> str | None:
    """``None`` stays ``None``; anything else is spelled as one string.

    A ``bool`` is spelled the way :func:`flag` spells it rather than as
    ``"True"``, so one truth value has one spelling everywhere in the published
    data.  Lifted from ``schemas/federal_register.py``'s ``_text``, which is the
    same projection with the bool case left implicit.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def flag(value: bool | None) -> str | None:
    """A published boolean: ``"true"``, ``"false"`` or NULL for "not stated"."""
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TableContractError(f"flag takes a bool or None, not {type(value).__name__}")
    return "true" if value else "false"


def json_column(value: object) -> str:
    """One ``*_json`` column: compact, key-sorted JSON, so equal values compare equal.

    Never ``None``: an absent list is ``"[]"`` and an absent mapping ``"{}"``,
    which a caller states by passing the empty container.  A column that is
    genuinely unknown is a plain column with a NULL, not an empty JSON document.

    A value JSON cannot represent raises rather than being coerced, including
    nested NaN and infinities. Encoding value errors become
    :class:`TableContractError` so the family can retain a named row refusal.
    Unsupported object types keep the encoder's ``TypeError``. Some of
    these columns carry whatever an upstream engine recorded -- ``evidence_json``
    does -- and a ``repr`` published as if it were data is worse than a refusal
    that names the column.
    """
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except ValueError as error:
        raise TableContractError("JSON column contains a non-finite number or circular reference") from error


def read_json_column(value: str | None) -> object:
    """The inverse of :func:`json_column`, for a reader holding a published row."""
    return None if value is None else json.loads(value)


def joined(parts: Iterable[str]) -> str:
    """Join already-ordered parts with :data:`UNIT_SEPARATOR`."""
    return UNIT_SEPARATOR.join(parts)


def digest(value: str | None) -> str | None:
    """``sha256:`` plus the hex digest of ``value``'s UTF-8 bytes, or NULL.

    The same spelling ``transport.captured.CapturedBodyResponse.sha256`` uses,
    so a digest this layer computes and one a capture carries are comparable
    without either side being reformatted.
    """
    if value is None:
        return None
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TableContract:
    """One published table: its columns in publish order, its identity, its prose.

    ``name`` is the R2 object key, the MCP view name and this contract's key in
    :data:`TABLE_CONTRACTS`, all one snake_case string. ``version_column`` names
    the source or processing version carried by a row, not a universal sort
    order. Its description states the meaning: dates and explicitly ordered
    revisions can order comparable versions; rule digests support equality
    only. A host chooses which input generation supersedes another before
    merging. ``None`` means no version column is declared. See
    ``docs/tables.md`` for the host's fresh/prior precedence and digest limits.
    ``descriptions`` carries exactly one sentence per column and is what
    spicy-regs's data dictionary reads, so a column added here fails that check
    until the prose catches up (§5.3).
    """

    name: str
    columns: tuple[str, ...]
    identity: tuple[str, ...]
    version_column: str | None
    descriptions: Mapping[str, str]
    grain: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _SNAKE_CASE.fullmatch(self.name) is None:
            raise TableContractError(f"table name must be snake_case: {self.name!r}")
        if not self.columns:
            raise TableContractError(f"{self.name}: a table needs at least one column")
        seen = set()
        for column in self.columns:
            if _SNAKE_CASE.fullmatch(column) is None:
                raise TableContractError(f"{self.name}: column names must be snake_case: {column!r}")
            if column in seen:
                raise TableContractError(f"{self.name}: duplicate column {column!r}")
            seen.add(column)
        if not self.identity:
            raise TableContractError(f"{self.name}: a table needs an identity")
        for column in self.identity:
            if column not in seen:
                raise TableContractError(f"{self.name}: identity column {column!r} is not a column")
        if len(set(self.identity)) != len(self.identity):
            raise TableContractError(f"{self.name}: duplicate identity column")
        if self.version_column is not None and self.version_column not in seen:
            raise TableContractError(f"{self.name}: version column {self.version_column!r} is not a column")
        if set(self.descriptions) != seen:
            missing = sorted(seen - set(self.descriptions))
            extra = sorted(set(self.descriptions) - seen)
            raise TableContractError(
                f"{self.name}: descriptions must be keyed by columns; missing {missing}, extra {extra}"
            )
        for column, sentence in self.descriptions.items():
            if not isinstance(sentence, str) or not sentence.strip():
                raise TableContractError(f"{self.name}: column {column!r} needs a description")
        if not isinstance(self.grain, str) or not self.grain.strip():
            raise TableContractError(f"{self.name}: a table needs a one-sentence grain")
        object.__setattr__(self, "descriptions", MappingProxyType(dict(self.descriptions)))

    def key(self, row: Row) -> tuple[str, ...]:
        """This row's identity tuple; a NULL part refuses rather than keying on ``None``.

        A row that cannot be keyed is a row a merge cannot deduplicate and a
        child table cannot point at.  The caller turns the refusal into a named
        refusal record rather than letting the row through unidentified.
        """
        parts: list[str] = []
        for column in self.identity:
            if column not in row:
                raise TableContractError(f"{self.name}: row is missing identity column {column!r}")
            value = row[column]
            if value is None:
                raise TableContractError(f"{self.name}: identity column {column!r} is null")
            parts.append(value)
        return tuple(parts)

    def checked(self, row: Row) -> Row:
        """Prove one shaped row against this contract, and return it unchanged.

        The single place a ``shape_*`` output is held to its column tuple: same
        column set, every value a string or NULL.  Order is not normalised here,
        so a test that asserts publish order is asserting something this did not
        already arrange. Identity is checked separately by :meth:`key`.
        Logical value types are not declared here: this does not infer JSON,
        date, boolean or numeric validation from a column name or description.
        """
        if not isinstance(row, dict):
            raise TableContractError(f"{self.name}: a row must be a dict")
        columns = set(self.columns)
        keys = set(row)
        if keys != columns:
            missing = sorted(columns - keys)
            extra = sorted(keys - columns)
            raise TableContractError(f"{self.name}: row columns differ; missing {missing}, unexpected {extra}")
        for column, value in row.items():
            if value is not None and not isinstance(value, str):
                raise TableContractError(f"{self.name}: column {column!r} is {type(value).__name__}, not str or None")
        return row


def table_contract(
    name: str,
    *,
    grain: str,
    identity: tuple[str, ...],
    version_column: str | None,
    columns: Mapping[str, str],
) -> TableContract:
    """Build a contract from one ordered ``column -> description`` mapping.

    Publish order is the mapping's own order, so a column and the sentence that
    describes it are written once, side by side, and cannot drift apart.
    """
    return TableContract(
        name=name,
        columns=tuple(columns),
        identity=identity,
        version_column=version_column,
        descriptions=columns,
        grain=grain,
    )


def natural_key(congress: object, kind: object, number: object) -> str:
    """``{congress}-{kind}-{number}`` with the kind lowercased: one spelling for every Congress.gov key.

    A bill, an amendment and a communication are all addressed this way by the
    publisher, and a foreign-key column pointing at any of them has to spell
    the key exactly as the target table does.
    """
    return f"{congress}-{str(kind).lower()}-{number}"


def bill_id(identity: object) -> str:
    """``{congress}-{bill_type}-{number}``, the natural key every bill table shares.

    ``identity`` is any record carrying ``congress``, ``bill_type`` and
    ``number`` -- ``sources.congress.bill_status.BillIdentity`` is the one this
    layer is given, read by attribute so this module stays a leaf.
    """
    return natural_key(identity.congress, identity.bill_type, identity.number)


__all__ = [
    "UNIT_SEPARATOR",
    "Row",
    "TableContract",
    "TableContractError",
    "bill_id",
    "digest",
    "flag",
    "joined",
    "json_column",
    "natural_key",
    "read_json_column",
    "table_contract",
    "text",
]
