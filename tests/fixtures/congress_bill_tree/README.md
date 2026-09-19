# Bill-tree structural fixtures

**These three files are constructed, not captured.** They are not publisher
bytes and no test here may be read as evidence about what GPO serves. They
exist because the shapes the tree parser must walk — divisions holding titles,
appropriations blocks under a `resolution-body`, a parenthetical continuation
header, a structural `subtitle` — are not present in any sample whose bytes this
repository retains.

Real, captured bill and resolution XML lives one directory over in
[`../govinfo_bills/`](../govinfo_bills/README.md), and the bill-tree tests use
those files for everything they can establish, including the `resolution-body`
case (`text-119hjres25enr.xml`, a complete unchanged 2,751-byte response).

## What each file reproduces, and from which measurement

Every structural claim below is taken from the per-file element inventory in
`docs/research/billtrax-raw-data-2026-09-19.json`
(`sources.billXmlStructure.files`), measured on 2026-09-19 over 40 files.

| File | Reproduces | Measured source |
| --- | --- | --- |
| `constructed-resolution-appropriations.xml` | A joint resolution making continuing appropriations: `resolution` root, `resolution-stage`, relative `res.dtd` SYSTEM id, `resolution-body` holding `title` → `section` → `appropriations-major`/`-intermediate`/`-small`, one parenthetical `-small` header, one `subtitle`, a `toc`, and `subsection` children | `BILLS-119hjres143ih.xml`, the only appropriations-structured document in the sample: 8 `appropriations-major`, 6 `-intermediate`, 5 `-small`, 13 `title`, 26 `section`, 47 `subsection`, 2 `toc`, 1 `subchapter`, inside a `resolution-body` and no `legis-body` |
| `constructed-bill-divisions.xml` | A bill with two `division`s, each holding `title`s, one `subtitle`, a section beside the divisions, and two sections sharing one `match_path` across divisions | `division` appears in 2 of the 10 sampled bills (13 occurrences); the division → title → section shape is the first of the three `normalize_bill` handles |
| `constructed-bill-divisions-engrossed.xml` | The same bill one stage later: one section's dollar amount changed, one section added, one section removed | The diff engine's `modified`/`added`/`removed` paths and the cross-division collision group |

The two `constructed-bill-divisions*` files carry a `Sec. 101` in each division,
so they collide on one `match_path` and the diff has to resolve them by division
key. That is deliberate: it is the case the engine's `_match_collision_group`
exists for, and the case a division-label display change could silently rewire.

Dollar amounts, headings and identifiers in these files are invented. They are
sized and spelled to look like the real thing so a reader is not misled about
the *shape*, and they establish nothing about the *content* of any real bill.

## What these fixtures cannot see

A constructed fixture proves what the engine does with a shape; it cannot prove
the publisher writes that shape, and it cannot surface markup nobody thought to
construct. Two things stand in that gap. DeltaTrack's own suite runs against a
real corpus — 3,822 cases at the pinned revision — and is what establishes the
engine's behaviour on documents these files only imitate. And the
element-inventory test in `tests/test_congress_bill_tree.py` counts every start
tag in the bytes with a regex — a different tool family from the expat parse
under test — and requires the census to agree, so an element nothing read shows
up as a discarded count rather than as nothing at all.
