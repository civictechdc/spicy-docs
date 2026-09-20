"""The overlap measurement's readings, its request bookkeeping, and its report block.

The tool exists to let the parse rule fail against the publisher. Two things
have to be right for a failure to be readable: what counts as agreement per
field, and what the publisher's answer was. Both are pinned here on constructed
receipts, so the offline suite never touches a publisher.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.analysis.record_communications_overlap import (
    MAX_CONGRESS_REQUESTS,
    MAX_GOVINFO_REQUESTS,
    RequestLog,
    detail_locator,
    generated_block,
    render,
    retained_entries,
    score,
)
from tools.analysis.record_communications_overlap import _referral_names_agree as referral_names_agree
from tools.analysis.record_communications_overlap import _round_robin as round_robin
from tools.analysis.record_communications_overlap import _safe as safe_name

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"
SECTIONS = FIXTURES / "record_communications"


def build_receipt(root: Path, *, sections: dict[str, tuple[str, int]], details: dict[str, dict]) -> Path:
    """A receipt shaped exactly as `fetch` leaves one, from committed fixtures."""
    for folder in ("granules", "sections", "details"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    for granule_id, (fixture, congress) in sections.items():
        (root / "sections" / f"{granule_id}.htm").write_bytes((SECTIONS / fixture).read_bytes())
        (root / "sections" / f"{granule_id}.json").write_text(
            json.dumps(
                {
                    "packageId": granule_id.split("-pt")[0],
                    "granuleId": granule_id,
                    "congress": congress,
                    "format": "htm",
                }
            )
        )
    rows = []
    for key, detail in details.items():
        if detail is not None:
            (root / "details" / f"{key}.json").write_text(json.dumps({"houseCommunication": detail}))
        rows.append(
            {
                "publisher": "congress-gov",
                "purpose": "detail",
                "key": key,
                "answer": "ok" if detail is not None else "absent",
                "requests": 1,
            }
        )
    rows.append(
        {"publisher": "govinfo", "purpose": "granules", "key": "CREC-2016-02-12", "answer": "ok", "requests": 1}
    )
    rows.append({"publisher": "govinfo", "purpose": "section", "key": "x", "answer": "ok", "requests": 3})
    (root / "requests.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")
    return root


def publisher_detail(number: int) -> dict:
    path = FIXTURES / "listings" / f"congress-house-communication-detail-114-ec-{number}.json"
    return json.loads(path.read_text())["houseCommunication"]


@pytest.fixture
def ground_truth_receipt(tmp_path: Path) -> Path:
    return build_receipt(
        tmp_path / "receipt",
        sections={"CREC-2016-02-12-pt1-PgH815-4": ("CREC-2016-02-12-pt1-PgH815-4.excerpt.htm", 114)},
        details={"114-ec-4329": publisher_detail(4329), "114-ec-4350": publisher_detail(4350)},
    )


# --- the caps and the locator ---------------------------------------------------------


def test_the_caps_are_the_ones_declared_before_the_run() -> None:
    """Stated in the module docstring and `tools/README.md`; a change here is a change there."""
    assert (MAX_GOVINFO_REQUESTS, MAX_CONGRESS_REQUESTS) == (40, 600)


def test_the_detail_locator_is_the_publishers_own_spelling() -> None:
    """Upper-case EC: a probe that asks only its own spelling confirms only its own spelling."""
    assert detail_locator(114, 4329) == "https://api.congress.gov/v3/house-communication/114/EC/4329?format=json"
    assert "/ec/" not in detail_locator(118, 1)


# --- scoring --------------------------------------------------------------------------


def test_the_two_ground_truths_score_as_agreement_on_every_field(ground_truth_receipt: Path) -> None:
    measurement = score(ground_truth_receipt)
    assert measurement["entriesPrinted"] == 4
    assert measurement["entriesCompared"] == 2
    assert measurement["splitRuleFired"] == 2
    for name in ("abstract", "report_nature", "legal_authority", "submitting_official", "submitting_agency"):
        assert measurement["fields"][name] == {
            "stated": 2,
            "agreed": 2,
            "precision": 1.0,
            "disagreements": [],
        }, name
    assert measurement["fields"]["referral_count"]["precision"] == 1.0
    assert measurement["fields"]["rin"]["stated"] == 1
    assert measurement["requests"] == {"govinfo": 4, "congressGov": 2}


def test_a_field_the_publisher_spells_differently_is_scored_as_a_disagreement(
    tmp_path: Path,
) -> None:
    """The scorer has to be able to fail, or its agreement means nothing."""
    wrong = publisher_detail(4329) | {"submittingAgency": "Department of Agriculture"}
    receipt = build_receipt(
        tmp_path / "receipt",
        sections={"CREC-2016-02-12-pt1-PgH815-4": ("CREC-2016-02-12-pt1-PgH815-4.excerpt.htm", 114)},
        details={"114-ec-4329": wrong},
    )
    agency = score(receipt)["fields"]["submitting_agency"]
    assert (agency["stated"], agency["agreed"], agency["precision"]) == (1, 0, 0.0)
    # And the disagreement is readable: both sides are in the sidecar.
    assert agency["disagreements"][0]["published"] == "Department of Agriculture"
    assert agency["disagreements"][0]["printed"].endswith("Department of Labor")


def test_a_row_the_split_rule_declined_is_not_counted_against_it(tmp_path: Path) -> None:
    """A NULL is the rule refusing to guess; scoring it as a miss inverts the finding."""
    declined = publisher_detail(4329) | {
        "number": 4340,
        "submittingOfficial": "General Counsel",
        "submittingAgency": "Peace Corps",
    }
    receipt = build_receipt(
        tmp_path / "receipt",
        sections={"CREC-2016-02-12-pt1-PgH815-4": ("CREC-2016-02-12-pt1-PgH815-4.excerpt.htm", 114)},
        details={"114-ec-4340": declined},
    )
    measurement = score(receipt)
    assert measurement["splitRuleFired"] == 0
    assert measurement["fields"]["submitting_official"]["stated"] == 0
    # The from-clause it kept whole is still scored, and still agrees.
    concatenation = measurement["fields"]["from_clause_concatenation"]
    assert (concatenation["stated"], concatenation["agreed"]) == (1, 1)


def test_the_committee_comparison_survives_the_publishers_own_renaming() -> None:
    """*Education and the Workforce* and *Education and Workforce Committee* are one committee."""
    assert referral_names_agree(("Education and the Workforce",), ["Education and Workforce Committee"])
    assert referral_names_agree(
        ("Appropriations", "Transportation and Infrastructure", "Ways and Means"),
        ["Appropriations Committee", "Ways and Means Committee"],
    )
    # A run-on joint referral the sentence does not separate still matches both.
    assert referral_names_agree(
        ("House Administration and Education and the Workforce",),
        ["House Administration Committee", "Education and Workforce Committee"],
    )
    assert not referral_names_agree(("Energy and Commerce",), ["Armed Services Committee"])
    assert not referral_names_agree((), ["Appropriations Committee"])


def test_every_retained_section_is_read_with_its_own_congress_and_granule(
    ground_truth_receipt: Path,
) -> None:
    rows = list(retained_entries(ground_truth_receipt))
    assert {congress for congress, _, _ in rows} == {114}
    assert {entry.record_package_id for _, _, entry in rows} == {"CREC-2016-02-12"}
    assert [entry.number for _, _, entry in rows] == [4329, 4335, 4340, 4350]


# --- the completeness witness in the sidecar ------------------------------------------


def test_the_sidecar_carries_the_per_issue_contiguity_witness(ground_truth_receipt: Path) -> None:
    issue = score(ground_truth_receipt)["issues"][0]
    assert issue["granuleId"] == "CREC-2016-02-12-pt1-PgH815-4"
    assert (issue["first"], issue["last"], issue["entries"]) == (4329, 4350, 4)
    # The fixture is an excerpt, so the witness reports holes -- which is the
    # point: it can say a block is incomplete.
    assert issue["contiguous"] is False and len(issue["holes"]) == 18


# --- the request budget ---------------------------------------------------------------


def test_requests_are_counted_across_resumes_from_the_retained_log(tmp_path: Path) -> None:
    log = RequestLog(tmp_path / "receipt")
    log.record(
        publisher="govinfo",
        purpose="granules",
        key="CREC-2015-06-10",
        url="https://x.invalid/a",
        status=200,
        media_type="application/json",
        body=b"{}",
        answer="ok",
    )
    log.record(
        publisher="govinfo",
        purpose="section",
        key="g",
        url="https://x.invalid/b",
        status=200,
        media_type="text/html",
        body=b"<pre/>",
        answer="ok",
        requests=3,
    )
    log.record(
        publisher="congress-gov",
        purpose="detail",
        key="114-ec-1",
        url="https://x.invalid/c",
        status=404,
        media_type=None,
        body=None,
        answer="absent",
    )
    assert (log.spent("govinfo"), log.spent("congress-gov")) == (4, 1)

    # A second process reads the same ledger rather than starting fresh.
    resumed = RequestLog(tmp_path / "receipt")
    assert (resumed.spent("govinfo"), resumed.spent("congress-gov")) == (4, 1)


def test_a_transport_failure_is_retried_on_resume_and_the_publishers_own_answer_is_not(
    tmp_path: Path,
) -> None:
    """`AGENTS.md`: a 404 is a record; a 502 is not, and establishes nothing."""
    from tools.analysis.record_communications_overlap import _answers

    log = RequestLog(tmp_path / "receipt")
    for key, answer, status in (("114-ec-1", "absent", 404), ("114-ec-2", "refused", 502), ("114-ec-3", "ok", 200)):
        log.record(
            publisher="congress-gov",
            purpose="detail",
            key=key,
            url="https://x.invalid/a",
            status=status,
            media_type=None,
            body=None,
            answer=answer,
        )
    answers = _answers(log, "congress-gov", "detail")
    outstanding = {key for key, answer in answers.items() if answer not in {"ok", "absent", "requested-empty"}}
    assert outstanding == {"114-ec-2"}


def test_entries_are_requested_round_robin_so_a_cap_truncates_every_issue(tmp_path: Path) -> None:
    receipt = build_receipt(
        tmp_path / "receipt",
        sections={
            "CREC-2016-02-12-pt1-PgH815-4": ("CREC-2016-02-12-pt1-PgH815-4.excerpt.htm", 114),
            "CREC-2008-06-11-pt1-PgH5326-4": ("CREC-2008-06-11-pt1-PgH5326-4.excerpt.htm", 110),
        },
        details={},
    )
    ordered = round_robin(list(retained_entries(receipt)))
    assert [entry.record_granule_id for _, entry in ordered] == [
        "CREC-2008-06-11-pt1-PgH5326-4",
        "CREC-2016-02-12-pt1-PgH815-4",
        "CREC-2008-06-11-pt1-PgH5326-4",
        "CREC-2016-02-12-pt1-PgH815-4",
        "CREC-2016-02-12-pt1-PgH815-4",
        "CREC-2016-02-12-pt1-PgH815-4",
    ]
    # Taking issue order instead would have spent the first four requests
    # entirely inside one section, which is the bias this avoids.
    assert [entry.number for _, entry in ordered[:4]] == [7093, 4329, 7094, 4335]


# --- credentials ----------------------------------------------------------------------


def test_a_planted_credential_survives_in_no_recorded_field(tmp_path: Path) -> None:
    secret = "K" * 40
    log = RequestLog(tmp_path / "receipt", secrets=(secret,))
    log.record(
        publisher="congress-gov",
        purpose="detail",
        key="114-ec-1",
        url=f"https://api.congress.gov/v3/house-communication/114/EC/1?api_key={secret}",
        status=500,
        media_type=None,
        body=None,
        answer="refused",
        note=f"RuntimeError: refused at ?api_key={secret} for {secret}",
    )
    written = (tmp_path / "receipt" / "requests.jsonl").read_text()
    assert secret not in written
    assert "<redacted>" in written


def test_a_credential_prefix_cannot_survive_truncation(tmp_path: Path) -> None:
    """Scrub before truncating: truncating first leaves the front of a key standing."""
    secret = "S" * 40
    log = RequestLog(tmp_path / "receipt", secrets=(secret,))
    log.record(
        publisher="congress-gov",
        purpose="detail",
        key="114-ec-1",
        url="https://x.invalid/a",
        status=500,
        media_type=None,
        body=None,
        answer="refused",
        note="x" * 380 + secret,
    )
    row = json.loads((tmp_path / "receipt" / "requests.jsonl").read_text().splitlines()[0])
    assert len(row["note"]) <= 400
    assert secret[:8] not in row["note"]


# --- the report block -----------------------------------------------------------------


def test_render_rewrites_only_the_block_between_the_markers(tmp_path: Path, ground_truth_receipt: Path) -> None:
    measurement = score(ground_truth_receipt)
    output = tmp_path / "m.json"
    output.write_text(json.dumps(measurement))
    report = tmp_path / "m.md"
    report.write_text(
        "# Title\n\nkept before\n\n<!-- generated: record-communications-overlap -->\nstale\n"
        "<!-- end generated -->\n\nkept after\n"
    )
    render(output, report)
    text = report.read_text()
    assert text.startswith("# Title\n\nkept before\n")
    assert text.endswith("kept after\n")
    assert "stale" not in text
    assert "| `abstract` | 2 | 2 | 100.0% |" in text
    assert generated_block(measurement) in text


def test_the_committed_sidecar_and_report_agree() -> None:
    """A report cannot drift from its own measurement."""
    output = ROOT / "docs/research/record-communications-overlap-2026-09-20.json"
    report = ROOT / "docs/research/record-communications-overlap-2026-09-20.md"
    if not output.exists():
        pytest.skip("the measurement has not been run yet")
    assert generated_block(json.loads(output.read_text())) in report.read_text()


def test_a_receipt_filename_is_safe_for_a_granule_key() -> None:
    assert safe_name("CREC-2016-02-12-pt1-PgH815-4") == "CREC-2016-02-12-pt1-PgH815-4"
    assert "/" not in safe_name("a/b?c=d")
