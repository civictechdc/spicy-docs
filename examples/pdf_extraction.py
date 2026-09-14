"""Offline dependency-injection example. Requires the pdf extra; makes no model calls.

Run: uv run --frozen --extra pdf python examples/pdf_extraction.py
The injected backend is deliberately a test double, not an OCR implementation.
"""

import json

from spicy_docs.extraction import DocumentExtractor, FullPage, NativeText, Raster, Recognition


class ExampleBackend:
    def recognize(self, image: Raster) -> Recognition:
        assert image.data.startswith(b"\x89PNG")
        return Recognition(
            "Injected test output", {"backend": "example-test-double"}, {"pixels": [image.width, image.height]}
        )


def run_example() -> list[dict]:
    import pymupdf

    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Native example text")
        document.new_page().insert_text((72, 72), "Page selected for an injected backend")
        source = document.tobytes()

    extractor = DocumentExtractor(NativeText())
    results = []
    for page in extractor.extract(source, media_type="application/pdf", overrides={2: FullPage(ExampleBackend())}):
        results.append(
            {
                "metadata": page.metadata,
                "body": page.text,
                "observations": [
                    {"id": o.id, "configuration": o.configuration, "raw": o.raw} for o in page.content.observations
                ],
            }
        )
    assert [page["body"] for page in results] == ["Native example text", "Injected test output"]
    return results


if __name__ == "__main__":
    print(json.dumps(run_example(), indent=2))
