# Chamber committee-roster fixtures

Captured 2026-09-19 for the A9 gap (committee assignments). Both files are
keyless and these U.S. government documents are public domain. Offline tests
establish behavior for these shapes; they do not establish coverage or
continuing live availability. The complete originals, their digests and the
whole-file counts (2,516 House assignments, 450 Senate committee seats, 9
placeholders) are in
`corpora/supply-2026-09-02/receipts/roster-comparison-2026-09-19/`.

| Fixture | Publisher object | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `memberdata-119-excerpt.xml` | reduced: [`MemberData.xml`](https://clerk.house.gov/xml/lists/MemberData.xml) (556,936 bytes, `sha256:07aec65948e99fd80b5e7c31722f1208d9f5e0717ba00f4b02122f4724cb0c18`): everything before `<members>`, five complete `<member>` elements, and the complete `<committees>` block, closed | 47,942 | `e08fe24e5b524b6d5cefc98be01e95862089b78711c204010966b9f5ba8c945d` |
| `cvc-member-data-excerpt.xml` | reduced: [`cvc_member_data.xml`](https://www.senate.gov/legislative/LIS_MEMBER/cvc_member_data.xml) (67,618 bytes, `sha256:9dd6448867e0dfa76512f11dc83369219f4a5f2aaa5fae75a6806d509e9edc96`): everything through `<lastUpdate>`, six complete `<senator>` elements, closed | 3,847 | `e11c521410a81b5d9992314e84021a3ecffc9d438e832b9438e602b53d26683a` |

## Reductions, stated exactly

Every reduction is a byte-exact selection of the publisher's file; nothing
inside a kept span was rewritten.

- **House.** The five `<member>` elements are the seats for AK00, AL01, AL03
  and CA11 kept in file order, plus FL20 because it is a **vacancy** (every
  `member-info` field empty, one `<committee rank=""/>` placeholder), plus AL03
  for the one member carrying `leadership="Chair"`. The `<committees>` block is
  kept complete: all 27 committees and their 109 subcommittees, so every
  assignment code in the excerpt resolves to its printed name and parent.
- **Senate.** The first five `<senator>` elements in file order, plus the next
  one carrying `position="Chairman"`, so a leadership position and a
  multi-committee senator (six committees) are both in the fixture.
- No session ids or menus to strip: neither file is HTML.

The build script is `build_fixtures.py` in the receipt directory, beside the
originals; it prints each source's and each fixture's size and SHA-256.

`memberdata-119-select-excerpt.xml` is a bounded cut of the House Clerk capture
retained September 22, 2026 UTC (native publish-date September 2, 2026). It keeps
literal title information, three complete member elements, and the IG00, QJ00
and ZS00 committee elements with their native type and children. The root and
wrapper whitespace were assembled; source field values were not edited.
Source SHA-256: `07aec65948e99fd80b5e7c31722f1208d9f5e0717ba00f4b02122f4724cb0c18`.
The exact source/fixture pins and full assignment replay are retained in
`~/Work/corpora/fork-execution-2026-09-21/rosters-qualification/select-code-fix/`.
