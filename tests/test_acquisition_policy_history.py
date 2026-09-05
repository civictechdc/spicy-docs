"""A release stays admissible when its acquisition policy version moves.

Admission required a release's declared `acquisitionPolicyVersion` to equal the
version the *running code* declares (`source_native.py`, the SPEC_FIELDS
identity block). Moving the Federal Register policy 1.0 -> 1.1 for composite
identity therefore made every already-published FR release inadmissible --
including the one holding the retained acquisition evidence a rebuild replays,
which is how this was found: the replay tool could not admit the release it
exists to replay.

This is the third instance of one design assumption, not a third bug. The
stored-request field list (fixed in 6293692) and the embedded schema bundle
(fixed in 83e2032) both validated a stored artefact against what today's code
produces rather than against what this project has accepted. A release acquired
under 1.0 IS a 1.0 release: that is a fact about how it was acquired, not a
defect to refuse.

The same block still compares `sourceSystemVersion` and `sourceStateScope` to
the live values. That fourth instance is left in place knowingly, with the
reason recorded in this change's commit message.
"""

from __future__ import annotations

from spicy_docs.source_native import KNOWN_ACQUISITION_POLICY_VERSIONS
from spicy_docs.source_native_profiles import FEDERAL_REGISTER_PROFILE


def test_the_federal_register_policy_history_holds_both_published_versions() -> None:
    """1.0 published the corpus on disk; 1.1 is composite identity."""

    assert KNOWN_ACQUISITION_POLICY_VERSIONS[FEDERAL_REGISTER_PROFILE.acquisition_policy_id] == frozenset(
        {"1.0", "1.1"}
    )


def test_the_running_version_is_one_the_reader_accepts() -> None:
    """A policy bump that forgets a history entry fails here, not at admission.

    Otherwise the acquirer would publish under a version its own reader
    refuses -- which is exactly what b590d86 did until this table existed.
    """

    accepted = KNOWN_ACQUISITION_POLICY_VERSIONS[FEDERAL_REGISTER_PROFILE.acquisition_policy_id]
    assert FEDERAL_REGISTER_PROFILE.acquisition_policy_version in accepted
