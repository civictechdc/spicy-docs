"""Adapter: a Gemini client as the ``ModelCall`` seam the model-backed modules take.

``GeminiClient`` satisfies ``GenerationClient`` (``generate(model, body) ->
dict``), the raw transport, while the two model-backed interpretation modules
take a narrower seam, ``model_call.ModelCall`` with the answer already parsed;
this builds the request body, asks for JSON back under the schema the caller
derived from its own answer declaration (Gemini's ``responseJsonSchema``,
through ``extraction.gemini.json_generation_config`` so the two request keys
have one home), pulls the answer text out of the candidate envelope, parses it
and carries the token counts the model tables publish. Nothing here validates
the answer against that schema: the readers already refuse, and a second
validator would be a second contract to keep in step with the first -- the
schema is what was asked for, the reader is what is accepted. The key never
appears in a log line or a row; the caller reads it and hands it to the
client, which sends it as a header.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from spicy_docs.extraction.gemini import GenerationClient, json_generation_config
from spicy_docs.interpretation.model_call import ModelCall, ModelCallError, ModelResponse

#: The model the two measured runs used (2026-09-19, 2026-09-20). A caller
#: naming its own model overrides it; nothing here is sealed to this one.
DEFAULT_MODEL = "gemini-3.8-flash"


def _answer_text(payload: Mapping[str, Any]) -> str:
    """The text parts of the first candidate, or a refusal naming what came back."""
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ModelCallError("model answer carried no candidates", details=payload)
    content = candidates[0].get("content") if isinstance(candidates[0], Mapping) else None
    parts = content.get("parts") if isinstance(content, Mapping) else None
    if not isinstance(parts, list) or not parts:
        raise ModelCallError("model answer carried no content parts", details=payload)
    texts = [part["text"] for part in parts if isinstance(part, Mapping) and isinstance(part.get("text"), str)]
    if not texts:
        raise ModelCallError("model answer carried no text", details=payload)
    return "".join(texts)


def model_call(client: GenerationClient, *, response_mime_type: str = "application/json") -> ModelCall:
    """Wrap a ``GenerationClient`` as a ``ModelCall``.

    ``client`` is any ``GenerationClient``: ``generate(model, body) ->
    Mapping``. The real ``GeminiClient`` satisfies it, and so does a stub in a
    test -- the protocol is structural, which is the whole reason this seam
    exists. The returned call raises ``ModelCallError`` when the answer carries
    no candidates, no content parts or no text, is not a mapping, or is not
    JSON.
    """

    def call(*, model: str, prompt: str, response_schema: Mapping[str, Any] | None = None) -> ModelResponse:
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": json_generation_config(schema=response_schema, response_mime_type=response_mime_type),
        }
        payload = client.generate(model, body)
        if not isinstance(payload, Mapping):
            raise ModelCallError("model answer was not a mapping", details=payload)
        text = _answer_text(payload)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            # The text is deliberately not in the message: it is model output,
            # and a prompt echo in a log is how a document leaks into a log.
            raise ModelCallError(f"model answer was not JSON: {error.msg}") from error
        usage = payload.get("usageMetadata")
        usage = usage if isinstance(usage, Mapping) else {}
        return ModelResponse(
            data=data,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )

    return call


__all__ = ["DEFAULT_MODEL", "model_call"]
