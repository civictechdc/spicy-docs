"""Reconstruct a publisher's structured vocabulary from a rendition that has none.

**Retrieve, then reconstruct, then interpret; never in the other order**: this
package runs only where retrieval has nothing structured to give, and what it
produces is a *derivative* -- every serialized file travels with a source map
back to the evidence it was built from, every node names the rule or the model
call that placed it, and a hosted row derived from it says ``derivation =
reconstructed``. The five modules run in the order a document passes through
them: ``profiles`` (frozen, versioned vocabulary records with their rules),
``evidence`` (the evidence-linked document model), ``parse`` (the
deterministic parser, with the injected ``classify_and_attach`` model seam
where rules cannot decide), ``serialize`` (deterministic XML plus a source
map) and ``validate`` (five findings and the gates over them). Everything but
``validate.schema_validity`` is standard library; that check needs ``lxml``
and names the ``reconstruct`` extra when it is absent.
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
