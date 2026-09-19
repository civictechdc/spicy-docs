"""Shared interpretation of publisher facts: rules in tables, findings that name the rule.

Acquisition and publisher-format parsing live under ``spicy_docs.sources``;
this package holds what is decided *about* those facts once they are typed --
a bill's stage, whether it is a money bill and of which kind, which catalog
bill a loose PDF is, which bill a recorded vote or a press release refers to,
which member a sponsor string names, which sections answer an interest area,
and the two model-backed labels (section classification and plain-language
summary). Every module here is pure and source-agnostic: no network, no
database, no clock beyond an injected one, inputs that are this repository's
own dataclasses or plain mappings shaped like the published tables, and
outputs that are frozen records carrying the rule that fired and the
identifiers of what it fired on, so a hosted table can store that provenance
beside the value. Rules are data -- a tuple of frozen rule records read in
order -- so a vocabulary has exactly one home and a reviewer reads the ladder
rather than the control flow.
"""
