# M3 implementation handoff and next-stage planning context

Date: 2026-08-16  
Repository: `D:\Projects\pdf2epub`  
Purpose: give a new Codex Plan-mode task enough verified context to audit the completed M3 work
and plan the next milestone without reconstructing the previous implementation session.

## 1. Instructions for the next Codex task

Before proposing or implementing anything:

1. Read `AGENTS.md` and all of `PROJECT_SPEC.md`.
2. Read this handoff, `docs/handoffs/M3_PLAN_MODE_HANDOFF.md`, ADR-006 through ADR-008,
   `docs/architecture.md`, `docs/document-ir.md`, and `docs/smoke-test.md`.
3. Inspect the actual Git branch, HEAD, status, diff, Python/uv/Java/GPU environment and current
   tests. Treat the live checkout as authoritative if it differs from this snapshot.
4. Review the current implementation boundaries listed below instead of assuming the design from
   this summary is still exact.
5. Keep work milestone-scoped. `PROJECT_SPEC.md` identifies M4 as the structure editing
   workbench; do not pull M5 parser, packaging, reader, or service work into it.
6. In Plan mode, stop after producing an evidence-backed implementation plan. Do not edit code,
   dependencies, lock files, model caches, or the local OCR environment.

## 2. Repository snapshot

At handoff creation time:

- Branch: `main`.
- HEAD: `b7a02f33486441691a2578b9146c436cbacaa132`.
- Commit subject: `Implement M3 scanned/mixed PDF OCR and page routing`.
- `origin/main` pointed to the same commit.
- Worktree was clean before this handoff file was created.
- M3 is contained in the commit above; M2 baseline was
  `777794df307abeedf6633acff44538a18bf32b8b`.
- This handoff is intentionally a new file. Do not overwrite the historical
  `docs/handoffs/M3_PLAN_MODE_HANDOFF.md`.

Recheck all of these facts in the new task because Git state can change.

## 3. What M3 delivered

M3 now provides a mixed digital/scanned PDF vertical slice through one versioned Document IR:

- deterministic page classification with stable reason codes and a recommended parser;
- per-page `auto`, forced Native, and forced Paddle OCR override, including multi-page selection;
- parser registry/router with lazy, provider-neutral adapters;
- PaddleOCR/PP-StructureV3 OCR normalized into Document IR rather than exposed to GUI/domain code;
- OCR bbox, confidence, raw sanitized data, model/package versions, device/options and provenance;
- content-addressed compressed OCR cache with checksum, size limit, atomic writes and corruption
  recovery;
- serial mixed-document batch parsing, stage progress, page-boundary cancellation, partial failure,
  fatal failure and explicit retry/fallback behavior;
- candidate-based whole-page reparse with conflict checks for user edits, merge/split history and
  all translation records;
- Page List classification/parser/status display, parser overrides, Analyze/Parse/Reparse/Retry,
  progress/cancel and OCR overlay confidence display;
- export without implicit OCR and an explicit incomplete-content confirmation/notice;
- complete and incomplete mixed EPUB outputs that pass EPUBCheck;
- generated legal scanned/mixed fixtures and fake OCR automated tests;
- a real PaddleOCR smoke script and deterministic M3 verification script.

Explicitly not added in M3:

- MinerU production adapter or models;
- Unlimited-OCR, Docling or multiple OCR engines;
- regional reparse;
- undo/redo;
- a complete structure editing workbench;
- a full EPUB reader;
- web backend, Redis or Celery;
- installers/packaging;
- other M4/M5 functionality.

## 4. Locked M3 runtime decisions

### OCR packages and extras

- `paddleocr[doc-parser]==3.7.0`.
- PaddleX resolves to and is locked at `3.7.2`.
- `paddlepaddle-gpu==3.3.0` from the official cu130 index.
- `paddlepaddle==3.3.0` from the official CPU index.
- Extras `ocr-gpu` and `ocr-cpu` are mutually exclusive through `tool.uv.conflicts`.
- Paddle indexes are explicit, so only Paddle packages resolve from them.
- Windows NVIDIA CUDA/cuDNN wheel requirements are explicitly locked because Paddle's Linux and
  Windows wheel metadata produced incorrect universal markers in uv without them.
- A clean Windows GPU-extra sync downloads roughly 1.3 GiB of NVIDIA runtime wheels, separate
  from OCR models.
- Normal Native/fake-OCR development does not require either OCR extra and must not access the
  network.

### Selected model/device profile

- Default on the current machine: `gpu:0`, FP32.
- Layout: `PP-DocLayout_plus-L`.
- Detection: `PP-OCRv5_server_det`.
- English recognition: `en_PP-OCRv4_mobile_rec`.
- Measured combined model cache: 226,603,830 bytes, roughly 216 MiB.
- Pages render at 200 DPI, cap at 25 MP, and detection explicitly uses maximum side 2200.
- Recognition batch is 4.
- Document orientation, unwarping, text-line orientation, tables, formulae, seals, charts and
  region sub-pipelines are disabled.
- CPU is an explicit fallback using FP32, at most 8 threads and oneDNN disabled.
- GPU OOM is not silently retried on CPU. The user must explicitly choose CPU retry.
- OCR failure never silently invokes Native; Force Native remains a user action.

### Actual GPU/CPU evidence

The isolated Spike D and production smoke established:

- NVIDIA GeForce RTX 4060 Laptop GPU, compute capability 8.9, 8188 MiB VRAM.
- Paddle `run_check()`, CUDA compilation/device enumeration and GPU matrix operation passed.
- A 23.75 MP page with max-side 2200 completed using about 4181 MiB peak VRAM.
- Default Paddle `text_det_limit_type=min` reached about 7917 MiB; production therefore sets
  `max` explicitly.
- Warm representative GPU median in the spike was about 0.99 seconds.
- The production adapter smoke produced 4 normalized blocks and 0 warnings.
- Production smoke first initialization/parse was 11.62 seconds; the second parse was a verified
  OCR cache hit in 0.206 seconds.
- Model bytes were unchanged between runs, proving no second download.
- CPU framework check passed. Full PP-StructureV3 CPU inference with oneDNN disabled exceeded 90
  seconds and approximately 20 GB RAM in the bounded spike; it was terminated to protect the
  machine. CPU therefore remains fallback, not the default.
- No MinerU package or model was installed or downloaded.

The temp spike/model paths used during verification are disposable evidence, not durable product
state. Do not build a new plan around their continued existence.

## 5. Document IR 1.2 and behavioral contracts

IR 1.2 added:

- `PageClassification`: `digital | scanned | image_text_layer | suspect | blank`, confidence,
  stable reasons, recommended parser and classifier version;
- page parser override, actual parser id/version/options/model versions;
- parse status `unparsed | parsed | stale | failed`, structured error and warnings;
- optional OCR block confidence;
- richer provider/parser/model/device/precision/raw-element provenance;
- minimal `CaptionBlock(for_asset_id)`.

Migration from 1.1 is conservative and must remain:

- idempotent and atomically persisted;
- preserving page/block IDs, source text, user edits, assets and translations;
- non-reparsing;
- explicit on unsupported or corrupt versions.

Important contracts for future editing work:

- Document IR remains the source of truth; EPUB is only output.
- Changing parser override does not immediately replace blocks. A parser mismatch marks existing
  content stale and keeps it visible until Parse/Reparse.
- Reparse builds and validates a complete candidate page before atomic replacement.
- Reparse conflicts include user edits, merge/split history and every TranslationRecord state.
- Confirmed whole-page replacement creates new stable IDs, removes active translations for old
  block IDs, and never inherits old translations.
- Failed reparse preserves existing blocks/edits/translations and leaves an existing page stale;
  a page without old content becomes failed.
- Raw extraction/cache and audit data are retained; M3 does not provide undo.
- Translation cache/state invalidation still follows source-text changes.
- GUI code must not depend on Paddle response structures, and domain/core code must not depend on
  PySide6.

## 6. Main code boundaries

Read these files before planning M4:

### Domain and persistence

- `src/pdf2epub/domain/models.py`: IR 1.2 entities and parse state.
- `src/pdf2epub/domain/identifiers.py`: stable block/parse identifiers.
- `src/pdf2epub/domain/errors.py`: typed OCR/parser/cache errors.
- `src/pdf2epub/persistence/migrations.py`: 1.0/1.1 to 1.2 migration.
- `src/pdf2epub/persistence/project_store.py`: atomic project persistence boundary.
- `src/pdf2epub/persistence/parse_cache.py`: OCR cache format and recovery.

### Classification and parsing

- `src/pdf2epub/pdf/analyzer.py`: Native page probes used for classification.
- `src/pdf2epub/pdf/classifier.py`: classifier v1 and stable reason codes.
- `src/pdf2epub/parsers/base.py`: provider-neutral parser protocol/options.
- `src/pdf2epub/parsers/registry.py`: registry and router.
- `src/pdf2epub/parsers/native_pdf.py`: Native parser adapter.
- `src/pdf2epub/parsers/paddle_structure.py`: lazy Paddle adapter, runtime/device/models/cache.
- `src/pdf2epub/parsers/ocr_normalization.py`: Paddle payload to IR mapping.
- `src/pdf2epub/application/parsing.py`: progress and reparse conflict/result types.
- `src/pdf2epub/application/workflow.py`: analyze/override/parse/batch/reparse orchestration.

### Editing, GUI and EPUB

- `src/pdf2epub/application/editing.py`: existing text edit and merge/split behavior. This is the
  natural starting boundary for M4 commands but must be reviewed before extending it.
- `src/pdf2epub/gui/main_window.py`: Page List, parsing actions, workers and export confirmations.
- `src/pdf2epub/gui/page_view.py`: preview/overlay selection and confidence rendering.
- `src/pdf2epub/gui/workers.py`: background progress worker.
- `src/pdf2epub/epub/builder.py` and `xhtml.py`: complete/incomplete output behavior.
- `src/pdf2epub/translation/`: existing paragraph-addressable translation and stale/cache rules.

### Tests and fixtures

- `src/pdf2epub/fixtures.py` and `scripts/make_fixtures.py`.
- `tests/unit/test_m3_classification.py`.
- `tests/unit/test_ocr_normalization.py`.
- `tests/unit/test_parse_cache.py`.
- `tests/integration/test_mixed_workflow.py`.
- `tests/gui/test_smoke.py`.
- `scripts/verify_m1.py`, `verify_m2.py`, `verify_m3.py`.
- `scripts/smoke_paddleocr.py`.

## 7. Last verified quality results

At commit content equivalent to the current handoff snapshot:

- `uv lock --check`: passed.
- `uv sync --locked`: passed.
- Ruff formatting check: 93 files formatted.
- Ruff lint: passed.
- `mypy --strict src tests`: passed, 67 source files checked.
- pytest: 78/78 passed.
- M1 deterministic vertical verification: passed.
- M2 deterministic vertical verification: passed.
- M3 fake-OCR mixed vertical verification: passed.
- Complete mixed EPUB: EPUBCheck 0 fatals, 0 errors, 0 warnings.
- Incomplete-notice mixed EPUB: EPUBCheck 0 fatals, 0 errors, 0 warnings.
- Real production GPU OCR/cache smoke: passed.
- CPU extra framework check: passed.
- `uv sync --all-extras`: rejected as designed with exit code 2.
- `git diff --check`: passed before the M3 commit.

Do not quote these as current without rerunning them in the next task.

## 8. Manual acceptance still required

Automated Qt tests passed, but a human has not yet recorded the full GUI visual smoke. Before M3
is treated as visually accepted, follow `docs/smoke-test.md` and verify at least:

1. Base installation without OCR extra still launches and Native PDF remains usable.
2. First model download is explicit and cancellable.
3. Auto routes digital/scanned mixed pages correctly.
4. Single/multi-page override marks stale and reparses correctly.
5. OCR overlay geometry, confidence, low-confidence styling and selection linkage are visually
   correct.
6. Progress remains responsive and cancellation stops after the current page.
7. Retry, Force Native and explicit CPU retry are understandable and do not silently fallback.
8. Reparse conflict confirmation protects edits and translations; failed candidates preserve old
   content.
9. Incomplete export requires confirmation and contains a visible notice.
10. Complete and incomplete GUI-produced EPUBs both pass EPUBCheck.
11. Project reopen preserves IR 1.2 states, overrides, warnings, edits, translations, assets and
    OCR provenance.

The next planner should distinguish this unperformed human visual check from automated and CLI
evidence. It may plan around it, but must not silently claim it passed.

## 9. Next milestone according to PROJECT_SPEC.md

The next milestone is M4, structure editing workbench:

- merge/split;
- block type change;
- heading level;
- running header/footer handling;
- local region reparse;
- undo/redo;
- provenance inspector;
- warning center.

The specification also expects Parsed Document View operations and auditable/reversible
structure operations. M4 must preserve the M1-M3 vertical slices, translation invalidation,
stable identities where semantically possible, raw extraction/provenance, parser abstraction and
valid complete/incomplete EPUB behavior.

Important M4 planning decisions that must be explicit rather than assumed:

- command model and finite undo/redo scope;
- operation/audit representation in IR and the next schema version/migration;
- stable block ID rules for merge, split, type/heading edits and undo/redo;
- exact source-text and TranslationRecord stale/delete/restore semantics for every operation;
- how running header/footer is represented: deletion, excluded flag, block type or reversible
  suppression;
- local-region reparse input geometry, supported parser capability, candidate/confirmation
  boundary and interaction with existing whole-page OCR cache;
- whether local reparse is Paddle-only in M4 and how unsupported Native behavior is surfaced;
- snapshot versus inverse-command persistence and crash/reopen behavior;
- asset/caption/reference integrity during structural edits;
- provenance inspector data boundary so Paddle raw payload does not leak into GUI models;
- warning identity, lifecycle, acknowledgement and whether warnings affect incomplete export;
- background worker, cancel and save boundaries for region reparse;
- GUI selection and overlay behavior when blocks are merged/split/replaced;
- fixture/golden strategy for multi-column, headers/footers, captions and region reparse;
- performance/resource caps and privacy/logging behavior.

Prefer the smallest M4 architecture that satisfies the specification. Do not turn M4 into a full
generic document editor or introduce M5 capabilities while solving these decisions.

## 10. Required regression and validation scope for the next plan

Every M4 implementation step should name tests, failure scenarios and `Done when`. The completed
plan should retain at least:

```powershell
$uv = 'C:\Users\lhai0704\.local\bin\uv.exe'

& $uv lock --check
& $uv sync --locked
& $uv run --locked pytest
& $uv run --locked ruff check .
& $uv run --locked ruff format --check .
& $uv run --locked mypy --strict src tests

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$root = Join-Path $env:TEMP "pdf2epub-next-verify-$stamp"
$fixtures = Join-Path $root 'fixtures'
New-Item -ItemType Directory -Path $root | Out-Null

& $uv run --locked python scripts\make_fixtures.py --output $fixtures
& .\scripts\bootstrap_epubcheck.ps1
$jar = (Resolve-Path '.tools\epubcheck-5.3.0\epubcheck.jar').Path

& $uv run --locked python scripts\verify_m1.py `
  --pdf (Join-Path $fixtures 'digital_single_column.pdf') `
  --workspace (Join-Path $root 'm1') `
  --epubcheck-jar $jar

& $uv run --locked python scripts\verify_m2.py `
  --pdf (Join-Path $fixtures 'digital_single_column.pdf') `
  --workspace (Join-Path $root 'm2') `
  --epubcheck-jar $jar

& $uv run --locked python scripts\verify_m3.py `
  --output-dir (Join-Path $root 'm3') `
  --epubcheck-jar $jar

git diff --check
git status --short
```

For any EPUB behavior change, validate a generated fixture with EPUBCheck. For any GUI behavior
change, update automated Qt coverage and define a documented human smoke. Use fake parsers/OCR in
automated tests; do not make CI download models or call paid translation APIs.

## 11. Suggested opening instruction for the new Plan-mode task

The user can attach or quote this file with a request similar to:

> Read AGENTS.md, PROJECT_SPEC.md, this M3 implementation handoff, the M3 planning handoff,
> ADR-006 through ADR-008, the current architecture/IR/smoke documents and the relevant source and
> tests. Stay in Plan mode. First audit the actual Git state, environment, M3 implementation and
> all quality gates. Then produce a concrete, minimal M4 structure-editing-workbench plan that
> preserves M1-M3 behavior. Make schema, command/undo, block-ID, translation invalidation, region
> reparse/cache, provenance, warnings, GUI and EPUB semantics explicit. Include alternatives and
> trade-offs, tests/failures/Done-when for every step, expected files, ADRs, full verification
> commands and required human GUI smoke. Do not implement anything until the plan is reviewed.

