---
name: filemap
description: Use when navigating this repository, locating where a capability or file lives, or after creating/repurposing files. Read filemap.tsv before searching the tree, and regenerate it when it is stale or after adding a file whose description changed.
---

# Filemap

`filemap.tsv` at the repository root maps every source file to its one-line
description and its kind, one path-sorted line per file:

    path<TAB>description<TAB>kind

`description` is the file's own first statement (module docstring paragraph,
heading, manifest title); it is empty where the file states none, so a
known-absent description stays distinguishable from an unmapped file. `kind`
is `src`, `test`, `doc` or `config`. Read it **before** exploring the tree —
"where does X live?" is a lookup, not a search.

## Workflow

1. Read `filemap.tsv` (or grep it: `rg "credential" filemap.tsv` returns
   readable rows) and find the file; then read that file directly.
2. Filter by kind when you know it: `rg $'\ttest\t' filemap.tsv` or
   `rg -v $'\ttest\t' filemap.tsv` to drop tests.
3. Only Grep/Glob when the map lacks specificity (a function or call site
   inside a file).
4. Never dispatch explorer agents when filemap.tsv answers the question.

## Keeping it fresh

- The gate (`./scripts/check`) runs `generate_filemap.py --check` and refuses a
  stale map. Regenerate with:
  `uv run --frozen python scripts/generate_filemap.py`
- When you create a file without a description, give it a one-line module
  docstring, heading or title, then regenerate.
- `--stats` lists files missing descriptions; the target is near-complete
  coverage. An empty description column means the file states no description
  of its own.

## Rules

- Point, don't count: prose must not hard-code file or test counts that decay;
  point at this map or the directory.
- Never hand-edit `filemap.tsv`; it is generated and the check gate compares
  its rows exactly.
