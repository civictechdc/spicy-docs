"""Read only small identity fields while scanning the complete source XML."""

from __future__ import annotations

from ..xml import scan_xml
from .models import CfrSourceError, _limit


class IdentityXmlScan:
    """Keep bounded ancestry and selected scalar fields, never a document tree."""

    def __init__(self, fields: set[tuple[str, ...]]) -> None:
        self.fields = fields
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.values: dict[tuple[str, ...], list[str]] = {}
        self._active: list[tuple[tuple[str, ...], list[str]]] = []
        self._field_characters = 0
        self.root = ""
        self.body_found = False

    @property
    def path(self) -> tuple[str, ...]:
        return tuple(tag for tag, _attrs in self.stack)

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        self.stack.append((tag, attributes))
        if len(self.stack) == 1:
            self.root = tag
        if self.path in self.fields:
            if sum(map(len, self.values.values())) + len(self._active) >= 256:
                raise CfrSourceError("CFR XML repeats too many identity fields")
            self._active.append((self.path, []))
        self.observe_start(tag, attributes)

    def data(self, text: str) -> None:
        for _path, parts in self._active:
            self._field_characters += len(text)
            if self._field_characters > 64 * 1024:
                raise CfrSourceError("CFR XML identity fields exceed 65,536 characters")
            parts.append(text)
        self.observe_text(text)

    def end(self, tag: str) -> None:
        if self._active and self._active[-1][0] == self.path:
            path, parts = self._active.pop()
            self.values.setdefault(path, []).append("".join(parts))
        self.observe_end(tag)
        self.stack.pop()

    def observe_start(self, tag: str, attributes: dict[str, str]) -> None:
        pass

    def observe_text(self, text: str) -> None:
        pass

    def observe_end(self, tag: str) -> None:
        pass

    def field(self, path: tuple[str, ...], *, required: bool = False) -> str | None:
        values = self.values.get(path, [])
        if len(values) > 1:
            raise CfrSourceError("CFR XML repeats an identity field: " + "/".join(path))
        value = values[0] if values else None
        if value is None or not value.strip():
            if required:
                raise CfrSourceError("CFR XML lacks an identity field: " + "/".join(path))
            return None
        return value

    def read(self, body: bytes, max_bytes: int) -> None:
        _limit(max_bytes)
        scan_xml(
            body,
            start=self.start,
            end=self.end,
            data=self.data,
            max_bytes=max_bytes,
            error_type=CfrSourceError,
            label="CFR XML",
        )
