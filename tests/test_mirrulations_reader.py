"""Tests for MirrulationsReader using a fake in-memory S3 resource."""

from collections.abc import Iterable
from json import dumps

import pytest
from botocore.exceptions import ClientError

from spicy_docs.schemas import COMMENT, DOCKET, DOCUMENT, RECORD_TYPES, RecordType
from spicy_docs.sources.mirrulations import MirrulationsReader

BUCKET = "mirrulations"
PREFIX = "raw-data"
AGENCY = "EPA"


def _docket_payload(docket_id: str) -> dict:
    return {
        "data": {
            "id": docket_id,
            "attributes": {
                "agencyId": "EPA",
                "title": f"Title {docket_id}",
                "docketType": "Rulemaking",
                "modifyDate": "2024-01-01",
                "dkAbstract": "abstract",
            },
        }
    }


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, size: int | None = None) -> bytes:
        return self._data if size is None else self._data[:size]

    def close(self) -> None:
        pass


class _FakeObj:
    def __init__(
        self,
        key: str,
        content: bytes,
        get_requests: list[tuple[str, dict[str, str]]] | None = None,
    ) -> None:
        self.key = key
        self._content = content
        self.e_tag = f'"etag:{key}"'
        self.size = len(content)
        self._get_requests = get_requests

    def get(self, **kwargs: str) -> dict:
        if self._get_requests is not None:
            self._get_requests.append((self.key, kwargs))
        if "IfMatch" in kwargs and kwargs["IfMatch"] != self.e_tag:
            raise ValueError("precondition failed")
        return {
            "Body": _FakeBody(self._content),
            "ContentLength": len(self._content),
            "ETag": self.e_tag,
            "VersionId": f"version:{self.key}",
        }


class _FakeObjects:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store

    def filter(self, Prefix: str):
        for key, content in self._store.items():
            if key.startswith(Prefix):
                yield _FakeObj(key, content)


class _FakeBucket:
    def __init__(self, store: dict[str, bytes]) -> None:
        self.objects = _FakeObjects(store)


class _FakeS3Resource:
    def __init__(self, store: dict[str, bytes]) -> None:
        self._store = store
        self.get_requests: list[tuple[str, dict[str, str]]] = []

    def Bucket(self, name: str) -> _FakeBucket:
        return _FakeBucket(self._store)

    def Object(self, name: str, key: str) -> _FakeObj:
        return _FakeObj(key, self._store[key], self.get_requests)


class _RaisingObj:
    """An S3 object whose body read fails — a transient download error."""

    def get(self, **kwargs: str) -> dict:
        class _Body:
            def read(self, size: int | None = None) -> bytes:
                raise OSError("connection reset by peer")

            def close(self) -> None:
                pass

        return {"Body": _Body()}


class _FlakyResource(_FakeS3Resource):
    """Fake S3 that fails ``read()`` for chosen keys (all attempts, or just the first).

    ``fail_once`` makes a key fail on its first fetch and succeed thereafter, so a
    single instance can prove the in-run retry pass recovers a transient blip.
    Listing (``Bucket``) is untouched, so the keys still appear in the listing.
    """

    def __init__(self, store: dict[str, bytes], transient_fail: Iterable[str] = (), fail_once: bool = False) -> None:
        super().__init__(store)
        self._transient_fail = set(transient_fail)
        self._fail_once = fail_once
        self._attempts: dict[str, int] = {}

    def Object(self, name: str, key: str):
        self._attempts[key] = self._attempts.get(key, 0) + 1
        first_attempt = self._attempts[key] == 1
        if key in self._transient_fail and (not self._fail_once or first_attempt):
            return _RaisingObj()
        return _FakeObj(key, self._store[key])


class _RefusingResource(_FakeS3Resource):
    """Fake S3 that answers chosen keys with a given HTTP status, and counts attempts.

    Drives the real ``ClientError`` shape botocore raises, so the status the
    reader reads is the one a refusal actually carries rather than a hand-built
    marker exception.
    """

    def __init__(self, store: dict[str, bytes], statuses: dict[str, int]) -> None:
        super().__init__(store)
        self._statuses = statuses
        self.attempts: dict[str, int] = {}

    def Object(self, name: str, key: str):
        self.attempts[key] = self.attempts.get(key, 0) + 1
        status = self._statuses.get(key)
        if status is None:
            return _FakeObj(key, self._store[key], self.get_requests)

        class _RefusedObj:
            def get(self, **kwargs: str) -> dict:
                raise ClientError(
                    {
                        "Error": {"Code": "AccessDenied", "Message": "Access Denied"},
                        "ResponseMetadata": {"HTTPStatusCode": status},
                    },
                    "GetObject",
                )

        return _RefusedObj()


class _RefusingListingResource(_FakeS3Resource):
    """Fail either when constructing a listing or while advancing its pages."""

    def __init__(self, store: dict[str, bytes], status: int, after_first: bool) -> None:
        super().__init__(store)
        self.error = ClientError(
            {
                "Error": {"Code": "ListingFailed", "Message": "Listing failed"},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "ListObjectsV2",
        )
        self.after_first = after_first

    def Bucket(self, name: str) -> _FakeBucket:
        resource = self

        class _RefusingObjects(_FakeObjects):
            def filter(self, Prefix: str):
                if not resource.after_first:
                    raise resource.error

                def pages():
                    yield next(_FakeObjects.filter(self, Prefix=Prefix))
                    raise resource.error

                return pages()

        bucket = super().Bucket(name)
        bucket.objects = _RefusingObjects(self._store)
        return bucket


def _docket_key(docket_id: str) -> str:
    return f"{PREFIX}/{AGENCY}/{docket_id}/text-{docket_id}/docket/{docket_id}.json"


def _numbered_store(count: int) -> tuple[list[str], dict[str, bytes]]:
    """``count`` dockets whose keys already sort in listing order."""
    store = {
        _docket_key(f"EPA-2024-{index:04d}"): dumps(_docket_payload(f"EPA-2024-{index:04d}")).encode()
        for index in range(count)
    }
    return list(store), store


def _make_store() -> dict[str, bytes]:
    return {
        _docket_key("EPA-2024-0001"): dumps(_docket_payload("EPA-2024-0001")).encode(),
        _docket_key("EPA-2025-0002"): dumps(_docket_payload("EPA-2025-0002")).encode(),
        # Not a docket / not json — must be ignored by list_json_files.
        f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001/comments/c.json": b"{}",
        f"{PREFIX}/{AGENCY}/EPA-2024-0001/binary-EPA-2024-0001/docket/x.pdf": b"x",
    }


def _raw_id(payload: dict) -> str:
    # The reader yields raw JSON; flattening to docket_id is the transform's job.
    return payload["data"]["id"]


def test_iter_records_yields_raw_payloads() -> None:
    reader = MirrulationsReader(_FakeS3Resource(_make_store()), BUCKET, PREFIX, AGENCY, DOCKET)
    records = list(reader.iter_records())

    ids = sorted(_raw_id(r) for r in records)
    assert ids == ["EPA-2024-0001", "EPA-2025-0002"]
    assert all(r["data"]["attributes"]["agencyId"] == "EPA" for r in records)
    # last_keys is populated for manifest tracking and matches what was yielded.
    assert len(reader.last_keys) == 2


def test_exact_source_enumeration_pins_listing_etags_versions_and_bytes() -> None:
    store = _make_store()
    resource = _FakeS3Resource(store)
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET)

    objects = list(reader.iter_source_objects())
    expected_keys = [_docket_key("EPA-2024-0001"), _docket_key("EPA-2025-0002")]

    assert [value.key for value in objects] == expected_keys
    assert [value.content for value in objects] == [store[key] for key in expected_keys]
    assert [value.etag for value in objects] == [f'"etag:{key}"' for key in expected_keys]
    assert [value.version_id for value in objects] == [f"version:{key}" for key in expected_keys]
    # GETs fan out over a thread pool, so dispatch order isn't guaranteed —
    # only the yielded object order (asserted above) is. Every key was still
    # fetched exactly once, pinned to its listed ETag.
    assert sorted(resource.get_requests, key=lambda r: r[0]) == [
        (key, {"IfMatch": f'"etag:{key}"'}) for key in expected_keys
    ]


def test_exact_source_enumeration_refuses_changed_object_metadata() -> None:
    store = {_docket_key("EPA-2024-0001"): b"{}"}

    class _ChangedObject(_FakeObj):
        def get(self, **kwargs: str) -> dict:
            response = super().get(**kwargs)
            response["ETag"] = '"changed-after-listing"'
            return response

    class _ChangedResource(_FakeS3Resource):
        def Object(self, name: str, key: str) -> _ChangedObject:
            return _ChangedObject(key, self._store[key], self.get_requests)

    reader = MirrulationsReader(
        _ChangedResource(store),
        BUCKET,
        PREFIX,
        AGENCY,
        DOCKET,
    )

    with pytest.raises(ValueError, match="returned ETag"):
        list(reader.iter_source_objects())


def test_iter_source_objects_yields_in_listing_order_despite_out_of_order_completion() -> None:
    """GETs run concurrently, so they may complete out of order; the objects
    yielded back must still match listing order, not completion order."""
    import threading

    keys, store = _numbered_store(3)
    first_key_may_finish = threading.Event()

    class _OrderedObj(_FakeObj):
        def get(self, **kwargs: str) -> dict:
            if self.key == keys[0]:
                # The first-listed key's GET can't finish until a later one has —
                # proof that completion order is reversed relative to listing order.
                assert first_key_may_finish.wait(timeout=5)
                return super().get(**kwargs)
            response = super().get(**kwargs)
            first_key_may_finish.set()
            return response

    class _OrderedResource(_FakeS3Resource):
        def Object(self, name: str, key: str) -> _OrderedObj:
            return _OrderedObj(key, self._store[key])

    reader = MirrulationsReader(_OrderedResource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=3)
    objects = list(reader.iter_source_objects())

    assert [value.key for value in objects] == keys


def test_iter_source_objects_fails_fast_on_a_failed_get() -> None:
    """The first failed GET aborts the enumeration instead of skipping ahead.

    An unreadable object makes the enumeration unusable as complete-snapshot
    evidence, so it must not be silently dropped in favor of later keys.
    """
    keys, store = _numbered_store(3)

    class _FailingResource(_FakeS3Resource):
        def Object(self, name: str, key: str):
            if key == keys[1]:
                return _RaisingObj()
            return _FakeObj(key, self._store[key])

    reader = MirrulationsReader(_FailingResource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)
    iterator = reader.iter_source_objects()

    first = next(iterator)
    assert first.key == keys[0]  # the key listed before the failure is still yielded
    with pytest.raises(OSError, match="connection reset"):
        next(iterator)  # the failing key aborts; the third key is never reached


def test_iter_source_objects_stops_dispatching_gets_once_a_failure_is_visible() -> None:
    """A failed GET must not keep the pool fetching the keys queued behind it.

    Keys 0-2 open the window together; the head is held until key 1 has failed,
    so a window refilled after the head is yielded would dispatch key 3 and the
    executor would then run it while the failure propagates. Nothing past the
    opening window may be fetched.
    """
    import threading
    from time import sleep

    keys, store = _numbered_store(8)
    failed = threading.Event()
    fetched: list[str] = []
    lock = threading.Lock()

    class _CountingFailingResource(_FakeS3Resource):
        def Object(self, name: str, key: str):
            with lock:
                fetched.append(key)
            if key == keys[1]:
                failed.set()
                return _RaisingObj()
            if key == keys[0]:
                assert failed.wait(timeout=5)
                sleep(0.05)  # long enough for the executor to record key 1's exception
            return _FakeObj(key, self._store[key])

    reader = MirrulationsReader(_CountingFailingResource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=3)
    iterator = reader.iter_source_objects()

    assert next(iterator).key == keys[0]
    with pytest.raises(OSError, match="connection reset"):
        next(iterator)

    assert set(fetched) <= set(keys[:3])


def test_iter_source_objects_closes_early_without_fetching_the_rest_of_the_agency() -> None:
    """A consumer that stops after one object must not pay for the whole listing.

    Closing the generator has to return rather than drain every remaining key:
    only the GETs already in flight when it closed may complete.
    """
    import threading

    keys, store = _numbered_store(8)
    fetched: list[str] = []
    lock = threading.Lock()

    class _CountingResource(_FakeS3Resource):
        def Object(self, name: str, key: str) -> _FakeObj:
            with lock:
                fetched.append(key)
            return _FakeObj(key, self._store[key])

    reader = MirrulationsReader(_CountingResource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=2)
    iterator = reader.iter_source_objects()

    assert next(iterator).key == keys[0]
    iterator.close()

    assert set(fetched) <= set(keys[:3])


class _TransientFlakyObj(_FakeObj):
    """Raises a genuine transient transport error for its first ``fail_first_n``
    GETs on this key, then succeeds like a normal ``_FakeObj``."""

    def __init__(
        self,
        key: str,
        content: bytes,
        attempts: dict[str, int],
        fail_first_n: int,
        exc_factory,
    ) -> None:
        super().__init__(key, content)
        self._attempts = attempts
        self._fail_first_n = fail_first_n
        self._exc_factory = exc_factory

    def get(self, **kwargs: str) -> dict:
        self._attempts[self.key] = self._attempts.get(self.key, 0) + 1
        if self._attempts[self.key] <= self._fail_first_n:
            raise self._exc_factory()
        return super().get(**kwargs)


class _TransientFlakyResource(_FakeS3Resource):
    """Fake S3 whose GETs for chosen keys raise a transient transport error for
    a fixed number of attempts before succeeding (or never, for an exhausted-
    budget test)."""

    def __init__(
        self,
        store: dict[str, bytes],
        transient_fail_keys: Iterable[str],
        fail_first_n: int,
        exc_factory,
    ) -> None:
        super().__init__(store)
        self._transient_fail_keys = set(transient_fail_keys)
        self._fail_first_n = fail_first_n
        self._exc_factory = exc_factory
        self.attempts: dict[str, int] = {}

    def Object(self, name: str, key: str):
        if key in self._transient_fail_keys:
            return _TransientFlakyObj(key, self._store[key], self.attempts, self._fail_first_n, self._exc_factory)
        return _FakeObj(key, self._store[key])


def _read_timeout() -> Exception:
    from botocore.exceptions import ReadTimeoutError

    return ReadTimeoutError(endpoint_url="https://mirrulations.s3.amazonaws.com/raw-data/EPA/x.json")


def test_iter_source_objects_retries_a_transient_transport_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read timeout (the exact failure behind the 47 lost agencies) retries
    with backoff and then succeeds; every listed object is still yielded, in
    listing order."""
    from spicy_docs.sources import mirrulations

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))
    monkeypatch.setattr(mirrulations.random, "uniform", lambda _lo, hi: hi)

    keys, store = _numbered_store(3)
    flaky_key = keys[1]
    resource = _TransientFlakyResource(store, [flaky_key], fail_first_n=2, exc_factory=_read_timeout)

    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)
    objects = list(reader.iter_source_objects())

    assert [value.key for value in objects] == keys  # nothing dropped, listing order preserved
    assert resource.attempts[flaky_key] == 3  # two failures, then a succeeding third attempt
    # Full jitter pinned to the ceiling by the monkeypatch above: 2**1, 2**2.
    assert delays == [2.0, 4.0]


def test_iter_source_objects_aborts_after_the_transient_retry_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient failure that never recovers still aborts -- patience is
    bounded, not infinite -- and the original exception surfaces unwrapped."""
    from botocore.exceptions import ReadTimeoutError

    from spicy_docs.sources import mirrulations

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))
    monkeypatch.setattr(mirrulations.random, "uniform", lambda _lo, hi: hi)

    keys, store = _numbered_store(1)
    resource = _TransientFlakyResource(
        store, keys, fail_first_n=mirrulations._MAX_TRANSIENT_ATTEMPTS + 1, exc_factory=_read_timeout
    )

    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    with pytest.raises(ReadTimeoutError):
        list(reader.iter_source_objects())

    assert resource.attempts[keys[0]] == mirrulations._MAX_TRANSIENT_ATTEMPTS
    assert len(delays) == mirrulations._MAX_TRANSIENT_ATTEMPTS - 1  # one sleep between each pair of attempts


def test_retry_transient_does_not_retry_a_payload_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic corruption must never be retried, even though it shares
    the module's failure-classification apparatus with transient errors."""
    from spicy_docs.sources import mirrulations
    from spicy_docs.sources.mirrulations import PayloadParseError

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))

    calls = 0

    def op() -> None:
        nonlocal calls
        calls += 1
        raise PayloadParseError("some/key.json")

    with pytest.raises(PayloadParseError):
        mirrulations._retry_transient("some/key.json", op)

    assert calls == 1
    assert delays == []


def test_iter_source_objects_aborts_immediately_on_a_changed_etag_with_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed object under If-Match is a data fact -- the snapshot would be
    unfaithful -- not a busy network, so it must not be retried."""
    from spicy_docs.sources import mirrulations

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))

    store = {_docket_key("EPA-2024-0001"): b"{}"}

    class _ChangedObject(_FakeObj):
        def get(self, **kwargs: str) -> dict:
            response = super().get(**kwargs)
            response["ETag"] = '"changed-after-listing"'
            return response

    class _ChangedResource(_FakeS3Resource):
        def Object(self, name: str, key: str) -> _ChangedObject:
            return _ChangedObject(key, self._store[key], self.get_requests)

    reader = MirrulationsReader(_ChangedResource(store), BUCKET, PREFIX, AGENCY, DOCKET)

    with pytest.raises(ValueError, match="returned ETag"):
        list(reader.iter_source_objects())
    assert delays == []


def test_iter_source_objects_aborts_immediately_on_a_listed_size_mismatch_with_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listed size that disagrees with the downloaded bytes is a data fact,
    not a busy network, so it must not be retried."""
    from spicy_docs.sources import mirrulations

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))

    store = {_docket_key("EPA-2024-0001"): b"{}"}

    class _WrongListedSizeObjects(_FakeObjects):
        def filter(self, Prefix: str):
            for entry in super().filter(Prefix=Prefix):
                entry.size = entry.size + 1  # listing lied about the object's size
                yield entry

    class _WrongListedSizeResource(_FakeS3Resource):
        def Bucket(self, name: str) -> _FakeBucket:
            bucket = super().Bucket(name)
            bucket.objects = _WrongListedSizeObjects(self._store)
            return bucket

    reader = MirrulationsReader(_WrongListedSizeResource(store), BUCKET, PREFIX, AGENCY, DOCKET)

    with pytest.raises(ValueError, match="listed size differs"):
        list(reader.iter_source_objects())
    assert delays == []


def test_iter_source_objects_aborts_immediately_on_a_missing_listing_etag_with_no_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listing with no ETag can't be pinned by a later GET -- a data fact,
    not a busy network -- so it must not be retried."""
    from spicy_docs.sources import mirrulations

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))

    store = {_docket_key("EPA-2024-0001"): b"{}"}

    class _MissingETagObjects(_FakeObjects):
        def filter(self, Prefix: str):
            for entry in super().filter(Prefix=Prefix):
                entry.e_tag = None
                yield entry

    class _MissingETagResource(_FakeS3Resource):
        def Bucket(self, name: str) -> _FakeBucket:
            bucket = super().Bucket(name)
            bucket.objects = _MissingETagObjects(self._store)
            return bucket

    reader = MirrulationsReader(_MissingETagResource(store), BUCKET, PREFIX, AGENCY, DOCKET)

    with pytest.raises(ValueError, match="lacks an ETag"):
        list(reader.iter_source_objects())
    assert delays == []


def test_processed_keys_are_skipped() -> None:
    already = {_docket_key("EPA-2024-0001")}
    reader = MirrulationsReader(_FakeS3Resource(_make_store()), BUCKET, PREFIX, AGENCY, DOCKET, processed_keys=already)
    records = list(reader.iter_records())
    assert [_raw_id(r) for r in records] == ["EPA-2025-0002"]


def test_since_year_filters_older_dockets() -> None:
    reader = MirrulationsReader(_FakeS3Resource(_make_store()), BUCKET, PREFIX, AGENCY, DOCKET, since_year=2025)
    records = list(reader.iter_records())
    assert [_raw_id(r) for r in records] == ["EPA-2025-0002"]


def test_iter_records_downloads_concurrently() -> None:
    """Downloads for one agency run in parallel, not one-at-a-time.

    A Barrier that only releases once all N downloads are simultaneously in
    flight is a deterministic proof of concurrency: a serial implementation
    can never gather N parties, so the barrier times out, those downloads
    raise, and nothing is yielded. Concurrent downloads all rendezvous and
    every payload comes back.
    """
    import threading

    n = 4
    store = {_docket_key(f"EPA-2024-{i:04d}"): dumps(_docket_payload(f"EPA-2024-{i:04d}")).encode() for i in range(n)}
    barrier = threading.Barrier(n, timeout=5)

    class _BarrierObj(_FakeObj):
        def get(self, **kwargs: str) -> dict:
            barrier.wait()  # blocks until all N downloads are concurrently in flight
            return super().get(**kwargs)

    class _BarrierResource(_FakeS3Resource):
        def Object(self, name: str, key: str) -> _BarrierObj:
            return _BarrierObj(key, self._store[key])

    reader = MirrulationsReader(_BarrierResource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=n)
    records = list(reader.iter_records())

    assert len(records) == n


class _CountingObjects(_FakeObjects):
    """Counts how many times the agency prefix is scanned."""

    def __init__(self, store: dict[str, bytes], scans: list[int]) -> None:
        super().__init__(store)
        self._scans = scans

    def filter(self, Prefix: str):
        self._scans[0] += 1
        return super().filter(Prefix=Prefix)


class _CountingResource(_FakeS3Resource):
    def __init__(self, store: dict[str, bytes], scans: list[int]) -> None:
        super().__init__(store)
        self._scans = scans

    def Bucket(self, name: str):
        bucket = super().Bucket(name)
        bucket.objects = _CountingObjects(self._store, self._scans)
        return bucket


def _typed_store() -> dict[str, bytes]:
    base = f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001"
    return {
        f"{base}/docket/EPA-2024-0001.json": dumps(_docket_payload("EPA-2024-0001")).encode(),
        f"{base}/documents/EPA-2024-0001-0001.json": b'{"data": {"id": "EPA-2024-0001-0001"}}',
        f"{base}/comments/EPA-2024-0001-0002.json": b'{"data": {"id": "EPA-2024-0001-0002"}}',
        # Non-JSON / binary — must be ignored.
        f"{base}/binary-EPA-2024-0001/docket/x.pdf": b"x",
    }


def test_single_scan_buckets_keys_by_record_type() -> None:
    """One prefix scan classifies an agency's keys for all record types.

    Replaces the prior behavior of scanning the whole agency prefix once per
    record type (3x). A counting fake proves exactly one scan happens.
    """
    from spicy_docs.sources.mirrulations import list_agency_files_by_type

    scans = [0]
    resource = _CountingResource(_typed_store(), scans)

    result = list_agency_files_by_type(resource, BUCKET, PREFIX, AGENCY, [DOCKET, DOCUMENT, COMMENT])

    assert scans[0] == 1
    assert result["dockets"] == [f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001/docket/EPA-2024-0001.json"]
    assert result["documents"] == [
        f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001/documents/EPA-2024-0001-0001.json"
    ]
    assert result["comments"] == [
        f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001/comments/EPA-2024-0001-0002.json"
    ]


def test_reader_factory_scans_each_agency_once() -> None:
    """The readers a factory builds for one agency share a single prefix scan."""
    from spicy_docs.sources.mirrulations import reader_factory

    scans = [0]
    resource = _CountingResource(_typed_store(), scans)
    read = reader_factory([DOCKET, DOCUMENT, COMMENT], resource_factory=lambda: resource)

    keys_by_type = {}
    for record_type in (DOCKET, DOCUMENT, COMMENT):
        reader = read(AGENCY, record_type)
        list(reader.iter_records())
        keys_by_type[record_type.name] = reader.last_keys

    assert scans[0] == 1  # one scan for the agency, not one per record type
    assert len(keys_by_type["dockets"]) == 1
    assert len(keys_by_type["documents"]) == 1
    assert len(keys_by_type["comments"]) == 1


def test_download_keys_yields_payloads() -> None:
    """download_keys concurrently downloads a given key list and yields payloads.

    This is the shared download engine used by both iter_records and the chunked
    ingest path (which downloads one bounded key-chunk at a time).
    """
    from spicy_docs.sources.mirrulations import download_keys

    store = _make_store()
    keys = [_docket_key("EPA-2024-0001"), _docket_key("EPA-2025-0002")]
    payloads = list(download_keys(_FakeS3Resource(store), BUCKET, keys, workers=4))

    ids = sorted(p["data"]["id"] for p in payloads)
    assert ids == ["EPA-2024-0001", "EPA-2025-0002"]


def test_download_keys_bounds_pending_work_for_a_streaming_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large key iterator is consumed only as worker slots become available."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from spicy_docs.sources import mirrulations

    release = threading.Event()
    initial_window_filled = threading.Event()
    consumed = 0

    def keys():
        nonlocal consumed
        for index in range(100):
            consumed += 1
            if consumed == 8:
                initial_window_filled.set()
            if consumed > 8 and not release.is_set():
                raise AssertionError("download_keys consumed beyond its bounded pending window")
            yield f"key-{index}"

    def blocked_download(_resource, _bucket, key, _extract, *, record_type=None):
        release.wait(timeout=5)
        return {"key": key}

    monkeypatch.setattr(mirrulations, "download_and_parse", blocked_download)
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(lambda: list(mirrulations.download_keys(object(), BUCKET, keys(), workers=4)))
        assert initial_window_filled.wait(timeout=5)
        assert consumed == 8
        release.set()
        assert len(result.result(timeout=5)) == 100


def test_bounded_reader_factory_streams_keys_without_building_a_manifest_list() -> None:
    from spicy_docs.sources.mirrulations import reader_factory

    resource = _FakeS3Resource(_typed_store())
    read = reader_factory([DOCUMENT], resource_factory=lambda: resource, bounded=True)
    reader = read(AGENCY, DOCUMENT)

    assert len(list(reader.iter_records())) == 1
    assert reader.last_keys == []


def test_bounded_reader_preserves_one_in_run_transient_retry() -> None:
    from spicy_docs.sources.mirrulations import reader_factory

    store = {_docket_key("EPA-2024-0001"): dumps(_docket_payload("EPA-2024-0001")).encode()}
    resource = _FlakyResource(store, transient_fail=store, fail_once=True)
    read = reader_factory([DOCKET], resource_factory=lambda: resource, bounded=True)

    assert len(list(read(AGENCY, DOCKET).iter_records())) == 1
    assert resource._attempts[_docket_key("EPA-2024-0001")] == 2


@pytest.mark.parametrize(
    ("content_length", "max_bytes", "etag", "reason", "expected_reads"),
    [
        (8, 2, '"expected"', "exceeds the 2 byte cap", 0),
        (None, 2, '"expected"', "exceeds the 2 byte cap", 1),
        (8, None, '"expected"', "returned 7 bytes but declared 8", 1),
        (7, None, '"changed"', "returned ETag", 1),
    ],
    ids=["advertised-oversize", "unadvertised-oversize", "wrong-length", "changed-etag"],
)
def test_download_object_bytes_closes_body_on_validation_failure(
    content_length: int | None,
    max_bytes: int | None,
    etag: str,
    reason: str,
    expected_reads: int,
) -> None:
    from spicy_docs.sources.mirrulations import download_object_bytes

    class _TrackingBody(_FakeBody):
        reads = 0
        closes = 0

        def read(self, size: int | None = None) -> bytes:
            self.reads += 1
            return super().read(size)

        def close(self) -> None:
            self.closes += 1

    body = _TrackingBody(b"payload")

    class _Obj:
        def get(self, **kwargs: str) -> dict:
            assert kwargs == {"IfMatch": '"expected"'}
            return {"Body": body, "ContentLength": content_length, "ETag": etag}

    class _Res:
        def Object(self, bucket: str, key: str) -> _Obj:
            return _Obj()

    with pytest.raises(ValueError, match=reason):
        download_object_bytes(_Res(), BUCKET, "some/key.json", if_match='"expected"', max_bytes=max_bytes)

    assert body.reads == expected_reads
    assert body.closes == 1


def test_download_and_parse_closes_body_on_read_error() -> None:
    """A failed download raises TransientDownloadError but still closes the body.

    If ``read()`` raises (timeout, connection reset) and the body is left open,
    the underlying S3 connection leaks into CLOSE_WAIT instead of returning to
    the pool. Enough leaks exhaust the pool and later downloads block forever
    acquiring a connection — the low-CPU / CLOSE_WAIT-pileup hang seen on large
    agencies. Closing the body on every path keeps the pool healthy; raising
    (rather than returning None) lets the caller keep the key out of the manifest
    so it's retried next run.
    """
    from spicy_docs.sources.mirrulations import TransientDownloadError, download_and_parse

    closed = {"value": False}

    class _Body:
        def read(self) -> bytes:
            raise OSError("connection reset by peer")

        def close(self) -> None:
            closed["value"] = True

    class _Obj:
        def get(self) -> dict:
            return {"Body": _Body()}

    class _Res:
        def Object(self, bucket: str, key: str) -> _Obj:
            return _Obj()

    with pytest.raises(TransientDownloadError):
        download_and_parse(_Res(), BUCKET, "some/key.json", lambda d: d)

    assert closed["value"] is True  # ...but the body was closed, so no leak


def test_download_and_parse_raises_parse_error_on_bad_json() -> None:
    """A body that decodes/extracts badly raises PayloadParseError, not transient.

    The bytes came off S3 fine — retrying just re-fetches the same corrupt
    payload — so this is a distinct, non-retryable failure class.
    """
    from spicy_docs.sources.mirrulations import PayloadParseError, download_and_parse

    store = {"bad/key.json": b"{ not valid json"}
    with pytest.raises(PayloadParseError):
        download_and_parse(_FakeS3Resource(store), BUCKET, "bad/key.json", lambda d: d)


def _mixed_failure_store() -> tuple[dict[str, bytes], str, str, str]:
    """A store with one good, one parse-failing, and one transient-failing key."""
    good = _docket_key("EPA-2024-0001")
    parse_bad = _docket_key("EPA-2025-0002")
    transient_bad = _docket_key("EPA-2024-0003")
    store = {
        good: dumps(_docket_payload("EPA-2024-0001")).encode(),
        parse_bad: b"{ broken json",
        transient_bad: dumps(_docket_payload("EPA-2024-0003")).encode(),
    }
    return store, good, parse_bad, transient_bad


@pytest.mark.parametrize("workers", [1, 4])
def test_download_keys_observes_every_key_that_produced_no_record(workers: int) -> None:
    """download_keys retains one observation per unyielded key (both branches).

    ``workers=1`` exercises the serial branch, ``workers=4`` the thread-pool
    branch (future->key attribution) — both must report the same outcomes.
    """
    from spicy_docs.sources.mirrulations import STATUS_TRANSPORT, STATUS_UNREADABLE, KeyOutcome, download_keys

    store, good, parse_bad, transient_bad = _mixed_failure_store()
    resource = _FlakyResource(store, transient_fail=[transient_bad])
    outcomes: list[KeyOutcome] = []
    payloads = list(
        download_keys(resource, BUCKET, [good, parse_bad, transient_bad], workers=workers, outcomes=outcomes)
    )

    assert [p["data"]["id"] for p in payloads] == ["EPA-2024-0001"]
    assert {o.key: o.status for o in outcomes} == {
        parse_bad: STATUS_UNREADABLE,
        transient_bad: STATUS_TRANSPORT,
    }
    for outcome in outcomes:
        assert outcome.reason  # the answer is named, not merely counted
        assert outcome.attempted_at.startswith("20") and outcome.attempted_at.endswith("+00:00")
        assert outcome.attempts == 1


def test_iter_records_excludes_transient_failures_from_last_keys() -> None:
    """A transient download failure is kept out of last_keys (and reported)."""
    from spicy_docs.sources.mirrulations import STATUS_TRANSPORT

    store = _make_store()
    bad = _docket_key("EPA-2025-0002")
    resource = _FlakyResource(store, transient_fail=[bad])
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    records = list(reader.iter_records())

    assert [_raw_id(r) for r in records] == ["EPA-2024-0001"]
    assert reader.last_keys == [_docket_key("EPA-2024-0001")]  # bad key excluded
    assert reader.failed_keys == [bad]
    assert reader.parse_failed_keys == []
    assert [(o.key, o.status) for o in reader.unresolved] == [(bad, STATUS_TRANSPORT)]


def test_iter_records_retries_transient_failure_once() -> None:
    """The in-run retry recovers a key that fails its first fetch, succeeds next."""
    store = _make_store()
    flaky = _docket_key("EPA-2025-0002")
    resource = _FlakyResource(store, transient_fail=[flaky], fail_once=True)
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    records = list(reader.iter_records())

    assert sorted(_raw_id(r) for r in records) == ["EPA-2024-0001", "EPA-2025-0002"]
    assert reader.failed_keys == []  # recovered on retry
    assert sorted(reader.last_keys) == sorted([_docket_key("EPA-2024-0001"), flaky])


def test_iter_records_keeps_parse_failures_out_of_last_keys() -> None:
    """A parse failure is an unresolved key, not a processed one.

    Rewritten from the assertion it replaced, which required the opposite: a
    malformed object used to be manifested as processed, so a later repair --
    upstream, or to this package's own parsing -- could never come back. The
    observation now says what was seen and when, and the key stays retryable.
    """
    from spicy_docs.sources.mirrulations import STATUS_UNREADABLE

    store = _make_store()
    bad = _docket_key("EPA-2025-0002")
    store[bad] = b"{ broken json"
    reader = MirrulationsReader(_FakeS3Resource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    records = list(reader.iter_records())

    assert [_raw_id(r) for r in records] == ["EPA-2024-0001"]
    assert reader.last_keys == [_docket_key("EPA-2024-0001")]  # the bad key is not processed
    assert reader.failed_keys == [bad]  # so the caller never manifests it
    assert reader.parse_failed_keys == [bad]
    (outcome,) = reader.unresolved
    assert (outcome.key, outcome.status) == (bad, STATUS_UNREADABLE)
    assert "JSONDecodeError" in outcome.reason and outcome.attempted_at


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("workers", [1, 4])
def test_an_access_refusal_aborts_the_run_and_writes_no_key(status: int, workers: int) -> None:
    """401/403 ends the run; it is never recorded as a key that merely failed.

    Recorded as a failed key, a refusal over a whole prefix reads downstream as
    those objects being absent. Both download branches must abort, and the
    default ``fail_fast=False`` must not soften it -- that switch governs
    transport answers, not access.
    """
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError
    from spicy_docs.transport.credentials import CredentialRefusedError

    store = _make_store()
    refused = _docket_key("EPA-2025-0002")
    reader = MirrulationsReader(
        _RefusingResource(store, {refused: status}), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=workers
    )

    with pytest.raises(MirrulationsAccessRefusedError) as raised:
        list(reader.iter_records())

    assert isinstance(raised.value, CredentialRefusedError)  # callers that abort on one keep aborting
    assert str(status) in str(raised.value)
    assert "Stopping rather than continuing or falling back" in str(raised.value)
    assert refused not in reader.failed_keys and refused not in reader.last_keys
    assert [o.key for o in reader.unresolved] == []


@pytest.mark.parametrize("status", [401, 403])
def test_an_access_refusal_aborts_the_exact_enumeration_too(status: int) -> None:
    """The evidence path raises the same typed refusal, not a bare botocore error."""
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError

    store = {_docket_key("EPA-2024-0001"): dumps(_docket_payload("EPA-2024-0001")).encode()}
    reader = MirrulationsReader(
        _RefusingResource(store, dict.fromkeys(store, status)), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1
    )

    with pytest.raises(MirrulationsAccessRefusedError):
        list(reader.iter_source_objects())


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("after_first", [False, True])
def test_iter_json_files_raises_typed_listing_refusal(status: int, after_first: bool) -> None:
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError, iter_json_files

    resource = _RefusingListingResource(_make_store(), status, after_first)
    keys = iter_json_files(resource, BUCKET, PREFIX, AGENCY, DOCKET.name, DOCKET.path_pattern)
    if after_first:
        assert next(keys) == _docket_key("EPA-2024-0001")
    with pytest.raises(MirrulationsAccessRefusedError, match=f"answered {status} for {PREFIX}/{AGENCY}/") as raised:
        list(keys)
    assert raised.value.__cause__ is resource.error
    assert resource.get_requests == []


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("after_first", [False, True])
def test_list_agency_files_by_type_raises_typed_listing_refusal(status: int, after_first: bool) -> None:
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError, list_agency_files_by_type

    resource = _RefusingListingResource(_typed_store(), status, after_first)
    with pytest.raises(MirrulationsAccessRefusedError, match=f"answered {status} for {PREFIX}/{AGENCY}/") as raised:
        list_agency_files_by_type(resource, BUCKET, PREFIX, AGENCY, [DOCKET, DOCUMENT, COMMENT])
    assert raised.value.__cause__ is resource.error
    assert resource.get_requests == []


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("after_first", [False, True])
def test_iter_source_objects_raises_typed_listing_refusal(status: int, after_first: bool) -> None:
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError

    resource = _RefusingListingResource(_make_store(), status, after_first)
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)
    with pytest.raises(MirrulationsAccessRefusedError, match=f"answered {status} for {PREFIX}/{AGENCY}/") as raised:
        list(reader.iter_source_objects())
    assert raised.value.__cause__ is resource.error
    assert reader.last_keys == reader.failed_keys == reader.unresolved == []


def test_listing_preserves_non_refusal_client_errors() -> None:
    from spicy_docs.sources.mirrulations import iter_json_files

    resource = _RefusingListingResource(_make_store(), 503, after_first=True)
    with pytest.raises(ClientError) as raised:
        list(iter_json_files(resource, BUCKET, PREFIX, AGENCY, DOCKET.name, DOCKET.path_pattern))
    assert raised.value is resource.error


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("workers", [1, 4])
def test_iter_records_fail_fast_preserves_typed_access_refusal(status: int, workers: int) -> None:
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError

    store = _make_store()
    refused = _docket_key("EPA-2025-0002")
    resource = _RefusingResource(store, {refused: status})
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=workers, fail_fast=True)
    with pytest.raises(MirrulationsAccessRefusedError, match=f"answered {status}"):
        list(reader.iter_records())
    assert resource.attempts[refused] == 1
    assert reader.last_keys == reader.failed_keys == reader.unresolved == []


def test_an_access_refusal_is_not_retried_as_a_transient_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A refusal must not spend the transient budget: it is an answer, not congestion."""
    from spicy_docs.sources import mirrulations
    from spicy_docs.sources.mirrulations import MirrulationsAccessRefusedError

    delays: list[float] = []
    monkeypatch.setattr(mirrulations.time, "sleep", lambda seconds: delays.append(seconds))

    key = _docket_key("EPA-2024-0001")
    resource = _RefusingResource({key: dumps(_docket_payload("EPA-2024-0001")).encode()}, {key: 403})
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    with pytest.raises(MirrulationsAccessRefusedError):
        list(reader.iter_source_objects())
    assert delays == []
    assert resource.attempts[key] == 1


@pytest.mark.parametrize(
    ("body", "named"),
    [
        (b"", "zero bytes"),
        (b"{}", "an empty object"),
        (b"null", "null"),
        (b"[]", "an array of 0 items"),
        (b'"a string"', "a bare str"),
    ],
)
def test_an_empty_or_mis_shaped_success_is_requested_empty_not_a_record(body: bytes, named: str) -> None:
    """A 2xx that carries no record is an observation of that answer.

    Before this, ``{}``, ``null`` and a bare scalar were yielded as records and
    manifested as processed: an empty answer became apparent coverage, which is
    exactly the absence a requested-empty observation exists to prevent.
    """
    from spicy_docs.sources.mirrulations import STATUS_REQUESTED_EMPTY

    store = _make_store()
    empty = _docket_key("EPA-2025-0002")
    store[empty] = body
    reader = MirrulationsReader(_FakeS3Resource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    records = list(reader.iter_records())

    assert [_raw_id(r) for r in records] == ["EPA-2024-0001"]  # no empty record was yielded
    assert reader.last_keys == [_docket_key("EPA-2024-0001")]  # and none was manifested
    (outcome,) = reader.unresolved
    assert (outcome.key, outcome.status) == (empty, STATUS_REQUESTED_EMPTY)
    assert named in outcome.reason  # the shape mismatch is named, not just counted


@pytest.mark.parametrize(
    ("body", "named"),
    [
        (b'{"data":{}}', "a data envelope containing an empty object"),
        (b'{"errors":[{"detail":"upstream failed"}]}', "a publisher error envelope"),
    ],
    ids=["empty-data", "publisher-error"],
)
@pytest.mark.parametrize("record_type", RECORD_TYPES.values(), ids=RECORD_TYPES)
@pytest.mark.parametrize("workers", [1, 4])
def test_a_populated_object_without_record_identity_is_requested_empty(
    body: bytes, named: str, record_type: RecordType, workers: int
) -> None:
    """The host's two reproduced null-id rows remain unresolved for every type."""
    store = _typed_store()
    key = next(key for key in store if record_type.path_pattern in key and key.endswith(".json"))
    store[key] = body
    # A second key exercises the thread-pool branch as well as a valid neighbor.
    good = key.replace(".json", "-good.json")
    payload = {"data": {"id": "EPA-2024-0001-good"}}
    store[good] = dumps(payload).encode()
    reader = MirrulationsReader(_FakeS3Resource(store), BUCKET, PREFIX, AGENCY, record_type, download_workers=workers)

    records = list(reader.iter_records())

    assert records == [payload]
    assert reader.last_keys == [good]
    assert reader.failed_keys == reader.parse_failed_keys == [key]
    (outcome,) = reader.unresolved
    assert (outcome.key, outcome.status, outcome.attempts) == (key, "requested-empty", 1)
    assert named in outcome.reason
    assert f"missing nonblank data.id identity for {record_type.name} ({record_type.dedup_key})" in outcome.reason
    if "errors" in body.decode():
        assert "upstream failed" in outcome.reason


@pytest.mark.parametrize("record_type", RECORD_TYPES.values(), ids=RECORD_TYPES)
@pytest.mark.parametrize(
    "payload",
    [
        {"title": "no data"},
        {"data": None},
        {"data": []},
        {"data": {"attributes": {"docketId": "parent-is-not-identity"}}},
        {"data": {"id": None}},
        {"data": {"id": ""}},
        {"data": {"id": " \t "}},
        {"data": {"id": 42}},
        {"data": {"id": {"nested": "id"}}},
    ],
    ids=[
        "no-data",
        "null-data",
        "array-data",
        "parent-id",
        "null-id",
        "empty-id",
        "blank-id",
        "number-id",
        "object-id",
    ],
)
def test_missing_or_empty_record_identity_stays_unresolved(payload: dict, record_type: RecordType) -> None:
    key = f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001{record_type.path_pattern}record.json"
    resource = _FakeS3Resource({key: dumps(payload).encode()})
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, record_type)

    assert list(reader.iter_records()) == []
    assert reader.last_keys == []
    (outcome,) = reader.unresolved
    assert (outcome.key, outcome.status) == (key, "requested-empty")
    assert f"missing nonblank data.id identity for {record_type.name} ({record_type.dedup_key})" in outcome.reason


@pytest.mark.parametrize("record_type", RECORD_TYPES.values(), ids=RECORD_TYPES)
@pytest.mark.parametrize("extra_fields", [{}, {"attributes": None, "unrecognized": [1, 2]}])
def test_record_identity_is_sufficient_and_raw_fields_are_preserved(
    record_type: RecordType, extra_fields: dict
) -> None:
    """All registered types define data.id as identity; optional fields stay raw."""
    identity = "EPA-2024-0001-0002"
    minimal = {"data": {"id": identity}}
    assert record_type.extract(minimal)[record_type.dedup_key] == identity
    payload = {"data": {"id": identity, **extra_fields}, "unknown": {"source": "kept"}}
    key = f"{PREFIX}/{AGENCY}/EPA-2024-0001/text-EPA-2024-0001{record_type.path_pattern}record.json"
    reader = MirrulationsReader(_FakeS3Resource({key: dumps(payload).encode()}), BUCKET, PREFIX, AGENCY, record_type)

    assert list(reader.iter_records()) == [payload]
    assert reader.last_keys == [key]
    assert reader.unresolved == []


def test_publisher_error_message_is_scrubbed_before_truncation_and_logging() -> None:
    from spicy_docs.sources import mirrulations
    from spicy_docs.sources.mirrulations import EmptyPayloadError, download_and_parse

    secret = "SENSITIVE" * 80  # crosses the truncation boundary
    message = f"upstream failed: https://example.test/?api_key={secret}&after=retained"
    body = dumps({"errors": [{"detail": message}]}).encode()
    key = _docket_key("EPA-2024-0001")
    resource = _FakeS3Resource({key: body})
    with pytest.raises(EmptyPayloadError) as raised:
        download_and_parse(resource, BUCKET, key, lambda payload: payload, record_type=DOCKET)
    detail = raised.value.detail
    assert "publisher error envelope" in detail and "upstream failed" in detail
    assert "api_key=<redacted>&after=retained" in detail
    assert "SENSITIVE" not in str(raised.value)
    assert len(detail) <= mirrulations._REASON_CHARACTERS

    logged = []
    sink = mirrulations.logger.add(lambda message: logged.append(str(message)))
    try:
        reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET)
        assert list(reader.iter_records()) == []
    finally:
        mirrulations.logger.remove(sink)
    assert reader.unresolved[0].reason == detail
    assert "SENSITIVE" not in "".join(logged)
    assert "api_key=<redacted>&after=retained" in "".join(logged)


def test_publisher_error_envelope_is_not_a_record_even_with_an_id() -> None:
    key = _docket_key("EPA-2024-0001")
    payload = {"data": {"id": "EPA-2024-0001"}, "errors": [{"detail": "upstream failed"}]}
    reader = MirrulationsReader(_FakeS3Resource({key: dumps(payload).encode()}), BUCKET, PREFIX, AGENCY, DOCKET)
    assert list(reader.iter_records()) == []
    assert reader.last_keys == []
    assert reader.unresolved[0].status == "requested-empty"
    assert "publisher error envelope" in reader.unresolved[0].reason


def test_direct_downloads_require_identity_without_a_record_type_label() -> None:
    from spicy_docs.sources.mirrulations import EmptyPayloadError, download_and_parse, download_keys

    key = _docket_key("EPA-2024-0001")
    resource = _FakeS3Resource({key: b'{"data":{}}'})
    with pytest.raises(EmptyPayloadError, match="missing nonblank data.id identity"):
        download_and_parse(resource, BUCKET, key, lambda payload: payload)
    outcomes = []
    assert list(download_keys(resource, BUCKET, [key], outcomes=outcomes)) == []
    assert outcomes[0].status == "requested-empty"


def test_bounded_reader_refuses_identity_free_success() -> None:
    from spicy_docs.sources.mirrulations import EmptyPayloadError, reader_factory

    key = _docket_key("EPA-2024-0001")
    resource = _FakeS3Resource({key: b'{"data":{}}'})
    read = reader_factory([DOCKET], resource_factory=lambda: resource, bounded=True)
    reader = read(AGENCY, DOCKET)
    with pytest.raises(EmptyPayloadError, match="dockets \\(docket_id\\)"):
        list(reader.iter_records())
    assert reader.last_keys == []
    assert len(resource.get_requests) == 1


@pytest.mark.parametrize("workers", [1, 4])
def test_identity_is_checked_after_an_in_run_transport_retry(workers: int) -> None:
    key = _docket_key("EPA-2024-0001")
    resource = _FlakyResource({key: b'{"data":{}}'}, transient_fail=[key], fail_once=True)
    reader = MirrulationsReader(resource, BUCKET, PREFIX, AGENCY, DOCKET, download_workers=workers)

    assert list(reader.iter_records()) == []
    assert reader.last_keys == []
    (outcome,) = reader.unresolved
    assert (outcome.status, outcome.attempts) == ("requested-empty", 2)
    assert "dockets (docket_id)" in outcome.reason


@pytest.mark.parametrize("body", [b'{"data":{}}', b'{"errors":[{"detail":"upstream failed"}]}'])
def test_identity_free_answer_is_retried_and_repaired(body: bytes) -> None:
    key = _docket_key("EPA-2024-0001")
    store = {key: body}
    prior = []
    for attempt in (1, 2):
        reader = MirrulationsReader(_FakeS3Resource(store), BUCKET, PREFIX, AGENCY, DOCKET, unresolved_keys=prior)
        assert list(reader.iter_records()) == []
        assert reader.last_keys == []
        assert reader.unresolved[0].attempts == attempt
        prior = reader.unresolved
    payload = _docket_payload("EPA-2024-0001")
    store[key] = dumps(payload).encode()
    repaired = MirrulationsReader(
        _FakeS3Resource(store), BUCKET, PREFIX, AGENCY, DOCKET, unresolved_keys=prior, key_lister=list
    )
    assert list(repaired.iter_records()) == [payload]
    assert repaired.last_keys == [key] and repaired.unresolved == []


def test_a_server_error_then_success_recovers_across_two_runs() -> None:
    """Run one leaves the key unresolved; run two asks again and manifests it.

    The manifest the caller keeps is ``last_keys``; the unresolved key is absent
    from it, so the second run re-lists it. It is also attempted before the
    newly listed work, so a capped or interrupted run cannot keep postponing it.
    """
    store = _make_store()
    flaky = _docket_key("EPA-2025-0002")

    first = MirrulationsReader(
        _RefusingResource(store, {flaky: 503}), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1
    )
    assert [_raw_id(r) for r in first.iter_records()] == ["EPA-2024-0001"]
    assert first.failed_keys == [flaky] and first.last_keys == [_docket_key("EPA-2024-0001")]

    manifest = set(first.last_keys)
    recovered = MirrulationsReader(
        _FakeS3Resource(store),
        BUCKET,
        PREFIX,
        AGENCY,
        DOCKET,
        processed_keys=manifest,
        download_workers=1,
        unresolved_keys=first.unresolved,
    )

    assert [_raw_id(r) for r in recovered.iter_records()] == ["EPA-2025-0002"]
    assert recovered.last_keys == [flaky] and recovered.unresolved == []


def test_a_malformed_record_repaired_upstream_is_recovered_on_the_next_run() -> None:
    """The two-run proof the replaced contract made impossible.

    Run one sees malformed bytes and records an observation. The mirror is then
    repaired. Run two, resuming from run one's manifest, asks again and yields
    the record. Under the replaced behaviour the key was manifested as processed
    in run one, so run two would have skipped it forever.
    """
    store = _make_store()
    broken = _docket_key("EPA-2025-0002")
    store[broken] = b"{ broken json"

    first = MirrulationsReader(_FakeS3Resource(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)
    assert [_raw_id(r) for r in first.iter_records()] == ["EPA-2024-0001"]
    manifest = set(first.last_keys)
    assert broken not in manifest

    store[broken] = dumps(_docket_payload("EPA-2025-0002")).encode()  # repaired upstream
    second = MirrulationsReader(
        _FakeS3Resource(store),
        BUCKET,
        PREFIX,
        AGENCY,
        DOCKET,
        processed_keys=manifest,
        download_workers=1,
        unresolved_keys=first.unresolved,
    )

    assert [_raw_id(r) for r in second.iter_records()] == ["EPA-2025-0002"]
    assert second.unresolved == [] and second.last_keys == [broken]


def test_previously_unresolved_keys_are_attempted_before_newly_listed_work() -> None:
    """Resume order, and no key attempted twice in one run."""
    keys, store = _numbered_store(4)
    fetched: list[str] = []

    class _OrderResource(_FakeS3Resource):
        def Object(self, name: str, key: str) -> _FakeObj:
            fetched.append(key)
            return _FakeObj(key, self._store[key])

    reader = MirrulationsReader(
        _OrderResource(store),
        BUCKET,
        PREFIX,
        AGENCY,
        DOCKET,
        download_workers=1,
        unresolved_keys=[keys[3], keys[1]],
    )
    list(reader.iter_records())

    assert fetched[:2] == [keys[3], keys[1]]  # the unresolved keys come first
    assert sorted(fetched) == sorted(keys)  # and each key is asked for exactly once


@pytest.mark.parametrize("workers", [1, 4])
@pytest.mark.parametrize(
    ("body", "status", "attempts_per_run"),
    [(b"{ broken json", None, 1), (b"{}", None, 1), (b"{}", 503, 2)],
)
def test_unresolved_attempts_accumulate_across_runs(
    body: bytes, status: int | None, attempts_per_run: int, workers: int
) -> None:
    from spicy_docs.sources.mirrulations import reader_factory

    store = _make_store()
    unresolved = _docket_key("EPA-2025-0002")
    store[unresolved] = body
    resource = _RefusingResource(store, {unresolved: status} if status is not None else {})
    prior = []
    processed: set[str] = set()
    for run in range(1, 4):
        read = reader_factory(
            [DOCKET],
            resource_factory=lambda: resource,
            processed_keys=processed,
            download_workers=workers,
            unresolved_keys=lambda _agency, _record_type, prior=prior: prior,
        )
        reader = read(AGENCY, DOCKET)
        list(reader.iter_records())
        (outcome,) = reader.unresolved
        assert outcome.key == unresolved
        assert outcome.attempts == resource.attempts[unresolved] == attempts_per_run * run
        assert unresolved not in reader.last_keys
        processed.update(reader.last_keys)
        prior = reader.unresolved


@pytest.mark.parametrize("workers", [1, 4])
@pytest.mark.parametrize("raise_failures", [False, True])
def test_download_keys_counts_retries_before_a_changed_failure(workers: int, raise_failures: bool) -> None:
    from spicy_docs.sources.mirrulations import STATUS_UNREADABLE, KeyOutcome, PayloadParseError, download_keys

    store = _make_store()
    broken = _docket_key("EPA-2025-0002")
    store[broken] = b"{ broken json"
    resource = _FlakyResource(store, transient_fail=[broken], fail_once=True)
    prior = KeyOutcome(broken, STATUS_UNREADABLE, "bad JSON", "2026-09-19T00:00:00+00:00", attempts=49)
    outcomes: list[KeyOutcome] = []
    records = download_keys(
        resource,
        BUCKET,
        [_docket_key("EPA-2024-0001"), broken],
        workers=workers,
        outcomes=outcomes,
        prior_outcomes=[prior],
        transient_retries=1,
        raise_failures=raise_failures,
    )
    if raise_failures:
        with pytest.raises(PayloadParseError):
            list(records)
    else:
        assert [_raw_id(record) for record in records] == ["EPA-2024-0001"]
    (outcome,) = outcomes
    assert outcome.status == STATUS_UNREADABLE
    assert outcome.attempts == 51
    assert resource._attempts[broken] == 2
    assert prior.attempts == 49


def test_a_recorded_reason_is_scrubbed_before_it_is_truncated() -> None:
    """A credential in a transport error never reaches an observation or a log.

    The mirror is read anonymously, but the S3 resource is injectable: a signed
    one renders its presigned URL into botocore's message. Scrubbing after
    truncation would cut the value and leave its front standing, so the order is
    the assertion -- the message is longer than the budget on purpose.
    """
    from spicy_docs.sources import mirrulations

    secret = "AKIAI" + "S" * 60
    padding = "x" * mirrulations._REASON_CHARACTERS

    class _SignedFailure(_FakeS3Resource):
        def Object(self, name: str, key: str):
            class _Obj:
                def get(self, **kwargs: str) -> dict:
                    raise OSError(
                        f"read timeout on https://mirrulations.s3.amazonaws.com/{key}"
                        f"?X-Amz-Signature={secret}&x={padding}"
                    )

            return _Obj()

    store = {_docket_key("EPA-2024-0001"): b"{}"}
    reader = MirrulationsReader(_SignedFailure(store), BUCKET, PREFIX, AGENCY, DOCKET, download_workers=1)

    list(reader.iter_records())

    (outcome,) = reader.unresolved
    assert secret not in outcome.reason
    assert "X-Amz-Signature=<redacted>" in outcome.reason
    assert len(outcome.reason) == mirrulations._REASON_CHARACTERS  # truncation still applies, second


def test_s3_resource_configures_retries() -> None:
    """The resource must set an explicit retry policy so a transient S3 error
    is retried rather than silently dropping the record (botocore's default
    leaves ``retries`` unset)."""
    from spicy_docs.sources.mirrulations import s3_resource

    cfg = s3_resource().meta.client.meta.config
    assert cfg.retries is not None
    # botocore normalizes max_attempts -> total_max_attempts under standard mode.
    attempts = cfg.retries.get("total_max_attempts") or cfg.retries.get("max_attempts", 0)
    assert attempts >= 2


def test_s3_resource_connection_pool_fits_download_workers() -> None:
    """The S3 resource's HTTP connection pool must be at least as large as the
    download thread pool. Otherwise concurrent GETs oversubscribe a too-small
    pool: connections churn into CLOSE_WAIT and the run stalls (botocore's
    default max_pool_connections is 10, below DEFAULT_DOWNLOAD_WORKERS)."""
    from spicy_docs.sources.mirrulations import DEFAULT_DOWNLOAD_WORKERS, s3_resource

    resource = s3_resource()
    pool_size = resource.meta.client.meta.config.max_pool_connections

    assert pool_size >= DEFAULT_DOWNLOAD_WORKERS
