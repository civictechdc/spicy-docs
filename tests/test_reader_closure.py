"""The source-native reader closure imports no acquisition-only dependency.

``spicy_docs.source_native`` and ``spicy_docs.source_native_profiles`` are the
two modules DocSpec imports to read and verify Federal Register and
Regulations.gov releases, and it installs the producer wheel with
``uv pip install --no-deps``. Neither module may therefore reach polars, httpx,
boto3/botocore, loguru, or tqdm at import time: those belong to acquisition
(Zyte, Mirrulations/S3, the public-table Parquet reader) and the legacy ETL
``RecordType`` schemas, none of which run on the read/verify path.

This is an eager-import guard, not an installability proof — the modules could
still fail on a machine without those libraries for some other reason.
DocSpec's installed-wheel test is the installability proof. Here a subprocess
imports both modules and fails if any of the six names landed in
``sys.modules``.
"""

from __future__ import annotations

import subprocess
import sys

_HEAVY_MODULES = ("polars", "httpx", "boto3", "botocore", "loguru", "tqdm")


def test_reader_closure_imports_without_heavy_third_party_modules() -> None:
    probe = (
        "import sys; "
        "import spicy_docs.source_native; "
        "import spicy_docs.source_native_profiles; "
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
