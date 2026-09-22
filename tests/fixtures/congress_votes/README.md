# House Clerk and Senate LIS roll-call vote fixtures

Complete, unchanged publisher XML bodies for one real vote per chamber,
captured keyless on 2026-09-19. Both digests match the 2026-09-18 measurement
in `docs/research/legislative-data-map-2026-09-18.json` (`samples.clerk-vote`,
`samples.senate-vote`) exactly, so neither file changed between that
measurement and this capture. These U.S. government roll-call records are
public domain.

| Fixture | Publisher response | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `clerk-roll240.xml` | [`clerk.house.gov/evs/2025/roll240.xml`](https://clerk.house.gov/evs/2025/roll240.xml), keyless | 82,515 | `0297b0c76d3c14452a91daf9828943e5669c00dcc408c07bc80870b9d8223542` |
| `senate-vote-119-1-00001.xml` | [`www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.xml`](https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00001.xml), keyless | 28,670 | `9d71d78a54c83522babd743209ca4a1a27baa2df122d6830c50ec2aa512ea17e` |
| `senate-vote-menu-119-1.xml` | [`www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_119_1.xml`](https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_119_1.xml), keyless -- **excerpt**, see below | 19,841 | `55c6f51697a46eac80bf151971bf6d9f428681e7eb1b54f828d7a62c3502789d` |

Both vote-body fixtures are the complete, unmodified publisher response and
are well under the 200 KB bound. Neither route takes a credential.

The menu fixture is not complete: captured 2026-09-19, the real
`vote_menu_119_1.xml` body is 419,112 bytes (sha256
`bbf37be1e0fe327fb6cd623cc7b2ed56253f5410ec0066831ba5eba605244a0c`) -- over
the 200 KB fixture bound named in the gap this fixture closes (A4), because
the 119th Congress's 1st session had recorded 659 votes by the capture date.
Per that bound, `senate-vote-menu-119-1.xml` keeps a **byte-exact head plus
tail excerpt** of the real response rather than the whole body: the first six
`<vote>` elements (`vote_number` 659 down to 654, in the publisher's own
newest-first order, including one `<en_bloc>` batch-confirmation vote) and
the last four (`vote_number` 4 down to 1, including two votes whose
`<question>` carries a nested `<measure>`), each copied verbatim from the
real response and concatenated around the unchanged `<vote_summary>`/
`<votes>` header and footer -- nothing in either kept span was rewritten,
reformatted or re-encoded. The table's SHA-256 is this 19,841-byte excerpt's
own digest (what the file on disk actually hashes to); the digest above is
the full 419,112-byte body's, for anyone re-fetching the live route to
confirm the excerpt is still a faithful subset.

## What each fixture is

`clerk-roll240.xml` -- 119th Congress, 1st session, roll 240 (H.R. 3424, the
SPACE Act, "On Motion to Suspend the Rules and Pass," 8-Sep-2025). Root
`<rollcall-vote>` with an external DOCTYPE
(`-//US Congress//DTDs/vote v1.0 20031119 //EN`), which
`reading/xml.py::parse_xml(allow_external_doctype=True)` tolerates without
resolving. 430 `<recorded-vote>` rows across three `totals-by-party` rows
(Republican, Democratic, Independent) that sum exactly to the
`totals-by-vote` grand total (397 Yea, 1 Nay, 0 Present, 32 Not Voting) --
only three spelled vote values appear (`Yea`, `Nay`, `Not Voting`); the DTD's
wider vocabulary (`Aye`/`No`/`Present`, used on a plain RECORDED VOTE rather
than a YEA-AND-NAY vote) is accepted by `normalize_vote` but not exercised by
this fixture.

`senate-vote-119-1-00001.xml` -- 119th Congress, 1st session, vote 1 ("On
Cloture on the Motion to Proceed S. 5," January 9, 2025). Root
`<roll_call_vote>`, no DOCTYPE. 99 `<member>` rows (84 Yea, 9 Nay, 0 Present,
6 Not Voting -- the Senate calls this bucket `absent`); `<tie_breaker>` is
present but empty (`<by_whom/>`, `<tie_breaker_vote/>`), since the vote was
not tied. Three of its members -- Cantwell (`S275`), Sanders (`S313`) and
Warner (`S327`) -- are long-serving senators who are also in
[`tests/fixtures/legislators/legislators-current-excerpt.json`](../legislators/legislators-current-excerpt.json),
so the LIS crosswalk test in `tests/test_congress_votes.py` reuses that
excerpt rather than adding a second one; the other 96 members resolve to
`bioguide_id=None`, since that small excerpt (5 of 539 current legislators)
carries only those three.

`senate-vote-menu-119-1.xml` -- the 119th Congress's 1st-session Senate
roll-call index (see above for how it was excerpted). Its ten `<vote>`
entries are exactly the real menu's first six and last four, in the
publisher's own order: `vote_number` 659 ("Motion to Invoke Cloture: Sara
Bailey to be Director of National Drug Control Policy") down through 654,
then 4 down through 1. The last entry, `vote_number` 1, is the same vote
`senate-vote-119-1-00001.xml` carries in full, so the locator this menu
entry builds round-trips to that already-fixtured file without a second live
fetch. Vote 655 is the excerpt's one `<en_bloc>` batch-confirmation vote (97
`<matter>` rows, no vote-level `issue`/`question`/`result` of its own); votes
4 and 3 each carry a `<question>` with a nested `<measure>` (`S.Amdt. 23`,
`S.Amdt. 14`) -- the one other shape the menu states beside the plain form.

## Refusal and identity fixtures

Refusal tests in `tests/test_congress_votes.py` mutate small
synthetic-but-realistic bodies (`CLERK_MINIMAL`, `SENATE_MINIMAL`,
`SENATE_MENU_MINIMAL`) rather than these real files, so a shape violation is
isolated to exactly the field under test. The identity-proof tests reuse the
real fixtures directly, parsed against a deliberately wrong `VoteLocator` or
a deliberately wrong `(congress, session)` pair.

## Candidate election fixture

`clerk-speaker-119-1-2.xml` is the complete, unchanged House Clerk response for
the 119th Congress, session 1, roll 2, Election of the Speaker:
[`clerk.house.gov/evs/2025/roll002.xml`](https://clerk.house.gov/evs/2025/roll002.xml).
Captured keyless on September 22, 2026 at 03:19:51 UTC, it is 85,579 bytes,
SHA-256 `32823e0664ec72fa387d3956b09e1d6f25c939274fc1ccb7d5d3ebb9cd2984b0`.
The raw `vote-type` says `YEA-AND-NAY`, but its native structure is
`totals-by-candidate`: Johnson (LA) 218, Jeffries 215, Emmer 1, Present 0,
Not Voting 0. All 434 literal member choices reconcile with those counts.
The parser therefore selects its tally kind from the native structure,
not the vote-type label. Named choices have no normalized yea/nay position.
This public-domain government source is a bounded regression witness; it
does not establish coverage of other elections.

## Multiple-document Senate fixture

`senate-vote-119-1-00522.xml` is the complete, unchanged Senate response
for Congress 119, session 1, vote 522:
[`vote_119_1_00522.xml`](https://www.senate.gov/legislative/LIS/roll_call_votes/vote1191/vote_119_1_00522.xml).
Captured on September 22, 2026 at 03:30:51 UTC, it is 65,978 bytes,
SHA-256 `418eb3d0635cf1f1f4e8565af24b794d24b1436dd282648742e3f1dbb752803e`.
It states 48 ordered document blocks and 48 ordered amendment blocks,
plus 100 native member observations. The first document numbers are
`55-25`, `55-45` and `54-7`, retained as text. Repeated amendment blocks
carry empty identifiers and the literal purpose “No Statement of Purpose
on File.” They remain separate observations; equal array lengths do not
establish an association between documents and amendments.
