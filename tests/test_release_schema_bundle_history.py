"""A published release stays admissible when the schema bundle moves.

Admission used to require a release's embedded schema bundle to equal
``installed_release_schema_bundle()`` byte-for-byte -- the bundle *today's*
code generates. Widening the acquisition-ledger ``failure`` shape therefore
made all 668 already-published releases inadmissible, measured against
``releases/fr-full-1994-2026`` before this was fixed: embedded
``sha256:a7e0dba5...`` against installed ``sha256:4c324165...``.

That is the same defect as the Federal Register field-set check fixed in
6293692: validating a stored artefact against what the current code produces
rather than against what this project has accepted. The remedy is the same --
a frozen table of accepted historical values -- and it carries the same trap,
which two drafts of that fix fell into: an entry computed from today's files
is not a historical record, because it moves when the files do.
"""

from __future__ import annotations

from spicy_docs.source_native import (
    KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS,
    installed_release_schema_bundle,
    schema_bundle_digest,
)

#: Measured from three independently built published releases -- fr-full-1994-2026,
#: regs-dockets-ACF and fr-slice-2026-04-13 -- which agree. Spelled out here rather
#: than imported so this test is an independent statement of what 1.0 was.
PUBLISHED_1_0_DIGEST = "sha256:a7e0dba5e0b26f69ad3a41901a08eb158d21eb59b856f9faf83d48640a85abdb"


def test_the_published_bundle_digest_is_still_accepted() -> None:
    """The 668 releases on disk must keep loading after the schema widens."""

    assert PUBLISHED_1_0_DIGEST in KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS.values()


def test_the_1_0_entry_is_frozen_and_is_not_the_current_bundle() -> None:
    """A historical entry computed from today's files is not historical.

    If ``KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS["1.0"]`` were derived from the
    installed schema files it would silently become the widened bundle, and the
    releases it exists to admit would be refused again -- under the new error.
    """

    assert KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS["1.0"] == PUBLISHED_1_0_DIGEST
    assert (
        KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS["1.0"]
        != schema_bundle_digest(installed_release_schema_bundle())
    )


def test_the_installed_bundle_is_one_the_reader_accepts() -> None:
    """A schema change that forgets a table entry fails here, not at admission.

    Otherwise the writer would embed a bundle the reader refuses, and every
    release built between the schema change and the table update would be
    unreadable by the code that wrote it.
    """

    assert (
        schema_bundle_digest(installed_release_schema_bundle())
        in KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS.values()
    )


def test_no_two_accepted_bundle_digests_are_the_same_value() -> None:
    """Catches a future entry written as a copy of the current one."""

    assert len(set(KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS.values())) == len(
        KNOWN_RELEASE_SCHEMA_BUNDLE_DIGESTS
    )
