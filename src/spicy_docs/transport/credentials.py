"""Credential-file reading and scrubbing shared by acquisition commands."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final


class CredentialRefusedError(RuntimeError):
    """401 or 403 ends the operation; callers must not continue or fall back."""

    details: object = None


#: The two statuses that end a run rather than produce a row. A refusal is not a
#: bad record: recorded as one, a revoked key or a gated route reads downstream
#: as the source having nothing there. Every fetcher shares this set so the rule
#: cannot drift between them.
ACCESS_REFUSED_STATUSES: Final = frozenset({401, 403})


def refusal_message(publisher: str, status: int, subject: str) -> str:
    """The single wording every 401/403 abort uses, so the contract stays one thing.

    ``subject`` names what was requested -- an id, an object key -- never a
    request URL, which can carry the credential into the message this builds.
    """
    return (
        f"{publisher} answered {status} for {subject}: access was refused. "
        "Stopping rather than continuing or falling back."
    )


def read_api_key(env_file: Path, name: str) -> str:
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {env_file}")


#: Query parameters that carry a secret in the routes this package requests:
#: api.data.gov's key, and the three AWS presigning parameters that appear in a
#: botocore error's endpoint URL whenever a caller supplies a signed S3 resource.
_CREDENTIAL_PARAMETERS: Final = ("api_key", "X-Amz-Credential", "X-Amz-Signature", "X-Amz-Security-Token")
_CREDENTIAL_PARAMETER_PATTERN: Final = re.compile(
    # The inner group is non-capturing *and* separate from the ``=``: bound the
    # other way, the alternation takes the ``=`` as part of the last name only,
    # and every other parameter redacts its own separator away.
    rf"((?:{'|'.join(re.escape(name) for name in _CREDENTIAL_PARAMETERS)})=)[^&\s'\"]+",
    re.IGNORECASE,
)


def scrub_credential(text: str, api_key: str = "") -> str:
    """Remove the credential from anything this tool records or prints.

    Two passes, because either alone leaves a hole. The pattern catches a
    credential this function was not handed -- a redirect to a different
    keyed host, a nested URL inside a message -- while the literal catches
    the key wherever it appears in a form the pattern does not match, such
    as a header echoed back in a response body. Scrubbing happens before
    truncation, never after: truncating first can cut a key in half and
    leave the front of it standing.

    ``api_key`` defaults to empty for the keyless and anonymous routes: they
    hold no literal to remove, but their transports still render URLs into
    exception messages, so the pattern pass still has work to do.
    """
    scrubbed = _CREDENTIAL_PARAMETER_PATTERN.sub(r"\1<redacted>", text)
    if len(api_key) >= 8:
        scrubbed = scrubbed.replace(api_key, "<redacted>")
    return scrubbed
