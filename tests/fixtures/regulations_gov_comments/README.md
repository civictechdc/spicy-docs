# Source-stated comment parent references

`ODNI-2009-0004-0002.source.json` is the complete retained Mirrulations response
reviewed on 2026-09-24, copied byte-for-byte from the SpicyRegs
`comments_null_dockets` fixture. SHA-256:
`d5ac7aa71069e0b52efc05497f623f804118b029db76ba0a967680ed64433413`.

The retained `source-receipts.json` supplies original locators, times and object
hashes for that source review. It also lists other observations not copied here.
This fixture names a parent document even though its native docket is null.
The object ID, public document ID and original document ID are different fields.
The directory or an ID prefix cannot supply a missing docket relationship.

This is an offline preservation test, not a fresh acquisition or population claim.

## Submitter class and campaign count

Four complete Mirrulations comment objects, read on 2026-09-28 and copied
byte-for-byte; each object's MD5 equals its listed S3 ETag.

| File | Mirrulations key under `s3://mirrulations/raw-data/` | Last-Modified | SHA-256 |
| --- | --- | --- | --- |
| `EPA-HQ-OW-2022-0114-1811.source.json` | `EPA/EPA-HQ-OW-2022-0114/text-EPA-HQ-OW-2022-0114/comments/EPA-HQ-OW-2022-0114-1811.json` | 2025-04-13 20:20:23Z | `dccedb9f286dfca158b5a2ae6d0a77cda946b7d1fd884098e36a2444391b0261` |
| `EPA-HQ-OW-2022-0114-0017.source.json` | `EPA/EPA-HQ-OW-2022-0114/text-EPA-HQ-OW-2022-0114/comments/EPA-HQ-OW-2022-0114-0017.json` | 2025-04-13 20:20:15Z | `895d3528bd3bdaa12cd1e43ff9401c8f388724e0a7fa338d8454015fedd43127` |
| `EPA-HQ-OW-2022-0114-0002.source.json` | `EPA/EPA-HQ-OW-2022-0114/text-EPA-HQ-OW-2022-0114/comments/EPA-HQ-OW-2022-0114-0002.json` | 2025-04-13 20:20:15Z | `69ec303bb31cac609d99c9619109059c95a8d5e4133e125f1826e7d0b23829af` |
| `CMS-2016-0123-0993.source.json` | `CMS/CMS-2016-0123/text-CMS-2016-0123/comments/CMS-2016-0123-0993.json` | 2025-04-13 11:16:02Z | `8d6e7d9e6dcbcd02d7c597690836175eb0ace9a5402ac8323df7c65f53961630` |

The three EPA records are from the PFAS drinking-water docket: a
`Mass Mail Campaign` record standing for 15,851 submissions (National Wildlife
Federation Action Fund), a `Company/Organization Comment` whose `organization`
is NULL, and a `Public Comment`; EPA states `duplicateComments` 1 for each
single comment. The CMS record states `Public Comment` and
`duplicateComments` 0, the value agencies that do not count leave.

## Attribute census

`attribute-census.json` is `full_census_summary.json` from
`~/Work/corpora/supply-2026-09-02/receipts/comments-full-reread-2026-09-28/comment-attributes/`,
copied byte-for-byte (SHA-256
`239ee63e30d3ee1f0e76eb52988d6204edba922e56fcad8d5e710d037f7a6e23`). Its script,
`full_census.py`, read every part of the spicy-regs re-read of every comment the
ETL manifest listed (plan `2e9c995713c0f403-s2`, 2026-09-28). For each attribute
the thin table does not map, it lists the rows that state it (non-null) and its
exact number of distinct values. `test_comment_attributes` holds
`comment_attributes`' columns and `COMMENT_ATTRIBUTES_LEFT_OUT` to it.
