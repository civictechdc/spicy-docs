# Read CFR agency and subject metadata

These readers accept retained publisher bytes. Keep the input bytes, URL,
capture time and digest with the returned observations. They perform no network
requests and publish no release.

## eCFR agency roster

```python
from spicy_docs.sources.cfr.agencies import read_ecfr_agency_roster

roster = read_ecfr_agency_roster(payload)
for agency in roster.records:
    print(agency.source_path, agency.raw, agency.references)
```

The [eCFR API guide](https://www.ecfr.gov/developers/documentation/api/v1.json)
describes `/api/admin/v1/agencies.json` as a nested agency list. Each agency
contains names, a slug and references to CFR structure. Children can omit their
own `children` field. This rolling endpoint supplies no immutable version.

The reader preserves every row and reference in source order, including unknown
fields and malformed values. Paths distinguish repeated slugs. Missing, null
and empty fields remain distinct in `raw`; shape issues identify affected
paths. Decimal numbers stay `Decimal` values. Duplicate JSON keys, invalid JSON
and exceeded byte/node/depth limits refuse the read.

Callers decide which fields, agency counts, identifiers and relationships they
will accept. The reader does not match agencies across publishers.

## Archives subject index

```python
from spicy_docs.sources.cfr.subject_index import read_cfr_subject_index

index = read_cfr_subject_index(payload)
for block in index.blocks:
    print(block.tag, block.text, block.heading, block.issues)
```

The [Archives overview](https://www.archives.gov/federal-register/cfr/subjects.html)
describes fifty title pages listing subjects by CFR title and part. Their
native revision statement identifies the list's revision; a page review date
is separate metadata.

The reader returns ordered `dt` and `dd` blocks, their attributes, decoded text,
literal heading pieces and original inner HTML. `byte_span` is a half-open span
in the original input: `payload[start:end] == raw_html`. `text_fragments` split
at markup boundaries; `text` concatenates them without adding whitespace.
Callers can apply their own display whitespace rules.

`metadata` retains `h1`, `h3` and `p` observations, including page identity and
revision statements. It does not select a date or validate a requested title.
`list_index` distinguishes separate definition lists.
The retained title 30 page splits its revision statement across two paragraphs;
both observations survive separately.

No-term headings, `N/A`, blank entries, unknown headings and duplicate part
entries remain visible. Known heading irregularities have explicit labels:
missing keyword, `Oart`, leaked `strong>` and alternate separator. A heading in
a `dd` stays a `dd`; associating it with later terms is the caller's decision.
Malformed direct list tags, unmatched closes and orphan text have issue-bearing
blocks. Unclosed entries stop at the next entry, list boundary or end of input.
Invalid UTF-8 gets replacement text and an issue; original bytes remain exact.

Bounds cover input bytes, returned blocks and each block's source length.
The parser accepts imperfect HTML; a successful read does not certify valid
markup, complete title coverage, legal applicability or assignment readiness.
