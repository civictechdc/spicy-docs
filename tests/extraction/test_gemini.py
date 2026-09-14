import base64
import copy
import json
from io import BytesIO

import httpx
import pytest
from PIL import Image

from spicy_docs.extraction import Box, ExtractionError, Raster
from spicy_docs.extraction.gemini import Gemini, GeminiClient
from spicy_docs.transport.credentials import CredentialRefusedError


def raster():
    out = BytesIO()
    Image.new("RGB", (20, 100), "white").save(out, format="PNG")
    return Raster(out.getvalue(), 20, 100)


def response(text, signature="opaque-signature"):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {"text": text, "thoughtSignature": signature},
                    ],
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 2},
    }


class Client:
    def __init__(self, final=None):
        self.requests = []
        self.final = (
            final if final is not None else {"blocks": [{"region_id": "S2", "text": "1500.00"}], "uncertainties": []}
        )

    def generate(self, model, body):
        self.requests.append(copy.deepcopy(body))
        text = json.dumps(self.final) if "responseJsonSchema" in body["generationConfig"] else "provisional observation"
        return response(text, f"signature-{len(self.requests)}")


def test_multiturn_preserves_history_images_signatures_raw_outputs_and_source_ids():
    client, image = Client(), raster()
    result = Gemini(client, mode="multiturn").recognize(image)
    assert result.text == "1500.00"
    assert len(client.requests) == 5
    assert len(result.images) == 4
    history = client.requests[-1]["contents"]
    assert len(history) == 9
    assert [history[i]["parts"][0]["thoughtSignature"] for i in [1, 3, 5, 7]] == [f"signature-{i}" for i in range(1, 5)]
    assert base64.b64decode(history[0]["parts"][0]["inlineData"]["data"]) == image.data
    assert history[-1]["parts"][0] == history[0]["parts"][0]
    assert result.blocks[0].box == Box(0, 0.3, 1, 0.7)
    schema = client.requests[-1]["generationConfig"]["responseJsonSchema"]
    assert schema["properties"]["blocks"]["items"]["properties"]["region_id"]["enum"] == ["P", "S1", "S2", "S3"]
    assert result.raw["calls"][-1]["request"] == client.requests[-1]
    assert result.raw["calls"][0]["response"]["usageMetadata"]["promptTokenCount"] == 7


def test_single_keeps_html_attributes_and_empty_text_is_not_an_error():
    class Single:
        def generate(self, model, body):
            return response('<input value="1500.00"/>')

    result = Gemini(Single()).recognize(raster())
    assert result.text == '<input value="1500.00"/>'
    assert len(result.raw["calls"]) == 1

    class Empty:
        def generate(self, model, body):
            return response("")

    assert Gemini(Empty()).recognize(raster()).text == ""


def test_multiturn_blank_control_keeps_uncertainties_and_all_calls():
    result = Gemini(Client({"blocks": [], "uncertainties": ["No legible body"]}), mode="multiturn").recognize(raster())
    assert result.text == "" and not result.blocks
    assert result.raw["final"]["uncertainties"] == ["No legible body"]
    assert len(result.raw["calls"]) == 5


def test_multiturn_prompts_are_injected_and_retained():
    client = Client()
    result = Gemini(
        client,
        mode="multiturn",
        overview_prompt="overview-test",
        summary_prompt="summary-test",
        final_prompt="final-test",
    ).recognize(raster())
    assert client.requests[0]["contents"][0]["parts"][-1]["text"] == "overview-test"
    assert client.requests[1]["contents"][-1]["parts"][-1]["text"] == "Image S1. summary-test"
    assert client.requests[-1]["contents"][-1]["parts"][-1]["text"] == "final-test"
    assert result.configuration["prompts"]["final"] == "final-test"


@pytest.mark.parametrize(
    "final",
    [
        {},
        {"blocks": [{"region_id": "invented", "text": "x"}], "uncertainties": []},
        {"blocks": [{"region_id": "P", "text": 15}], "uncertainties": []},
        {"blocks": [], "uncertainties": [], "extra": True},
    ],
)
def test_invalid_final_is_retained_and_refused(final):
    with pytest.raises(ExtractionError, match="invalid structure") as error:
        Gemini(Client(final), mode="multiturn").recognize(raster())
    assert len(error.value.details["calls"]) == 5
    assert error.value.details["calls"][-1]["response"]


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"candidates": []},
        {"candidates": None},
        {"candidates": [None]},
        {"candidates": [{"finishReason": "MAX_TOKENS"}]},
        {"candidates": [{"finishReason": "STOP", "content": None}]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [None]}}]},
    ],
)
def test_blocked_or_truncated_results_are_not_successful_blank_pages(raw):
    class Bad:
        def generate(self, model, body):
            return raw

    with pytest.raises(ExtractionError) as error:
        Gemini(Bad()).recognize(raster())
    assert error.value.details["calls"][0]["response"] == raw


def test_client_uses_header_scrubs_before_truncation_and_keeps_injected_client_open():
    key = "long-test-secret-that-must-not-appear"

    def serve(request):
        assert request.headers["x-goog-api-key"] == key
        assert key not in str(request.url)
        return httpx.Response(500, text=f"api_key=other-secret {key}")

    with httpx.Client(transport=httpx.MockTransport(serve)) as http:
        with GeminiClient(api_key=key, http_client=http) as client, pytest.raises(ExtractionError) as error:
            client.generate("gemini-test", {})
        assert not http.is_closed
    assert key not in error.value.details
    assert "other-secret" not in error.value.details

    def failure(request):
        raise httpx.ReadTimeout(key + "x" * 900, request=request)

    with httpx.Client(transport=httpx.MockTransport(failure)) as http:
        with pytest.raises(ExtractionError) as error:
            GeminiClient(api_key=key, http_client=http).generate("gemini-test", {})
        assert key not in str(error.value)
        assert str(error.value).startswith("<redacted>")


@pytest.mark.parametrize("status", [401, 403])
def test_credential_refusal_aborts_without_retry(status):
    calls = []

    def serve(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "refused"})

    with httpx.Client(transport=httpx.MockTransport(serve)) as http, pytest.raises(CredentialRefusedError):
        GeminiClient(api_key="test-key-long", http_client=http).generate("gemini-test", {})
    assert len(calls) == 1


def test_response_size_bound_and_strip_coverage():
    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="x" * 20))) as http,
        pytest.raises(ExtractionError, match="max_response_bytes"),
    ):
        GeminiClient(api_key="test-key-long", http_client=http, max_response_bytes=10).generate("gemini-test", {})
    with pytest.raises(ValueError, match="without gaps"):
        Gemini(Client(), mode="multiturn", strips=(Box(0, 0, 1, 0.2), Box(0, 0.4, 1, 1)))
