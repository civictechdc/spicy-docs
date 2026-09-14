"""Credential-file reading and scrubbing shared by acquisition commands."""

from __future__ import annotations

import re
from pathlib import Path


class CredentialRefusedError(RuntimeError):
    """401 or 403 ends the operation; callers must not continue or fall back."""

    details: object = None


def read_api_key(env_file: Path, name: str) -> str:
    for line in env_file.read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == name:
            return value.strip().strip("'\"")
    raise SystemExit(f"{name} not found in {env_file}")


def scrub_credential(text: str, api_key: str) -> str:
    """Remove the credential from anything this tool records or prints.

    Two passes, because either alone leaves a hole. The pattern catches a
    credential this function was not handed -- a redirect to a different
    keyed host, a nested URL inside a message -- while the literal catches
    the key wherever it appears in a form the pattern does not match, such
    as a header echoed back in a response body. Scrubbing happens before
    truncation, never after: truncating first can cut a key in half and
    leave the front of it standing.
    """
    scrubbed = re.sub(r"(api_key=)[^&\s'\"]+", r"\1<redacted>", text)
    if len(api_key) >= 8:
        scrubbed = scrubbed.replace(api_key, "<redacted>")
    return scrubbed
