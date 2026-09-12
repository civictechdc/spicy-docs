"""Preflight ownership of immutable release and persistent blob-store paths."""

from pathlib import Path

from spicy_docs.releases.format import SourceNativeReleaseError


def require_separate_paths(left: Path, right: Path, *, labels: tuple[str, str]) -> None:
    selected_left = Path(left).absolute().resolve(strict=False)
    selected_right = Path(right).absolute().resolve(strict=False)
    if (
        selected_left == selected_right
        or selected_left.is_relative_to(selected_right)
        or selected_right.is_relative_to(selected_left)
    ):
        raise SourceNativeReleaseError(f"{labels[0]} and {labels[1]} must not overlap")
