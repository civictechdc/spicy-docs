"""Provider-client refusals never chain to an exception that holds the credential or the provider payload."""

from __future__ import annotations

import traceback

import pytest

from spicy_docs.transport.provider_api import strict_provider_json, validate_provider_credential


class _Refused(ValueError):
    pass


def _detached(error: BaseException, secret: str) -> None:
    assert error.__cause__ is None and error.__context__ is None
    assert secret not in "".join(traceback.format_exception(error))


def test_an_unencodable_credential_is_refused_without_the_codec_error_that_holds_it() -> None:
    secret = "key-with-€-euro"
    with pytest.raises(_Refused, match="PROVIDER_KEY contains unsupported credential characters") as raised:
        validate_provider_credential(secret, name="PROVIDER_KEY", error_type=_Refused)
    _detached(raised.value, secret)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"echo": "Bearer s3cr3t-token", ', "invalid JSON response"),
        (b'{"echo": "Bearer s3cr3t-token \xff"}', "invalid JSON response"),
        (b'{"echo": "Bearer s3cr3t-token", "echo": 1}', "repeats field 'echo'"),
        (b'["Bearer s3cr3t-token"]', "must be a JSON object"),
    ],
)
def test_an_unreadable_envelope_is_refused_without_the_parser_error_that_holds_the_payload(
    payload: bytes, message: str
) -> None:
    with pytest.raises(_Refused, match=message) as raised:
        strict_provider_json(payload, provider="Provider", error_type=_Refused)
    _detached(raised.value, "s3cr3t-token")
