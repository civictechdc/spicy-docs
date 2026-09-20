"""The Gemini adapter: the request it builds, the answer it parses, what it refuses.

The seam it fills is the one the two model-backed interpretation modules take,
so what matters here is that the schema each of those modules derived from its
own answer declaration actually *leaves* -- as `responseJsonSchema`, beside
`responseMimeType`, which is where BillTrax's zod schemas sat and what this
port dropped (register row C1, 2026-09-19).
"""

import json

import pytest

from spicy_docs.extraction.gemini import json_generation_config
from spicy_docs.interpretation.bill_summaries import SUMMARY_ANSWER_SCHEMA
from spicy_docs.interpretation.gemini_call import DEFAULT_MODEL, model_call
from spicy_docs.interpretation.model_call import ModelCallError


class StubClient:
    """A ``GenerationClient`` that records the body and answers with a fixed payload."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def generate(self, model, body):
        self.calls.append((model, body))
        return self.payload


def envelope(text, *, usage=None):
    payload = {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]}
    if usage is not None:
        payload["usageMetadata"] = usage
    return payload


def test_the_schema_the_caller_derived_is_what_leaves_on_the_request() -> None:
    client = StubClient(envelope('{"ok": true}'))
    model_call(client)(model="gemini-x", prompt="the prompt", response_schema=SUMMARY_ANSWER_SCHEMA)
    model, body = client.calls[0]
    assert model == "gemini-x"
    config = body["generationConfig"]
    # The publisher's own two spellings, asserted against literals exactly
    # once: everything else in this repository builds them through
    # `json_generation_config`.
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"] == SUMMARY_ANSWER_SCHEMA
    assert body["contents"] == [{"role": "user", "parts": [{"text": "the prompt"}]}]


def test_an_adapter_asked_for_no_schema_sends_none() -> None:
    # `response_schema` is optional on the seam, so the body must not grow a
    # null schema key that the publisher would have to interpret.
    client = StubClient(envelope("{}"))
    model_call(client)(model="m", prompt="p")
    config = client.calls[0][1]["generationConfig"]
    assert "responseJsonSchema" not in config
    assert config == json_generation_config()


def test_the_parsed_answer_and_the_publishers_own_token_counts_come_back() -> None:
    payload = envelope(
        json.dumps({"summary": "s", "audience": "a", "topThreeProvisions": []}),
        usage={"promptTokenCount": 250, "candidatesTokenCount": 197},
    )
    response = model_call(StubClient(payload))(model="m", prompt="p")
    assert response.data == {"summary": "s", "audience": "a", "topThreeProvisions": []}
    assert (response.input_tokens, response.output_tokens) == (250, 197)


def test_an_answer_without_token_counts_is_still_read() -> None:
    response = model_call(StubClient(envelope('[{"sectionId": "sec-0"}]')))(model="m", prompt="p")
    assert response.data == [{"sectionId": "sec-0"}]
    assert (response.input_tokens, response.output_tokens) == (None, None)


def test_the_text_parts_of_one_candidate_are_joined() -> None:
    payload = {"candidates": [{"content": {"parts": [{"text": '{"a":'}, {"text": " 1}"}]}}]}
    assert model_call(StubClient(payload))(model="m", prompt="p").data == {"a": 1}


@pytest.mark.parametrize(
    "payload,match",
    [
        ({}, "no candidates"),
        ({"candidates": []}, "no candidates"),
        ({"candidates": [{"content": {}}]}, "no content parts"),
        ({"candidates": [{"content": {"parts": [{"inlineData": {}}]}}]}, "no text"),
        ("not-a-mapping", "not a mapping"),
    ],
)
def test_an_envelope_that_carries_no_answer_is_refused(payload, match) -> None:
    with pytest.raises(ModelCallError, match=match):
        model_call(StubClient(payload))(model="m", prompt="p")


def test_a_non_json_answer_is_refused_without_echoing_it() -> None:
    # The text is model output over a bill; a refusal that quotes it is how a
    # document reaches a log.
    secret = "I cannot summarize this classified appropriation."
    with pytest.raises(ModelCallError) as refusal:
        model_call(StubClient(envelope(secret)))(model="m", prompt="p")
    assert "was not JSON" in str(refusal.value)
    assert secret not in str(refusal.value)


def test_the_default_model_is_the_one_both_measured_runs_used() -> None:
    assert DEFAULT_MODEL == "gemini-3.8-flash"
