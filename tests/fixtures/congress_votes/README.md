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

No fixture was reduced, truncated or reformatted; both are well under the 200
KB bound. Neither route takes a credential.

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

## Refusal and identity fixtures

Refusal tests in `tests/test_congress_votes.py` mutate small
synthetic-but-realistic bodies (`CLERK_MINIMAL`, `SENATE_MINIMAL`) rather than
these two files, so a shape violation is isolated to exactly the field under
test. The identity-proof tests reuse these real fixtures directly, parsed
against a deliberately wrong `VoteLocator`.
