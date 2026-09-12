"""Releases: compatibility behavior."""

from __future__ import annotations

import hashlib
import subprocess
import tomllib
from pathlib import Path

from spicy_docs.source_native import (
    installed_release_schema_bundle,
    release_schema_bundle,
)


def test_new_path_uses_only_shared_artifact_implementation() -> None:
    source_native = Path(__file__).parents[2] / "src/spicy_docs/source_native.py"
    profile = Path(__file__).parents[2] / "src/spicy_docs/sources/federal_register/native.py"
    implementations = sorted(source_native.with_name("releases").glob("*.py"))
    text = source_native.read_text() + profile.read_text() + "".join(path.read_text() for path in implementations)

    assert "rulespec_conformance" not in text
    assert "build_artifact_root" in text
    assert "docspec" not in text.lower()
    assert "refspec" not in text.lower()


def test_base_package_keeps_acquisition_analytics_and_platform_dependencies_optional() -> None:
    project_root = Path(__file__).parents[2]
    configuration = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    project = configuration["project"]

    dependencies = project["dependencies"]
    assert "rulespec-artifacts==1.0.11" in dependencies
    assert configuration["tool"]["uv"]["sources"]["rulespec-artifacts"] == {
        "path": "vendor/rulespec_artifacts-1.0.11-py3-none-any.whl"
    }
    rulespec_wheel = project_root / "vendor/rulespec_artifacts-1.0.11-py3-none-any.whl"
    assert hashlib.sha256(rulespec_wheel.read_bytes()).hexdigest() == (
        "bedd8ee4799d9633963272714a30258f505404155732480ad5cb1dde2d7cbf4f"
    )
    excluded = ("boto3", "httpx", "loguru", "polars", "tqdm", "pyarrow", "refspec", "rdflib", "rulespec-conformance")
    assert not any(dependency.startswith(excluded) for dependency in dependencies)
    assert "build-source-catalog" not in project["scripts"]


def test_installed_schema_bundle_is_the_exact_generated_bundle() -> None:
    assert installed_release_schema_bundle() == release_schema_bundle()


def test_the_vendored_wheel_is_tracked_by_git() -> None:
    """A bumped wheel that git ignores is invisible until someone clones.

    ``vendor/.gitignore`` ignores everything and re-admits exactly one wheel by
    name, so bumping the vendored version silently requires moving that
    allowlist line too. Miss it and ``git add`` stages the deletion of the old
    wheel and nothing else: the working tree still has the file, every local
    check passes, and only a fresh checkout -- a worktree, a clone, CI -- gets
    an empty vendor directory that cannot install. That failure has happened
    three times on this dependency, so it is checked here rather than
    remembered.

    The pin test above reads the wheel from the working tree, which is exactly
    what cannot see this; this one asks git what it would hand a new checkout.
    """

    project_root = Path(__file__).parents[2]
    configuration = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    wheel = configuration["tool"]["uv"]["sources"]["rulespec-artifacts"]["path"]
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", wheel],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert tracked.returncode == 0, (
        f"{wheel} is declared in pyproject.toml but git does not track it; "
        f"add it to vendor/.gitignore's allowlist. {tracked.stderr.strip()}"
    )
