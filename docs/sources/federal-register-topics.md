# Federal Register topics

Use `read_fr_topics(payload)` from `spicy_docs.sources.federal_register.topics`
for retained `topics.json` bytes. `FrTopicsAcquirer` fetches the same fixed
endpoint with an explicit `FrTopicsBudget` and optional HTTP transport.
It returns exact captured bytes plus the parsed observations; callers retain
the bytes and capture history.

The result includes both `thesaurus` and `ad_hoc` collections, row/link/CFR
reference paths, declared and observed counts, and the input hash and size.
Raw JSON keeps unknown fields and collections. Rows retain source order,
duplicate slugs, empty strings and empty arrays. CFR references stay arbitrary
finite JSON values. Only the caller decides whether counts agree, a topic is
useful, or a link names another record.

This undocumented endpoint has an observed shape, not a formal published
schema. Missing or incorrectly typed known keys refuse; unknown keys survive.
The bounded reader rejects duplicate JSON object keys, non-finite numbers and
excessive input size, node count or depth. Finite fractional numbers use Python
binary floats; exact number spelling remains in the retained bytes.

Acquisition requires HTTP 200, JSON content type, the exact requested URL and
the expected topics shape. Refusals retain available response evidence. An empty
collection is an empty observation, not proof that topics do not exist. No
source storage, release, stable topic ID, vocabulary selection, reconciliation
or canonical row digest is created.
