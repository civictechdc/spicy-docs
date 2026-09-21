#!/usr/bin/env python3
"""Extract per-file descriptions and build filemap.json for agent navigation.

Walks the repository and extracts the first-line description of each file
using language-appropriate conventions, then writes a JSON map agents read
before exploring rather than searching blind:

* Python: first non-empty line of the module docstring
* Markdown: YAML frontmatter title, else the first heading
* JSON: top-level "title" and/or "description" (or "name" for manifests)
* TOML: top-level or [project] "description"
* YAML: top-level "title" or "description"

Usage:
  uv run --frozen python scripts/generate_filemap.py           # write filemap.json
  uv run --frozen python scripts/generate_filemap.py --check   # exit 1 if stale
  uv run --frozen python scripts/generate_filemap.py --stats   # coverage and gaps
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "filemap.json"

INCLUDE_EXTENSIONS = frozenset({".py", ".md", ".json", ".toml", ".yaml", ".yml"})

# Data and generated directories are not navigable source; they would flood the
# map with null entries and stale measurements.
EXCLUDE_PATTERNS = [
    re.compile(r"^tests/fixtures/"),
    re.compile(r"^docs/research/"),
    re.compile(r"^sample-data/"),
    re.compile(r"^vendor/"),
    re.compile(r"^filemap\.json$"),
]

MAX_DESCRIPTION = 120


def clean_desc(raw: str) -> str | None:
    desc = re.sub(r"\s+", " ", raw).strip().rstrip(".")
    if not desc:
        return None
    if len(desc) > MAX_DESCRIPTION:
        desc = desc[: MAX_DESCRIPTION - 3] + "..."
    return desc


def extract_python(content: str) -> str | None:
    stripped = re.sub(r"^#!.*\n", "", content)
    stripped = re.sub(r"^(?:#[^\n]*\n|\s*\n)*", "", stripped).lstrip()
    match = re.match(r'^(?:"""|\'\'\')([\s\S]*?)(?:"""|\'\'\')', stripped)
    if not match:
        return None
    for line in match.group(1).splitlines():
        desc = clean_desc(line)
        if desc:
            return desc
    return None


def extract_markdown(content: str) -> str | None:
    frontmatter = re.match(r"^---\s*\n([\s\S]*?)\n---", content)
    if frontmatter:
        title = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', frontmatter.group(1), re.MULTILINE)
        if title:
            return clean_desc(title.group(1))
    heading = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    return clean_desc(heading.group(1)) if heading else None


def extract_json(content: str) -> str | None:
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    title = obj.get("title")
    description = obj.get("description")
    if title and description:
        return clean_desc(f"{title} — {description}")
    if title:
        return clean_desc(str(title))
    if description:
        return clean_desc(str(description))
    if isinstance(obj.get("name"), str):
        return clean_desc(obj["name"])
    return None


def extract_toml(content: str) -> str | None:
    match = re.search(r'^\s*description\s*=\s*"([^"]+)"', content, re.MULTILINE)
    return clean_desc(match.group(1)) if match else None


def extract_yaml(content: str) -> str | None:
    for key in ("title", "description"):
        match = re.search(rf"^{key}:\s*(.+)$", content, re.MULTILINE)
        if match:
            desc = clean_desc(match.group(1).strip('"').strip("'"))
            if desc:
                return desc
    return None


EXTRACTORS = {
    ".py": extract_python,
    ".md": extract_markdown,
    ".json": extract_json,
    ".toml": extract_toml,
    ".yaml": extract_yaml,
    ".yml": extract_yaml,
}


def walk_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*")):
        if path.suffix not in INCLUDE_EXTENSIONS:
            continue
        if any(part.startswith(".") for part in path.relative_to(ROOT).parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if any(pattern.search(rel) for pattern in EXCLUDE_PATTERNS):
            continue
        files.append(path)
    return files


def build_filemap() -> tuple[dict[str, str | None], int, int]:
    files = walk_files()
    entries: dict[str, str | None] = {}
    described = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            desc = EXTRACTORS[path.suffix](path.read_text())
        except (OSError, UnicodeDecodeError):
            desc = None
        entries[rel] = desc
        described += desc is not None
    return entries, described, len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if filemap.json is stale")
    parser.add_argument("--stats", action="store_true", help="print coverage and list undescribed files")
    args = parser.parse_args(argv)

    entries, described, total = build_filemap()
    payload = {
        "_comment": "Auto-generated by scripts/generate_filemap.py — do not hand-edit.",
        "generated": datetime.now(UTC).isoformat(),
        "coverage": f"{described}/{total} files ({round(described / total * 100)}%)",
        "files": entries,
    }
    rendered = json.dumps(payload, indent=2) + "\n"

    if args.stats:
        print(f"Filemap: {described}/{total} files described ({round(described / total * 100)}%)")
        undescribed = [rel for rel, desc in entries.items() if desc is None]
        if 0 < len(undescribed) <= 50:
            print("\nFiles missing descriptions:")
            for rel in undescribed:
                print(f"  {rel}")
        elif undescribed:
            print(f"\n{len(undescribed)} files missing descriptions")
        return 0

    if args.check:
        try:
            existing = json.loads(OUTPUT.read_text())
        except (OSError, json.JSONDecodeError):
            print(
                "filemap.json missing or invalid. Run: uv run --frozen python scripts/generate_filemap.py",
                file=sys.stderr,
            )
            return 1
        if existing.get("files") != entries:
            print("filemap.json is stale. Run: uv run --frozen python scripts/generate_filemap.py", file=sys.stderr)
            return 1
        print("filemap.json is up to date.")
        return 0

    OUTPUT.write_text(rendered)
    print(f"Wrote {OUTPUT}")
    print(f"Coverage: {described}/{total} files ({round(described / total * 100)}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
