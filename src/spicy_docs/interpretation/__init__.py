"""Shared interpretation of publisher facts: rules in tables, findings that name the rule.

Acquisition and publisher-format parsing live under ``spicy_docs.sources``;
this package decides what those typed facts mean -- a bill's stage, whether it
is a money bill and of which kind, which catalog bill a loose PDF is, which
bill a recorded vote or a press release refers to, which member a sponsor
string names, which sections answer an interest area, and the two model-backed
labels. Every module here is pure and source-agnostic -- no network, no
database, no clock beyond an injected one -- takes this repository's own
dataclasses or plain mappings shaped like the published tables, and returns
frozen findings carrying the rule that fired and the identifiers it fired on.
Rules are data, a tuple of frozen records read in order, so a vocabulary has
exactly one home and a reviewer reads the ladder rather than the control flow.
"""
