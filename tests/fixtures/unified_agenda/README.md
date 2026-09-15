# Unified Agenda fixture

`reginfo-rin-data-202510.xml`: the Fall 2025 edition export from
`https://www.reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_202510.xml`, captured 2026-09-14 keyless, reduced to the root
element with its attributes and the first 2 of 3,954 `RIN_INFO` records
(7,183 bytes, SHA-256 `95bb0fc531bc79b6f0582096ecb1485d01aba79082350056ff07120f64825c83`).
The complete response is 17,624,465 bytes, SHA-256 `4dc85fe08251eed1499dee5f2a2f7e3fcf4717baf468409c1f884dd68782b75f`, which
equals the digest and length RefSpec pinned independently for the same edition.
Abstracts carry HTML inside CDATA, including a literal `<!DOCTYPE html>` that
is text, not a declaration. The full file is in
`corpora/supply-2026-09-02/receipts/spicyregs-merge-probes-2026-09-14/`.

`record-199704-1115-AE47.xml` retains a historical record with a legal-authority
continuation in `ADDITIONAL_INFO`. `record-200404-1084-AA00.xml` retains the
publisher's XML-invalid `0x19` byte in an abstract; the source reader must refuse
it. Neither fixture repairs or normalizes the publisher's text.

Both fixtures combine the unchanged source prolog/root opening and one complete
record with an appended closing root tag. `records-provenance.json` records
their original URLs, byte spans, source and fixture pins, and transformations.
Full retained editions remain in RefSpec's
`output/registry-real-data-sources/unified-agenda-editions/`.
