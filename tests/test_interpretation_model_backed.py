"""Section classification and bill summaries: sealed prompts, injected model, kept provenance."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from spicy_docs.interpretation import bill_summaries, section_classification
from spicy_docs.interpretation.bill_summaries import (
    DIFF_SUMMARY_ANSWER_SCHEMA,
    DIFF_SUMMARY_FIELDS,
    DIFF_SUMMARY_PROMPT_VERSION,
    MAX_PROVISIONS,
    MONEY_BILL_FRAMES,
    SUMMARY_ANSWER_SCHEMA,
    SUMMARY_CHARS,
    SUMMARY_FIELDS,
    BillVersionText,
    DiffItemText,
    build_diff_prompt,
    build_prompt,
    content_hash,
    diff_text_from_items,
    needs_regeneration,
    summarize_bill,
    summarize_diff,
)
from spicy_docs.interpretation.model_call import (
    AnswerField,
    ModelCallError,
    ModelResponse,
    answer_schema,
    answer_shape_block,
)
from spicy_docs.interpretation.money_bills import MONEY_BILL_KINDS
from spicy_docs.interpretation.section_classification import (
    CLASSIFICATION_ANSWER_SCHEMA,
    CLASSIFICATION_FIELDS,
    CLASSIFICATION_LABELS,
    CLASSIFICATIONS_WRAPPER_KEY,
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
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
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
    assert result.prompt_version == section_classification.PROMPT_VERSION
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
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse({"classifications": [{"sectionId": "sec-99", "label": "other", "confidence": 1}]})

    with pytest.raises(ModelCallError, match="outside its batch"):
        classify_sections(sections(1), call, model="m", clock=clock())


def test_a_confidence_outside_zero_to_one_is_refused() -> None:
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
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


def summary_call(*, model: str, prompt: str, **_: object) -> ModelResponse:
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
    assert result.prompt_version == bill_summaries.PROMPT_VERSION
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
    current = bill_summaries.PROMPT_VERSION
    assert not needs_regeneration(cached_content_hash=digest, cached_prompt_version=current, digest=digest)
    # A summary stored under the prompt that never named its keys is regenerated.
    assert needs_regeneration(cached_content_hash=digest, cached_prompt_version="v1", digest=digest)
    assert needs_regeneration(cached_content_hash=None, cached_prompt_version=current, digest=digest)


def test_a_summary_outside_the_declared_length_is_refused() -> None:
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse({"summary": "Too short.", "audience": "Readers", "topThreeProvisions": []})

    with pytest.raises(ModelCallError, match="characters"):
        summarize_bill(VERSION, call, model="m", clock=clock())


def test_more_than_three_provisions_is_refused() -> None:
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
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
    # v2 (2026-09-19): both prompts name the keys and types their readers
    # require. The two constants have moved apart since: the classification
    # prompt is at v3 (2026-09-20) because only its `sectionId` wording was
    # wrong, and a version is per prompt so that a stored row stays
    # attributable to the bytes that produced it.
    assert bill_summaries.PROMPT_VERSION == "v2"
    assert section_classification.PROMPT_VERSION == "v3"


# --- diff summaries (ported from BillTrax summarize/route.ts) ---

DIFF_ITEMS = (
    DiffItemText("unchanged", "Kept Section", "Kept Section", "same text", "same text"),
    DiffItemText("added", None, "New Widget Program", None, "Funds $2M for widget research."),
    DiffItemText("removed", "Old Gadget Program", None, "Funded gadget research.", None),
)


def diff_call(*, model: str, prompt: str, **_: object) -> ModelResponse:
    return ModelResponse(
        {
            "headline": "Adds widget research funding, drops gadget program.",
            "keyChanges": ["Adds $2M for widget research", "Removes gadget program funding"],
            "sectionsAdded": ["New Widget Program"],
            "sectionsRemoved": ["Old Gadget Program"],
            "dollarChanges": ["Section New Widget Program increased by $2M"],
        },
        input_tokens=400,
        output_tokens=60,
    )


def test_diff_text_drops_unchanged_items_and_excerpts_each_body() -> None:
    text = diff_text_from_items(DIFF_ITEMS)
    assert "Kept Section" not in text
    assert text == (
        "[ADDED] New Widget Program: Funds $2M for widget research.\n\n"
        "[REMOVED] Old Gadget Program: Funded gadget research."
    )


def test_diff_text_falls_back_to_the_older_placement_only_when_the_newer_is_none() -> None:
    # `d.to_heading ?? d.from_heading` -- only None falls through; an empty
    # string heading or body is kept exactly as sent (route.ts:106-107).
    item = DiffItemText("modified", "Old Heading", "", "old body", "")
    assert diff_text_from_items((item,)) == "[MODIFIED] : "


def test_diff_text_caps_items_at_forty_and_excerpts_at_three_hundred_characters() -> None:
    long_item = DiffItemText("added", None, "Long", None, "z" * 400)
    text = diff_text_from_items((long_item,) * 50)
    assert text.count("[ADDED]") == 40
    assert "z" * 300 in text and "z" * 301 not in text


def test_a_diff_with_only_unchanged_items_produces_no_row() -> None:
    only_unchanged = (DiffItemText("unchanged", "A", "A", "x", "x"),)
    assert (
        summarize_diff(
            VERSION.identity, from_version_id="v1", to_version_id="v2", items=only_unchanged, call=diff_call, model="m"
        )
        is None
    )


def test_the_diff_summary_keeps_the_exact_provenance_columns() -> None:
    result = summarize_diff(
        VERSION.identity,
        from_version_id="v1",
        to_version_id="v2",
        items=DIFF_ITEMS,
        call=diff_call,
        model="test-model-1",
        clock=clock(),
    )
    assert result is not None
    assert result.identity == VERSION.identity
    assert (result.from_version_id, result.to_version_id) == ("v1", "v2")
    assert result.headline == "Adds widget research funding, drops gadget program."
    assert result.key_changes == ("Adds $2M for widget research", "Removes gadget program funding")
    assert result.sections_added == ("New Widget Program",)
    assert result.sections_removed == ("Old Gadget Program",)
    assert result.dollar_changes == ("Section New Widget Program increased by $2M",)
    assert result.model == "test-model-1"
    assert result.prompt_version == DIFF_SUMMARY_PROMPT_VERSION == "v2"
    assert result.content_hash == content_hash(diff_text_from_items(DIFF_ITEMS))
    assert (result.input_tokens, result.output_tokens) == (400, 60)
    assert result.requested_at == "2026-09-19T12:00:00+00:00"
    assert result.completed_at == "2026-09-19T12:00:03+00:00"


@pytest.mark.parametrize(
    "answer,match",
    [
        ("not-a-mapping", "must be a mapping"),
        ({"keyChanges": [], "sectionsAdded": [], "sectionsRemoved": [], "dollarChanges": []}, "headline"),
        ({"headline": "H", "sectionsAdded": [], "sectionsRemoved": [], "dollarChanges": []}, "keyChanges"),
        (
            {
                "headline": "H",
                "keyChanges": "not-a-list",
                "sectionsAdded": [],
                "sectionsRemoved": [],
                "dollarChanges": [],
            },
            "keyChanges",
        ),
        (
            {"headline": "H", "keyChanges": [1], "sectionsAdded": [], "sectionsRemoved": [], "dollarChanges": []},
            "keyChanges",
        ),
    ],
)
def test_a_malformed_diff_summary_answer_is_refused(answer, match) -> None:
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse(answer)

    with pytest.raises(ModelCallError, match=match):
        summarize_diff(
            VERSION.identity, from_version_id="v1", to_version_id="v2", items=DIFF_ITEMS, call=call, model="m"
        )


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
    # v1 was b16cf2b16fdf32ddca72facd2db5d87cff0b12d3e0e69b28cf3ab65550173655;
    # it named none of the keys _read_answer requires (C1, 2026-09-19).
    assert bill_summaries.PROMPT_VERSION == "v2"
    assert digest(build_prompt(VERSION)) == "5f2cf1983b3065d3674646c97b07b08f15ea3d2ff9352094d2f187dd409d212e"


def test_the_classification_prompt_is_the_pinned_bytes() -> None:
    # v1 was 7fdb2f0aca587e55f62cece1fbdc7455fa27f583665f5d38f9f64950bf4c3bc7.
    # v2 was 3c8af9496addd0b8598212f2f2b899950284c5aa850a47f04c92cd8f4cd5909f;
    # it asked for "the section's bracketed id, copied exactly as given below"
    # and two live calls copied the brackets too, storing zero rows. v3 names
    # the part of the bracketed line it wants. `section_block` is untouched:
    # `[<id>] <heading>` is BillTrax's own rendering.
    assert section_classification.PROMPT_VERSION == "v3"
    assert digest(section_classification.build_prompt(PINNED_SECTIONS)) == (
        "63005e503ed202cd94a4595227733c2f446b451e8f4c5e60f11ef47ece7c3631"
    )


def test_the_diff_summary_prompt_is_the_pinned_bytes() -> None:
    # v1 was f9828decc6d973153997d44c693234bf331d8befa4c6f86be7ab2a76c1b15387,
    # `summarize/route.ts:119-129`'s template literal byte for byte. v2 keeps
    # its wording and order but states each key's type (see the module
    # docstring); it still carries no non-ASCII bytes, unlike the two prompts
    # above.
    assert DIFF_SUMMARY_PROMPT_VERSION == "v2"
    prompt = build_diff_prompt(diff_text_from_items(DIFF_ITEMS))
    assert digest(prompt) == "74172eba372dc534989ad25e96ae24b92c6402c55ec1990c4511fca8c2ecb967"
    assert prompt.isascii()


def test_the_prompts_carry_the_source_s_own_typography() -> None:
    assert "— someone who does not work in government" in bill_summaries.SUMMARY_PROMPT_TEMPLATE
    assert "Bill: {display_number} — {title}" in bill_summaries.SUMMARY_PROMPT_TEMPLATE
    assert "A single paragraph (4–6 sentences)" in SUMMARY_FIELDS[0].describes
    assert "package — a single bill" in MONEY_BILL_FRAMES["omnibus"]
    assert "bill — emergency or one-time" in MONEY_BILL_FRAMES["supplemental"]
    assert "levels — it does NOT appropriate" in MONEY_BILL_FRAMES["ndaa"]
    # The TS sources carry exactly these two non-ASCII codepoints inside the
    # prompt-bearing literals; anything else means a character drifted. Since
    # v2 the field declarations are prompt-bearing too -- their lines are what
    # is sent -- so they are folded in here, and the diff prompt (whose TS
    # source has no typographic dashes) must not change the set.
    sealed = bill_summaries.SUMMARY_PROMPT_TEMPLATE + section_classification.CLASSIFY_PROMPT_TEMPLATE
    sealed += "".join(MONEY_BILL_FRAMES.values()) + bill_summaries.DIFF_SUMMARY_PROMPT_TEMPLATE
    sealed += "".join(field.kind + field.describes for _, _, fields in PROMPTS for field in fields)
    assert {character for character in sealed if ord(character) > 127} == {"–", "—"}


# --- the prompt and its reader are one statement (C1, 2026-09-19) ---

#: Every prompt with the declaration its own reader reads. Both are taken from
#: the module, never restated here: a test that repeats a key spelling can only
#: prove the spelling it repeated.
PROMPTS: tuple[tuple[str, str, tuple[AnswerField, ...]], ...] = (
    ("summary", build_prompt(VERSION), SUMMARY_FIELDS),
    ("classification", section_classification.build_prompt(PINNED_SECTIONS), CLASSIFICATION_FIELDS),
    ("diff summary", build_diff_prompt(diff_text_from_items(DIFF_ITEMS)), DIFF_SUMMARY_FIELDS),
)

#: The keys and types the model returned on the first live bill-summary call,
#: taken from the retained receipt `c1-provenance.json` (204 tokens in, 206
#: out). The values stand in for the model's prose, which the receipt
#: deliberately did not retain: only the shape is the evidence.
#:
#: The spelling is the model's, and it was not stable. That run's own README
#: tabulates `affected_audience` from another invocation of the byte-identical
#: v1 prompt, where the retained JSON records `most_affected_audience`. Both
#: miss the same two keys and refuse identically, which is why the fix is a
#: prompt that states the key set, not a reader taught one more synonym.
C1_LIVE_ANSWER = {
    "summary": "This bill funds the Department of Defense for the coming fiscal year. " * 3,
    "most_affected_audience": "Service members and defense contractors",
    "notable_provisions": ["Sets troop pay", "Authorizes shipbuilding"],
}
#: The other invocation's spelling, from the same receipt's README table.
C1_OTHER_SPELLING = "affected_audience"


@pytest.mark.parametrize("name,prompt,fields", PROMPTS, ids=[row[0] for row in PROMPTS])
def test_each_prompt_names_every_key_its_reader_requires(name, prompt, fields) -> None:
    assert fields, f"the {name} prompt declares no answer fields"
    for field in fields:
        assert f'"{field.key}" ({field.kind})' in prompt
        for alias in field.aliases:
            # An alias is tolerated on the way in, never offered on the way out.
            assert f'"{alias}"' not in prompt
    # And nothing beyond them: the prompt's key list is the declaration itself,
    # so it cannot offer a key no reader declares.
    assert answer_shape_block(fields) in prompt


def test_the_wrapper_the_reader_unwraps_is_not_offered_by_the_prompt() -> None:
    # BillTrax's ClassifySchema wrapped the array (classifications.ts:21-29),
    # so the wrapper stays readable; the prompt asks for the bare array, and
    # both shapes must reach _read_row.
    prompt = section_classification.build_prompt(PINNED_SECTIONS)
    assert '"classifications"' not in prompt
    row = {"sectionId": "sec-0", "label": "other", "confidence": 0.5}
    for answer in (row_list := [row], {"classifications": row_list}):
        results = classify_sections(
            sections(1), lambda *, model, prompt, a=answer, **_: ModelResponse(a), model="m", clock=clock()
        )
        assert [result.section_id for result in results] == ["sec-0"]


@pytest.mark.parametrize(
    "answer,reads",
    [
        ({"summary": None, "audience": "Readers", "top_provisions": ["a"]}, ("a",)),
        ({"summary": None, "audience": "Readers", "topThreeProvisions": ["a"]}, ("a",)),
    ],
    ids=["snake_cased alias", "the key the prompt names"],
)
def test_the_reader_accepts_the_alias_the_prompt_does_not_offer(answer, reads) -> None:
    answer = {**answer, "summary": C1_LIVE_ANSWER["summary"]}
    result = summarize_bill(VERSION, lambda *, model, prompt, **_: ModelResponse(answer), model="m", clock=clock())
    assert result is not None
    assert result.top_provisions == reads


def test_a_classification_row_keyed_by_the_snake_cased_alias_is_read() -> None:
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse([{"section_id": "sec-0", "label": "deadline", "confidence": 0.7}])

    results = classify_sections(sections(1), call, model="m", clock=clock())
    assert [(r.section_id, r.label) for r in results] == [("sec-0", "deadline")]


def test_the_answer_the_first_live_call_returned_names_the_keys_it_is_missing() -> None:
    # The v1 prompt asked for its three items in prose and named no key, so
    # gemini-3.8-flash chose its own spellings and the reader refused the
    # answer: 204 tokens in, 206 out, zero rows (receipt
    # ~/Work/corpora/supply-2026-09-02/receipts/d1-measured-run-2026-09-19).
    # A refusal must name every key that is missing, not just the first.
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse(dict(C1_LIVE_ANSWER), input_tokens=204, output_tokens=206)

    with pytest.raises(ModelCallError) as refusal:
        summarize_bill(VERSION, call, model="gemini-3.8-flash", clock=clock())
    assert str(refusal.value) == "summary answer is missing audience, topThreeProvisions"
    assert refusal.value.details == C1_LIVE_ANSWER


def test_the_other_invocations_spelling_refuses_identically() -> None:
    # Same v1 prompt, same bill, a different key the model invented: the
    # refusal names the same two missing keys, so nothing here is tuned to one
    # observed answer.
    answer = {
        "summary": C1_LIVE_ANSWER["summary"],
        C1_OTHER_SPELLING: C1_LIVE_ANSWER["most_affected_audience"],
        "notable_provisions": C1_LIVE_ANSWER["notable_provisions"],
    }
    with pytest.raises(ModelCallError, match="^summary answer is missing audience, topThreeProvisions$"):
        summarize_bill(VERSION, lambda *, model, prompt, **_: ModelResponse(answer), model="m", clock=clock())


def test_the_v2_prompt_asks_for_the_keys_that_answer_lacked() -> None:
    # The other direction: the same answer under the keys the prompt now names
    # is read, so the fix is the spelling and not the content.
    corrected = {
        "summary": C1_LIVE_ANSWER["summary"],
        "audience": C1_LIVE_ANSWER["most_affected_audience"],
        "topThreeProvisions": C1_LIVE_ANSWER["notable_provisions"],
    }
    result = summarize_bill(VERSION, lambda *, model, prompt, **_: ModelResponse(corrected), model="m", clock=clock())
    assert result is not None
    assert result.audience == "Service members and defense contractors"
    assert result.top_provisions == ("Sets troop pay", "Authorizes shipbuilding")


def test_a_diff_answer_that_leaves_its_lists_out_names_them() -> None:
    # The same defect class next door: v1 named the five keys but not their
    # types, so a list with nothing in it could arrive absent or as null.
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse({"headline": "H", "keyChanges": []})

    with pytest.raises(ModelCallError, match="missing sectionsAdded, sectionsRemoved, dollarChanges"):
        summarize_diff(
            VERSION.identity, from_version_id="v1", to_version_id="v2", items=DIFF_ITEMS, call=call, model="m"
        )


def test_a_classification_row_missing_a_key_names_it() -> None:
    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse({"classifications": [{"sectionId": "sec-0", "label": "other"}]})

    with pytest.raises(ModelCallError, match="classification row is missing confidence"):
        classify_sections(sections(1), call, model="m", clock=clock())


# --- the shape is a constraint on the request, not only words in the prompt
#     (2026-09-20; the follow-up the C1 decision named) ---

#: The answers the `v2` prompts actually came back with, live, on 2026-09-19,
#: rebuilt from the rows in
#: `~/Work/corpora/supply-2026-09-02/receipts/c1-prompt-fix-2026-09-19/`
#: (`gemini-3.8-flash`, 250/197 and 309/243 tokens). Unlike `C1_LIVE_ANSWER`
#: above, these are the model's own bytes, because here the values are the
#: evidence: a schema that admits a hand-written answer of the right shape has
#: only checked itself.
LIVE_ANSWERS = json.loads((Path(__file__).parent / "fixtures/interpretation/c1-v2-live-answers.json").read_text())

#: Each declaration beside the schema its module actually sends. Both come from
#: the module; the keys are never restated here, so a field added to a tuple
#: fails this file only by reaching the schema.
#: Each prompt beside the schema its module sends, extending `PROMPTS` rather
#: than restating it, so a row cannot pair one module's prompt with another's
#: schema.
SCHEMAS: tuple[tuple[str, str, tuple[AnswerField, ...], dict], ...] = (
    (*PROMPTS[0], SUMMARY_ANSWER_SCHEMA),
    (*PROMPTS[1], CLASSIFICATION_ANSWER_SCHEMA["items"]),
    (*PROMPTS[2], DIFF_SUMMARY_ANSWER_SCHEMA),
)
SCHEMA_IDS = [row[0] for row in SCHEMAS]


@pytest.mark.parametrize("name,prompt,fields,schema", SCHEMAS, ids=SCHEMA_IDS)
def test_the_schema_requires_exactly_the_keys_its_declaration_names(name, prompt, fields, schema) -> None:
    declared = [field.key for field in fields]
    assert schema == answer_schema(fields), f"the {name} schema is not the one its declaration derives"
    assert schema["required"] == declared
    assert list(schema["properties"]) == declared
    assert schema["additionalProperties"] is False
    for field in fields:
        for alias in field.aliases:
            # Tolerated by the reader, never offered by the request -- in the
            # schema for the same reason it is not in the prompt.
            assert alias not in schema["properties"]
            assert alias not in schema["required"]


@pytest.mark.parametrize("name,prompt,fields,schema", SCHEMAS, ids=SCHEMA_IDS)
def test_the_derived_schema_is_a_draft_2020_12_schema(name, prompt, fields, schema) -> None:
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("name,prompt,fields,schema", SCHEMAS, ids=SCHEMA_IDS)
def test_every_bound_the_schema_enforces_is_stated_in_the_prompt_s_own_words(name, prompt, fields, schema) -> None:
    # The two halves of one declaration, checked against each other: a number
    # the request enforces that the prompt never says would be exactly the v1
    # defect running the other way. Both halves come from this row, so a
    # vocabulary is checked against the prompt that actually carries it.
    bounds = {"minLength", "maxLength", "minItems", "maxItems", "minimum", "maximum"}
    for field in fields:
        for key, value in field.schema.items():
            if key in bounds:
                assert str(value) in field.kind, f"{field.key}: the prompt does not state {key}"
            if key == "enum":
                for choice in value:
                    assert choice in prompt, f"{name}: the prompt never offers {choice}"


@pytest.mark.parametrize(
    "field,message",
    [
        ({"shape": "text"}, "unknown answer shape"),
        ({"shape": "array of strings", "bounds": (1, 3)}, "bound the prompt cannot state"),
        ({"shape": "string", "bounds": (None, 1200)}, "bound the prompt cannot state"),
        ({"shape": "number", "bounds": (0, None)}, "bound the prompt cannot state"),
        ({"shape": "number", "choices": ("a", "b")}, "only a string is drawn from a fixed vocabulary"),
        ({"shape": "string", "bounds": (60,)}, "bounds is a (lower, upper) pair"),
    ],
    ids=[
        "unknown shape",
        "array lower bound",
        "string missing a bound",
        "number missing a bound",
        "choices on a number",
        "a 1-tuple",
    ],
)
def test_a_declaration_the_prompt_could_not_state_is_refused_where_it_is_written(field, message) -> None:
    # `kind` and `schema` are both derived, so a declaration the prompt cannot
    # pronounce would ship a request enforcing more than it says -- the v1
    # defect turned around. It is refused at construction, where the mistake
    # is, rather than at the first live call.
    with pytest.raises(ValueError, match=re.escape(message)):
        AnswerField("someKey", describes="what it holds", **field)


def test_a_key_added_to_a_declaration_reaches_the_schema() -> None:
    widened = (*SUMMARY_FIELDS, AnswerField("sponsorTake", "string", "what the sponsor says it does"))
    schema = answer_schema(widened)
    assert schema["required"][-1] == "sponsorTake"
    assert schema["properties"]["sponsorTake"] == {"type": "string"}


def test_the_schema_states_the_bounds_and_the_vocabulary_its_reader_enforces() -> None:
    summary_properties = SUMMARY_ANSWER_SCHEMA["properties"]
    assert summary_properties["summary"] == {
        "type": "string",
        "minLength": SUMMARY_CHARS[0],
        "maxLength": SUMMARY_CHARS[1],
    }
    assert summary_properties["audience"] == {"type": "string"}
    assert summary_properties["topThreeProvisions"] == {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": MAX_PROVISIONS,
    }
    row = CLASSIFICATION_ANSWER_SCHEMA["items"]["properties"]
    assert row["confidence"] == {"type": "number", "minimum": 0, "maximum": 1}
    assert row["label"] == {"type": "string", "enum": list(LABEL_NAMES)}
    # `keyChanges` names five bullets in its prose and `_read_diff_answer`
    # enforces no count, so the schema states none. A request may not enforce
    # more than its reader does, or a refusal stops being attributable.
    assert DIFF_SUMMARY_ANSWER_SCHEMA["properties"]["keyChanges"] == {"type": "array", "items": {"type": "string"}}


def test_the_classification_request_asks_for_the_bare_array_the_prompt_asks_for() -> None:
    assert CLASSIFICATION_ANSWER_SCHEMA["type"] == "array"
    # The wrapper stays derivable from the same declaration and unsent, like
    # the prompt's own silence about it (BillTrax's ClassifySchema shape).
    wrapped = answer_schema(CLASSIFICATION_FIELDS, wrapper=CLASSIFICATIONS_WRAPPER_KEY)
    assert wrapped["required"] == [CLASSIFICATIONS_WRAPPER_KEY]
    assert wrapped["properties"][CLASSIFICATIONS_WRAPPER_KEY]["items"] == CLASSIFICATION_ANSWER_SCHEMA["items"]
    assert CLASSIFICATIONS_WRAPPER_KEY not in json.dumps(CLASSIFICATION_ANSWER_SCHEMA)


@pytest.mark.parametrize(
    "kind,schema",
    [("summary", SUMMARY_ANSWER_SCHEMA), ("diffSummary", DIFF_SUMMARY_ANSWER_SCHEMA)],
)
def test_the_schema_accepts_the_answers_the_v2_prompts_actually_returned(kind, schema) -> None:
    Draft202012Validator(schema).validate(LIVE_ANSWERS[kind])


def test_the_schema_refuses_both_spellings_the_v1_prompt_provoked() -> None:
    # The same two answers the reader refuses, refused one step earlier -- on
    # the request, where BillTrax refused them. Every key is wrong in the same
    # two ways: two required keys absent, two properties the schema does not
    # allow.
    validator = Draft202012Validator(SUMMARY_ANSWER_SCHEMA)
    other = {
        "summary": C1_LIVE_ANSWER["summary"],
        C1_OTHER_SPELLING: C1_LIVE_ANSWER["most_affected_audience"],
        "notable_provisions": C1_LIVE_ANSWER["notable_provisions"],
    }
    for answer in (C1_LIVE_ANSWER, other):
        missing = {
            error.message.split("'")[1] for error in validator.iter_errors(answer) if error.validator == "required"
        }
        assert missing == {"audience", "topThreeProvisions"}
    assert validator.is_valid(
        {
            "summary": C1_LIVE_ANSWER["summary"],
            "audience": C1_LIVE_ANSWER["most_affected_audience"],
            "topThreeProvisions": C1_LIVE_ANSWER["notable_provisions"],
        }
    )


def test_the_schema_does_not_offer_the_alias_the_reader_still_reads() -> None:
    aliased = {
        "summary": C1_LIVE_ANSWER["summary"],
        "audience": "Readers",
        "top_provisions": ["a"],
    }
    assert not Draft202012Validator(SUMMARY_ANSWER_SCHEMA).is_valid(aliased)
    # ...and the reader reads it anyway; see
    # test_the_reader_accepts_the_alias_the_prompt_does_not_offer above. One
    # direction, on purpose.


def test_each_reader_sends_the_schema_its_own_declaration_derives() -> None:
    sent: list[object] = []

    def recording(answer):
        def call(*, model: str, prompt: str, response_schema=None) -> ModelResponse:
            sent.append(response_schema)
            return ModelResponse(answer)

        return call

    summarize_bill(VERSION, recording(LIVE_ANSWERS["summary"]), model="m", clock=clock())
    summarize_diff(
        VERSION.identity,
        from_version_id="v1",
        to_version_id="v2",
        items=DIFF_ITEMS,
        call=recording(LIVE_ANSWERS["diffSummary"]),
        model="m",
        clock=clock(),
    )
    classify_sections(
        sections(1),
        recording([{"sectionId": "sec-0", "label": "other", "confidence": 0.5}]),
        model="m",
        clock=clock(),
    )
    assert sent == [SUMMARY_ANSWER_SCHEMA, DIFF_SUMMARY_ANSWER_SCHEMA, CLASSIFICATION_ANSWER_SCHEMA]


#: The three section ids the 2026-09-20 batch actually sent, from the receipt
#: `~/Work/corpora/supply-2026-09-02/receipts/c1-classification-2026-09-20/`.
#: The prompt shows each one inside brackets (`section_block`), and the live
#: answer copied the brackets too.
LIVE_SECTION_IDS = tuple(f"introduced-in-house|govinfo|{index}" for index in range(3))


def test_the_schema_accepts_the_classification_answer_that_the_reader_refused() -> None:
    # The whole point of keeping the reader as the contract. This answer is
    # schema-valid in every respect the schema constrains -- a bare array,
    # three rows, the three required keys, a label from the sealed enum, a
    # confidence in range -- and it is still an answer no row may be stored
    # from, because every `sectionId` names a section the batch never sent.
    Draft202012Validator(CLASSIFICATION_ANSWER_SCHEMA).validate(LIVE_ANSWERS["classification"])


def test_the_live_classification_answer_copied_the_prompt_s_own_brackets() -> None:
    # Measured 2026-09-20 under `v2`, `gemini-3.8-flash`, 263 in / 80 out, one
    # keyed call. `section_block` writes `[<id>] <heading>` and the `v2`
    # `sectionId` field asked for "the section's bracketed id, copied exactly
    # as given below", so the model returned `[introduced-in-house|govinfo|0]`
    # -- the id as shown, brackets and all -- while `_read_row` requires the
    # bare id. Same defect family as the `v1` key spellings: the prompt
    # describes the value it wants ambiguously and the reader enforces
    # something else.
    #
    # The wording moved to `v3` the same day and `section_block` did not: the
    # bracketed line is BillTrax's own. This answer is kept exactly as it came
    # back, as the **counter-example**. It is what the old phrase provoked, and
    # the reader refuses it under every prompt version, which is why the fix
    # was the prompt and never a widened reader.
    returned = [row["sectionId"] for row in LIVE_ANSWERS["classification"]]
    assert returned == [f"[{section_id}]" for section_id in LIVE_SECTION_IDS]
    for section_id in LIVE_SECTION_IDS:
        assert f"[{section_id}]" in section_classification.section_block(
            [ClassifiableSection(section_id, "body", "Heading")]
        )

    def call(*, model: str, prompt: str, **_: object) -> ModelResponse:
        return ModelResponse(LIVE_ANSWERS["classification"], input_tokens=263, output_tokens=80)

    batch = tuple(ClassifiableSection(section_id, f"body {index}") for index, section_id in enumerate(LIVE_SECTION_IDS))
    with pytest.raises(ModelCallError, match="outside its batch"):
        classify_sections(batch, call, model="gemini-3.8-flash", clock=clock())


def test_the_schema_travels_beside_the_prompt_and_not_inside_it() -> None:
    # The prompts' pinned digests above are the real assertion that adding a
    # response schema changed no prompt byte and so no PROMPT_VERSION. This
    # states the reason they still hold: nothing about the schema is rendered
    # into a prompt.
    assert bill_summaries.PROMPT_VERSION == DIFF_SUMMARY_PROMPT_VERSION == "v2"
    assert section_classification.PROMPT_VERSION == "v3"
    for _, prompt, _fields in PROMPTS:
        for token in ("responseJsonSchema", "additionalProperties", "minLength", "maxItems", "required"):
            assert token not in prompt
