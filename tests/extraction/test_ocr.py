"""OCR backend contract: RapidOCR, AppleVision and MLX accept injected engines, preserve raw detections and
confidence, convert Apple's bottom-left coordinates to top-left, and refuse partial MLX generation.
"""

import sys
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from spicy_docs.extraction import Box, ExtractionError, Raster
from spicy_docs.extraction.ocr import MLX, AppleVision, RapidOCR


def raster():
    out = BytesIO()
    Image.new("RGB", (100, 100), "white").save(out, format="PNG")
    return Raster(out.getvalue(), 100, 100)


def test_rapidocr_accepts_injected_engine_and_preserves_quad_confidence_and_text():
    class Engine:
        def __call__(self, data):
            assert data.startswith(b"\x89PNG")
            return [([[10, 20], [80, 20], [80, 40], [10, 40]], "900.00", 0.9)], [0.01]

    result = RapidOCR(engine=Engine()).recognize(raster())
    assert result.text == "900.00"
    assert result.blocks[0].box == Box(0.1, 0.2, 0.8, 0.4)
    assert result.blocks[0].confidence == 0.9
    assert result.raw["detections"][0]["points"][0] == [10, 20]
    assert result.configuration["engine_injected"] is True
    assert result.configuration["options"] is None  # An injected engine's settings are not inferred.
    with pytest.raises(ValueError, match="configure an injected"):
        RapidOCR(engine=Engine(), intra_op_num_threads=2)


def test_apple_bottom_left_coordinates_become_top_left_without_losing_raw():
    class Engine:
        def __init__(self, image, **options):
            assert image.size == (100, 100)
            assert options["recognition_level"] == "accurate"

        def recognize(self):
            return [("stamp", 0.8, (0.1, 0.6, 0.3, 0.2))]

    result = AppleVision(engine_factory=Engine).recognize(raster())
    assert result.text == "stamp"
    assert abs(result.blocks[0].box.y0 - 0.2) < 1e-9
    assert result.blocks[0].box.y1 == 0.4
    assert result.raw["detections"][0][2] == (0.1, 0.6, 0.3, 0.2)


def test_model_factories_are_configurable_and_lazy():
    lighton = MLX.lighton(max_tokens=100)
    table = MLX.glm(task="table", temperature=0.1)
    assert lighton.max_tokens == 100 and lighton.prompt == ""
    assert table.prompt == "Table Recognition:" and table.temperature == 0.1
    assert lighton._loaded is table._loaded is None


@pytest.mark.parametrize("finish_reason", ["stop", "length", None])
def test_mlx_uses_model_once_passes_image_and_refuses_partial_generation(monkeypatch, tmp_path, finish_reason):
    events = []
    mx = ModuleType("mlx.core")
    mx.random = SimpleNamespace(seed=lambda seed: events.append(("seed", seed)))
    mlx = ModuleType("mlx")
    mlx.core = mx
    vlm = ModuleType("mlx_vlm")

    def load(path):
        events.append(("load", path))
        return object(), object()

    def generate(model, processor, prompt, *, image, max_tokens, temperature):
        assert prompt == "formatted Table Recognition:"
        assert Path(image).read_bytes().startswith(b"\x89PNG")
        assert max_tokens == 8192 and temperature == 0
        yield SimpleNamespace(
            text='<input value="1500.00"/>', finish_reason=finish_reason, prompt_tokens=12, generation_tokens=8
        )

    vlm.load, vlm.stream_generate = load, generate
    prompts = ModuleType("mlx_vlm.prompt_utils")
    prompts.apply_chat_template = lambda processor, config, text, num_images: "formatted " + text
    utils = ModuleType("mlx_vlm.utils")
    utils.load_config = lambda path: {"model_type": "test"}
    for name, module in {
        "mlx": mlx,
        "mlx.core": mx,
        "mlx_vlm": vlm,
        "mlx_vlm.prompt_utils": prompts,
        "mlx_vlm.utils": utils,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    backend = MLX.glm(model=str(tmp_path), revision=None, task="table")
    if finish_reason == "stop":
        for _ in range(2):
            result = backend.recognize(raster())
            assert result.text == '<input value="1500.00"/>'
            assert result.raw["prompt_tokens"] == 12
        assert sum(event[0] == "load" for event in events) == 1
        backend.close()
        assert backend._loaded is None
    else:
        with pytest.raises(ExtractionError, match="did not complete") as error:
            backend.recognize(raster())
        assert error.value.details["raw"]["text"] == '<input value="1500.00"/>'
