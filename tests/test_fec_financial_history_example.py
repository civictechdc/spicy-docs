import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from examples.fec_financial_history import PREFIXES, capture, read_previous


def source(year=2024, *, etag='"first"', size=20):
    key = f"bulk-downloads/{year}/CommunicationCosts_{year}.csv"
    return {
        "key": key,
        "url": f"https://www.fec.gov/files/{key}",
        "size": size,
        "etag": etag,
        "last_modified": "2026-09-01T00:00:00Z",
    }


class Client:
    def __init__(self, rows, *, failed=(), listing_failure=False):
        self.rows = rows
        self.failed = failed
        self.listing_failure = listing_failure
        self.http = SimpleNamespace(request_count=0)
        self.downloads = []

    def objects(self, prefix, *, max_pages):
        self.http.request_count += 1
        yield {
            "records": [{"metadata": row} for row in self.rows if row["key"].startswith(prefix)],
            "evidence": {"sha256": "sha256:" + "1" * 64},
        }
        if self.listing_failure:
            raise RuntimeError("listing continuation failed")

    def download(self, url, **kwargs):
        self.downloads.append((url, kwargs))
        if url in self.failed:
            raise RuntimeError("controlled transfer failure")
        reused = kwargs["expected_sha256"] is not None
        self.http.request_count += not reused
        return {
            "url": url,
            "sha256": kwargs["expected_sha256"] or "sha256:" + "2" * 64,
            "bytes": kwargs["expected_size"],
            "downloaded": not reused,
            "reused": reused,
            "response": {} if reused else {"observed_at": "original-body-observation"},
        }


def test_selected_population_bounds_and_original_headers_preserved(tmp_path):
    row = source()
    row["future_source_field"] = {"empty": [], "null": None}
    ignored = dict(source(2022), key="bulk-downloads/2022/indiv22.zip")
    client = Client([row, ignored])
    result = capture(client, tmp_path / "out", max_bytes=20, max_objects=1)
    assert result["acquisition_complete"]
    assert result["objects"][0]["source"] == row
    assert len(client.downloads) == 1
    assert client.downloads[0][1]["etag"] == row["etag"]
    assert client.downloads[0][1]["expected_size"] == 20
    assert len((tmp_path / "out/listings.jsonl").read_text().splitlines()) == len(PREFIXES)


@pytest.mark.parametrize("bounds", [{"max_bytes": 19}, {"max_objects": 1}])
def test_exceeded_bound_transfers_nothing(tmp_path, bounds):
    client = Client([source(), source(2022)])
    result = capture(client, tmp_path / "out", **bounds)
    assert not result["acquisition_complete"]
    assert client.downloads == []
    assert all(row["outcome"] == "not-requested" for row in result["objects"])


def test_incomplete_enumeration_never_downloads_or_claims_completion(tmp_path):
    client = Client([source()], listing_failure=True)
    result = capture(client, tmp_path / "out")
    assert not result["enumeration_complete"] and not result["acquisition_complete"]
    assert client.downloads == []


def test_refresh_reuses_only_unchanged_success_and_retains_old_body_observation(tmp_path):
    rows = [source(year) for year in (2020, 2022, 2024)]
    prior = capture(Client(rows, failed=[rows[1]["url"]]), tmp_path / "prior")
    current = [rows[0], rows[1], dict(rows[2], etag='"changed"'), source(2026)]
    client = Client(current)
    result = capture(client, tmp_path / "current", previous=prior)
    assert result["acquisition_complete"]
    assert [kwargs["expected_sha256"] is not None for _, kwargs in client.downloads] == [True, False, False, False]
    assert [row["change"] for row in result["objects"]] == [
        "unchanged-listing",
        "unchanged-listing",
        "changed-listing",
        "newly-listed",
    ]
    assert result["objects"][0]["asset"]["response"] == prior["objects"][0]["asset"]["response"]
    assert not prior["acquisition_complete"]


def test_missing_key_and_zero_byte_object_are_explicit(tmp_path):
    prior = capture(Client([source(2022)]), tmp_path / "prior")
    client = Client([source(size=0)])
    result = capture(client, tmp_path / "current", previous=prior)
    assert result["not_listed_this_run"] == [source(2022)["key"]]
    assert result["objects"][0]["outcome"] == "listed-zero-bytes-not-acquired"
    assert not result["acquisition_complete"]
    assert not client.downloads


def test_changed_prior_pin_and_unrelated_selector_rejected(tmp_path):
    result = capture(Client([source()]), tmp_path / "out")
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(result))
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    assert read_previous(path, pin) == result
    with pytest.raises(ValueError, match="pin"):
        read_previous(path, "0" * 64)
    changed = deepcopy(result)
    changed["selector"] = "other"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="selection"):
        read_previous(path, hashlib.sha256(path.read_bytes()).hexdigest())
