"""The proxy client smoke harness: one bounded fetch per target, one fallback retry, scrubbed dated receipts.

Each provider is exercised through the same harness. A missing credential fails fast with the
provider client's own error and exit 2. A 403/429 retries once in the provider's fallback mode under
the run's retry budget. Wall and publisher markers are read from the bytes and named. No receipt or
report line carries the credential, even where a prefix cut could have kept part of it. An existing
receipt is never overwritten, and no request is made when one exists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from spicy_docs.sources import firecrawl, zyte
from tools.analysis import proxy_client_smoke as smoke

TOKEN = "super-secret-token-value-42"
FCC, CFTC, USITC, FERC, PDF = smoke.TARGETS
PROVIDERS = [smoke.PROVIDERS["zyte"], smoke.PROVIDERS["firecrawl"]]
RESPONSE_TYPES = {"zyte": zyte.ZyteHttpResponse, "firecrawl": firecrawl.FirecrawlResponse}
CREDENTIAL_ENV = {"zyte": zyte.ZYTE_TOKEN_ENV, "firecrawl": firecrawl.FIRECRAWL_API_KEY_ENV}
#: What the Authorization header would carry, so a receipt can be checked for it.
AUTH_SCHEME = {"zyte": "Basic", "firecrawl": "Bearer"}
STARTED = datetime(2026, 9, 25, 23, 30, tzinfo=UTC)


class _FakeFetcher:
    """One scripted outcome per (url, mode) pair; never touches the network."""

    def __init__(self, provider: smoke.Provider, outcomes: dict[tuple[str, str], object]) -> None:
        setattr(self, provider.credential_attribute, TOKEN)
        self.outcomes = outcomes
        self.calls: list[tuple[str, str]] = []

    def fetch(self, url: str, *, timeout_seconds: float, max_bytes: int, mode: str):
        self.calls.append((url, mode))
        outcome = self.outcomes[(url, mode)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(
    provider: smoke.Provider, url: str, *, status: int = 200, body: bytes = b"<html>real page</html>", mode=None
):
    return RESPONSE_TYPES[provider.name](
        requested_url=url,
        resolved_url=url,
        status_code=status,
        content_type="text/html",
        body=body,
        mode=mode or provider.body_mode,
    )


def _receipt_lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _target_rows(path) -> list[dict]:
    return [line for line in _receipt_lines(path) if "target" in line]


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_each_target_is_fetched_once_in_the_publisher_bytes_mode_when_it_answers_200(tmp_path, capsys, provider):
    fetcher = _FakeFetcher(
        provider, {(target.url, provider.body_mode): _response(provider, target.url) for target in smoke.TARGETS}
    )
    receipt = tmp_path / "receipt.jsonl"

    assert smoke.run(fetcher, provider, receipt, started=STARTED) == 0

    assert fetcher.calls == [(target.url, provider.body_mode) for target in smoke.TARGETS]
    header = _receipt_lines(receipt)[0]
    assert header["kind"] == f"{provider.name}-client-smoke-run"
    assert header["provider"] == provider.name
    assert header["started_utc"] == STARTED.isoformat()
    assert header["command"].endswith(f"--provider {provider.name}")
    rows = _target_rows(receipt)
    assert [row["target"] for row in rows] == [target.name for target in smoke.TARGETS]
    assert all(row["mode"] == provider.body_mode for row in rows)
    assert all("retried_after_status" not in row for row in rows)
    assert FCC.name in capsys.readouterr().out


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
@pytest.mark.parametrize("refusal", [403, 429])
def test_a_target_refusal_retries_once_in_the_fallback_mode(provider, refusal: int) -> None:
    fetcher = _FakeFetcher(
        provider,
        {
            (FCC.url, provider.body_mode): _response(
                provider, FCC.url, status=refusal, body=b"<title>Access Denied</title>"
            ),
            (FCC.url, provider.retry_mode): _response(
                provider, FCC.url, mode=provider.retry_mode, body=b"<html>fallback</html>"
            ),
        },
    )

    record, retried = smoke.probe_target(fetcher, provider, FCC, retries_left=1)

    assert retried is True
    assert fetcher.calls == [(FCC.url, provider.body_mode), (FCC.url, provider.retry_mode)]
    assert record["mode"] == provider.retry_mode
    assert record["retried_after_status"] == refusal
    assert record["status_code"] == 200


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_the_retry_budget_caps_live_requests_at_one_per_target_plus_the_retries(tmp_path, provider) -> None:
    outcomes = {}
    for target in smoke.TARGETS:
        outcomes[(target.url, provider.body_mode)] = _response(
            provider, target.url, status=403, body=b"<title>Access Denied</title>"
        )
        outcomes[(target.url, provider.retry_mode)] = _response(provider, target.url, mode=provider.retry_mode)
    fetcher = _FakeFetcher(provider, outcomes)

    assert smoke.run(fetcher, provider, tmp_path / "receipt.jsonl") == 0

    assert len(fetcher.calls) == len(smoke.TARGETS) + smoke.MAX_RETRIES
    rows = _target_rows(tmp_path / "receipt.jsonl")
    untried = len(smoke.TARGETS) - smoke.MAX_RETRIES
    assert [row.get("retried_after_status") for row in rows] == [403] * smoke.MAX_RETRIES + [None] * untried
    assert [row["mode"] for row in rows] == [provider.retry_mode] * smoke.MAX_RETRIES + [provider.body_mode] * untried


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_an_exhausted_retry_budget_makes_no_second_request(provider) -> None:
    fetcher = _FakeFetcher(
        provider,
        {(FCC.url, provider.body_mode): _response(provider, FCC.url, status=403, body=b"<title>Access Denied</title>")},
    )

    record, retried = smoke.probe_target(fetcher, provider, FCC, retries_left=0)

    assert retried is False
    assert len(fetcher.calls) == 1
    assert "retried_after_status" not in record


@pytest.mark.parametrize(
    ("body", "target", "classification", "marker"),
    [
        (
            b"<HTML><TITLE>Access Denied</TITLE>You don't have permission to access",
            FCC,
            "wall",
            "You don't have permission to access",
        ),
        (b"<title>Attention Required! | Cloudflare</title>", CFTC, "wall", "Attention Required! | Cloudflare"),
        (b"<html>Sorry, you have been blocked</html>", CFTC, "wall", "Sorry, you have been blocked"),
        (b"<results><investigations><investigation>", USITC, "publisher-page", "<results><investigations>"),
        (b"%PDF-1.4\nrest", FCC, "publisher-page", "%PDF-"),
        (b"%PDF-1.4\npdf bytes", PDF, "publisher-page", "%PDF-"),
        (b"<html>ctl00_ctl00_cphContentMain", CFTC, "publisher-page", "ctl00_ctl00"),
        (b"<html>no known shape</html>", FERC, "unrecognized", None),
    ],
)
def test_body_classification_names_the_marker_found(
    body: bytes, target: smoke.Target, classification: str, marker: str | None
) -> None:
    verdict = smoke.classify_body(body, target)
    assert verdict.classification == classification
    assert verdict.marker == marker


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_a_provider_error_is_recorded_scrubbed_and_the_run_continues(tmp_path, provider) -> None:
    outcomes: dict[tuple[str, str], object] = {
        (FCC.url, provider.body_mode): provider.transport_error(f"echoing {TOKEN}")
    }
    for target in smoke.TARGETS[1:]:
        outcomes[(target.url, provider.body_mode)] = _response(provider, target.url)
    fetcher = _FakeFetcher(provider, outcomes)

    assert smoke.run(fetcher, provider, tmp_path / "receipt.jsonl") == 0

    rows = _target_rows(tmp_path / "receipt.jsonl")
    assert rows[0]["target"] == FCC.name and rows[0]["error"] == "echoing <redacted>"
    assert all("error" not in row for row in rows[1:])
    assert len(fetcher.calls) == len(smoke.TARGETS)


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_receipts_scrub_the_credential_before_truncating_the_body_prefix(tmp_path, capsys, provider) -> None:
    reflected = b"x" * 60 + TOKEN.encode() + b"y" * 100
    fetcher = _FakeFetcher(
        provider,
        {(target.url, provider.body_mode): _response(provider, target.url, body=reflected) for target in smoke.TARGETS},
    )
    receipt = tmp_path / "receipt.jsonl"

    smoke.run(fetcher, provider, receipt)

    receipt_text = receipt.read_text()
    assert TOKEN not in receipt_text
    assert TOKEN[:20] not in receipt_text
    assert '"Authorization"' not in receipt_text and AUTH_SCHEME[provider.name] not in receipt_text
    assert TOKEN not in capsys.readouterr().out
    row = next(line for line in _receipt_lines(receipt) if line.get("target") == FCC.name)
    assert "<redacted>" in row["body_prefix"]


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_a_missing_credential_fails_fast_with_the_providers_typed_error(monkeypatch, capsys, tmp_path, provider):
    name = CREDENTIAL_ENV[provider.name]
    monkeypatch.delenv(name, raising=False)
    receipt = tmp_path / "receipt.jsonl"

    with pytest.raises(provider.transport_error, match=f"{name} is required for live acquisition"):
        provider.fetcher_type.from_environment()
    assert smoke.main(["--provider", provider.name, "--receipt", str(receipt)]) == 2
    assert f"{name} is required for live acquisition" in capsys.readouterr().err
    assert not receipt.exists()


@pytest.mark.parametrize("provider", PROVIDERS, ids=lambda provider: provider.name)
def test_the_default_receipt_is_dated_from_the_run_clock_and_never_overwritten(monkeypatch, tmp_path, capsys, provider):
    monkeypatch.setattr(smoke, "RECEIPTS_ROOT", tmp_path)
    monkeypatch.setenv(CREDENTIAL_ENV[provider.name], TOKEN)
    calls = []

    def fetch(_self, url, *, timeout_seconds, max_bytes, mode):
        calls.append(url)
        return _response(provider, url, mode=mode)

    monkeypatch.setattr(provider.fetcher_type, "fetch", fetch)

    assert smoke.main(["--provider", provider.name], clock=lambda: STARTED) == 0
    receipt = tmp_path / f"{provider.name}-client-smoke-2026-09-25" / smoke.RECEIPT_NAME
    assert receipt == smoke.default_receipt_path(provider, STARTED)
    retained = receipt.read_bytes()
    assert _receipt_lines(receipt)[0]["started_utc"] == STARTED.isoformat()
    assert len(calls) == len(smoke.TARGETS)
    capsys.readouterr()

    # A second run the same day finds the retained receipt and stops before any request.
    assert smoke.main(["--provider", provider.name], clock=lambda: STARTED) == 2
    assert "already exists" in capsys.readouterr().err
    assert receipt.read_bytes() == retained
    assert len(calls) == len(smoke.TARGETS)
