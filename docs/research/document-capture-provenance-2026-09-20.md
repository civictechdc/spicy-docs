# DocumentCapture provenance: G3 and G4

G4's public-law correction keeps the XML member and its ZIP archive as
separate byte objects. `artifact.locator.path` names the unchanged XML fixture;
`artifact.sha256`, `byteSize` and `mediaType` describe that member.
`profile.ext.archiveMember` names `PLAW-119publ1.xml`, repeats its byte facts
for an explicit equality check, and holds the archive's URL, retained path,
digest, size, media type and full acquisition timestamp. The member inherits
the archive acquisition time; it does not claim a separate HTTP request.

The original retained ZIP was read offline and its unique member compared
byte for byte with the fixture. The bounded receipt excerpt is
`tests/fixtures/document_capture_provenance/public-law.json`, which pins the
original receipt by path, digest and line. Generic artifact checks compare
**each** stated locator with independent retained evidence: hashing a local
XML file cannot justify associating its digest with a ZIP URL. Tests restore
that wrong association and require a finding.

## Required provenance in SpicyDocs

`spicy_docs.schemas.document_capture.provenance.check_provenance(capture)`
returns findings with codes and JSON paths. Run it in addition to the pinned
parent/profile schemas and Rulespec invariants. It performs no acquisition.
`FAMILY_REQUIREMENTS` is the executable family policy; explanations of missing
evidence do not turn findings into passes.

| Family | Required source provenance | Additional requirements |
| --- | --- | --- |
| `uslm-law` | Acquisition record, publisher URL, full timestamp, GovInfo pair, pinned MODS identity | Archive/member association when archive-sourced |
| `bill-xml` | Acquisition record, publisher URL, full timestamp, GovInfo pair, pinned MODS identity | Native bill identity remains in the existing profile |
| `committee-report-html` | Acquisition record, publisher URL, full timestamp, GovInfo pair, pinned MODS identity | Decisions for blank-line blocks, table rows and cells |
| `federal-register-xml` | Acquisition record, publisher URL, full timestamp | Existing publication identity and dates; decision for generated back matter |
| `cfr-reconstruction` | Acquisition record, publisher URL, full timestamp, GovInfo pair, pinned MODS identity | Extractor intermediate, page dimensions, decisions including generated root and own-text children |
| `slip-opinion-pdf` | Acquisition record, publisher URL, full timestamp | Extractor intermediate, page dimensions, decisions for pages, lines and opinion groups |
| `senate-expenditures-pdf` | Acquisition record, publisher URL, full timestamp, GovInfo pair, pinned MODS identity | Extractor intermediate, page dimensions, decisions for root, pages, lines and tables; original PDF and cut method for a derived fixture |

All families require a stated rendition-selection reason. All stated
`page-region` coordinates require a positive page and ordered four-value
permille box; `utf8-byte` requires its range; `xml-node-path` requires its
path. A page container covers `[0, 0, 1000, 1000]`. Missing cell boxes remain
findings. Multi-page wrappers use their descendants' span references; the
current parent has only one direct node source, so it cannot state multiple
page regions on a wrapper. No invented union across pages is written.

The paired identity includes explicit `granuleId: null` for a package-level
rendition; null never means an unknown granule. CFR's pair comes from its
retained URL and granule record. Public-law identity comes from the retained
member name and validated USLM identity. Bill identity comes from its retained
URL. These remain distinct from MODS-backed pairs. The committee report's
complete MODS and the Senate granule's complete MODS are parsed afresh and
pinned, with the exact identity element paths. Senate's host record supplies
the package id and its root supplies the granule id.

The Senate capture's artifact remains the derived one-page PDF. Its
`derivedFrom` extension owns the full publisher PDF's URL, digest, timestamp,
original page 17 and cut method. Putting that URL or retrieval timestamp on
the cut would repeat G4 in a different family. Its internal page 1 remains
correct for its own bytes.

### Evidence limits that remain findings

The CFR receipt explicitly says its acquisition run retained no per-request
log. The committee-report fixture records only 2026-09-19. Neither justifies
inventing a full timestamp. No matching MODS was retained for the worked bill,
public law or CFR section. Six Senate cells have text but no observed box.
The committed captures therefore retain 11 findings: two timestamps, three
MODS records, and six coordinate findings. The other two families have none.
G3's converter and package-check work is delivered; complete source evidence
and parent-level enforcement remain open.

## What rulespec must change

The parent and profile meta-schema in this repository remain byte-identical
to their pinned originals. The USLM extension is a temporary family-owned
representation, not a change to the meaning of the parent.

1. Add shared archive/member provenance to
   `release-records/schemas/document-capture-v1.schema.json`. An archive must
   have its own locator, SHA-256, byte size, media type and retrieval timestamp;
   a member must name that archive and its exact entry path. The member's
   artifact digest and media type describe uncompressed member bytes. Require
   equality between repeated member byte facts and the artifact. Reject a ZIP
   locator used as the member's direct locator. The byte validator must verify
   both the archive and the uniquely named member; duplicate entry names
   require an ordinal or an explicit ambiguity refusal.
2. Migration must move this profile extension into the shared representation,
   publish updated parent/meta-schema/validator resources, and update pins
   and captures together. SpicyDocs cannot tighten parent fields through the
   current profile meta-schema; no vendored parent file is edited here.

3. Define a shared `SourceRecord` with role (`acquisition`, `mods`, or
   `derivation`), its own exact byte pin (`sha256`, `byteSize`, `mediaType`),
   locator, and evidence selector. Acquisition records must identify the
   publisher URL and full RFC 3339 timestamp, including recorded fractional
   seconds and timezone; conversion time and publisher Last-Modified are not
   substitutes. MODS records must name the exact retained metadata bytes and
   identity paths. Preserve the publisher's package id and a separately named
   granule id as a pair, with explicit package/granule scope. Require a
   non-null granule id for granule scope. Bind MODS claims to that same pair.
   Do not require GovInfo identity on Federal Register or Supreme Court data.
4. Add a shared derived-artifact relationship: the original artifact has its
   own URL, digest and retrieval time; the derivative has its own locator and
   digest plus the method and source-page mapping. A locally generated PDF cut
   must never inherit the original's URL as its own direct locator. Keep
   acquisition and derivation timestamps distinct.
5. Require an acquisition source record and publisher locator for acquired
   renditions (through an archive or original artifact for members/derivatives).
   Require a full acquisition timestamp on newly conforming records. A legacy
   date-only record must remain an explicit incomplete finding, not a fabricated
   midnight or a successful full-precision record. Require an extractor
   intermediate for PDF and OCR renditions and a rendition-selection/fallback
   reason. For each applicable family require the paired GovInfo identity and
   MODS reference described in the table above.
6. Add conditional `SourceLocator` requirements: `page-region` requires
   `page` and `box`; `utf8-byte` requires `start` and `end` with ordered bounds;
   `xml-node-path` requires `path`. Apply these to effective span sources after
   defaults merge as well as direct node sources. Require dimensions for every
   referenced PDF page. Add a multiple-region source form for multi-page nodes;
   preserve evidence references for generated wrappers rather than requiring
   them to steal their children's spans. Missing observed geometry must remain
   a finding, even when an issue explains it. Require cell row/column identity
   and observed geometry for PDF cells; do not invent spans or header flags.
7. Require `Decision` for reconstructed, markup-derived, PDF/OCR-derived and
   generated nodes, including wrappers and inferred heading levels. Add a
   dedicated rule-version binding to its implementation pin and dependencies;
   the current converter digest and rule string do not express that binding.
   Distinguish publisher-read fields from fields inferred on an otherwise
   native node. Do not infer this distinction solely from the presence of a
   decision, since deleting it must still produce a finding.
8. Extend `document-capture-profile-v1.schema.json` with a narrowly defined
   declaration of applicable provenance requirements referencing shared parent
   definitions. Keep arbitrary overrides of parent fields forbidden. Move
   `sourceRecords`, `govinfoIdentity`, `derivedFrom`, `renditionReason` and the
   archive/member extension out of these family extensions only when the owner
   publishes the equivalent shared representation. The current meta-schema
   permits closed extension values but neither reusable `$defs`/`$ref` inside
   them nor tightening parent fields, so these shared changes are unbuilt here.
9. Add negative fixtures and invariant tests for missing/mismatched source
   pins, unpaired identities, missing MODS evidence, date-only or truncated
   timestamps, wrong archive/member associations, derivative/original URL
   confusion, incomplete effective coordinates, missing page dimensions,
   reconstructed wrappers without decisions and stale rule-version bindings.
   Release parent/meta-schema/validator together, then move SpicyDocs profiles,
   `PINS.json`, dependency pin and committed captures together. Keep the current
   pinned bytes unchanged until that release.

Normalized `bill_id`, USC/FR citation targets, dockets, RINs and committee-code
relationships stay in downstream analytical tables linked to capture evidence.
Their absence from a capture is measured, not repaired by guessing from text.
Source-native bill/law identity and FR citation remain in their family
extensions. The pinned MODS records now also carry ordered source fields,
including identifiers, dates, bill/law references and committee authority ids,
with literal values, attributes and XML child-index paths. FR retains the
publisher JSON path/digest, docket strings, stated RIN list (empty here), and
literal dates text. They are not evidence
of a normalized relationship model.
