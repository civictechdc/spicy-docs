"""Every source guide and top-level guide is reachable from ``docs/README.md`` (E5).

Walks the guide folders the index promises to cover and fails the moment a new
page lands without a link; the allowlist may name only pages that still exist.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
README = DOCS / "README.md"

LINK_TARGET = re.compile(r"]\(([^)]+)\)")

# Pages deliberately left off the README nav, and why. Keep this short; prefer
# adding a link over adding an entry here.
UNINDEXED: dict[str, str] = {}


def _linked_targets(text: str) -> set[str]:
    """Every markdown link target in `text`, with any `#anchor` dropped."""
    return {target.split("#", 1)[0] for target in LINK_TARGET.findall(text)}


def _guides(*parts: str) -> list[Path]:
    """Every guide markdown path under the sources and top-level docs folders."""
    return sorted((DOCS / Path(*parts)).glob("*.md"))


def test_every_sources_extraction_and_top_level_guide_is_linked_from_readme() -> None:
    """Every source, extraction and top-level guide is linked from docs/README.md."""
    targets = _linked_targets(README.read_text())
    pages = [*_guides("sources"), *_guides("extraction"), *(p for p in _guides() if p.name != "README.md")]
    assert pages, "expected at least one guide under docs/"
    missing = []
    for page in pages:
        rel = page.relative_to(DOCS).as_posix()
        if rel in UNINDEXED:
            continue
        if rel not in targets:
            missing.append(rel)
    assert not missing, f"docs/README.md does not link: {missing}"


def test_the_allowlist_names_only_pages_that_still_exist() -> None:
    """A page pulled from the allowlist (or renamed) should not leave a stale entry behind."""
    stale = [rel for rel in UNINDEXED if not (DOCS / rel).is_file()]
    assert not stale, f"UNINDEXED names a page that no longer exists: {stale}"
