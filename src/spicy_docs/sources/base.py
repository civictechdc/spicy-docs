"""Base interface for acquisition readers.

Subclass `Reader` to add a connector that pulls records from an external
system (S3 bucket, REST API, scraped HTML, etc.). Source-native publication
uses `SourceNativeProfile` and the shared release publisher.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator


class Reader(ABC):
    """A connector that reads records from an external system.

    Subclasses configure connection details via ``__init__`` and yield
    records (dicts) from ``iter_records``. Pagination, batching, retries,
    and dedup semantics are the subclass's responsibility.

    Subclasses that pull from a keyed source (S3 keys, URLs, file paths)
    should populate ``last_keys`` during ``iter_records`` with the keys
    *successfully* consumed, so the caller can append them to a manifest.
    Keys that were attempted but failed go on ``failed_keys`` instead — the
    caller must NOT manifest these, so the next run retries them. Both default
    to empty lists for sources without addressable keys.
    """

    def __init__(self) -> None:
        self.last_keys: list[str] = []
        self.failed_keys: list[str] = []

    @abstractmethod
    def iter_records(self) -> Iterator[dict]: ...
