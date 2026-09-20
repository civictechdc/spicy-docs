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

G3 requirements and the committed-input measurement follow in the next change.
