from __future__ import annotations

import hashlib
import importlib.metadata
import os
import site
from pathlib import Path
from typing import Any, Literal

import pymupdf

from pdf2epub.domain.errors import (
    OcrError,
    OcrModelUnavailableError,
    OcrPayloadError,
    OcrRuntimeUnavailableError,
)
from pdf2epub.parsers.base import OcrParseOptions, PageContext, PageParseResult, ParseOptions
from pdf2epub.parsers.ocr_normalization import (
    NORMALIZATION_SCHEMA,
    normalize_ppstructure_payload,
)
from pdf2epub.pdf.analyzer import native_text_quality
from pdf2epub.pdf.classifier import classify_page
from pdf2epub.pdf.renderer import RENDERER_VERSION, PdfRenderer
from pdf2epub.persistence.parse_cache import OcrCacheKey, OcrCacheRecord, OcrParseCache

PARSER_ID = "paddle_ppstructure_v3"
PARSER_VERSION = "3.7.0"
LAYOUT_MODEL = "PP-DocLayout_plus-L"
DETECTION_MODEL = "PP-OCRv5_server_det"
RECOGNITION_MODELS = {
    "en": "en_PP-OCRv4_mobile_rec",
    "zh": "PP-OCRv5_server_rec",
}
_DLL_HANDLES: list[Any] = []


def default_model_cache_root() -> Path:
    configured = os.environ.get("PADDLE_PDX_CACHE_HOME")
    if configured:
        return Path(configured)
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "pdf2epub" / "models" / "paddlex"
    return Path.home() / ".pdf2epub" / "models" / "paddlex"


def configure_windows_gpu_dll_search() -> tuple[Path, ...]:
    """Expose CUDA DLLs bundled by Paddle's Windows GPU wheel to this process only."""
    if os.name != "nt":
        return ()
    candidates: list[Path] = []
    for root_text in site.getsitepackages():
        root = Path(root_text)
        candidates.extend(
            [
                root / "nvidia" / "cu13" / "bin" / "x86_64",
                root / "nvidia" / "cudnn" / "bin",
            ]
        )
    existing = tuple(path for path in candidates if path.is_dir())
    if not existing:
        return ()
    current = os.environ.get("PATH", "")
    prefix = os.pathsep.join(str(path) for path in existing)
    if prefix not in current:
        os.environ["PATH"] = f"{prefix}{os.pathsep}{current}"
    if hasattr(os, "add_dll_directory"):
        for path in existing:
            _DLL_HANDLES.append(os.add_dll_directory(str(path)))
    return existing


def _language_key(language: str) -> str:
    normalized = language.strip().casefold().replace("_", "-")
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("zh") or normalized in {"ch", "chinese"}:
        return "zh"
    raise OcrError(
        f"No M3 PaddleOCR model profile is configured for language {language!r}",
        code="unsupported_ocr_language",
    )


def _directory_hash(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(candidate for candidate in path.rglob("*") if candidate.is_file())
    if not files:
        raise OcrModelUnavailableError(
            f"OCR model directory is empty: {path.name}", code="ocr_model_missing", fatal=True
        )
    for candidate in files:
        relative = candidate.relative_to(path).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with candidate.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _sanitize(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"byte_length": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if isinstance(value, dict):
        return {str(key): _sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if hasattr(value, "tolist"):
        return _sanitize(value.tolist())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class PaddleStructureParser:
    parser_id = PARSER_ID
    parser_version = PARSER_VERSION
    capabilities: tuple[str, ...] = ("pdf", "ocr", "layout", "rendered_crops")
    cancellation_boundary: Literal["page"] = "page"

    def __init__(self, *, renderer: PdfRenderer | None = None) -> None:
        self.renderer = renderer or PdfRenderer()
        self._pipeline: Any = None
        self._pipeline_identity: tuple[str, str, int] | None = None
        self._model_hashes: dict[str, str] = {}

    def can_parse(self, context: PageContext) -> bool:
        return context.source_path.suffix.casefold() == ".pdf" and context.source_path.is_file()

    def fingerprint(self, context: PageContext, options: ParseOptions) -> tuple[str, str]:
        ocr_options = self._ocr_options(options)
        package_versions = self._package_versions(require_runtime=False)
        models = self._model_names(context.language)
        key = self._cache_key(
            context,
            ocr_options,
            rotation=self._page_geometry(context)[2],
            package_versions=package_versions,
            model_names=models,
            model_hashes=self._available_model_hashes(models),
        )
        options_hash = hashlib.sha256(
            ocr_options.model_dump_json(exclude={"allow_model_download", "bypass_cache"}).encode()
        ).hexdigest()
        return key.fingerprint, options_hash

    def parse_page(self, context: PageContext, options: ParseOptions) -> PageParseResult:
        ocr_options = self._ocr_options(options)
        models = self._model_names(context.language)
        cache_root = default_model_cache_root()
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache_root)
        missing = [
            model
            for model in models.values()
            if not (cache_root / "official_models" / model).is_dir()
        ]
        if missing and not ocr_options.allow_model_download:
            raise OcrModelUnavailableError(
                "OCR models are not installed; approve the first model download before parsing",
                code="ocr_model_download_required",
                fatal=True,
            )
        if not missing:
            os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

        package_versions = self._package_versions(require_runtime=True)
        pipeline = self._get_pipeline(ocr_options, context.language, models)
        self._model_hashes = self._available_model_hashes(models, require_all=True)
        page_width, page_height, rotation, quality = self._page_geometry(context)
        classification = classify_page(quality, rotation)
        key = self._cache_key(
            context,
            ocr_options,
            rotation=rotation,
            package_versions=package_versions,
            model_names=models,
            model_hashes=self._model_hashes,
        )
        options_hash = hashlib.sha256(
            ocr_options.model_dump_json(exclude={"allow_model_download", "bypass_cache"}).encode()
        ).hexdigest()
        cache = OcrParseCache(context.project_root)
        if not ocr_options.bypass_cache and (record := cache.load(key)) is not None:
            return PageParseResult(
                page=record.page,
                assets=tuple(record.assets),
                parse_fingerprint=key.fingerprint,
                cache_hit=True,
            )

        image_path = self.renderer.render_page(
            context.source_path,
            context.source_sha256,
            context.page_index,
            context.project_root / "cache" / "parse" / "ocr_renders",
            dpi=ocr_options.dpi,
            max_pixels=ocr_options.max_page_pixels,
        )
        try:
            results = list(pipeline.predict(str(image_path)))
        except Exception as exc:
            message = str(exc).casefold()
            if "out of memory" in message or "resourceexhausted" in message:
                raise OcrError(
                    "GPU memory was exhausted while parsing this page",
                    code="ocr_gpu_oom",
                    fatal=True,
                ) from exc
            raise OcrError(
                "PP-StructureV3 inference failed on "
                f"page {context.page_index + 1}: {type(exc).__name__}",
                code="ocr_inference_failed",
            ) from exc
        if len(results) != 1:
            raise OcrPayloadError(
                "PP-StructureV3 returned an unexpected page count", code="ocr_schema"
            )
        raw = getattr(results[0], "json", None)
        if not isinstance(raw, dict):
            raise OcrPayloadError("PP-StructureV3 returned no JSON payload", code="ocr_schema")
        payload = _sanitize(raw)
        if not isinstance(payload, dict):
            raise OcrPayloadError(
                "PP-StructureV3 payload could not be sanitized", code="ocr_schema"
            )
        relative_cache = (
            Path("cache") / "parse" / PARSER_ID / f"{key.fingerprint}.json.gz"
        ).as_posix()
        provenance_models = {
            **{f"{role}_model": name for role, name in models.items()},
            **{f"{role}_sha256": digest for role, digest in self._model_hashes.items()},
        }
        normalized = normalize_ppstructure_payload(
            payload,
            context=context,
            options=ocr_options,
            page_width=page_width,
            page_height=page_height,
            rotation=rotation,
            quality=quality,
            classification=classification,
            parser_version=self.parser_version,
            options_hash=options_hash,
            parse_fingerprint=key.fingerprint,
            raw_cache_path=relative_cache,
            package_versions=package_versions,
            model_versions=provenance_models,
        )
        cache.store(
            OcrCacheRecord(
                key=key,
                raw_data=payload,
                page=normalized.page,
                assets=list(normalized.assets),
            )
        )
        return PageParseResult(
            page=normalized.page,
            assets=normalized.assets,
            parse_fingerprint=key.fingerprint,
        )

    @staticmethod
    def _ocr_options(options: ParseOptions) -> OcrParseOptions:
        if isinstance(options, OcrParseOptions):
            return options
        return OcrParseOptions(**options.model_dump())

    @staticmethod
    def _package_versions(*, require_runtime: bool) -> dict[str, str]:
        versions: dict[str, str] = {}
        for package in ("paddleocr", "paddlex", "paddlepaddle-gpu", "paddlepaddle"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                continue
        if require_runtime and "paddleocr" not in versions:
            raise OcrRuntimeUnavailableError(
                "PaddleOCR is not installed; install the ocr-gpu or ocr-cpu extra",
                code="ocr_runtime_missing",
                fatal=True,
            )
        return versions

    @staticmethod
    def _model_names(language: str) -> dict[str, str]:
        key = _language_key(language)
        return {
            "layout": LAYOUT_MODEL,
            "text_detection": DETECTION_MODEL,
            "text_recognition": RECOGNITION_MODELS[key],
        }

    @staticmethod
    def _available_model_hashes(
        models: dict[str, str], *, require_all: bool = False
    ) -> dict[str, str]:
        root = default_model_cache_root() / "official_models"
        hashes: dict[str, str] = {}
        for role, model in models.items():
            directory = root / model
            if directory.is_dir():
                hashes[role] = _directory_hash(directory)
            elif require_all:
                raise OcrModelUnavailableError(
                    f"OCR model is missing after initialization: {model}",
                    code="ocr_model_missing",
                    fatal=True,
                )
        return hashes

    def _get_pipeline(self, options: OcrParseOptions, language: str, models: dict[str, str]) -> Any:
        identity = (options.device, _language_key(language), options.cpu_threads)
        if self._pipeline is not None and self._pipeline_identity == identity:
            return self._pipeline
        if options.device == "gpu:0":
            configure_windows_gpu_dll_search()
        try:
            from paddleocr import PPStructureV3
        except (ImportError, OSError) as exc:
            raise OcrRuntimeUnavailableError(
                "PaddleOCR could not be loaded; verify the selected OCR extra",
                code="ocr_runtime_import_failed",
                fatal=True,
            ) from exc
        kwargs: dict[str, Any] = {
            "device": options.device,
            "layout_detection_model_name": models["layout"],
            "text_detection_model_name": models["text_detection"],
            "text_recognition_model_name": models["text_recognition"],
            "text_recognition_batch_size": options.recognition_batch_size,
            "text_det_limit_side_len": options.text_det_limit_side_len,
            "text_det_limit_type": options.text_det_limit_type,
            "text_det_thresh": options.text_det_thresh,
            "text_det_box_thresh": options.text_det_box_thresh,
            "text_det_unclip_ratio": options.text_det_unclip_ratio,
            "text_rec_score_thresh": options.text_rec_score_thresh,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "use_seal_recognition": False,
            "use_table_recognition": False,
            "use_formula_recognition": False,
            "use_chart_recognition": False,
            "use_region_detection": False,
        }
        if options.device == "cpu":
            kwargs.update({"enable_mkldnn": False, "cpu_threads": options.cpu_threads})
        try:
            self._pipeline = PPStructureV3(**kwargs)
        except Exception as exc:
            raise OcrRuntimeUnavailableError(
                f"PP-StructureV3 could not initialize: {type(exc).__name__}",
                code="ocr_runtime_initialization_failed",
                fatal=True,
            ) from exc
        self._pipeline_identity = identity
        return self._pipeline

    @staticmethod
    def _page_geometry(
        context: PageContext,
    ) -> tuple[float, float, int, Any]:
        try:
            with pymupdf.open(context.source_path) as document:
                page = document.load_page(context.page_index)
                payload = page.get_text("dict", sort=False)
                text = "".join(
                    str(span.get("text", ""))
                    for block in payload.get("blocks", [])
                    if block.get("type") == 0
                    for line in block.get("lines", [])
                    for span in line.get("spans", [])
                )
                image_area = max(
                    (
                        max(0.0, float(block["bbox"][2]) - float(block["bbox"][0]))
                        * max(0.0, float(block["bbox"][3]) - float(block["bbox"][1]))
                        for block in payload.get("blocks", [])
                        if block.get("type") == 1 and block.get("bbox")
                    ),
                    default=0.0,
                )
                rect = page.rect
                quality = native_text_quality(text, image_area, rect.width * rect.height)
                return rect.width, rect.height, page.rotation, quality
        except Exception as exc:
            raise OcrError(
                f"Could not inspect page {context.page_index + 1} for OCR",
                code="ocr_page_inspection_failed",
            ) from exc

    def _cache_key(
        self,
        context: PageContext,
        options: OcrParseOptions,
        *,
        rotation: int,
        package_versions: dict[str, str],
        model_names: dict[str, str],
        model_hashes: dict[str, str],
    ) -> OcrCacheKey:
        option_payload = options.model_dump(exclude={"allow_model_download", "bypass_cache"})
        return OcrCacheKey(
            source_sha256=context.source_sha256,
            page_index=context.page_index,
            render_version=RENDERER_VERSION,
            dpi=options.dpi,
            rotation=rotation,
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            package_versions=package_versions,
            model_names=model_names,
            model_hashes=model_hashes,
            language=context.language,
            device=options.device,
            precision=options.precision,
            engine="paddle_inference",
            options=option_payload,
            normalization_schema=NORMALIZATION_SCHEMA,
        )
