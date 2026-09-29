"""The commit an installed distribution records in its PEP 610 ``direct_url.json``.

A git install records the commit it resolved under ``vcs_info.commit_id``; a
wheel, path, editable or registry install records none. The diff engine's
stamp and the Record parser's pin check both read it here.
"""

from __future__ import annotations

import json
from importlib import metadata


def recorded_commit(distribution: metadata.Distribution) -> str | None:
    """``vcs_info.commit_id`` from the distribution's ``direct_url.json``; ``None`` where it records none."""
    text = distribution.read_text("direct_url.json")
    if not text:
        return None
    try:
        commit = json.loads(text).get("vcs_info", {}).get("commit_id")
    except (json.JSONDecodeError, AttributeError):
        return None
    return commit if isinstance(commit, str) and commit else None
