# Third-party notices

The M0-M3 runtime uses:

- PyMuPDF, dual-licensed under GNU AGPL v3 or a commercial Artifex license.
- Qt for Python / PySide6, available under LGPLv3, GPLv3, or a Qt commercial license.
- Pydantic, distributed under the MIT license.
- HTTPX and its HTTP Core stack, distributed under the BSD 3-Clause license.
- Optional PaddlePaddle, PaddleOCR, and PaddleX OCR components, distributed under the Apache
  License 2.0. Their optional model artifacts are downloaded separately after user confirmation;
  consult each model directory/readme for model-specific notices.
- Optional OpenCV and related document-parser dependencies brought in by PaddleOCR; their upstream
  notices and transitive licenses must be preserved in a distributable OCR build.

EPUBCheck is a development/runtime validation tool downloaded separately by
`scripts/bootstrap_epubcheck.ps1` and is distributed under the BSD 3-Clause license.

This file is an engineering notice, not legal advice. A distributable application must bundle
the applicable license texts and preserve the relinking/replacement rights required by Qt's
LGPL terms.
