"""Core operations and setup failures with optional imports unavailable.

Subprocesses block the optional imports even though the contributor environment
has every extra installed; pins that the core CLI, the example's
publish/verify/evidence/inspect path and reconstruction parse/serialize work
without extras, and that a missing live, table or parquet dependency is a named
``dependency-missing`` setup failure that writes no release.
"""

from __future__ import annotations

import json
import subprocess
import sys
from io import BytesIO, StringIO
from pathlib import Path

import httpx
import polars as pl
import pytest

from spicy_docs.cli.source_native import main
from spicy_docs.schemas.spicy_regs_public_tables import PUBLIC_COMMENT_FILE_COLUMNS

_OPTIONAL = ("httpx", "boto3", "botocore", "loguru", "tqdm", "polars", "pyarrow", "duckdb")
#: The `reconstruct` extra. Only `reconstruction.validate.schema_validity`
#: uses it, so everything else in that package must work without it.
_RECONSTRUCT = ("lxml",)
_IMPLEMENTATION = "git+https://example.test/spicy-docs@" + "a" * 40
_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "offline_release.py"


def _without_optional(code: str) -> None:
    setup = f"""
import importlib.abc
import sys
class UnavailableOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {_OPTIONAL!r}:
            raise ModuleNotFoundError(f"No module named '{{fullname}}'", name=fullname)
sys.meta_path.insert(0, UnavailableOptional())
"""
    result = subprocess.run([sys.executable, "-c", setup + code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def _publish_args(directory: Path, source: str, *scope: str) -> list[str]:
    return [
        "publish",
        "--source",
        source,
        *scope,
        "--destination",
        str(directory / "release"),
        "--blob-store",
        str(directory / "blobs"),
        "--implementation-id",
        _IMPLEMENTATION,
    ]


def test_core_cli_and_example_publish_replay_read_evidence_and_inspect_without_extras(tmp_path: Path) -> None:
    """The core CLI and the example's publish, verify, evidence read and inspect all succeed with no extra imported."""
    _without_optional(f"""
import json
import runpy
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from spicy_docs.cli.source_native import main
with redirect_stdout(StringIO()):
    try:
        main(['--help'])
    except SystemExit as error:
        assert error.code == 0
example = runpy.run_path({_EXAMPLE.as_posix()!r})
result = example['run_example'](Path({str(tmp_path)!r}))
assert result['publication']['ok'] is True
assert result['verification']['ok'] is True
assert len(result['records']) == 1
assert result['evidenceByteLength'] > 0
out, errors = StringIO(), StringIO()
status = main([
    'inspect', '--source', 'gao-product-pages',
    '--release', result['release'], '--blob-store', result['blobStore'],
    '--logical-id', result['publication']['logicalId'],
    '--artifact-digest', result['publication']['artifactDigest'],
    '--accepted-verifier-implementation-id', example['IMPLEMENTATION_ID'],
], stdout=out, stderr=errors)
assert status == 0, errors.getvalue()
assert json.loads(out.getvalue())['collectionOutcome'] == result['publication']['collectionOutcome']
assert not set({_OPTIONAL!r}).intersection(sys.modules)
""")


@pytest.mark.parametrize(
    ("source", "scope", "missing"),
    [
        ("federal-register", ("--since", "2026-08-25", "--until", "2026-08-25"), "httpx"),
        (
            "regulations-documents",
            ("--since", "2026-08-25", "--until", "2026-08-25", "--agency", "EPA"),
            "boto3",
        ),
    ],
)
def test_missing_live_dependency_is_setup_failure(
    tmp_path: Path, source: str, scope: tuple[str, ...], missing: str
) -> None:
    """A live source missing httpx or boto3 exits 1 with ``dependency-missing`` and writes no release."""
    args = _publish_args(tmp_path, source, *scope)
    _without_optional(f"""
import json
from io import StringIO
from pathlib import Path
from spicy_docs.cli.source_native import main
out, errors = StringIO(), StringIO()
assert main({args!r}, stdout=out, stderr=errors) == 1
report = json.loads(errors.getvalue())
assert report['error']['code'] == 'dependency-missing', report
assert {missing!r} in report['error']['message']
assert out.getvalue() == ''
assert not Path({str(tmp_path / "release")!r}).exists()
""")


def test_public_table_command_reports_missing_pyarrow(tmp_path: Path) -> None:
    """Publishing a public table without pyarrow exits 1 with ``dependency-missing``."""
    args = [
        "publish-public-table",
        "--table",
        "federal-register",
        "--source-release",
        str(tmp_path / "source"),
        "--source-blob-store",
        str(tmp_path / "blobs"),
        "--source-accepted-verifier-implementation-id",
        _IMPLEMENTATION,
        "--destination",
        str(tmp_path / "table"),
        "--implementation-id",
        _IMPLEMENTATION,
    ]
    _without_optional(f"""
import json
from io import StringIO
from spicy_docs.cli.source_native import main
out, errors = StringIO(), StringIO()
assert main({args!r}, stdout=out, stderr=errors) == 1
report = json.loads(errors.getvalue())
assert report['error']['code'] == 'dependency-missing', report
assert 'pyarrow' in report['error']['message']
assert out.getvalue() == ''
""")


def test_injected_parquet_capture_reports_missing_polars(tmp_path: Path) -> None:
    """Reading an injected parquet capture without polars exits 1 with ``dependency-missing`` and writes no release."""
    parquet = tmp_path / "empty-comments.parquet"
    content = BytesIO()
    pl.DataFrame(schema={name: pl.String for name in PUBLIC_COMMENT_FILE_COLUMNS}).write_parquet(content)
    parquet.write_bytes(content.getvalue())
    args = _publish_args(tmp_path, "spicy-regs-public-comments", "--agency", "EPA")
    _without_optional(f"""
import json
from io import StringIO
from pathlib import Path
from spicy_docs.cli.source_native import main
from spicy_docs.sources.public_comments.native import PublicTableCapture
body = Path({str(parquet)!r}).read_bytes()
def fetch(url):
    if url.endswith('/part-0.parquet'):
        return PublicTableCapture(url, body, '2026-08-25T00:00:00Z')
    return None
out, errors = StringIO(), StringIO()
assert main({args!r}, fetch_public_table=fetch, stdout=out, stderr=errors) == 1
report = json.loads(errors.getvalue())
assert report['error']['code'] == 'dependency-missing', report
assert 'polars' in report['error']['message']
assert out.getvalue() == ''
assert not Path({str(tmp_path / "release")!r}).exists()
""")


def test_cli_preserves_real_httpx_exception_and_refusal_context(tmp_path: Path) -> None:
    """A transport failure reports ``transport-failed`` while the request, response and failed acquisition survive."""
    request = httpx.Request("GET", "https://www.federalregister.gov/api/v1/documents")
    response = httpx.Response(403, request=request)
    original = httpx.HTTPStatusError("publisher refused the request", request=request, response=response)

    def fetch(_url: str) -> bytes:
        raise original

    output, errors = StringIO(), StringIO()
    status = main(
        _publish_args(tmp_path, "federal-register", "--since", "2026-08-25", "--until", "2026-08-25"),
        fetch=fetch,
        stdout=output,
        stderr=errors,
    )
    report = json.loads(errors.getvalue())
    assert status == 1
    assert report["error"]["code"] == "transport-failed"
    assert original.response is response
    assert original.request is request
    assert getattr(original, "failed_acquisition", None) == report["failedAcquisition"]
    assert report["failedAcquisition"]["response"]["reason"] == "transport-unavailable"
    assert output.getvalue() == ""


def test_cli_does_not_swallow_unrelated_injected_errors(tmp_path: Path) -> None:
    """An injected non-transport exception propagates unchanged instead of being reported as a source failure."""
    original = RuntimeError("injected implementation defect")

    def fetch(_url: str) -> bytes:
        raise original

    with pytest.raises(RuntimeError) as caught:
        main(
            _publish_args(tmp_path, "federal-register", "--since", "2026-08-25", "--until", "2026-08-25"),
            fetch=fetch,
            stdout=StringIO(),
            stderr=StringIO(),
        )
    assert caught.value is original


def test_reconstruction_parses_serializes_and_reports_four_of_five_findings_without_lxml() -> None:
    """With lxml blocked in a subprocess, reconstruction parses and serializes while schema validity refuses by name.

    Four of the five checks report; the extra buys schema validation and
    nothing else, and blocking happens in a subprocess because this environment
    has every extra installed.
    """
    code = f"""
import importlib.abc, json, sys
from pathlib import Path

class Unavailable(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {_RECONSTRUCT!r}:
            raise ModuleNotFoundError(f"No module named {{fullname!r}}", name=fullname)

sys.meta_path.insert(0, Unavailable())

from spicy_docs.reconstruction import EXTRA_REQUIRED, extra_available
from spicy_docs.reconstruction.evidence import EvidenceDocument
from spicy_docs.reconstruction.parse import parse_cfr
from spicy_docs.reconstruction.profiles import CFR_PROFILE, check_schema_bundle
from spicy_docs.reconstruction.serialize import serialize_cfr
from spicy_docs.reconstruction.validate import ValidateError, check, schema_validity

assert not extra_available()
assert "reconstruct" in EXTRA_REQUIRED

fixtures = Path({str(Path(__file__).parent / "fixtures" / "reconstruction" / "cfr")!r})
evidence = EvidenceDocument.from_json(json.loads((fixtures / "CFR-2024-title12-vol1-sec1-1.evidence.json").read_text()))
document = parse_cfr(evidence)
serialized = serialize_cfr(document, section="1.1")
assert serialized.xml.startswith(b'<?xml version="1.0" encoding="UTF-8"?>')
assert serialized.source_map.entries

# The bundle is still readable and still checked against its pin; only the
# validator needs the extra.
assert [entry.name for entry in check_schema_bundle(CFR_PROFILE)] == ["CFRMergedXML.xsd"]

findings = {{finding.check: finding for finding in check(document, serialized, section="1.1", schema=False)}}
assert findings["content_fidelity"].passed and findings["coverage"].passed
assert findings["structural_fidelity"].passed
assert findings["schema_validity"].measures["skipped"] is True

try:
    schema_validity(serialized.xml)
except ValidateError as error:
    assert "reconstruct" in str(error), error
else:
    raise AssertionError("schema validation must refuse by name without the extra")

assert "lxml" not in sys.modules
"""
    _without_optional(code)
