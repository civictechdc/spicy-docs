"""Reconstruct a publisher's structured vocabulary from a rendition that has none.

**Retrieve, then reconstruct, then interpret; never in the other order.** A
body is taken in the publisher's most structured rendition first (XML, then
HTML, then text, then PDF). This package runs only where retrieval has
nothing structured to give, and what it produces is a *derivative*: every
serialized file travels with a source map back to the evidence it was built
from, every node names the rule or the model call that placed it, and a
hosted row derived from it says ``derivation = reconstructed``. Interpretation
(``spicy_docs.interpretation``) runs after, over facts and findings, and never
rewrites text; reconstruction rewrites nothing either -- it assembles and
classifies the extractor's own text and reports where it could not.

The five modules, in the order a document passes through them:

- ``profiles`` -- one frozen, versioned record per target vocabulary: what it
  applies to, the schema bundle pinned by digest, the rules as a table (each
  tagged ``schema``, ``guide`` or ``heuristic``), the serializer, the checks.
- ``evidence`` -- the evidence-linked document model: blocks with page or
  line coordinates and style observations, built from ``extraction``'s
  retained pages or the markup reader's events; nothing is dropped.
- ``parse`` -- the deterministic structural parser; every node carries its
  ``evidence_refs`` and a ``decision`` naming the rule. Where rules cannot
  decide, the ``classify_and_attach`` seam takes an injected model call that
  chooses between evidence-backed alternatives and may abstain.
- ``serialize`` -- deterministic XML in the target vocabulary, plus a sidecar
  source map from XML paths to evidence ids; the vocabulary carries no
  custom attribute and every generated id is marked as generated.
- ``validate`` -- five separate findings (schema validity, content fidelity,
  structural fidelity, coverage, acceptance) and the gates as a pure function
  over them.

Everything but ``validate.schema_validity`` is standard library. That one
check needs ``lxml`` and names the ``reconstruct`` extra when it is absent,
the way ``sources.congress.bill_tree`` names ``bill-diff``.
"""

from __future__ import annotations

EXTRA_REQUIRED = "schema validation needs the 'reconstruct' extra: uv sync --extra reconstruct"

#: Every id this package mints (``b0001`` for a block, ``n0001`` for a node,
#: ``u0001`` for an unresolved region) is generated here and never taken from
#: the publisher; records that carry ids state this so a consumer never reads
#: one as a publisher identifier.
ID_ORIGIN = "generated"


def extra_available() -> bool:
    """Whether the ``reconstruct`` extra is installed. Tests skip on this rather than fail."""
    try:
        # lxml ships no type stubs, so `ty` cannot resolve the import; whether
        # the module is importable at all is exactly what is being asked.
        import lxml.etree  # noqa: F401  # ty: ignore[unresolved-import]
    except ModuleNotFoundError:
        return False
    return True


__all__ = ["EXTRA_REQUIRED", "ID_ORIGIN", "extra_available"]
