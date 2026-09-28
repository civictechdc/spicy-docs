# Read a bill's legislative stage

`interpretation.bill_stage` reads retained BILLSTATUS actions and reports the
matched rule, full action text, date, and position. `bill_family` uses the same
code-aware reader for bill-level and action-level rows. Raw publisher action
codes, types, dates, times, and text remain in the source/action tables.

`STAGES` and `STAGE_KEYS` retain the progress ladder. `OUTCOME_STAGES` adds
`failed` and `vetoed` as separate display labels. They are not progress
percentages: `stage_index` returns `-1` and `stage_progress` raises `ValueError`
for either. No inspected production caller composes stage inference with
`stage_progress`; the bill and action table columns accept strings. Consumers
with a fixed allowlist must add these outcomes before adopting this version.

The latest classified action wins by date, then by place in the list. A
BILLSTATUS list runs newest first (no exception among the 930,779 actions of the
live generation measured on 2026-09-28), so `bill_family` passes
`newest_first=True`; a caller with a chronological list keeps the default. The
list's order, not `actionTime`, orders one day's actions: it already follows the
stated times and places the untimed Library of Congress actions among them.
Unknown actions leave the result alone. A failed passage vote can be
followed by a successful one. A veto stays visible through consideration and a
single chamber's override vote; recorded enactment ends it. `law` is displayed
as **Became law**, covering signature and veto override. An agreed simple
resolution reports `passed_chamber`; it does not become a law.

Public prints and star prints do not establish a legislative stage. Enrollment
establishes passage, not presentation to the President. Committee referrals
establish committee consideration, not arrival in the other chamber. Debate on
passage, failed procedural motions, and passage of another bill's special rule
do not establish passage of this measure. The text reader recognizes explicit
passage results, including suspension votes; it does not infer a result merely
from the words “on passage.”

Only narrowly qualified codes supplement text. `36000`, `E40000`, or the
`BecameLaw` type establish enactment; `8000`/`17000` establish chamber passage;
`28000`/`E20000` establish presentation. Explicit failed/veto text overrides a
contradictory passage code. The enacted-code rule remains the same source rule
used by the existing signing-date reader. Unknown codes use text. `E30000` is
intentionally excluded: the retained GPO guide describes signature, but actual
veto records also carry that code. Codes alone are not a universal event map.

## Why these corrections are qualified

The independent cases came from
[unitedstates/congress action tests](https://github.com/unitedstates/congress/blob/8184bcb13160da2389dea4c902de67817db681fc/test/test_bill_actions.py)
and its [vote transitions](https://github.com/unitedstates/congress/blob/8184bcb13160da2389dea4c902de67817db681fc/congress/tasks/bill_info.py#L1140).
We then retrieved complete official histories and retained the regression
inputs under [`tests/fixtures/bill_stage`](../../tests/fixtures/bill_stage/).

- `111-HJRES64`: veto followed by a failed House override, previously shown as
  passed. The result is now `vetoed`.
- `118-HRES5`: introduced and agreed on the same day. Read in its declared
  direction, either list order reports `passed_chamber`; reading the
  newest-first file as chronological selected the introduction, the defect that
  also left most referred bills reading `introduced`.
- `118-HR5525`: the House rejected passage. The result is `failed`; the preceding
  failed motion to recommit does not determine the passage result.

The dated workspace review retains additional live controls for enacted bills,
an override, and ordinary passage. A replay of the live bill-family generation
(`c28ed5b1…`, 2026-09-28) through the 0.50.1 rules reproduces every published
stage, rule, matcher and action index of its 172,991 bills with actions; the
0.51.0 rules change the stage of 154,374 of them, most from `introduced` or
`other_chamber` to `committee`. The receipt is
`~/Work/corpora/supply-2026-09-02/receipts/unitedstates-reuse-20260928/release-0.51.0/stage-replay/`,
and `docs/decisions.md` (0.51.0) lists the largest moves. Full legislative lifecycle
reconstruction, chamber-aware calendar interpretation, constitutional-amendment
completion, and retrospective timeline queries remain separate work. The
existing signing-date API is unchanged.

```sh
uv run --frozen pytest -q tests/test_interpretation_bill_stage.py tests/test_bill_family.py
```
