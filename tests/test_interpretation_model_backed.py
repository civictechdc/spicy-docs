"""Section classification and bill summaries: sealed prompts, injected model, kept provenance."""

import hashlib
from datetime import UTC, datetime

import pytest

from spicy_docs.interpretation import bill_summaries, section_classification
from spicy_docs.interpretation.bill_summaries import (
    MONEY_BILL_FRAMES,
    BillVersionText,
    build_prompt,
    content_hash,
    needs_regeneration,
    summarize_bill,
)
from spicy_docs.interpretation.model_call import ModelCallError, ModelResponse
from spicy_docs.interpretation.money_bills import MONEY_BILL_KINDS
from spicy_docs.interpretation.section_classification import (
    CLASSIFICATION_LABELS,
    LABEL_NAMES,
    ClassifiableSection,
    classify_sections,
)
from spicy_docs.sources.congress.bill_status import BillIdentity

CLOCK_TIMES = [datetime(2026, 9, 19, 12, 0, tzinfo=UTC), datetime(2026, 9, 19, 12, 0, 3, tzinfo=UTC)]


def clock():
    times = iter(CLOCK_TIMES * 8)
    return lambda: next(times)


def sections(count: int) -> tuple[ClassifiableSection, ...]:
    return tuple(ClassifiableSection(f"sec-{index}", f"body {index}", f"Heading {index}") for index in range(count))


def answering(labels: dict[str, str]):
    def call(*, model: str, prompt: str) -> ModelResponse:
        rows = [
            {"sectionId": section_id, "label": label, "confidence": 0.9}
            for section_id, label in labels.items()
            if f"[{section_id}]" in prompt
        ]
        return ModelResponse({"classifications": rows}, input_tokens=100, output_tokens=20)

    return call


# --- section classification ---


def test_the_five_labels_are_the_sealed_vocabulary() -> None:
    assert LABEL_NAMES == ("funding_opportunity", "directive", "deadline", "restriction", "other")


def test_the_prompt_is_generated_from_the_label_table() -> None:
    prompt = section_classification.build_prompt(sections(1))
    for label in CLASSIFICATION_LABELS:
        assert f"- {label.name}: {label.definition}" in prompt
    assert "[sec-0] Heading 0" in prompt


def test_the_body_is_truncated_to_five_hundred_characters() -> None:
    long_section = ClassifiableSection("sec-long", "y" * 900)
    prompt = section_classification.build_prompt((long_section,))
    assert "y" * 500 in prompt
    assert "y" * 501 not in prompt


def test_classification_carries_the_provenance_billtrax_never_stored() -> None:
    results = classify_sections(sections(1), answering({"sec-0": "directive"}), model="test-model-1", clock=clock())
    assert len(results) == 1
    result = results[0]
    assert (result.section_id, result.label, result.confidence) == ("sec-0", "directive", 0.9)
    assert result.model == "test-model-1"
    assert result.prompt_version == "v1"
    assert len(result.prompt_hash) == 64
    assert result.requested_at == "2026-09-19T12:00:00+00:00"
    assert result.completed_at == "2026-09-19T12:00:03+00:00"


def test_sections_are_sent_in_batches_and_each_batch_is_named() -> None:
    labels = {f"sec-{index}": "other" for index in range(5)}
    results = classify_sections(sections(5), answering(labels), model="m", batch_size=2, clock=clock())
    assert len(results) == 5
    assert [result.batch_index for result in results] == [0, 0, 1, 1, 2]
    assert len({result.prompt_hash for result in results}) == 3


def test_a_label_outside_the_vocabulary_is_refused() -> None:
    with pytest.raises(ModelCallError, match="sealed vocabulary"):
        classify_sections(sections(1), answering({"sec-0": "urgent"}), model="m", clock=clock())


def test_a_section_the_batch_never_named_is_refused() -> None:
    def call(*, model: str, prompt: str) -> ModelResponse:
        return ModelResponse({"classifications": [{"sectionId": "sec-99", "label": "other", "confidence": 1}]})

    with pytest.raises(ModelCallError, match="outside its batch"):
        classify_sections(sections(1), call, model="m", clock=clock())


def test_a_confidence_outside_zero_to_one_is_refused() -> None:
    def call(*, model: str, prompt: str) -> ModelResponse:
        return ModelResponse({"classifications": [{"sectionId": "sec-0", "label": "other", "confidence": 4}]})

    with pytest.raises(ModelCallError, match="0 to 1"):
        classify_sections(sections(1), call, model="m", clock=clock())


# --- bill summaries ---

VERSION = BillVersionText(
    identity=BillIdentity(119, "hr", 4366),
    version_id="ver-1",
    version_label="Engrossed in House",
    title="Department of Defense Appropriations Act, 2026",
    status="Passed House by recorded vote: 217-212.",
    text="A BILL making appropriations for the Department of Defense. " * 20,
    money_bill_kind="ndaa",
)


def summary_call(*, model: str, prompt: str) -> ModelResponse:
    return ModelResponse(
        {
            "summary": "This bill authorizes defense programs for the coming fiscal year. " * 3,
            "audience": "Defense contractors and service members",
            "topThreeProvisions": ["Sets troop pay", "Authorizes shipbuilding"],
        },
        input_tokens=5000,
        output_tokens=250,
    )


def test_every_money_bill_kind_has_a_sealed_frame() -> None:
    assert set(MONEY_BILL_FRAMES) == set(MONEY_BILL_KINDS)


def test_the_ndaa_frame_keeps_the_authorize_versus_appropriate_distinction() -> None:
    assert "does NOT appropriate" in MONEY_BILL_FRAMES["ndaa"]
    assert MONEY_BILL_FRAMES["ndaa"] in build_prompt(VERSION)


def test_the_prompt_carries_the_identity_status_and_capped_body() -> None:
    prompt = build_prompt(VERSION)
    assert "Bill: HR 4366 — Department of Defense Appropriations Act, 2026" in prompt
    assert "Version: Engrossed in House" in prompt
    assert "Passed House by recorded vote: 217-212." in prompt
    long_version = BillVersionText(
        VERSION.identity, "ver-2", "Introduced", "Title", "Introduced in House", "z" * 30_000
    )
    body = build_prompt(long_version).split("Bill text (may be truncated):\n", 1)[1]
    assert len(body) == 25_000


def test_the_summary_keeps_the_exact_provenance_columns() -> None:
    result = summarize_bill(VERSION, summary_call, model="test-model-1", clock=clock())
    assert result is not None
    assert result.model == "test-model-1"
    assert result.prompt_version == "v1"
    assert result.content_hash == content_hash(VERSION.text)
    assert (result.input_tokens, result.output_tokens) == (5000, 250)
    assert result.requested_at == "2026-09-19T12:00:00+00:00"
    assert result.completed_at == "2026-09-19T12:00:03+00:00"
    assert result.identity == VERSION.identity
    assert result.version_id == "ver-1"
    assert result.top_provisions == ("Sets troop pay", "Authorizes shipbuilding")


def test_a_version_too_short_to_summarize_produces_no_row() -> None:
    stub = BillVersionText(VERSION.identity, "ver-3", "Introduced", "Title", "Introduced in House", "too short")
    assert summarize_bill(stub, summary_call, model="m", clock=clock()) is None


def test_regeneration_is_decided_by_content_hash_and_prompt_version() -> None:
    digest = content_hash(VERSION.text)
    assert not needs_regeneration(cached_content_hash=digest, cached_prompt_version="v1", digest=digest)
    assert needs_regeneration(cached_content_hash=digest, cached_prompt_version="v0", digest=digest)
    assert needs_regeneration(cached_content_hash=None, cached_prompt_version="v1", digest=digest)


def test_a_summary_outside_the_declared_length_is_refused() -> None:
    def call(*, model: str, prompt: str) -> ModelResponse:
        return ModelResponse({"summary": "Too short.", "audience": "Readers", "topThreeProvisions": []})

    with pytest.raises(ModelCallError, match="characters"):
        summarize_bill(VERSION, call, model="m", clock=clock())


def test_more_than_three_provisions_is_refused() -> None:
    def call(*, model: str, prompt: str) -> ModelResponse:
        return ModelResponse(
            {
                "summary": "A sufficiently long plain-language summary of the bill. " * 3,
                "audience": "Readers",
                "topThreeProvisions": list("abcd"),
            }
        )

    with pytest.raises(ModelCallError, match="at most 3"):
        summarize_bill(VERSION, call, model="m", clock=clock())


def test_both_model_backed_modules_share_one_prompt_version_constant_shape() -> None:
    assert bill_summaries.PROMPT_VERSION == section_classification.PROMPT_VERSION == "v1"


# --- the prompts are sealed bytes, pinned ---

PINNED_SECTIONS = (
    ClassifiableSection("sec-0", "body 0", "Heading 0"),
    ClassifiableSection("sec-1", "body 1", None),
)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_summary_prompt_is_the_pinned_bytes() -> None:
    # A prompt is sealed under PROMPT_VERSION: changing one character changes
    # what every stored summary was generated from, so it changes with the
    # version or not at all. Typography counts -- the em and en dashes here are
    # the source's own, not ASCII hyphens.
    assert digest(build_prompt(VERSION)) == "b16cf2b16fdf32ddca72facd2db5d87cff0b12d3e0e69b28cf3ab65550173655"


def test_the_classification_prompt_is_the_pinned_bytes() -> None:
    assert digest(section_classification.build_prompt(PINNED_SECTIONS)) == (
        "7fdb2f0aca587e55f62cece1fbdc7455fa27f583665f5d38f9f64950bf4c3bc7"
    )


def test_the_prompts_carry_the_source_s_own_typography() -> None:
    assert "— someone who does not work in government" in bill_summaries.SUMMARY_PROMPT_TEMPLATE
    assert "Bill: {display_number} — {title}" in bill_summaries.SUMMARY_PROMPT_TEMPLATE
    assert "A single paragraph (4–6 sentences)" in bill_summaries.SUMMARY_PROMPT_TEMPLATE
    assert "package — a single bill" in MONEY_BILL_FRAMES["omnibus"]
    assert "bill — emergency or one-time" in MONEY_BILL_FRAMES["supplemental"]
    assert "levels — it does NOT appropriate" in MONEY_BILL_FRAMES["ndaa"]
    assert "confidence (0–1)" in section_classification.CLASSIFY_PROMPT_TEMPLATE
    # The TS sources carry exactly these two non-ASCII codepoints inside the
    # prompt-bearing literals; anything else means a character drifted.
    sealed = bill_summaries.SUMMARY_PROMPT_TEMPLATE + section_classification.CLASSIFY_PROMPT_TEMPLATE
    sealed += "".join(MONEY_BILL_FRAMES.values())
    assert {character for character in sealed if ord(character) > 127} == {"–", "—"}
