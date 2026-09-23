"""The :class:`TableContract` record every published table declares, and the value helpers every ``shape_*`` row goes
through.

The package is a stdlib-only leaf (``docs/research/table-contracts-2026-09-19.md`` §1), so anything a shaper needs from
``sources`` or ``interpretation`` -- a referral vocabulary, a prompt frame, a version-kind label -- arrives as a
caller-named argument.  A ``Row`` holds only strings or NULL, because spicy-regs publishes these as all-VARCHAR Parquet
read through a DuckDB view.
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
    """``None`` stays ``None``; anything else is spelled as one string, a ``bool`` as ``"true"``/``"false"`` so one
    truth value has one spelling in the published data.

    Lifted from ``schemas/federal_register.py``'s ``_text``, the same projection with the bool case left implicit.
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
    """One ``*_json`` column: compact, key-sorted JSON so equal values compare equal, never ``None`` -- an absent list
    is ``"[]"`` and an absent mapping ``"{}"``, which the caller states by passing the empty container.

    A value JSON cannot represent raises rather than being coerced, including nested NaN and infinities: encoding value
    errors become :class:`TableContractError` for a named row refusal while unsupported object types keep the encoder's
    ``TypeError``.  A ``repr`` published as if it were data is worse than either refusal.
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
    """One published table: its columns in publish order, its identity, its version column and one sentence per column.

    ``name`` is the R2 object key, the MCP view name and this contract's key in :data:`TABLE_CONTRACTS`, all one
    snake_case string. ``version_column`` names the source or processing version a row carries, not a universal sort
    order, and ``None`` means none is declared: dates and explicitly ordered revisions can order, rule digests support
    equality only, and a host chooses which input generation supersedes another before merging. ``descriptions`` is what
    spicy-regs's data dictionary reads, so a column added here fails that check until the prose catches up (§5.3).

    Construction refuses a non-snake_case name or column, a duplicate column, an empty identity, an identity or version
    column that is not a column, and a description set not keyed exactly by the columns.
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
        """Prove one shaped row has exactly this contract's columns, each a string or NULL, and return it unchanged.

        Order is not normalised here, so a test that asserts publish order is asserting something this did not already
        arrange; identity is checked separately by :meth:`key`, and no logical type is inferred from a column name or
        description.
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


#: Every dash a U.S. Code section is printed with: hyphen, non-breaking hyphen, figure dash, en dash, em dash,
#: horizontal bar, minus sign, and the Windows-1252 en and em dash bytes a bad decode leaves as C1 controls.  The same
#: nine characters RefSpec's section oracle folds (``usc_section_oracle._DASHES``).
DASH_SPELLINGS = "‐‑‒–—―−\x96\x97"
_DASH_TO_HYPHEN = str.maketrans(dict.fromkeys(DASH_SPELLINGS, "-"))


def usc_section_key(section: object) -> str | None:
    """A U.S. Code section as a join key: trimmed, lower-cased, and every dash spelling an ASCII hyphen.

    Case carries no identity in the Code, but the publishers disagree on it. The classification tables print ``199A``
    and ``1400Z-1``, where RefSpec's oracle keys ``199a`` and ``1400z-1``. The release point also spells a compound
    section with an en dash where the tables print a hyphen. This is RefSpec's ``normalize_section``, restated in this
    leaf so a shaper and a citation reader fold one way; B4's grammar adopts it. ``None`` stays ``None``.
    See ``docs/decisions.md``, "U.S. Code section join keys are lower-cased on both sides".
    """
    if section is None:
        return None
    return str(section).strip().lower().translate(_DASH_TO_HYPHEN)


__all__ = [
    "DASH_SPELLINGS",
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
    "usc_section_key",
]
