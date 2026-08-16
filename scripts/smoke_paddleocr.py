from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from pdf2epub.application.workflow import BookWorkflow
from pdf2epub.fixtures import make_scanned_only
from pdf2epub.parsers.base import OcrParseOptions
from pdf2epub.parsers.paddle_structure import (
    DETECTION_MODEL,
    LAYOUT_MODEL,
    RECOGNITION_MODELS,
    configure_windows_gpu_dll_search,
    default_model_cache_root,
)


def _framework_check(device: str) -> dict[str, object]:
    if device == "gpu:0":
        configure_windows_gpu_dll_search()
    try:
        import paddle
    except (ImportError, OSError) as exc:
        raise RuntimeError("PaddlePaddle runtime is unavailable for the selected extra") from exc
    paddle.utils.run_check()
    result: dict[str, object] = {
        "paddle_version": paddle.__version__,
        "compiled_with_cuda": paddle.is_compiled_with_cuda(),
        "device_count": paddle.device.cuda.device_count(),
    }
    if device == "gpu:0":
        if not paddle.is_compiled_with_cuda() or paddle.device.cuda.device_count() < 1:
            raise RuntimeError("The selected PaddlePaddle runtime cannot use gpu:0")
        paddle.set_device("gpu:0")
        tensor = paddle.to_tensor([[1.0, 2.0], [3.0, 4.0]])
        result.update(
            {
                "gpu_name": paddle.device.cuda.get_device_name(0),
                "tensor_result": paddle.matmul(tensor, tensor).numpy().tolist(),
                "active_device": paddle.device.get_device(),
            }
        )
    return result


def _models_ready(root: Path) -> tuple[list[str], int]:
    models = [LAYOUT_MODEL, DETECTION_MODEL, RECOGNITION_MODELS["en"]]
    missing = [model for model in models if not (root / "official_models" / model).is_dir()]
    total = sum(
        path.stat().st_size
        for model in models
        for path in (root / "official_models" / model).rglob("*")
        if path.is_file()
    )
    return missing, total


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the explicit real PaddleOCR M3 smoke")
    parser.add_argument("--device", choices=["gpu:0", "cpu"], default="gpu:0")
    parser.add_argument("--framework-check", action="store_true")
    parser.add_argument("--confirm-model-download", action="store_true")
    parser.add_argument("--no-model-download", action="store_true")
    parser.add_argument("--require-existing-models", action="store_true")
    parser.add_argument("--require-cache-hit", action="store_true")
    parser.add_argument("--benchmark-cpu", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    arguments = parser.parse_args()
    if arguments.confirm_model_download and arguments.no_model_download:
        parser.error("model download cannot be both confirmed and disabled")

    model_root = default_model_cache_root()
    os.environ["PADDLE_PDX_CACHE_HOME"] = str(model_root)
    framework = _framework_check(arguments.device)
    missing, model_bytes_before = _models_ready(model_root)
    if arguments.require_existing_models and missing:
        raise RuntimeError(f"Required OCR models are missing: {', '.join(missing)}")
    if arguments.framework_check and arguments.output_dir is None:
        print(
            json.dumps(
                {
                    "framework": framework,
                    "model_cache": str(model_root),
                    "missing_models": missing,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if missing and not arguments.confirm_model_download:
        raise RuntimeError(
            "OCR models are missing. Re-run with --confirm-model-download after reviewing "
            f"the download destination: {model_root}"
        )

    output = (arguments.output_dir or Path.cwd() / "paddleocr-smoke-output").resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = output / "scanned-only.pdf"
    if not fixture.exists():
        make_scanned_only(fixture)
    project_root = output / "real-ocr.bepub-project"
    if project_root.exists():
        raise RuntimeError(f"Smoke project already exists: {project_root}")
    workflow = BookWorkflow()
    project = workflow.create_project(project_root, fixture, title="M3 Real OCR Smoke")
    project = workflow.set_page_override(project, [0], "paddle_ppstructure_v3")
    options = OcrParseOptions(
        device=arguments.device,
        allow_model_download=arguments.confirm_model_download,
    )
    started = time.perf_counter()
    project, first_cache_hit = workflow.parse_page(project, 0, options=options)
    first_seconds = time.perf_counter() - started
    started = time.perf_counter()
    project, second_cache_hit = workflow.parse_page(project, 0, options=options)
    second_seconds = time.perf_counter() - started
    page = project.document.pages[0]
    if page.parser_id != "paddle_ppstructure_v3" or not page.blocks:
        raise RuntimeError("Real OCR smoke returned no normalized Document IR blocks")
    if arguments.require_cache_hit and not second_cache_hit:
        raise RuntimeError("The repeated OCR parse did not hit the project OCR cache")
    missing_after, model_bytes_after = _models_ready(model_root)
    if missing_after:
        raise RuntimeError(f"OCR initialization left models missing: {', '.join(missing_after)}")

    cpu_note: str | None = None
    if arguments.benchmark_cpu:
        cpu_note = (
            "Full CPU PP-Structure benchmark not repeated: Spike D exceeded 90 seconds and "
            "20 GB RAM; GPU was selected by the resource gate."
        )
    print(
        json.dumps(
            {
                "framework": framework,
                "device": arguments.device,
                "model_cache": str(model_root),
                "model_bytes_before": model_bytes_before,
                "model_bytes_after": model_bytes_after,
                "first_seconds": first_seconds,
                "first_cache_hit": first_cache_hit,
                "second_seconds": second_seconds,
                "second_cache_hit": second_cache_hit,
                "block_count": len(page.blocks),
                "warning_count": len(page.parse_warnings),
                "cpu_benchmark": cpu_note,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
