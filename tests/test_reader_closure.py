"""The source-native reader closure imports no acquisition-only dependency.

DocSpec installs the producer wheel with ``uv pip install --no-deps`` and
imports five modules from it to read and verify Federal Register and
Regulations.gov releases -- ``federal_register_source_native``,
``regulations_gov_source_native``, ``source_native``, ``source_native_profiles``
and ``source_native_store`` (DocSpec ``tests/test_source_catalog_installed_wheel.py``,
which is the authority for this list). None may reach polars, httpx,
boto3/botocore, loguru, or tqdm at import time: those belong to acquisition
(Zyte, Mirrulations/S3, the public-table Parquet reader) and the legacy ETL
``RecordType`` schemas, none of which run on the read/verify path.

The list was two modules until 2026-09-05, when spicyregZ2 read it against
DocSpec's probe and found it named two of the five. All five passed already, so
this widening fixes no failure -- it closes the gap where three modules could
have grown a heavy import with nothing to catch it. A guard that covers less
than the contract it protects reports success about the part nobody was going
to break.

This is an eager-import guard, not an installability proof — the modules could
still fail on a machine without those libraries for some other reason.
DocSpec's installed-wheel test is the installability proof. Here a subprocess
imports all five modules and fails if any of the six names landed in
``sys.modules``.
"""

from __future__ import annotations

import subprocess
import sys

#: Kept in step with DocSpec's installed-wheel probe. Adding a module to the
#: read/verify contract there means adding it here.
_READER_MODULES = (
    "spicy_docs.federal_register_source_native",
    "spicy_docs.regulations_gov_source_native",
    "spicy_docs.source_native",
    "spicy_docs.source_native_profiles",
    "spicy_docs.source_native_store",
)

_HEAVY_MODULES = ("polars", "httpx", "boto3", "botocore", "loguru", "tqdm")


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

    Importing the five together hides the case where one module's closure is
    dirty but a sibling happened to shadow it. Each is therefore probed alone.
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
