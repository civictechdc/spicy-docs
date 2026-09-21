"""The Gemini adapter: the request it builds, the answer it parses, and what it refuses.

Pins the seam both model-backed interpretation modules take: a caller-derived
schema leaves the wire as ``responseJsonSchema`` beside ``responseMimeType``,
publisher token counts pass through, and an envelope without an answer or with
non-JSON text is refused without echoing the model's text.
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
    """The caller's schema is forwarded verbatim as ``responseJsonSchema`` with the publisher's JSON mime type."""
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
    """An omitted ``response_schema`` must not become a null schema key on the request."""
    # `response_schema` is optional on the seam, so the body must not grow a
    # null schema key that the publisher would have to interpret.
    client = StubClient(envelope("{}"))
    model_call(client)(model="m", prompt="p")
    config = client.calls[0][1]["generationConfig"]
    assert "responseJsonSchema" not in config
    assert config == json_generation_config()


def test_the_parsed_answer_and_the_publishers_own_token_counts_come_back() -> None:
    """Parsed JSON and the publisher's prompt/candidate token counts both return on the response."""
    payload = envelope(
        json.dumps({"summary": "s", "audience": "a", "topThreeProvisions": []}),
        usage={"promptTokenCount": 250, "candidatesTokenCount": 197},
    )
    response = model_call(StubClient(payload))(model="m", prompt="p")
    assert response.data == {"summary": "s", "audience": "a", "topThreeProvisions": []}
    assert (response.input_tokens, response.output_tokens) == (250, 197)


def test_an_answer_without_token_counts_is_still_read() -> None:
    """A missing ``usageMetadata`` yields ``None`` token counts rather than failing the read."""
    response = model_call(StubClient(envelope('[{"sectionId": "sec-0"}]')))(model="m", prompt="p")
    assert response.data == [{"sectionId": "sec-0"}]
    assert (response.input_tokens, response.output_tokens) == (None, None)


def test_the_text_parts_of_one_candidate_are_joined() -> None:
    """Multiple text parts in one candidate are concatenated before JSON parsing."""
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
    """No candidates, no content parts, no text or a non-mapping payload each refuse with a named reason."""
    with pytest.raises(ModelCallError, match=match):
        model_call(StubClient(payload))(model="m", prompt="p")


def test_a_non_json_answer_is_refused_without_echoing_it() -> None:
    """A non-JSON answer raises ``ModelCallError`` that names the failure but never quotes the model text."""
    # The text is model output over a bill; a refusal that quotes it is how a
    # document reaches a log.
    secret = "I cannot summarize this classified appropriation."
    with pytest.raises(ModelCallError) as refusal:
        model_call(StubClient(envelope(secret)))(model="m", prompt="p")
    assert "was not JSON" in str(refusal.value)
    assert secret not in str(refusal.value)


def test_the_default_model_is_the_one_both_measured_runs_used() -> None:
    """``DEFAULT_MODEL`` stays the model both measured runs used."""
    assert DEFAULT_MODEL == "gemini-3.8-flash"
