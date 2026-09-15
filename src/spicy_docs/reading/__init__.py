"""Bounded reading mechanics shared by every publisher family.

These modules answer *how* captured bytes are read: XML/HTML markup with
original-byte positions, strict JSON, paged JSON traversal, S3 listings, zip
archives, PDF/image header facts, media types, refusal bodies and evidence
zip metadata. Publisher facts (*who*) live in :mod:`spicy_docs.sources`; each
family module states its own contract and bounds on top of these readers.

Import readers from their own submodule
(``from spicy_docs.reading.xml import parse_xml``). Package-level re-exporting
would recreate the eager heavy-import problem documented in
``spicy_docs/sources/__init__.py``.
"""
