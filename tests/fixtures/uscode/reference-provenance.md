# Reference-reader fixture provenance

`title-05-s423.xml` is an unchanged copy of RefSpec's retained fixture at
`tests/fixtures/uslm-source-links/title-05-s423.xml`. It contains the U.S. Code
section's USLM markup, inline source credit, notes and XHTML table links inside
an `uscDoc` wrapper. It is a fragment, not a complete title release.

- Bytes: 12,406
- SHA-256: `1b48c549c44207d1d0ab796bfdbcd81a0059cf4ed822ff3c3c8652f0484bb6a1`
- Native section identifier: `/us/usc/t5/s423`
- The retained fragment does not state a release point; none is inferred here.

The tests also read complete `usc01.xml` and `usc50A.xml` members already
described in [the fixture inventory](README.md). Independent ElementTree walks
check every reference, source-credit text, attribute, ancestor and element path.
Constructed mutations cover unfamiliar references, missing identifiers, empty
credits, malformed XML and resource limits. These checks establish source
fidelity for the retained inputs, not legal meaning or publisher completeness.
