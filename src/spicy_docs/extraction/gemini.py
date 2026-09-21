"""Gemini image recognition with an injected client and retained conversations."""

from __future__ import annotations

import base64
import copy
import json
import re
from collections.abc import Mapping
from itertools import pairwise
from typing import Any, Protocol

from spicy_docs.transport.credentials import CredentialRefusedError, scrub_credential

from .model import Box, ExtractionError, Raster, Recognition, TextBlock
from .prompts import FINAL, OVERVIEW, SUMMARY, TRANSCRIBE

DEFAULT_STRIPS = (Box(0, 0, 1, 0.4), Box(0, 0.3, 1, 0.7), Box(0, 0.6, 1, 1))


class GenerationClient(Protocol):
    def generate(self, model: str, body: dict[str, Any]) -> dict[str, Any]: ...


class GeminiClient:
    """Bounded HTTP transport; owns its client only when one was not injected."""

    def __init__(self, *, api_key: str, http_client=None, timeout: float = 120, max_response_bytes: int = 16 * 1024**2):
        if len(api_key) < 8 or timeout <= 0 or max_response_bytes < 1:
            raise ValueError("supply a nonempty API key and positive request bounds")
        self._key, self._client = api_key, http_client
        self._owns_client = http_client is None
        self.timeout, self.max_response_bytes = timeout, max_response_bytes

    def generate(self, model, body):
        import httpx

        if not re.fullmatch(r"[A-Za-z0-9._-]+", model):
            raise ValueError("model must be a Gemini model name")
        if self._client is None:
            self._client = httpx.Client(follow_redirects=False)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            with self._client.stream(
                "POST", url, headers={"x-goog-api-key": self._key}, json=body, timeout=self.timeout
            ) as response:
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > self.max_response_bytes:
                        raise ExtractionError("Gemini response exceeds max_response_bytes")
                    chunks.append(chunk)
                raw = scrub_credential(b"".join(chunks).decode("utf-8", errors="replace"), self._key)
                if response.status_code in {401, 403}:
                    error = CredentialRefusedError(f"Gemini refused credentials ({response.status_code})")
                    error.details = raw
                    raise error
                if response.status_code != 200:
                    raise ExtractionError(f"Gemini HTTP {response.status_code}", details=raw)
                try:
                    parsed = json.loads(raw)
                except ValueError:
                    raise ExtractionError("Gemini returned invalid JSON", details=raw) from None
                if not isinstance(parsed, dict):
                    raise ExtractionError("Gemini response must be an object", details=parsed)
                return parsed
        except httpx.HTTPError as exc:
            # Never chain an HTTP exception that might contain a credential echoed by transport.
            raise ExtractionError(scrub_credential(str(exc), self._key)[:500]) from None

    def close(self):
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def json_generation_config(
    generation: Mapping[str, Any] | None = None,
    *,
    schema: Mapping[str, Any] | None = None,
    response_mime_type: str = "application/json",
) -> dict[str, Any]:
    """``generationConfig`` asking for JSON, constrained by ``schema`` when one is given.

    One home for the two keys, because they belong together: a
    ``responseJsonSchema`` sent without ``responseMimeType`` is not a JSON request
    at all. Page recognition and the interpretation package's ``ModelCall`` adapter
    both build their request through here.
    """
    config = dict(generation or {})
    config["responseMimeType"] = response_mime_type
    if schema is not None:
        config["responseJsonSchema"] = schema
    return config


def _message(image, text):
    return {
        "role": "user",
        "parts": [
            {"inlineData": {"mimeType": image.media_type, "data": base64.b64encode(image.data).decode()}},
            {"text": text},
        ],
    }


def _answer(raw):
    candidates = raw.get("candidates", [])
    if (
        not isinstance(candidates, list)
        or len(candidates) != 1
        or not isinstance(candidates[0], dict)
        or candidates[0].get("finishReason") != "STOP"
    ):
        raise ExtractionError("Gemini response was blocked, ambiguous or incomplete", details=raw)
    content = candidates[0].get("content", {})
    if not isinstance(content, dict):
        raise ExtractionError("Gemini returned invalid model content", details=raw)
    parts = content.get("parts", [])
    if not isinstance(parts, list) or not all(isinstance(p, dict) for p in parts):
        raise ExtractionError("Gemini returned invalid content parts", details=raw)
    texts = [p["text"] for p in parts if isinstance(p.get("text"), str) and not p.get("thought")]
    if content.get("role") != "model" or not texts:
        raise ExtractionError("Gemini returned no transcription part", details=raw)
    return "".join(texts), content


class Gemini:
    def __init__(
        self,
        client: GenerationClient,
        *,
        model="gemini-3.8-flash",
        mode="single",
        generation: dict[str, Any] | None = None,
        prompt=TRANSCRIBE,
        overview_prompt=OVERVIEW,
        summary_prompt=SUMMARY,
        final_prompt=FINAL,
        strips=DEFAULT_STRIPS,
    ):
        if mode not in {"single", "multiturn"}:
            raise ValueError("Gemini mode must be single or multiturn")
        if not 1 <= len(strips) <= 8 or any(b.x0 != 0 or b.x1 != 1 for b in strips):
            raise ValueError("provide one to eight full-width strips")
        if strips[0].y0 != 0 or strips[-1].y1 != 1 or any(a.y0 >= b.y0 or a.y1 < b.y0 for a, b in pairwise(strips)):
            raise ValueError("strips must cover the page from top to bottom without gaps")
        self.client, self.model, self.mode, self.prompt = client, model, mode, prompt
        self.prompts = {"overview": overview_prompt, "summary": summary_prompt, "final": final_prompt}
        self.strips = tuple(strips)
        self.generation = {"maxOutputTokens": 8192, "thinkingConfig": {"thinkingLevel": "low"}, **(generation or {})}
        if not 1 <= self.generation["maxOutputTokens"] <= 32768 or self.generation.get("candidateCount", 1) != 1:
            raise ValueError("require one candidate and 1..32768 maxOutputTokens")

    def recognize(self, image: Raster) -> Recognition:
        from jsonschema import Draft202012Validator, ValidationError

        from .pages import crop

        calls = []
        settings = {
            "backend": "gemini",
            "model": self.model,
            "mode": self.mode,
            "generation": copy.deepcopy(self.generation),
            "prompts": {"single": self.prompt} if self.mode == "single" else dict(self.prompts),
        }

        def call(stage, history, schema=None):
            config = copy.deepcopy(self.generation)
            if schema:
                config = json_generation_config(config, schema=schema)
            body = {"contents": copy.deepcopy(history), "generationConfig": config}
            record = {"stage": stage, "request": copy.deepcopy(body)}
            calls.append(record)
            raw = self.client.generate(self.model, body)
            record["response"] = copy.deepcopy(raw)
            return _answer(raw)

        try:
            if self.mode == "single":
                text, _ = call("full", [_message(image, self.prompt)])
                return Recognition(text, settings, {"calls": calls}, images=(image,))
            images = (image, *(crop(image, box) for box in self.strips))
            # Crop rounding can change the exact region; use actual bounds in result metadata.
            regions = {"P": Box()}
            w, h = image.box.x1 - image.box.x0, image.box.y1 - image.box.y0
            for i, strip in enumerate(images[1:], 1):
                regions[f"S{i}"] = Box(
                    (strip.box.x0 - image.box.x0) / w,
                    (strip.box.y0 - image.box.y0) / h,
                    (strip.box.x1 - image.box.x0) / w,
                    (strip.box.y1 - image.box.y0) / h,
                )
            schema = {
                "type": "object",
                "properties": {
                    "blocks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "region_id": {"type": "string", "enum": list(regions)},
                                "text": {"type": "string"},
                            },
                            "required": ["region_id", "text"],
                            "additionalProperties": False,
                        },
                    },
                    "uncertainties": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["blocks", "uncertainties"],
                "additionalProperties": False,
            }
            history = [_message(image, self.prompts["overview"])]
            _, content = call("overview", history)
            for i, strip in enumerate(images[1:], 1):
                # Keep raw model Content, including opaque continuation signatures.
                history = [*history, copy.deepcopy(content), _message(strip, f"Image S{i}. {self.prompts['summary']}")]
                _, content = call(f"S{i}", history)
            history = [*history, copy.deepcopy(content), _message(image, self.prompts["final"])]
            text, _ = call("final", history, schema)
            try:
                final = json.loads(text)
                Draft202012Validator(schema).validate(final)
            except (ValueError, ValidationError):
                raise ExtractionError("Gemini final transcription has invalid structure or source references") from None
            blocks = tuple(TextBlock(b["text"], regions[b["region_id"]]) for b in final["blocks"])
            return Recognition(
                "\n".join(b.text for b in blocks), settings, {"calls": calls, "final": final}, blocks, images
            )
        except ExtractionError as exc:
            raise ExtractionError(
                str(exc), details={"configuration": settings, "calls": calls, "failure": exc.details}
            ) from None
        except CredentialRefusedError as exc:
            exc.details = {"configuration": settings, "calls": calls, "failure": getattr(exc, "details", None)}
            raise
