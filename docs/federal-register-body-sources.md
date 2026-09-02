# Federal Register body-source knowledge

SpicyDocs now preserves the source-specific rules from the former SpicySearch
body-fetch campaigns in `spicy_docs.federal_register_body_sources`. The module
derives locators and verifies already fetched bytes. It does not select a
rendition, perform network I/O, or store a document body. DocSpec owns candidate
choice; a future SpicyDocs adapter must own bounded acquisition, exact capture,
and byte receipts.

## Why each rule survived or did not

| Prior behavior | Decision | Why |
| --- | --- | --- |
| Derive publisher XML and text siblings from `body_html_url` | Retain, with stricter identity checks | The publisher exposes real sibling paths, and the pre-2000 corpus showed that XML absence did not mean body absence. The old global string replacement could derive a plausible URL from the wrong record; the new helper requires the host, path, date, and document number to agree first. |
| Derive a govinfo FR granule from publication date and document number | Retain | This is a stable source-addressing rule and recovered a measured publisher gap. The helper emits the candidate without ranking it. |
| Treat a 44,165-byte response as a govinfo soft 404 | Do not retain as an invariant | That size described one observed error-page version. A later valid document could have the same size, and a changed error template would bypass the check. The durable checks are the final URL, error-page marker, and printed FR document marker. |
| Require `[FR Doc No: ...]` in a govinfo body | Retain and strengthen | govinfo can return HTTP 200 for a missing granule. The marker binds the bytes to the requested identity. A MODS-resolved alternate must now print the resolved `accessId`; the old alternate branch checked only that it was not the known error page. |
| Accept the base marker for a split number such as `97-26440-2` | Retain narrowly | FederalRegister.gov created a disambiguation suffix while the printed document kept the unsuffixed number. The new rule accepts a base only for the measured three-part numeric shape, not for every string ending in digits. |
| Resolve a synthetic `X` number by matching `start_page` in the issue MODS | Retain and strengthen | This preserves a real cross-source identity difference. The streaming parser keeps the FederalRegister.gov number separate from the govinfo `accessId` and refuses zero, multiple, malformed, oversized, or DTD-bearing evidence instead of taking the first regex match. |
| Use `.xml` then `.txt` then govinfo as a fixed runtime cascade | Leave selection to DocSpec policy | The availability observation is valuable, but candidate preference is a DocSpec decision. SpicyDocs exposes all locators without choosing one or turning a past cutoff into an unversioned policy; its eventual adapter owns acquisition and capture after DocSpec selects a candidate. |
| Prove publisher text and govinfo agreement | Keep in SpicySearch Validation | Agreement measures whether two carriers yield the same recovered terms; it does not establish source acquisition identity and must not become a runtime shortcut. Copying the check here would create a second validation implementation. |
| Sleep 0.4 seconds with three workers | Do not retain as source semantics | The useful performance lesson is to meter request starts rather than add response latency to a post-request sleep. The exact interval and worker count came from one host/client campaign and can drift. A future DocSpec transport policy must state and receipt its own current bounds. |
| Append failures and digests to ad hoc ledgers, rescan output directories, and write manifests directly | Do not retain | The code arose from a resumable research campaign. SpicyDocs' shared acquisition and publication path provides immutable members, exact digests, bounded reads, and explicit failures. Restoring the loop would duplicate those mechanisms with weaker arrival evidence. |

## Bounds and handoff

For URL length `U`, granule bytes `B`, and MODS bytes `M`:

- locator derivation takes `O(U)` time and `O(U)` output space;
- granule validation takes `O(B)` time and `O(U)` auxiliary space;
- MODS resolution takes `O(M)` time and `O(D + A)` auxiliary space, where
  `D` is XML nesting depth and `A` is the largest retained `start` or
  `accessId` value;
- byte parsers reject a payload beyond the caller-supplied positive bound;
- every helper performs zero network requests and zero filesystem writes.

A future integration should let DocSpec choose a candidate and ask a SpicyDocs
body adapter to acquire it. That SpicyDocs adapter must set and receipt its byte
budget, retry policy, and request-start rate, seal the selected bytes through
the shared publication path, and preserve both the source document number and
any MODS-resolved govinfo `accessId` in the acquisition evidence.
