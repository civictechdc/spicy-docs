# Acquisition decisions retained during refactoring

These notes explain current rules and their available provenance. Keep campaign
narratives and measurements with corpus receipts.

## Community supply precedes origin acquisition

Prefer spicy-regs public tables for data they carry. Capture whole named agency
Parquet objects, retaining locator, fetch time, stated freshness, size, and
SHA-256 before classifying rows. Origin acquisition supplies missing coverage.
A live query result cannot substitute for pinned input.

The former README cited a platform `PLAN.md`, “Supply-precedence ruling,”
accepted 2026-08-31. That plan is not retained here. Available evidence is in
commits `48dac81` (capture) and `b25a3e9` (ruling tests),
`spicy_regs_public_tables_source_native.py`, and its tests. This note records
implemented behavior, not a reconstruction of the missing plan. Sources remain
explicit CLI choices; fallback is not automatic.

## Federal Register identity and fields version separately

Acquisition policy `1.1` identifies a record by
`(document_number, publication_date)`. Requested-field policy remains `1.0`:
`correction_of` was proposed with the identity change, then deferred and never
added to the accepted fields or schema. Do not force these versions to match.
Adding that field requires a new acquisition-policy decision.

This is the implemented result of SD-24 / DocSpec decision 0003,
`docs/decisions/0003-federal-register-record-identity.md` in the DocSpec repository.
That record includes superseded proposals. Local authority is
`sources/federal_register/profile.py`, accepted field sets in
`federal_register_source_native.py`, and identity/replay tests. The adopted
[release specification](superpowers/specs/2026-08-25-source-native-release-spec.md)
defines shared publication requirements.

## Similar sources can need different rules

Regulations.gov documents and dockets select the newest observation. Identical
same-instant observations may collapse. Document ties changing only
`openForComment` use a narrower tie comparison while preserving the canonical
observation digest. Equal-version comment ambiguity is refused. These are
source rules to preserve when sharing mechanics.

Regulations.gov and captured public comments share strict integer-only JSON
decoding with source-specific exceptions and wording. Federal Register keeps
distinct finite-float/non-finite diagnostics and response-shape checks; GAO
requires canonical capture manifests. These differences remain deliberate.

## GAO evidence is bounded and literal

Capture a closed, sorted set of at most 1,000 product IDs through the bounded
Zyte raw-HTTP transport. Each HTML body is at most 8 MiB; total HTML is at most
1 GiB. Preserve exact bytes and the one literal publisher topic anchor. A release
covers its named products, not the whole catalog. Topic interpretation belongs
downstream. See `gao_product_pages_source_native.py` and the offline example.
