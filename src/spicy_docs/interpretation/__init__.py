"""Judgements derived from acquired source records, kept apart from acquisition.

A source module reads what a publisher served and proves its identity; nothing
in it decides what the bytes mean. The modules here do decide: that two sections
of different printings are the same section modified, that one moved, that a
dollar figure changed. Each names its threshold, its origin and what it was
measured against, because a judgement without those is not reproducible. Read
[the source workflow](../../../docs/source-workflows.md) before moving anything
across that line.
"""
