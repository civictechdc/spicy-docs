"""Cross-parity between the two public Federal Register document-number normalizers.

``spicy_docs.sources.sec_comments.join.normalize_fr_doc_num`` (the strict SEC
join's key) and
``spicy_docs.interpretation.identifier_shapes.unpadded_federal_register_document_number``
(spicy-regs' comparison key) both delegate their spelling mechanics to one
shared core in ``identifier_shapes`` -- the measured en-dash fold, the
zero-padding rule, the C/R year segment's last-dash-only handling, and the
measured C7 -> Z7 mirror series. This file pins the documented output of both
entry points over the same inputs, so the shared rules and the deliberate
divergences (the join remaps the mirror's C7 series; the spicy-regs key is
pinned byte-identical and never remaps) each live exactly once and drift apart
loudly.
"""

import pytest

from spicy_docs.interpretation.identifier_shapes import (
    fr_doc_num_mirror_series,
    fr_doc_num_release_spelling,
    hyphenate_fr_doc_num,
    unpadded_federal_register_document_number,
)
from spicy_docs.sources.sec_comments.join import SecCommentsJoinError, normalize_fr_doc_num

#: input -> (join output, unpadded-key output). The two agree everywhere except the
#: C7 series, where only the strict join applies the measured mirror remap.
PARITY = [
    ("2010-00239", "2010-239", "2010-239"),
    ("2010-02394", "2010-2394", "2010-2394"),
    ("05-18895", "05-18895", "05-18895"),
    ("2024-31178", "2024-31178", "2024-31178"),
    ("E8\u201327139", "E8-27139", "E8-27139"),
    ("C1-2010-12986", "C1-2010-12986", "C1-2010-12986"),
    ("C1-2013-00201", "C1-2013-201", "C1-2013-201"),
    ("C1-2012-09978", "C1-2012-9978", "C1-2012-9978"),
    ("2010-00000", "2010-0", "2010-0"),
    ("06-00018", "06-18", "06-18"),
    ("Z7-14563", "Z7-14563", "Z7-14563"),
    ("C7-01476", "C7-1476", "C7-1476"),
    ("C7-14563", "Z7-14563", "C7-14563"),
    ("C7-15181", "Z7-15181", "C7-15181"),
]


@pytest.mark.parametrize(("stated", "join_key", "unpadded_key"), PARITY)
def test_both_entry_points_produce_their_documented_outputs(stated: str, join_key: str, unpadded_key: str) -> None:
    """The join's release-spelling key and the unpadded comparison key, both pinned per input."""
    assert normalize_fr_doc_num(stated) == join_key
    assert unpadded_federal_register_document_number(stated) == unpadded_key
    # Both keys are fixed points of their own entry point.
    assert normalize_fr_doc_num(join_key) == join_key
    assert unpadded_federal_register_document_number(unpadded_key) == unpadded_key


def test_the_c7_remap_is_the_one_documented_divergence() -> None:
    """Only the strict join remaps the mirror's C7 series; the spicy-regs key stays byte-identical."""
    assert fr_doc_num_mirror_series("C7-14563") == "Z7-14563"
    assert unpadded_federal_register_document_number("C7-14563") == "C7-14563"
    assert unpadded_federal_register_document_number("Z7-14563") == "Z7-14563"


def test_the_shared_release_spelling_holds_the_rules_once() -> None:
    """The core the join delegates to: en dash folded, C7 remapped, final sequence unpadded only."""
    assert hyphenate_fr_doc_num("E8\u201327139") == "E8-27139"
    assert fr_doc_num_release_spelling("E8\u201327139") == "E8-27139"
    assert fr_doc_num_release_spelling("C7-14563") == "Z7-14563"
    assert fr_doc_num_release_spelling("C1-2013-00201") == "C1-2013-201"
    with pytest.raises(ValueError, match="dash-final"):
        fr_doc_num_release_spelling("no dash at all")


def test_the_entry_points_keep_their_own_admission() -> None:
    """Each entry point refuses on its own grammar: the join raises, the key returns None."""
    with pytest.raises(SecCommentsJoinError):
        normalize_fr_doc_num("e9-09366")  # the join admits only uppercase letter prefixes
    assert unpadded_federal_register_document_number("e9-09366") == "E9-9366"  # the key folds case
    assert unpadded_federal_register_document_number("SR1-12345") is None  # no form reads two letters
    assert normalize_fr_doc_num("SR1-12345") == "SR1-12345"  # the join's grammar admits it
