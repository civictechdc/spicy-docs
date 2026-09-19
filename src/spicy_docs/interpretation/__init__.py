"""Shared judgment logic layered over publisher facts, source-agnostic.

A `sources.*` module reads what a publisher states, byte for byte. Modules
here take those typed facts as input and produce an interpretation no
publisher states directly -- a document's *kind*, a bill's legislative
*stage*, a classification. Interpretation is the one DRY home for this logic
(`docs/research/billtrax-value-inventory-2026-09-19.md`, "The split this
inventory assigns to"): every product that needs the same judgment imports
the same function instead of re-deriving it.
"""
