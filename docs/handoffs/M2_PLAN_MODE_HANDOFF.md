# M2 Plan Mode 交接文档

更新日期：2026-08-16

## 1. 项目与下一阶段目标

本项目是一个 local-first 的 PySide6 桌面应用。M0/M1 已完成从数字 PDF 到可编辑、版本化 Document IR，再到合法单语 EPUB 3 的第一条垂直切片。

下一阶段只规划 `PROJECT_SPEC.md` 定义的 M2：

> 数字 PDF → 逐段翻译 → 原文/译文交替的双语 EPUB。

不要在 M2 引入 OCR、MinerU、Unlimited-OCR、扫描/混合 PDF parser、完整 EPUB Reader、Web 后端、Redis、Celery、安装包或 M3/M4 功能。

## 2. 开始前必须阅读

新对话中的 Codex 应完整阅读：

1. 根目录 `AGENTS.md`；
2. 根目录 `PROJECT_SPEC.md`；
3. 本交接文档；
4. `docs/architecture.md`、`docs/document-ir.md` 和 `docs/decisions/`；
5. 与 M2 直接相关的现有 domain、application、persistence、epub、gui 和 tests 代码。

必须先检查实际仓库、Git 状态、Python/Java/uv 环境和现有测试结果，再制定计划。不要只根据本交接文档推断实现状态。

## 3. M0/M1 已实现内容

- Python 3.12.9、uv lock、Hatchling、PySide6 Essentials、Pydantic 2。
- pytest、pytest-qt、Ruff 和严格 mypy 质量门。
- `src` 布局，GUI、application、domain、parser、persistence 和 EPUB 分层。
- 严格、版本化的 Document IR；EPUB 不是内部数据源。
- 稳定 document/page/span/block/asset ID，以及 raw extraction provenance。
- `source_text_raw`、`source_text_normalized`、`source_text_user` 和统一 `effective_text`。
- `.bepub-project` 原子保存/加载、源 PDF 默认复制、SHA-256 校验和 stale 标记。
- 自有文字和程序生成图片组成的合法 PDF fixture corpus。
- PyMuPDF native parser、图片提取/去重、解析缓存、页面渲染缓存。
- 单栏/双栏 reading order、段落合并、连字符规范化和标题规则。
- 文本编辑、paragraph/heading 类型调整、heading level、相邻 merge 和光标 split。
- Qt 三栏界面、后台 parse/render/export、bbox/block 双向联动和轻量预览。
- 标准库 EPUB 3 packager、内部一致性检查和外部 EPUBCheck 5.3.0。
- CLI、spike、ADR、golden tests 和端到端验证脚本。

## 4. 当前验证基线

截至本交接文档创建时：

- `uv sync --locked`：通过；
- `uv lock --check`：通过；
- pytest：25 passed；
- Ruff lint/format：通过；
- mypy：44 个源文件无问题；
- EPUBCheck：0 fatals、0 errors、0 warnings；
- 真实窗口 smoke：编辑、merge、split、预览、导出、关闭重开均通过；
- 100 页 fixture 使用按需页面加载，没有预渲染全部页面；
- 端到端验证第二次解析命中缓存，没有重复解析未变化页面。

这些是规划 M2 时必须维持的回归基线，不代表新对话可以跳过重新验证。

## 5. M2 的规格范围

`PROJECT_SPEC.md` 对 M2 的明确要求是：

- Translator interface；
- FakeTranslator；
- 一个真实 provider adapter；
- translation context；
- translation memory/cache；
- batch translation；
- `translated`、`stale`、`failed` 等状态；
- bilingual preview；
- Source → Translation 双语 EPUB export；
- 可设置源语言和目标语言；
- API 失败不得损坏或丢失项目；
- 修改原文后，仅对应译文进入 stale；
- 重复运行/导出不得重复调用已缓存翻译；
- EPUBCheck 无 error。

持久化单位必须是 paragraph。调用模型时可以提供章节标题、前后段落、术语表、专有名词表和风格设置作为 context，但响应只能绑定当前 paragraph ID。

缓存 key 至少包含：有效源文本的规范化结果、源语言、目标语言、provider、model、prompt version 和 glossary version。只修改 EPUB 样式不得使缓存失效。

## 6. 现有架构中与 M2 直接相关的位置

- `src/pdf2epub/domain/models.py`：当前 IR 尚无 translation 模型或语言/翻译设置。
- `src/pdf2epub/application/editing.py`：源文本编辑、merge/split/type change 必须在 M2 中触发精确翻译失效规则。
- `src/pdf2epub/application/workflow.py`：项目级同步服务；GUI worker 在其外层处理后台执行。
- `src/pdf2epub/persistence/project_store.py`：版本化 JSON、atomic replace 和显式 migration 边界。
- `src/pdf2epub/epub/xhtml.py`：预览与 EPUB 共用的语义 XHTML 入口。
- `src/pdf2epub/epub/builder.py`：当前仅 Original-only；需要扩展为 Source → Translation，而不是建立第二套导出路径。
- `src/pdf2epub/gui/main_window.py`：当前有 Structure、EPUB Preview、Logs；M2 需要最小 Translation View 和批量操作。
- `src/pdf2epub/gui/workers.py`：现有 `QThreadPool`/`QRunnable` 模式应复用，翻译不可阻塞 GUI。
- `tests/`：现有 fake、fixture、golden、GUI smoke 和 EPUBCheck 方式应延续。

## 7. Plan mode 必须显式解决的问题

不要在计划中默默假设以下选择：

1. **真实 provider 和 model**：规格要求一个真实 provider，但当前尚未选择。计划应列出最小 adapter 方案、依赖、请求/响应结构、超时、重试和费用风险，并在实现前取得用户选择。
2. **API key 存储**：不得进入项目 JSON、日志或 Git。应比较环境变量与 Windows keychain 的最小方案；新增依赖必须有明确收益。
3. **IR 版本演进**：说明 translation 数据加入 `BookDocument` 后使用兼容 minor schema 还是显式 migration，并给出旧 M1 项目的加载测试。
4. **缓存持久化**：优先评估项目内原子 JSON；只有数据规模证明确有需要时才引入 SQLite。不得提前引入服务型存储。
5. **有效源文本与失效**：缓存和 stale 判断必须基于用户当前看到的有效源文本，而不是只看 parser raw text。
6. **merge/split/type change 语义**：明确原 translation 如何保留、丢弃或标 stale，以及新 block ID 与 cache 的关系。
7. **标题和 TOC 翻译**：规格强调 paragraph 单位，但双语 EPUB 的标题/TOC 语言策略没有完全定死；计划必须指出冲突并提出最小修正。
8. **并发、取消和部分失败**：批量任务中已成功段落必须安全保存；cancel/网络失败不能回滚或覆盖其他有效翻译。
9. **日志与隐私**：默认日志不包含正文、完整响应或 API key；必须明确哪些文字会发送给远端。
10. **测试是否触网**：自动化测试只使用 FakeTranslator；真实 provider 仅做显式、手工、可选 smoke，绝不能在 CI 或普通 pytest 中付费调用。

## 8. 建议的最小 M2 垂直切片

Plan mode 应把工作拆成可独立验收的小步骤，至少覆盖：

1. translation domain models、状态机和 IR migration；
2. Translator protocol、TranslationRequest/Result 和 FakeTranslator；
3. context builder、cache key 与项目内持久化；
4. application service：单段/多段翻译、cache hit、stale、retry、cancel、partial failure；
5. 一个用户确认的真实 provider adapter；
6. 最小 Translation View：语言设置、段落选择、批量翻译、状态、译文编辑和 retry；
7. 复用 XHTML 生成器的双语 preview；
8. Source → Translation EPUB、稳定段落锚点、语言属性和内容覆盖检查；
9. EPUBCheck、fake provider 端到端测试和真实窗口 smoke；
10. ADR-005：translation cache key，以及必要的 provider/secret 决策记录。

每一步都应写出自动化测试、失败场景、`Done when` 和不会实现的未来范围。

## 9. M2 完成条件建议

- 可为项目设置 source/target language。
- 可选择多个 paragraph 后后台翻译，GUI 保持响应。
- FakeTranslator 的调用次数可证明 cache hit，不以时间或肉眼推断。
- 原文未变时重启应用、刷新预览和重复导出均不会调用 provider。
- 修改某一段原文只使该段 translation stale。
- 用户编辑译文后状态与 provider 结果来源可追踪，保存重开不丢失。
- 网络/API 单段失败不会损坏项目，成功段落仍已保存且失败段可 retry。
- 双语预览和 EPUB 都按 source → translation 逐段交替。
- XHTML 有正确 `lang`，锚点唯一，图片/heading/TOC 不回归。
- EPUBCheck 0 errors。
- 原有 25 个 M0/M1 测试继续通过，并补充 M2 单元、集成和 GUI 测试。

## 10. 当前验证命令

```powershell
Set-Location 'D:\Projects\pdf2epub'
$Pdf2EpubUv = 'C:\Users\lhai0704\.local\bin\uv.exe'

& $Pdf2EpubUv sync --locked
& $Pdf2EpubUv lock --check
& $Pdf2EpubUv run --locked pytest
& $Pdf2EpubUv run --locked ruff check .
& $Pdf2EpubUv run --locked ruff format --check .
& $Pdf2EpubUv run --locked mypy src tests scripts

.\scripts\bootstrap_epubcheck.ps1
$env:EPUBCHECK_JAR = (Resolve-Path '.tools\epubcheck-5.3.0\epubcheck.jar').Path
& $Pdf2EpubUv run --locked python scripts\make_fixtures.py --output 'tmp\fixtures'
```

## 11. 可直接交给新 Codex 对话的请求

```text
请完整阅读 AGENTS.md、PROJECT_SPEC.md 和 docs/handoffs/M2_PLAN_MODE_HANDOFF.md。

这是现有本地项目的下一阶段规划任务。先检查实际仓库、Git 状态、本地开发环境、当前代码边界和测试结果，然后只为 M2“数字 PDF → 双语 EPUB”制定具体实施计划，本次不要改代码。

计划必须遵守 PROJECT_SPEC.md，并优先采用满足规格的最小架构。需要覆盖版本化 translation IR、旧项目 migration、Translator/FakeTranslator、一个真实 provider、上下文、缓存 key、批量任务、cancel/partial failure、stale 失效、译文编辑、GUI Translation View、双语预览、Source → Translation EPUB、EPUBCheck、隐私和测试。

不要加入 OCR、MinerU、Unlimited-OCR、扫描/混合 PDF 支持、完整 EPUB Reader、Web 后端、Redis、Celery、安装包或 M3/M4 功能。

真实 provider/model、API key 存储、标题/TOC 翻译策略等未定事项必须明确列为决策点，并给出最小推荐与取舍；不要静默假设。如果 PROJECT_SPEC.md 与当前代码或 M2 目标存在冲突，请指出并提出最小修正。

每个步骤都要包含测试和 Done when，最后给出预计新增/修改文件以及完整验证命令。
```
