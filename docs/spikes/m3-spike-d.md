# M3 Spike D: PaddleOCR/PP-StructureV3 on Windows

Date: 2026-08-16. Status: passed for the GPU profile.

## Environment

- Windows Home China, build 26200, x86-64.
- Python 3.12.9.
- NVIDIA GeForce RTX 4060 Laptop GPU, compute capability 8.9, 8188 MiB VRAM.
- NVIDIA driver 610.62, Driver API 13.3.
- PaddlePaddle GPU 3.3.0 from the official cu130 index.
- PaddleOCR 3.7.0 and resolved PaddleX 3.7.2.

The official Windows support page names Windows Pro/Enterprise rather than Home, so this spike is
the compatibility evidence for the current machine. No MinerU dependency or model was installed.

## MinerU desk-research boundary

The official MinerU quick start currently supports Python 3.10-3.12 and a pure-CPU pipeline, lists
16 GB minimum/32 GB recommended RAM, and calls for at least 20 GB disk. Those costs are materially
larger than the selected M3 Paddle profile and the project would need a separate adapter and model
cache policy. M3 therefore performed no MinerU install, model download, import, or inference. Its
empirical comparison remains an explicitly approved M5/research task.

Official source: https://opendatalab.github.io/MinerU/quick_start/

## Configuration and results

The selected profile uses `PP-DocLayout_plus-L`, `PP-OCRv5_server_det`, and
`en_PP-OCRv4_mobile_rec`. Their measured cache sizes were 124.37 MiB, 84.26 MiB, and 7.48 MiB.
The isolated GPU environment occupied about 2.95 GiB; the CPU environment occupied about 0.87
GiB. A clean uv synchronization downloaded about 1.3 GiB of CUDA/cuDNN runtime wheels separately
from the roughly 216 MiB model cache.

- `paddle.utils.run_check()` passed on `gpu:0` and a GPU matrix multiplication returned the
  expected result.
- Paddle enumerated the RTX 4060 and logged compute capability 8.9 with Driver/Runtime API 13.3.
- First model initialization/download took 26.84 seconds. The first 200 DPI inference took 1.86
  seconds; three warm runs had a 0.99 second median.
- The result contained ordered heading/text blocks, OCR polygons/boxes, and recognition scores.
- A 23.75 MP input with `text_det_limit_type="max"` and side limit 2200 completed in 1.29 seconds
  with about 4181 MiB peak VRAM.
- Omitting the explicit `max` limit allowed Paddle's default `min` behavior and reached about 7917
  MiB. The production adapter therefore sets both the length and limit type.
- A second run used the existing model files and made no model download.

The Windows GPU wheel installed CUDA/cuDNN DLLs below `site-packages/nvidia`. Paddle did not find
them until those directories were added to the current process DLL search path. The adapter does
this locally and never changes the system PATH.

CPU framework validation passed. PP-StructureV3 with oneDNN enabled failed in Paddle 3.3.0 with
`ConvertPirAttribute2RuntimeAttribute`. With oneDNN disabled it entered inference but exceeded 90
seconds and approximately 20 GB RAM; the bounded spike terminated that process. CPU remains an
explicit fallback extra with oneDNN disabled, not the default profile.

## Decision

Use the mutually exclusive `ocr-gpu` extra by default on this machine. Keep `ocr-cpu` as a
separately installed fallback. Do not silently fall back between devices or parsers. GPU OOM is a
page/batch error and the GUI offers an explicit CPU retry.

Official sources consulted:

- https://www.paddlepaddle.org.cn/documentation/zh/install/index_cn.html
- https://www.paddlepaddle.org.cn/documentation/docs/zh/install/pip/windows-pip.html
- https://github.com/PaddlePaddle/PaddleOCR/blob/main/pyproject.toml
- https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PP-StructureV3.html
