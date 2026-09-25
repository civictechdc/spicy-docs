# CFTC comments portal fixtures

The archived fixtures below are trimmed slices of bytes the portal itself served, retrieved
through the Wayback Machine's raw-content mode (`id_`, which serves the
original capture bytes unmodified) on 2026-09-24. Trimming keeps the
load-bearing markup byte-for-byte and drops surrounding chrome and repeated
items; nothing inside the kept structure was edited. Each file's provenance:

| Fixture | Portal URL | Wayback capture | Trim |
| --- | --- | --- | --- |
| `releases-2026.html` | `https://comments.cftc.gov/PublicComments/ReleasesWithComments.aspx?Type=ListAll&Year=2026` | `20260101072051` | 10 release items cut to the first 3; year links kept; chrome dropped |
| `comment-list-1647.html` | `https://comments.cftc.gov/PublicComments/CommentList.aspx?id=1647` | `20160227084336` (http spelling) | 8 rows cut to the first 4; grid and header intact; no pager on this page |
| `comment-list-3098-p12.html` | `https://comments.cftc.gov/PublicComments/CommentList.aspx?3098&ctl00_ctl00_cphContentMain_MainContent_gvCommentListChangePage=12` | `20250123073127` | 10 rows cut to the first 2; pager, current-page item and totals intact. This capture is the search-all listing (`?3098` bare token), used to exercise the pager grammar; the per-rule walk uses `?id={ruleId}` |
| `view-comment-59866.html` | `https://comments.cftc.gov/PublicComments/ViewComment.aspx?id=59866` | `20250503203627` | labelled detail block and attachments grid kept; chrome dropped |
| `comment-letter.pdf.head` | `https://comments.cftc.gov/Handlers/PdfHandler.ashx?id=10` | `20111015183534` | first 2048 bytes (`%PDF-1.4` magic confirmed; a second head from `id=10000`, capture `20160521233024`, matched the same grammar) |

Those initial captures followed Cloudflare refusals to curl, HTTPX and a real
browser. Later bounded requests on the same day succeeded; the route is
intermittent, not consistently unavailable. Tests still build complete PDFs
synthetically where the trailer check needs them.

## Live response fixtures

The campaign receipt
`scraper-completion-2026-09-24T235248Z/cftc` retains exact response bodies and
request outcomes outside the repository. These fixtures keep the selected
publisher markup byte-for-byte inside a minimal HTML wrapper:

| Fixture | Source URL and UTC capture | Original body SHA-256 | Trim |
| --- | --- | --- | --- |
| `releases-2026-live-details.html` | `https://comments.cftc.gov/PublicComments/ReleasesWithComments.aspx?Type=ListAll&Year=2026`, 2026-09-24 23:55 | `9ed740ac24c04ee7d18d3f6a9e64864848c3cf57db0b6a3864b10dbf57deb19a` | Title and the complete items for rules 7641 and 7650; these state an extended date and a related release outside the title paragraph. |
| `view-comment-113989-live.html` | `https://comments.cftc.gov/PublicComments/ViewComment.aspx?id=113989`, 2026-09-24 23:58 | `2994c06667a06a6103ee407da32d3953b1333d12f362dd6922d8bdc2fc7f3452` | Complete `pnlCommentWrap` including native Unicode submitter and filename. |
