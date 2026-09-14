"""Optional local recognition providers; engines load once on first use."""

from __future__ import annotations

import io
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from .model import Box, ExtractionError, Raster, Recognition, TextBlock


def _version(package):
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _box(x0, y0, x1, y1):
    # Providers can put edges just outside an image. Preserve original coordinates in raw.
    return Box(max(0, x0), max(0, y0), min(1, x1), min(1, y1))


class RapidOCR:
    def __init__(self, *, engine=None, **options: Any):
        self.engine = engine
        self._injected = engine is not None
        if self._injected and options:
            raise ValueError("configure an injected RapidOCR engine before passing it")
        self.options: dict[str, Any] = {"intra_op_num_threads": 4, "inter_op_num_threads": 1, **options}

    def recognize(self, image: Raster) -> Recognition:
        if self.engine is None:
            from rapidocr_onnxruntime import RapidOCR as Engine

            self.engine = Engine(**self.options)
        result, elapsed = self.engine(image.data)
        detections, blocks = [], []
        for points, text, confidence in result or []:
            points = [[float(x), float(y)] for x, y in points]
            xs, ys = zip(*points, strict=True)
            box = _box(min(xs) / image.width, min(ys) / image.height, max(xs) / image.width, max(ys) / image.height)
            blocks.append(TextBlock(text, box, float(confidence)))
            detections.append({"points": points, "text": text, "confidence": float(confidence)})
        return Recognition(
            "\n".join(b.text for b in blocks),
            {
                "backend": "rapidocr",
                "version": _version("rapidocr-onnxruntime"),
                "engine_injected": self._injected,
                "options": None if self._injected else self.options,
            },
            {"detections": detections, "engine_elapsed": elapsed, "coordinates": "image pixels; top-left origin"},
            tuple(blocks),
        )


class AppleVision:
    def __init__(self, *, recognition_level="accurate", languages=("en-US",), engine_factory=None):
        if recognition_level not in {"accurate", "fast"}:
            raise ValueError("recognition_level must be accurate or fast")
        self.level, self.languages, self.engine_factory = recognition_level, tuple(languages), engine_factory

    def recognize(self, image: Raster) -> Recognition:
        from PIL import Image

        factory = self.engine_factory
        if factory is None:
            if platform.system() != "Darwin":
                raise ExtractionError("Apple Vision requires macOS")
            from ocrmac import ocrmac

            factory = ocrmac.OCR
        with Image.open(io.BytesIO(image.data)) as source:
            result = factory(source, recognition_level=self.level, language_preference=list(self.languages)).recognize()
        blocks = tuple(
            TextBlock(text, _box(x, 1 - y - h, x + w, 1 - y), float(conf)) for text, conf, (x, y, w, h) in result
        )
        return Recognition(
            "\n".join(b.text for b in blocks),
            {
                "backend": "apple-vision",
                "version": _version("ocrmac"),
                "macos": platform.mac_ver()[0],
                "recognition_level": self.level,
                "languages": list(self.languages),
            },
            {"detections": result, "coordinates": "normalized x/y/width/height; bottom-left origin"},
            blocks,
        )


class MLX:
    """MLX-VLM with explicit model, revision and prompt; reusable across pages.

    Hugging Face identifiers require a revision. Local directories are caller-pinned.
    This object and MLX's generator are intended for serial use in one worker.
    """

    def __init__(
        self,
        model: str,
        *,
        revision: str | None = None,
        prompt: str = "",
        max_tokens: int = 8192,
        temperature: float = 0,
        seed: int = 0,
    ):
        if max_tokens < 1 or temperature < 0:
            raise ValueError("max_tokens must be positive and temperature nonnegative")
        if not Path(model).is_dir() and not revision:
            raise ValueError("a remote model identifier requires an explicit revision")
        self.model, self.revision, self.prompt = model, revision, prompt
        self.max_tokens, self.temperature, self.seed = max_tokens, temperature, seed
        self._loaded: tuple[Any, Any, dict, str] | None = None

    @classmethod
    def lighton(
        cls,
        *,
        model="mlx-community/LightOnOCR-2-1B-bf16",
        revision="16e06849ba5c689f782473651914d6613d25d884",
        **options: Any,
    ):
        return cls(model, revision=revision, **options)

    @classmethod
    def glm(
        cls,
        *,
        task="text",
        model="mlx-community/GLM-OCR-bf16",
        revision="24f15402e83baa0a80eeeaecf5480e172abc6f2e",
        **options: Any,
    ):
        prompts = {"text": "Text Recognition:", "table": "Table Recognition:", "formula": "Formula Recognition:"}
        if task not in prompts:
            raise ValueError("GLM task must be text, table or formula")
        options.setdefault("prompt", prompts[task])
        return cls(model, revision=revision, **options)

    def recognize(self, image: Raster) -> Recognition:
        import mlx.core as mx
        from mlx_vlm import load, stream_generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        if self._loaded is None:
            path = self.model
            if not Path(path).is_dir():
                from huggingface_hub import snapshot_download

                path = snapshot_download(path, revision=self.revision)
            model, processor = load(path)
            self._loaded = model, processor, load_config(path), path
        model, processor, config, path = self._loaded
        # MLX-VLM's loader annotation omits the detokenizer it installs at runtime.
        processor = cast(Any, processor)
        formatted = apply_chat_template(processor, config, self.prompt, num_images=1)
        if not isinstance(formatted, str):
            raise ExtractionError("selected MLX model requires an unsupported prompt template", details=formatted)
        settings = {
            "backend": "mlx-vlm",
            "version": _version("mlx-vlm"),
            "model": self.model,
            "revision": self.revision,
            "resolved_path": path,
            "prompt": self.prompt,
            "formatted_prompt": formatted,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "seed": self.seed,
        }
        mx.random.seed(self.seed)
        parts, last = [], None
        # Use MLX-VLM's supported path input, as in the qualified experiment.
        with TemporaryDirectory(prefix="spicy-docs-mlx-") as directory:
            source = Path(directory) / "page.png"
            source.write_bytes(image.data)
            for item in stream_generate(
                model, processor, formatted, image=str(source), max_tokens=self.max_tokens, temperature=self.temperature
            ):
                parts.append(item.text)
                last = item
        text = "".join(parts)
        raw = {
            "text": text,
            "finish_reason": getattr(last, "finish_reason", None),
            "prompt_tokens": getattr(last, "prompt_tokens", None),
            "generation_tokens": getattr(last, "generation_tokens", None),
        }
        if last is None or raw["finish_reason"] != "stop" or (raw["generation_tokens"] or 0) >= self.max_tokens:
            raise ExtractionError("MLX generation did not complete", details={"configuration": settings, "raw": raw})
        return Recognition(text, settings, raw)

    def close(self):
        self._loaded = None
