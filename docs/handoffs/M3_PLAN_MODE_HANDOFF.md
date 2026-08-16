# M3 Plan Mode 交接文档

更新日期：2026-08-16

## 1. 用途与下一阶段目标

本文件用于交给一个新的 Codex 对话。新对话应先进入 **Plan mode**，只规划
`PROJECT_SPEC.md` 中的 M3“扫描/混合 PDF”，本轮不要直接实现代码。

M0/M1 已完成数字 PDF → 可编辑 Document IR → 单语 EPUB；M2 已完成逐段翻译、
双语预览和 Source → Translation EPUB。M3 的目标是：

> 对每一页进行 Native / OCR / Suspect 分类，允许用户覆盖解析策略，让数字页和扫描页
> 通过不同 parser 进入同一份 Document IR，并保持现有编辑、翻译和 EPUB 能力不回归。

M3 只包含：

- page classification；
- per-page / page-range parser override；
- 一个正式的 PaddleOCR / PP-Structure adapter；
- OCR bbox overlay；
- digital + scanned mixed document handling；
- OCR result cache；
- parser unavailable/failure fallback；
- 对应的 GUI、持久化、测试、文档和验证脚本。

不要在 M3 加入 MinerU 生产 adapter、Unlimited-OCR、Docling、多 OCR 引擎切换、局部区域
重解析、undo/redo、完整结构编辑工作台、完整 EPUB Reader、Web 后端、Redis、Celery、
安装包或其他 M4/M5 功能。

## 2. 新对话开始前必须完整阅读

1. `AGENTS.md`；
2. `PROJECT_SPEC.md`，尤其第 4、7、9、22–30 节；
3. 本文件 `docs/handoffs/M3_PLAN_MODE_HANDOFF.md`；
4. `docs/architecture.md`、`docs/document-ir.md`；
5. `docs/decisions/` 下全部 ADR；
6. 当前 analyzer、parser、workflow、Document IR、persistence、GUI、fixture 和测试代码。

本文件只是交接快照。新对话必须重新检查实际 Git 状态、代码、锁文件、机器环境和测试，
不能仅凭本文直接假设现状。

## 3. 当前 Git 与环境快照

交接时观察到：

- 仓库：`D:\Projects\pdf2epub`；
- 分支：`main`；
- HEAD：`777794d Implement M2 paragraph translation and bilingual EPUB export`；
- `main` 与 `origin/main` 同步；
- worktree 干净；
- Windows 11 家庭版 64 位，版本 `10.0.26200`；
- Python `3.12.9`；
- uv `0.12.4`；
- Java 21；
- EPUBCheck `5.3.0`；
- NVIDIA GeForce RTX 4060 Laptop GPU，8 GiB，驱动 `610.62`；
- 当前锁定环境没有 PaddlePaddle、PaddleOCR 或其他 OCR 运行时。

GPU 的存在不等于 PaddleOCR GPU 版在当前 Windows、Python 3.12 和驱动组合上可用。M3
计划必须先用当前官方资料和最小 spike 验证兼容性，不能静默选择 GPU 路线。

## 4. M2 后的已实现基线

### 4.1 核心架构

- Python `src` 布局，domain、application、parser、persistence、translation、EPUB、GUI 分层。
- `BookDocument` 是唯一事实来源；EPUB 永远只是输出。
- domain/core 不依赖 PySide6；GUI 不读取 PyMuPDF 或 provider 原始 payload。
- `.bepub-project` 保存源 PDF 副本、版本化 `document.json`、assets 和 cache。
- 保存使用临时文件 + `os.replace` 原子替换。
- parser raw cache 和 provenance 被保留，默认日志不记录正文。

### 4.2 数字 PDF 能力

- PyMuPDF 文档检查、页面预览、原生文本和内嵌图片提取。
- 单栏/双栏 reading order、行合并、断词规范化和 heading heuristic。
- 稳定 span/block/asset ID、bbox overlay 和 block 联动。
- 页面按需 parse/render，未变化页面命中 parse cache。
- 文本编辑、paragraph/heading 类型切换、merge/split。
- 原始文本、规范化文本和用户文本分层保存。

### 4.3 M2 翻译能力

- Document IR `1.1`，显式支持从 `1.0` 内存迁移并在下次保存写回。
- paragraph-addressable `TranslationRecord` 和项目级 `TranslationSettings`。
- `Translator` protocol、`FakeTranslator`、LongCat `LongCat-2.0` adapter。
- LongCat key 只读取 `LONGCAT_API_KEY`，不进入项目、cache、日志或 Git。
- context 包括最近 heading、前后 paragraph、语言、glossary 和 style。
- cache key 包含有效源文、语言、provider/model、prompt、glossary 和 context fingerprint。
- 项目内原子 JSON translation cache；Document IR 仍是译文事实来源。
- 串行批量任务、queued/translating 瞬态、逐段保存、cancel、partial/fatal failure、retry。
- 源文和翻译设置的精确 stale 规则；用户译文为 `user_edited`。
- GUI Translation View、隐私确认、双语预览和 Source → Translation EPUB。
- 标题和 TOC 在 M2 保持原文；M1 Original-only EPUB 路径仍兼容。

### 4.4 当前 ADR

- ADR-001：Document IR；
- ADR-002：项目内原子 JSON；
- ADR-003：自有薄 EPUB packager；
- ADR-004：Translation IR 1.1 与 migration；
- ADR-005：translation cache、LongCat 和 secrets。

M3 若引入 OCR 运行时、IR schema 变化、parser routing 或新的 cache 语义，应新增 ADR，而不是
修改历史 ADR 来掩盖新决策。

## 5. 当前验证基线

交接前重新运行得到：

- `uv sync --locked`：通过；
- `uv lock --check`：通过；
- pytest：`62 passed`；
- Ruff lint：通过；
- Ruff format check：通过；
- strict mypy：通过；
- M1 verify：第二次解析命中 cache；
- M1 EPUBCheck：0 fatal / 0 error / 0 warning；
- M2 fake verify：partial failure、retry、cache、stale、保存重开和双语 EPUB 通过；
- M2 EPUBCheck：0 fatal / 0 error / 0 warning；
- 仓库未发现 API key。

pytest-qt 在这台 Windows 机器的 Qt 消息循环中可能打印非终止性的 first-chance
`0x8001010d` 提示，但测试进程最终正常返回成功。新对话应重新确认；不要把提示隐藏成通过，
也不要在没有复现证据时把它归因于 M3/OCR。

真实 LongCat 付费 smoke 没有执行。任何曾在对话中暴露的 key 都应视为已泄漏并轮换；M3
规划和自动测试不需要 LongCat key，也不应触发真实翻译。

## 6. 与 M3 直接相关的现有代码边界

### `src/pdf2epub/pdf/analyzer.py`

目前只生成 `NativeTextQuality(status=usable/suspect/no_text)`。它会检查字符数、乱码/控制字符
比例和图片覆盖率，但尚未生成规格中的 `PageClassification`，也没有置信度、推荐 parser 或
用户 override。

### `src/pdf2epub/domain/models.py`

当前 `Page` 只有 `parser_id`、`parse_status`、`parse_fingerprint`、`quality` 和 blocks。
没有正式的 classification、auto recommendation、override、OCR confidence 或 parser options
快照。M3 很可能需要 Document IR `1.2`，但必须先给出最小模型与 `1.1 → 1.2` migration，
不要为了猜测未来能力堆字段。

### `src/pdf2epub/parsers/base.py`

已有 `DocumentParser` protocol、`PageContext`、`ParseOptions` 和 `PageParseResult`。这是 OCR
adapter 应遵守的边界，但当前 protocol 没有通用 fingerprint 方法，`ParseOptions` 也只包含
native 图片选项和像素上限。

### `src/pdf2epub/parsers/native_pdf.py`

`NativePdfParser` 已实现自己的 fingerprint、原子 raw cache、图片资产、provenance 和 IR
normalization。OCR parser 应复用这些项目级约定，不得让 PaddleOCR/PP-Structure 原始类型
泄漏到 domain、workflow 或 GUI。

### `src/pdf2epub/application/workflow.py`

`BookWorkflow` 目前硬绑定单个 `NativePdfParser`，并直接调用其 `.fingerprint()`。M3 需要最小
parser registry/router 或 selection service，使 automatic/override 都经过同一应用边界。
不要在 GUI 中实例化 PaddleOCR 或解析其返回值。

### `src/pdf2epub/persistence/project_store.py`

已有 Document IR migration 和原子保存。M3 的 page override、classification 和 parser
options 必须进入版本化项目状态；OCR raw/result cache 仍应是可丢弃优化，不能成为事实来源。

### `src/pdf2epub/gui/main_window.py`

现有页面列表、PDF page/bbox view、Structure、Translation、EPUB Preview 和 Logs。M3 应在现有
页面工作流上增加状态文字、范围选择、Auto/Native/OCR override、批量进度和 cancel；不要创建
第二套 GUI 或完整 Reader。

### fixtures/tests/scripts

当前 fixture 全是仓库生成的合法数字 PDF。M3 需要生成：纯扫描、多页 mixed、带隐藏文字层、
低质量/乱码文字层、OCR 失败等最小 fixture。自动测试优先 fake OCR adapter；真实 PaddleOCR
不得成为每次 pytest 都下载模型或依赖 GPU 的隐式网络测试。

## 7. M3 计划必须显式解决的决策点

### 7.1 PaddleOCR / PP-StructureV3 的实际可用版本

规格写的是 PaddleOCR/PP-StructureV3，但库、API、模型和安装矩阵会变化。Plan mode 必须查询
当前官方文档并验证：

- Windows + Python 3.12 是否正式支持；
- CPU 与 CUDA/GPU 包的准确安装方式和兼容矩阵；
- PP-StructureV3 的当前 Python API、模型下载行为和 license；
- 初次模型下载大小、缓存位置、离线行为和失败提示；
- 是否需要把 OCR 放在可选 dependency group，而不是强迫所有开发/翻译任务安装大依赖。

最小推荐：自动测试使用 `FakeOcrParser`/fixture payload；正式 adapter 作为明确的 OCR 可选依赖，
用仓库生成的无版权扫描页做显式本机 smoke。只有 spike 证明 GPU 路线稳定才选择 GPU，否则先用
CPU 完成 M3 垂直切片。计划必须写明取舍，不能静默采用此推荐。

### 7.2 Spike D 与 MinerU 边界

`PROJECT_SPEC.md` 要求 M3 前在少量页面对比 PaddleOCR / MinerU，但 M3 生产范围只要求
PaddleOCR/PP-Structure adapter。

计划应把 MinerU 限制为只读研究/独立 spike 输出，不把它加入生产依赖、Document IR 分支、GUI
选项或 M3 验收。是否实际安装 MinerU、下载模型或修改本机环境，必须先列出成本并取得用户明确
同意。

### 7.3 Page classification 与 override 的事实模型

必须区分：

- analyzer 的观察结果；
- automatic classification/recommended parser；
- 用户 override（Auto/Native/OCR）；
- 本次实际使用的 parser/options；
- parse terminal state 和脱敏错误。

重新分析不得覆盖用户 override。classification 算法版本或 parser options 改变时，需要明确哪些
页面 stale、哪些 cache key 变化。

### 7.4 Parser registry/router

规划一个满足两个正式 parser 的最小 registry/router。不要上插件框架、依赖注入容器或服务型
调度器。GUI/application 只传 parser selection，router 返回 provider-neutral `PageParseResult`。

### 7.5 OCR normalization、raw data 与 provenance

需要明确 PP-Structure 的文字、bbox、reading order、block type、confidence、图片/caption 如何映射
到当前 IR。必须保存经过脱敏/可控大小的 raw extraction data 或 raw cache path，并记录 parser、
model/version、options、source page 和来源元素 ID。OCR 结果不能覆盖原始 PDF，也不能伪装成 native。

### 7.6 OCR cache key

至少应覆盖：

```text
source_pdf_hash + page + parser_id + parser/model_version + normalized_options_hash
```

计划应决定语言、layout model、OCR model、设备/precision 等哪些会改变输出并进入 key。cache 损坏
应是可恢复错误，不得破坏 Document IR。不要引入 Redis、Celery 或数据库；先使用项目内版本化、
原子文件缓存。

### 7.7 重解析与已有人工编辑/译文冲突

这是 M3 最重要且当前未解决的产品边界。切换 parser 或重新 OCR 可能替换整页 blocks，导致稳定
ID、人工编辑和 translation binding 变化。计划必须明确：

- 未解析页可以直接解析；
- 已解析但无人改/无译文的页如何安全替换；
- 含 `source_text_user`、manual structure edit、`user_edited`/有效译文的页如何阻止静默覆盖；
- 是否先采用“明确确认后整页替换，旧 raw/cache 保留，新 blocks untranslated”的最小语义；
- 是否需要冲突提示，而不是在 M3 实现复杂 block matching/merge。

不要默默继承旧 block 的译文，也不要把复杂 revision/undo 系统提前带入 M3。

### 7.8 批量、取消、部分失败和 fallback

OCR 必须在 worker 中执行，按页保存终态。Cancel 后已完成页保留，未开始页不被标成成功；单页
失败不回滚其他页。parser unavailable、模型下载失败、OOM 和 OCR runtime error 应分层。

“fallback”不能意味着扫描页 OCR 失败后静默导出空 native 结果。最小策略应向用户显示失败，允许
retry、切换 Native 或暂时跳过，并在预览/导出中明确内容不完整。

### 7.9 GUI 最小交互

计划至少覆盖：

- Page List 的 Native/OCR/Suspect 文字状态；
- 多页/范围选择；
- Auto、Force Native、Force OCR；
- 当前推荐 parser、实际 parser、override 和错误摘要；
- 批量 Analyze/Parse、进度、cancel、retry；
- OCR bbox overlay 与现有 block/text 编辑联动；
- 操作期间哪些控件禁用，窗口如何保持响应；
- reparse 会覆盖人工编辑/译文时的明确确认。

颜色不能是唯一状态表达。GUI 不得读取 Paddle 原始响应。

### 7.10 隐私与资源限制

M3 OCR 默认本地执行，不发送用户页面到远端。模型下载是网络行为，应在安装/首次使用说明中明确。
继续限制不可信 PDF、页面尺寸、render pixels、OCR 输入像素、任务取消和错误日志正文。计划必须讨论
大页、超长书、OOM、临时文件和模型 cache 的边界。

## 8. 建议的最小 M3 规划顺序

Plan mode 可以调整顺序，但每步都必须给出自动化测试、失败场景和 `Done when`：

1. 重新审计仓库、官方依赖兼容性和本机 CPU/GPU；只做 M3 spike 计划。
2. 扩展合法 fixture corpus：scanned、mixed、hidden text layer、suspect/failure。
3. 设计 Document IR 1.2、page classification/override/options/error 与 1.1 migration。
4. 将 fingerprint 提升为通用 parser 边界，增加最小 registry/router 和 fake OCR parser。
5. 实现可解释 page classifier，并证明 override 优先且可保存重开。
6. 实现 PaddleOCR/PP-Structure adapter，将结果归一化为现有 IR/provenance。
7. 实现版本化 OCR cache、损坏恢复、parser unavailable/runtime/OOM 错误分类。
8. 实现逐页/范围 batch、串行或受控并发、progress、cancel、partial failure 和逐页保存。
9. 明确定义 reparse 与人工编辑/translation 的冲突保护。
10. 扩展 GUI Page List、override、OCR 状态、bbox overlay、retry 和不完整内容提示。
11. 验证 mixed Document IR 能继续编辑、翻译、预览和导出，且原生页不被 OCR。
12. 新增 ADR、架构/IR/smoke 文档和确定性 `verify_m3.py`；运行真实 PaddleOCR 手工 smoke。

最小架构优先。不要为了未来多 parser 提前设计通用插件市场或分布式任务系统。

## 9. M3 完成条件

- 页面自动标注 Native / OCR / Suspect，并显示可解释 reasons。
- 用户可对单页和页范围设置 Auto/Native/OCR override，保存重开后仍存在。
- override 始终优先于自动推荐。
- 数字页默认走 Native，不因引入 OCR 而回归或重复 OCR。
- 扫描页经真实 PaddleOCR adapter 生成可编辑、带 bbox/provenance 的 IR blocks。
- mixed fixture 最终进入一份统一 Document IR，可继续翻译和导出。
- OCR cache hit 由 fake/adapter 调用次数及重开测试证明。
- 单页失败、模型不可用、cancel 或保存失败不会损坏其他页面或项目。
- 已有人工编辑/译文不会被 reparse 静默覆盖。
- OCR bbox 与现有 PDF Page View / Parsed Document View 联动。
- 自动测试不下载模型、不触发付费服务；真实 OCR smoke 明确分离。
- M1/M2 全部回归测试通过。
- mixed fixture 导出的 EPUB 通过 EPUBCheck，内容缺失不会被隐藏。

## 10. 预期测试范围

计划至少应包含：

- classifier：native、scanned、text layer、suspect、rotation/large page 边界；
- override：单页、范围、清除 override、保存重开、classifier rerun 不覆盖；
- migration：1.1 → 新 schema、未知版本、额外字段、round-trip；
- router：auto/native/OCR、parser unavailable、非法 selection；
- fake OCR：bbox、confidence、reading order、provenance、raw cache path；
- cache：key 各维度、hit/miss、损坏、重开、失败不缓存；
- batch：全成功、部分失败、cancel 前/中/后、保存失败、retry；
- reparse conflict：人工源文、merge/split、有效/手改/stale 译文；
- GUI：范围选择、override、progress、cancel、retry、文字状态、响应性；
- mixed end-to-end：Native 页未调用 OCR、扫描页未误走 Native、统一 IR、翻译/导出回归；
- EPUBCheck：0 error。

OCR 输出在不同机器可能存在浮点或文本细微差异。golden tests 应对 bbox 使用容差，并把 provider-
neutral normalization 与真实 runtime smoke 分开；不要把易漂移的完整 Paddle payload 当 golden。

## 11. 当前完整回归命令

```powershell
Set-Location 'D:\Projects\pdf2epub'
$Pdf2EpubUv = 'C:\Users\lhai0704\.local\bin\uv.exe'

git status --short --branch
git log -3 --oneline --decorate

& $Pdf2EpubUv sync --locked
& $Pdf2EpubUv lock --check
& $Pdf2EpubUv run --locked pytest
& $Pdf2EpubUv run --locked ruff check .
& $Pdf2EpubUv run --locked ruff format --check .
& $Pdf2EpubUv run --locked mypy src tests scripts

.\scripts\bootstrap_epubcheck.ps1
$env:EPUBCHECK_JAR = (Resolve-Path '.tools\epubcheck-5.3.0\epubcheck.jar').Path

& $Pdf2EpubUv run --locked python scripts\make_fixtures.py `
  --output 'tmp\fixtures'

& $Pdf2EpubUv run --locked python scripts\verify_m1.py `
  --pdf 'tmp\fixtures\digital_single_column.pdf' `
  --workspace 'tmp\m1-regression' `
  --epubcheck-jar $env:EPUBCHECK_JAR

& $Pdf2EpubUv run --locked python scripts\verify_m2.py `
  --pdf 'tmp\fixtures\digital_single_column.pdf' `
  --workspace 'tmp\m2-regression' `
  --epubcheck-jar $env:EPUBCHECK_JAR

git diff --check
git status --short --branch
```

注意：verify workspace 必须是新的空路径；脚本会拒绝覆盖既有验证项目。

## 12. 新对话可直接发送的请求

```text
请完整阅读 AGENTS.md、PROJECT_SPEC.md 和
docs/handoffs/M3_PLAN_MODE_HANDOFF.md，并阅读其中列出的当前架构、ADR 和相关代码。

这是现有本地项目的下一阶段规划任务。请保持在 Plan mode，本次不要修改代码、依赖、锁文件、
模型缓存或本机 OCR 环境。先检查实际仓库、Git 状态、当前 commit、本地 Python/uv/Java/GPU
环境、现有代码边界和全部测试结果，再只为 M3“扫描/混合 PDF”制定具体实施计划。

计划必须遵守 PROJECT_SPEC.md，并优先采用满足 M3 验收的最小架构。需要覆盖：

- PaddleOCR/PP-StructureV3 的官方兼容性与最小 Spike D；
- page classification、reasons、recommended parser；
- 单页和页范围 Auto/Native/OCR override；
- Document IR 版本升级和旧 M2 项目 migration；
- parser registry/router 与 provider-neutral adapter；
- OCR normalization、bbox、confidence、raw data 和 provenance；
- OCR cache key、模型版本/options、损坏恢复；
- mixed document、批量任务、progress、cancel、partial failure 和 fallback；
- 重解析与人工编辑、block ID、现有译文/stale 的冲突保护；
- GUI Page List/override/OCR overlay/retry/错误与不完整内容提示；
- local-first 隐私、模型下载、CPU/GPU、资源限制；
- fake OCR 自动测试、合法 scanned/mixed fixtures、真实 OCR 手工 smoke；
- M1/M2 回归、mixed EPUB 与 EPUBCheck。

不要加入 MinerU 生产 adapter、Unlimited-OCR、Docling、多 OCR 引擎、局部区域重解析、undo/redo、
完整结构编辑工作台、完整 EPUB Reader、Web 后端、Redis、Celery、安装包或 M4/M5 功能。MinerU
如需比较，只能作为边界清晰的 M3 前研究 spike，并先说明是否会安装依赖/下载模型。

PaddleOCR 精确版本、CPU/GPU 路线、可选依赖组织、IR 1.2 字段、分类阈值、OCR cache 组成、
reparse 覆盖语义和失败 fallback 都是必须显式列出的决策点。请给出最小推荐、替代方案和取舍，
不要静默假设。对于会变化的依赖/API 信息，只使用当前官方一手资料。

如果 PROJECT_SPEC.md、当前代码和 M3 目标存在冲突，请指出并提出最小修正。每个实施步骤都要
包含测试、失败场景和 Done when。最后给出预计新增/修改文件、ADR、完整自动验证命令，以及
需要用户明确执行的真实 OCR/GUI smoke。计划完成后停下等待审阅，不要开始实现。
```

## 13. 交接原则

下一阶段的成功标准不是“接上 OCR API”，而是：用户能看到每页为什么被判为 Native/OCR/
Suspect，能安全覆盖策略；不同 parser 的结果进入同一可审计 IR；失败或重解析不会静默丢失人工
编辑与译文；最终 mixed PDF 仍能生成可验证且不隐藏内容缺失的双语 EPUB。
