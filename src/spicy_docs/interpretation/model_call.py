"""The one injected model seam the two model-backed interpretation modules share.

``section_classification`` and ``bill_summaries`` both send a prompt and read
back structured output with token counts. Neither owns a client: the caller
passes a ``ModelCall``, exactly as ``spicy_docs.extraction.gemini`` takes an
injected ``GenerationClient``, so the rules stay pure and a test needs no
network. What the modules own is the prompt, the sealed vocabulary and the
provenance the answer is stored with.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ModelCallError(RuntimeError):
    """The model's answer does not satisfy the prompt's stated shape."""

    def __init__(self, message: str, *, details: Any = None):
        super().__init__(message)
        self.details = details


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """``data`` is the parsed structured answer; token counts are provenance, kept when reported."""

    data: Any
    input_tokens: int | None = None
    output_tokens: int | None = None


class ModelCall(Protocol):
    def __call__(self, *, model: str, prompt: str) -> ModelResponse: ...


__all__ = ["ModelCall", "ModelCallError", "ModelResponse"]
