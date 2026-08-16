# ADR-006: PaddleOCR runtime and model profile

Status: accepted for M3.

M3 uses one production OCR adapter: PaddleOCR 3.7.0 PP-StructureV3 with PaddleX 3.7.2 and
PaddlePaddle 3.3.0. `ocr-gpu` selects the official cu130 Windows wheel and is the verified default
for the current RTX 4060 machine. `ocr-cpu` selects the official CPU wheel. The extras and their
indexes are explicit and mutually exclusive in uv.

Paddle 3.3.0's Linux and Windows GPU wheels expose inconsistent dependency markers to a universal
resolver. The GPU extra therefore repeats the exact CUDA/cuDNN Windows wheel requirements declared
by the installed Paddle wheel; otherwise uv can lock them as Linux-only and omit required DLLs on
Windows.

On Windows, the explicitly locked NVIDIA runtime wheels download about 1.3 GiB in addition to the
roughly 216 MiB OCR model profile. Installation and first-model-download prompts must present
those as separate costs.

The fixed English profile is `PP-DocLayout_plus-L`, `PP-OCRv5_server_det`, and
`en_PP-OCRv4_mobile_rec`. It disables document orientation, unwarping, text-line orientation,
table, formula, seal, chart, and region sub-pipelines. Pages render at 200 DPI with a 25 MP cap;
text detection explicitly uses maximum side 2200. GPU/CPU use FP32, recognition batch 4, and CPU
uses at most 8 threads with oneDNN disabled due the recorded Paddle 3.3.0 Windows failure.

Models live under `%LOCALAPPDATA%/pdf2epub/models/paddlex` unless `PADDLE_PDX_CACHE_HOME` is set.
The first download requires explicit consent. Native parsing, project loading, and automated fake
OCR tests neither import Paddle nor access the network. GPU DLL directories bundled in the wheel
are added only to the application process search path.

The empirical evidence and rejected CPU default are recorded in `docs/spikes/m3-spike-d.md`.
MinerU remains desk research only and has no M3 dependency or adapter.
