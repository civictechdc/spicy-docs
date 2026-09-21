"""Reader imports stay independent of acquisition and optional table libraries.

The five public paths match DocSpec's installed-wheel probe. Import each alone
as well as together: a clean combined import can hide an order-dependent leak.
This guard checks eager imports; the installed-wheel consumer probe separately
checks operation without the producer's acquisition dependencies installed.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

#: Kept in step with DocSpec's installed-wheel probe. Adding a module to the
#: read/verify contract there means adding it here.
_READER_MODULES = (
    "spicy_docs.source_native",
    "spicy_docs.source_native.federal_register",
    "spicy_docs.source_native.profiles",
    "spicy_docs.source_native.regulations_gov",
    "spicy_docs.source_native.store",
)

_HEAVY_MODULES = (
    "polars",
    "httpx",
    "boto3",
    "botocore",
    "loguru",
    "tqdm",
    "pyarrow",
    "duckdb",
    "pymupdf",
    "fitz",
    "PIL",
    "rapidocr_onnxruntime",
    "ocrmac",
    "mlx",
    "mlx_vlm",
    "torch",
    "transformers",
)


@pytest.mark.parametrize(
    "module", ["spicy_docs.extraction", "spicy_docs.extraction.ocr", "spicy_docs.extraction.gemini"]
)
def test_extraction_interfaces_import_without_optional_dependencies(module):
    probe = f"""
import importlib.abc
import sys
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {_HEAVY_MODULES!r}:
            raise AssertionError('Unexpected optional import: ' + fullname)
sys.meta_path.insert(0, BlockOptional())
import {module}
from spicy_docs.extraction import DocumentExtractor, FullPage, Recognition
from spicy_docs.extraction.ocr import MLX
from spicy_docs.extraction.gemini import Gemini
extractor = DocumentExtractor(FullPage(MLX.lighton()))
assert Recognition('native', {{}}, {{}}).text == 'native'
"""
    completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_reader_closure_imports_without_heavy_third_party_modules() -> None:
    imports = " ".join(f"import {name};" for name in _READER_MODULES)
    probe = (
        "import sys; "
        f"{imports} "
        f"heavy = {_HEAVY_MODULES!r}; "
        "present = [name for name in heavy if name in sys.modules]; "
        "print(','.join(present)); "
        "raise SystemExit(bool(present))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, f"heavy modules pulled in: {completed.stdout!r} {completed.stderr}"


def test_each_reader_module_is_guarded_individually() -> None:
    """A module that only stays clean because another imported first is not clean.

    Each is probed alone because importing the five together hides the case where one module's closure is dirty but a
    sibling happened to shadow it.
    """
    for module in _READER_MODULES:
        probe = (
            "import sys; "
            f"import {module}; "
            f"heavy = {_HEAVY_MODULES!r}; "
            "present = [name for name in heavy if name in sys.modules]; "
            "print(','.join(present)); "
            "raise SystemExit(bool(present))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, f"{module} pulled in heavy modules: {completed.stdout!r} {completed.stderr}"


@pytest.mark.parametrize(
    "module",
    ["spicy_docs.sources.federal_register.profile", "spicy_docs.sources.federal_register.replay"],
)
def test_federal_register_replay_imports_no_live_transport(module: str) -> None:
    """One source's policy must be usable without another source's transport."""
    forbidden = (
        *_HEAVY_MODULES,
        "urllib.request",
        "ssl",
        "socket",
        "spicy_docs.sources.zyte",
        "spicy_docs.sources.gao.native",
        "spicy_docs.cli.source_native",
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                f"import sys; import {module}; "
                f"present = [name for name in {forbidden!r} if name in sys.modules]; "
                "print(','.join(present)); raise SystemExit(bool(present))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, f"{module} imported live transport: {completed.stdout} {completed.stderr}"
