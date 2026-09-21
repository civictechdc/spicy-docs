"""Retained topic examples preserve literal fields or explicit refusal evidence.

Pins exact admitted HTML and evidence digests, refusal retention without a
release, and unexpected publication failures.
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from rulespec_artifacts import ArtifactPin, LocalMemberSource

from examples.offline_release import FIXTURES, IMPLEMENTATION_ID, PRODUCT_ID, PRODUCT_URL, run_example
from spicy_docs.source_native import SourceNativeReleaseReader
from spicy_docs.source_native.profiles import GAO_PRODUCT_PAGE_PROFILE
from spicy_docs.source_native.store import LocalSourceNativeBlobStore
from spicy_docs.sources.gao.native import parse_gao_product_page_response


@pytest.mark.parametrize(
    ("case", "slug", "label"),
    [
        ("matching", "information-security", "Information Security"),
        ("unexpected", "agency-operations", "Agency Operations"),
    ],
)
def test_topic_example_exposes_literal_values_and_exact_admitted_html(
    tmp_path: Path, case: str, slug: str, label: str
) -> None:
    """A topic example exposes literal values and exact admitted HTML with matching digests and evidence."""
    result = json.loads(json.dumps(run_example(tmp_path, case=case)))
    publication = result["publication"]
    assert publication["collectionOutcome"] == result["verification"]["collectionOutcome"]
    reader = SourceNativeReleaseReader(
        LocalMemberSource(Path(result["release"])),
        blob_source=LocalSourceNativeBlobStore(Path(result["blobStore"]), create=False),
        profile=GAO_PRODUCT_PAGE_PROFILE,
        expected_pin=ArtifactPin(publication["logicalId"], publication["artifactDigest"]),
        accepted_verifier_implementation_ids=frozenset({IMPLEMENTATION_ID}),
    )

    (row,) = reader.iter_records()
    topic = {"href": f"/topics/{slug}", "label": label, "slug": slug}
    assert row["record"]["publisherTopic"] == topic
    assert row["record"]["canonicalUrl"] == PRODUCT_URL
    assert row == result["records"][0]
    evidence = reader.record_evidence(PRODUCT_ID)
    assert evidence is not None
    assert evidence == result["recordEvidence"]
    pack = reader.read_evidence(evidence["evidenceBlobRef"], max_bytes=result["evidenceByteLength"])
    response = parse_gao_product_page_response(pack)
    assert response["results"][0]["publisherTopic"] == topic
    with ZipFile(BytesIO(pack)) as archive:
        html = archive.read("product.html")
    assert html == (FIXTURES / f"{case}.html").read_bytes()
    assert row["record"]["htmlSha256"] == result["inputSha256"] == "sha256:" + hashlib.sha256(html).hexdigest()
    assert row["record"]["htmlByteLength"] == len(html)
    assert list(reader.iter_renditions()) == []
    assert result["input"] == "one synthetic GAO page; no live requests"


def test_missing_topic_example_retains_refused_html_without_a_release(tmp_path: Path) -> None:
    """A missing-topic example retains the refused HTML without creating a release."""
    result = json.loads(json.dumps(run_example(tmp_path, case="missing")))

    assert "publication" not in result
    assert "records" not in result
    assert not Path(result["release"]).exists()
    refusal = result["refusal"]
    assert refusal["ok"] is False
    assert refusal["error"]["code"] == "acquisition-failed"
    assert "exactly one publisher topic field with one topic anchor" in refusal["error"]["message"]
    response = refusal["failedAcquisition"]["response"]
    assert response["status"] == "retained"
    assert response["requestKey"] == PRODUCT_URL
    store = LocalSourceNativeBlobStore(Path(result["blobStore"]), create=False)
    with store.open(response["blobRef"]) as stream:
        html = stream.read(response["byteSize"] + 1)
    assert html == (FIXTURES / "missing.html").read_bytes()
    assert "sha256:" + hashlib.sha256(html).hexdigest() == result["inputSha256"]
    assert response["byteSize"] == len(html)


def test_topic_example_does_not_hide_unexpected_publication_failure(tmp_path: Path) -> None:
    """An unexpected publication failure is not hidden."""
    (tmp_path / "gao").mkdir()
    with pytest.raises(RuntimeError, match="destination-exists"):
        run_example(tmp_path, case="missing")
