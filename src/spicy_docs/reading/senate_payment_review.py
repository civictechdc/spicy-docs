"""Pinned, positional review evidence for Senate payment-line experiments.

This is a truth-set gate, not a payment parser. Native word boxes and raw table
cells stay available when line or cross-page grouping is ambiguous. Matching a
review sample establishes agreement with those annotations, never whole-report
qualification or permission to carry office/payee context onto another page.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from spicy_docs.schemas.senate_expenditure_tables import page_context, parse_amount
from spicy_docs.schemas.tables import bytes_digest


def review_pages(body: bytes, *, pages: Sequence[int], source_page_offset: int = 0) -> dict[str, Any]:
    """Capture selected one-based pages; boxes use unrotated native PDF coordinates.

    ``source_page_offset`` is explicit retained-cut provenance, not inferred from
    printed labels. It must be checked against the acquisition/fixture receipt.
    No lines, names, amounts or dates are paired automatically.
    """
    import pymupdf

    from spicy_docs.extraction.api import DocumentExtractor, NativeText

    if (
        not pages
        or len(set(pages)) != len(pages)
        or any(type(page) is not int or page < 1 for page in pages)
        or type(source_page_offset) is not int
        or source_page_offset < 0
    ):
        raise ValueError("review needs distinct positive pages and a nonnegative source offset")
    result: dict[str, Any] = {"input_sha256": bytes_digest(body), "pages": {}}
    with pymupdf.open(stream=body, filetype="pdf") as document:
        if max(pages) > len(document):
            raise ValueError("review page is outside the retained PDF")
        extracted = DocumentExtractor(NativeText(), tables=True).extract(
            body, media_type="application/pdf", pages=list(pages)
        )
        for page in extracted:
            number = page.metadata["page"]
            native = document[number - 1]
            result["pages"][str(number)] = {
                "source_page": number + source_page_offset,
                "rotation": native.rotation,
                "context": asdict(page_context(page.text)),
                "text": page.text,
                "tables": [asdict(table) for table in page.tables],
                "words": [
                    {"text": word[4], "bbox": list(word[:4]), "block": word[5], "line": word[6], "word": word[7]}
                    for word in native.get_text("words")
                ],
            }
    return result


def validate_review_sample(
    capture: Mapping[str, Any], truth: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> None:
    """Refuse drift or any candidate disagreement with the exact reviewed sample.

    Each annotation names page-local word indices and literal text. Candidate
    rows must match the annotated groups/lines exactly, including decimal strings.
    Fields with unresolved ownership stay in ``unresolved`` observations, not in
    candidate rows. This function never supplies missing field associations.
    """
    if capture["input_sha256"] != truth["input_sha256"]:
        raise ValueError("review input digest differs")
    for number, expected in truth["pages"].items():
        page = capture["pages"][number]
        if (
            page["source_page"] != expected["source_page"]
            or page["context"]["printed_page"] != expected["printed_page"]
        ):
            raise ValueError("review page mapping differs")
    for observation in truth["observations"]:
        page = capture["pages"][str(observation["page"])]
        indices = observation["word_indices"]
        if (
            not indices
            or len(set(indices)) != len(indices)
            or any(type(index) is not int or index < 0 or index >= len(page["words"]) for index in indices)
        ):
            raise ValueError("review word locator is invalid")
        literal = " ".join(page["words"][index]["text"] for index in indices)
        if literal != observation["literal"]:
            raise ValueError("review literal differs at its word locator")
        if "decimal" in observation:
            amount = parse_amount(literal)
            if amount is None or format(amount, ".2f") != observation["decimal"]:
                raise ValueError("review exact decimal differs")
    if list(candidates) != truth["candidate_rows"]:
        raise ValueError("candidate payment rows differ from the reviewed sample")
