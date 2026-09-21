---
name: filemap
description: Use when navigating this repository, locating where a capability or file lives, or after creating/repurposing files. Read filemap.json before searching the tree, and regenerate it when it is stale or after adding a file whose description changed.
---

# Filemap

`filemap.json` at the repository root maps every source file to its one-line
description: a Python module docstring's first line, a Markdown heading or
frontmatter title, a JSON/TOML/YAML title. Read it **before** exploring the
tree — "where does X live?" is a lookup, not a search.

## Workflow

1. Read `filemap.json` and find the file; then read that file directly.
2. Only Grep/Glob when the map lacks specificity (a function or call site
   inside a file).
3. Never dispatch explorer agents when filemap.json answers the question.

## Keeping it fresh

- The gate (`./scripts/check`) runs `generate_filemap.py --check` and refuses a
  stale map. Regenerate with:
  `uv run --frozen python scripts/generate_filemap.py`
- When you create a file without a description, give it a one-line module
  docstring, heading or title, then regenerate.
- `--stats` lists files missing descriptions; the target is near-complete
  coverage. A `null` entry means the file states no description of its own.

## Rules

- Point, don't count: prose must not hard-code file or test counts that decay;
  point at this map or the directory.
- Never hand-edit `filemap.json`; it is generated and the check gate compares
  entries exactly.
