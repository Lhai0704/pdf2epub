# PDF → 双语 EPUB 桌面软件：项目规格说明书

**工作名称：pdf2epub（可后续改名）**  
**文档用途：交给 Codex / ChatGPT Work / 人类开发者作为项目起始规格**  
**版本：v0.1-spec**  
**日期：2026-08-16**

---

## 0. 如何使用这份文档

这份文档不是产品宣传稿，而是开发规格。目标是让一个第一次接触本项目的开发代理，在没有额外口头上下文的情况下，也能理解：

1. 产品解决什么问题；
2. 第一阶段必须做什么、明确不做什么；
3. PDF 解析、OCR、结构恢复、翻译、EPUB 导出的边界如何划分；
4. 中间数据模型如何设计；
5. GUI 应该如何组织；
6. 代码仓库如何拆分；
7. 如何测试“没有丢字、没有乱序、没有把错误静默带进 EPUB”；
8. 应该按什么里程碑逐步实现，而不是一次做成一个巨型项目。

**本项目最重要的原则：不要直接把 PDF 转成 EPUB。**  
正确模型是：

```text
PDF
  ↓
页面分析 / 原生文字提取 / OCR / 文档解析
  ↓
统一的结构化 Document IR（项目的事实来源）
  ↓
结构校正 + 人工编辑 + 可选 AI 辅助
  ↓
逐段翻译 + 翻译缓存
  ↓
EPUB / HTML / Markdown 等输出
```

EPUB 是输出格式，不是内部工作格式。

---

# 1. 产品愿景

用户经常拥有 PDF 电子书，其中包括：

- 正常数字 PDF：文字可选择，但在手机上不能很好重排；
- 扫描版 PDF：整页是图片，需要 OCR；
- 扫描图 + 隐藏 OCR 文字层的 PDF；
- 数字页、扫描页混合的 PDF；
- 英文或其他外语书籍，需要逐段双语阅读；
- 包含插图、标题、脚注、多栏排版、页眉页脚等结构的书籍。

目标用户希望最终得到一个适合手机阅读器（尤其是微信读书等 EPUB 阅读环境）的 **reflowable 双语 EPUB**：原文一段，译文一段，图片和章节结构尽可能保留。

产品不是简单的文件格式转换器，而是一个轻量的“电子书恢复与制作工作台”。

---

# 2. 核心目标

## 2.1 必须做到

- 导入 PDF 并逐页分析。
- 判断页面是否适合原生文字提取、OCR 或其他解析方式。
- 允许用户按页或页范围手动覆盖自动判断结果。
- 对数字 PDF 尽量直接提取原生文字、坐标和原图，避免无意义 OCR。
- 对扫描 PDF 支持 OCR / 结构化文档解析。
- 将不同解析引擎的结果统一映射到内部 Document IR。
- 能恢复标题、段落、图片、图片说明、页眉页脚等基本结构。
- GUI 中能同时看到原 PDF 页面与解析后的结构/文本。
- 用户能校正文本和结构，而不必重新处理整本书。
- 翻译以“段落”为稳定单元，但翻译时可带上下文。
- 翻译结果与原段落稳定绑定，支持缓存和增量重翻。
- 生成简洁、高兼容性的 EPUB 3。
- 生成后自动进行 EPUB 合规检查。
- 项目可保存并恢复，处理过程可追踪、可重做。

## 2.2 非目标（第一阶段明确不做）

以下内容容易让项目失控，第一版不要承诺：

- 100% 还原杂志、教材、论文的复杂视觉版式；
- 漫画、复杂古籍、竖排、双向文字的完整支持；
- 极复杂数学公式的完美可编辑重建；
- 所有表格都转换成语义化 HTML 表格；
- 内置一个功能完整的商业级 EPUB Reader；
- 一次性集成所有 OCR/VLM/LLM 供应商；
- 云端账户系统、协作、多用户同步；
- DRM 处理或规避；
- 自动修改原文事实内容。

---

# 3. 设计原则

## 3.1 Local-first

PDF、OCR 结果、编辑结果、图片和项目状态默认保存在本地。只有用户明确启用在线翻译/在线 OCR 时，相应内容才发送给外部 API。

## 3.2 Document IR 是唯一事实来源

所有输入引擎输出统一映射到 Document IR。GUI 不直接绑定 PaddleOCR、MinerU 或 PyMuPDF 的原始结构。

## 3.3 可追踪，不静默修改

任何可能改变文本的步骤都应该能回答：

- 这段文字来自哪一页？
- 原始 bbox 在哪里？
- 是哪个解析器生成的？
- OCR 置信度是多少？
- 是否被 AI 修改过？
- 是否被用户手动修改过？
- 当前译文由哪个 provider/model/prompt 生成？

## 3.4 AI 做语义辅助，不承担不可验证的整书转换

不要让 LLM 直接接收整本 PDF 然后“返回 EPUB”。

程序负责可核验的事实提取；AI 主要帮助：

- 判断两个文本块是否属于同一段；
- 恢复跨页段落；
- 判断标题层级；
- 识别 caption / footnote / body 等语义；
- 翻译；
- 提示疑似错误。

## 3.5 增量、可重做

重新 OCR 第 37 页，不应导致第 1–36 页重新运行；修改第 152 段，不应导致全书重新翻译。

## 3.6 简单 EPUB 优先于炫技 EPUB

EPUB 内容尽量使用朴素 XHTML + CSS，不依赖 JavaScript、hover、复杂双栏或浏览器特性。

---

# 4. PDF 页面类型与自动判断

每页至少归入以下逻辑类别之一：

## 4.1 DIGITAL_NATIVE

特征：

- 存在可用文本对象；
- Unicode 质量合理；
- 文本覆盖页面主要内容；
- 提取结果不是明显乱码。

默认解析：PyMuPDF 原生文本 + 坐标提取。

## 4.2 SCANNED_IMAGE

特征：

- 页面主要为整页位图；
- 几乎无可用文字层；
- 原生提取字符数接近零。

默认解析：OCR / 文档结构解析。

## 4.3 IMAGE_WITH_TEXT_LAYER

特征：

- 有明显整页扫描图；
- 同时存在隐藏或覆盖文字层。

默认策略：比较文字层质量；GUI 允许：

- 使用已有文字层；
- 重新 OCR；
- 强制忽略文字层。

## 4.4 MIXED_OR_SUSPECT

例如：

- 原生文字提取乱码；
- 页面只提取到一小部分文字；
- 图文混排复杂；
- 双栏/三栏阅读顺序异常；
- 某页旋转方向异常。

默认策略：标记为需要检查，并允许切换解析器。

## 4.5 页面分类输出

```python
class PageClassification(BaseModel):
    page_index: int
    kind: Literal[
        "digital_native",
        "scanned_image",
        "image_with_text_layer",
        "mixed_or_suspect",
    ]
    confidence: float
    reasons: list[str]
    recommended_parser: str
```

自动判断只能是建议，用户的手动 override 优先。

---

# 5. 总体处理流水线

```text
[Import PDF]
      ↓
[PDF Analyzer]
      ↓
[Page Classification]
      ↓
┌──────────────┬──────────────┬────────────────┐
│ Native       │ OCR          │ Document/VLM   │
│ PyMuPDF      │ PaddleOCR    │ MinerU / etc.  │
└──────────────┴──────────────┴────────────────┘
      ↓
[Normalize to Document IR]
      ↓
[Reading Order / Paragraph Reconstruction]
      ↓
[Human Review + Optional AI Structure Repair]
      ↓
[Translation Pipeline]
      ↓
[Book Structure / Chapters / TOC]
      ↓
[EPUB XHTML + CSS + Assets]
      ↓
[EPUBCheck]
      ↓
[bilingual.epub]
```

每个阶段都必须能缓存结果，并且支持局部重跑。

---

# 6. Document IR：核心中间模型

Document IR 是整个系统的核心。它应该独立于具体 OCR 引擎、GUI 和 EPUB。

## 6.1 基础实体

建议至少有：

- `BookDocument`
- `Page`
- `Block`
- `ParagraphBlock`
- `HeadingBlock`
- `ImageBlock`
- `CaptionBlock`
- `TableBlock`（可先只保留图片/原始数据）
- `FootnoteBlock`
- `PageHeaderBlock`
- `PageFooterBlock`
- `TranslationRecord`
- `ProcessingProvenance`

## 6.2 建议字段

```json
{
  "schema_version": "1.0",
  "book": {
    "title": "Example Book",
    "source_language": "en",
    "target_language": "zh-CN"
  },
  "pages": [
    {
      "page_index": 11,
      "classification": "digital_native",
      "parser": "pymupdf_native",
      "blocks": [
        {
          "id": "p0011-b0003",
          "type": "paragraph",
          "bbox": [102.5, 220.1, 821.2, 410.3],
          "reading_order": 7,
          "source_text_raw": "Deep learning has become...",
          "source_text_normalized": "Deep learning has become...",
          "confidence": 0.98,
          "style": {
            "font_size": 11.0,
            "bold": false,
            "italic": false
          },
          "translation": {
            "text": "深度学习已经成为……",
            "status": "translated",
            "provider": "example-provider",
            "model": "example-model",
            "prompt_version": "translate-v1"
          },
          "provenance": {
            "source": "pymupdf",
            "user_edited": false,
            "ai_structure_edited": false
          }
        }
      ]
    }
  ]
}
```

## 6.3 原始文本与规范化文本分离

至少保留：

- `source_text_raw`：解析器直接输出；
- `source_text_normalized`：去断行、连字符修复、结构恢复后的文本；
- `source_text_user`：如用户手动修改，可单独记录或通过 revision 记录。

不要覆盖掉 raw 数据。

## 6.4 ID 必须稳定

翻译缓存、编辑历史、EPUB 锚点都依赖稳定 ID。

建议 ID 与“页面 + 原始 block identity”相关，但在合并段落后生成稳定 paragraph ID；不要每次程序启动都随机生成新 ID。

---

# 7. 解析器抽象

GUI 和业务层只能依赖统一接口。

```python
from typing import Protocol

class DocumentParser(Protocol):
    parser_id: str

    def can_parse(self, context: "PageContext") -> bool: ...

    def parse_page(
        self,
        context: "PageContext",
        options: "ParseOptions",
    ) -> "PageParseResult": ...
```

第一阶段实现：

1. `NativePdfParser`
2. `PaddleStructureParser`（后续里程碑）
3. `MinerUParser`（实验/后续）
4. `UnlimitedOcrParser`（实验插件，不作为 MVP 强依赖）

未来新增 Docling 或其他引擎时，不应修改 GUI 主逻辑。

---

# 8. 数字 PDF：NativePdfParser

推荐基于 PyMuPDF。

职责：

- 打开 PDF；
- 获取 page size、rotation；
- 提取 text spans / blocks / words；
- 获取字体大小、粗体/斜体等可用信息；
- 提取 bbox；
- 直接提取内嵌图片资源；
- 生成页面预览图；
- 对乱码/异常提取输出质量指标。

不要仅使用“纯文本输出”；必须保留布局坐标。

## 8.1 原生提取质量检测

可构造启发式指标：

- 字符数；
- Unicode replacement character 数量；
- 控制字符比例；
- 词间空格合理性；
- 页面可见文字区域覆盖程度；
- 单字/单字符 block 过多；
- 文本是否大量重复；
- 页面图像占比。

这些指标用于分类和 warning，而不是绝对判定。

---

# 9. 扫描 PDF 与 OCR

## 9.1 PaddleOCR / PP-StructureV3

定位：第一批正式支持的 OCR/文档解析方案。

原因：它不只是字符识别，还能提供版面、阅读顺序、表格/公式等文档结构能力。

实现时不要让 PaddleOCR 的原始返回结构泄漏到核心层。创建 adapter 映射到 Document IR。

## 9.2 MinerU

定位：值得优先做技术 spike 的结构化 PDF 解析器。

目标不是立刻绑定为唯一方案，而是比较：

- 章节/标题恢复；
- 多栏阅读顺序；
- 页眉页脚处理；
- 图片与 caption；
- 扫描页表现；
- CPU/GPU 环境复杂度。

## 9.3 Unlimited-OCR

定位：实验性 parser plugin。

由于其路线较新、通常更依赖 GPU/VLM 推理环境，MVP 不应以它为必需依赖。只有 adapter 层稳定后再加入。

## 9.4 OCR 必须支持的交互

用户可以：

- 选中一页：重新 OCR；
- 选中范围：统一设置解析器；
- 强制 Native；
- 强制 OCR；
- 使用自动模式；
- 对单个区域重新 OCR（后续版本）；
- 对比不同解析器结果（后续版本）。

---

# 10. 阅读顺序与段落恢复

这是核心难题之一，优先级高于“接更多 OCR 引擎”。

## 10.1 需要处理

- 行 → 段落；
- 跨页段落；
- `tech-` + `niques` 形式的断词；
- 标题与正文区分；
- 多栏阅读顺序；
- 页眉页脚去除；
- 页码去除；
- 图片 caption；
- footnote；
- list；
- chapter break。

## 10.2 先规则、后 AI

优先使用可解释的几何/排版规则：

- y 间距；
- x 对齐；
- 字体大小；
- 缩进；
- 行尾标点；
- 是否以连字符结尾；
- 上一块和下一块字体/style 相似度；
- page column 区域。

对于规则不确定的情况，再调用 AI。

## 10.3 AI 结构修复接口

AI 不应返回任意改写后的整章文本，而应返回结构化操作，例如：

```json
{
  "operations": [
    {"op": "merge", "block_ids": ["b17", "b18"]},
    {"op": "set_type", "block_id": "b19", "type": "heading", "level": 2},
    {"op": "mark_running_header", "block_id": "b20"}
  ]
}
```

每个操作可审计、可撤销。

---

# 11. 图片提取

优先级：

1. 若数字 PDF 内嵌原始 JPEG/PNG 等资源，优先直接提取；
2. 若是扫描页中的局部插图，使用 bbox crop；
3. 复杂矢量图无法可靠转换时，可退化为高分辨率区域渲染。

每张图片至少记录：

- asset id；
- source page；
- bbox；
- extraction method；
- MIME type；
- hash；
- caption block id（如有）。

不要把整个页面作为图片塞进 reflowable EPUB，除非用户明确选择“保留整页图片”。

---

# 12. 翻译系统

## 12.1 翻译单位

持久化单位是 paragraph，但模型调用时应提供上下文。

建议上下文：

```text
章节标题
上一段（context only）
当前段（translate this）
下一段（context only）
术语表
人物/专有名词表
用户风格设置
```

返回结果必须只绑定当前 paragraph ID。

## 12.2 Translator 抽象

```python
class Translator(Protocol):
    provider_id: str

    async def translate(
        self,
        request: TranslationRequest,
    ) -> TranslationResult: ...
```

核心层不得绑定单一模型供应商。

第一版只需要实现 **一个** provider adapter + 一个 fake/mock translator 用于测试。

## 12.3 Translation Memory / Cache

缓存 key 至少包含：

```text
hash(
  normalized_source_text
  + source_language
  + target_language
  + provider
  + model
  + prompt_version
  + glossary_version
)
```

只修改 EPUB 样式时绝不能重新翻译。

## 12.4 翻译状态

```text
untranslated
queued
translating
translated
failed
user_edited
stale
```

如果原文被修改，应把原译文标记为 `stale`，而不是静默保留为“有效”。

## 12.5 API key

- 不写入项目文件；
- 优先通过系统 keychain / 环境变量；
- 日志不得打印完整 key；
- 明确显示哪些文字会被发送到远端。

---

# 13. EPUB 生成

目标是 EPUB 3，优先兼容性和可重排阅读。

## 13.1 推荐 HTML 结构

```html
<section class="chapter" id="chapter-03">
  <h1>Chapter 3</h1>

  <div class="para" id="p-000123">
    <p class="source" lang="en">Original paragraph...</p>
    <p class="translation" lang="zh-CN">对应译文……</p>
  </div>
</section>
```

## 13.2 推荐样式原则

- 不使用 JS；
- 不使用复杂 grid 作为主要阅读布局；
- source/translation 纵向交替；
- 字体由阅读器控制；
- 适度 paragraph spacing；
- 图片 `max-width: 100%`；
- 保留 `lang` 属性；
- heading 建立正确 TOC；
- 每个 paragraph 有稳定 id，方便未来定位。

## 13.3 输出模式

最终可支持：

- Original only；
- Translation only；
- Source → Translation；
- Translation → Source。

MVP 只做 `Source → Translation` 即可。

## 13.4 EPUB 验证

导出后必须调用 EPUBCheck。

GUI 展示：

```text
EPUB validation: PASS
0 errors
2 warnings
```

若存在 error，不应把结果表现为“成功完成”；允许用户仍然保存，但必须明确标记 validation failed。

---

# 14. EPUB 预览

MVP 不需要实现完整 Reader。

流程：

```text
Document IR
   ↓
生成与 EPUB 相同/近似的 XHTML + CSS
   ↓
QWebEngineView / WebView
```

预览重点：

- 章节顺序；
- 原译段落配对；
- 图片位置；
- heading；
- spacing。

后续如果需要真正读取打包后的 EPUB，再评估 epub.js / Readium 等方案。

---

# 15. GUI 规格

建议使用 PySide6，第一版做桌面应用。

## 15.1 主界面

三栏布局：

```text
┌──────────────┬────────────────────────┬────────────────────────┐
│ Pages        │ PDF Page               │ Parsed Document        │
│              │                        │                        │
│ 1 Native ✓   │ 原始页面               │ Heading                │
│ 2 Native ✓   │ bbox overlay           │ Paragraph              │
│ 3 OCR    ✓   │                        │ Paragraph              │
│ 4 Suspect ⚠  │ 点击 block 高亮        │ Image                  │
│ ...          │                        │ Caption                │
└──────────────┴────────────────────────┴────────────────────────┘

Bottom / Tabs:
[Structure] [Translation] [EPUB Preview] [Logs]
```

## 15.2 Page List

每页显示：

- 页号；
- 自动类型；
- 当前 parser；
- 状态；
- warning；
- 是否用户 override。

状态颜色仅作为辅助，不应是唯一信息表达方式。

## 15.3 PDF Page View

需要：

- zoom；
- page navigation；
- overlay bbox；
- 点击 bbox 与右侧 block 联动；
- 可开关 block type label；
- OCR/解析后刷新 overlay。

## 15.4 Parsed Document View

至少能：

- 编辑 block text；
- 修改 block type；
- 合并相邻段落；
- 拆分段落；
- 删除“页眉/页脚/噪声”；
- 调整 heading level；
- 查看 provenance；
- undo/redo（MVP 可以先做有限命令栈）。

## 15.5 Translation View

显示：

```text
Original paragraph
[editable translation]
Status / provider / model
[Translate] [Retry] [Mark approved]
```

支持多选段落批量翻译。

## 15.6 EPUB Preview

显示最终双语排版；提供：

- chapter navigation；
- basic font size preview setting；
- re-generate preview；
- export EPUB；
- validation result。

---

# 16. 项目持久化格式

建议每本书创建一个 project directory：

```text
MyBook.bepub-project/
├── project.json
├── document.json
├── source/
│   └── original.pdf        # 可配置为 copy 或 reference
├── assets/
│   ├── images/
│   └── page_previews/
├── cache/
│   ├── parse/
│   └── translation/
├── exports/
│   └── MyBook-bilingual.epub
└── logs/
```

MVP 使用版本化 JSON 便于调试；数据量明显变大后可将 translation cache / job index 迁移到 SQLite。

所有 JSON 写入采用 atomic replace，避免应用崩溃时损坏项目。

---

# 17. 任务状态与后台工作

OCR、PDF render、翻译不能阻塞 GUI 主线程。

建议统一 Job 模型：

```python
class Job(BaseModel):
    id: str
    kind: Literal["render", "parse", "ocr", "translate", "export"]
    status: Literal["queued", "running", "success", "failed", "cancelled"]
    progress_current: int
    progress_total: int | None
    message: str | None
```

第一版可使用 `QThreadPool` / worker pattern；不要过早引入分布式任务队列。

需要支持 cancel，尤其是批量 OCR/翻译。

---

# 18. 推荐技术栈

## 18.1 基础

- Python：建议以 Python 3.12 为第一兼容基线，确认所有 OCR/GUI 依赖后再升级；
- Packaging / env：`uv`；
- GUI：PySide6；
- PDF：PyMuPDF；
- 数据模型：Pydantic；
- 测试：pytest；
- lint/format：Ruff；
- type checking：mypy 或 pyright（二选一即可）；
- logging：标准 `logging` 或 structlog（MVP 标准 logging 即可）。

## 18.2 文档解析

- Native：PyMuPDF；
- OCR/Structure：PaddleOCR PP-StructureV3；
- Spike：MinerU；
- Experimental：Unlimited-OCR；
- Reference/optional：Docling。

## 18.3 EPUB

先做一个技术 spike：

- 评估 EbookLib 是否满足最小 EPUB 3 输出；
- 若库抽象妨碍控制，则实现非常薄的内部 EPUB packager；
- 无论选择哪种，最终都必须经过 EPUBCheck。

不要在架构中让 EbookLib 类型泄漏到 domain layer。

## 18.4 翻译

- provider-neutral adapter；
- 第一个 adapter 可以使用 OpenAI-compatible HTTP API 或用户选定 provider；
- 测试必须有 `FakeTranslator`，CI 不调用真实收费 API。

---

# 19. 推荐仓库结构

```text
bilingual-epub-studio/
├── AGENTS.md
├── PROJECT_SPEC.md
├── README.md
├── pyproject.toml
├── uv.lock
├── src/
│   └── bilingual_epub_studio/
│       ├── app.py
│       ├── domain/
│       │   ├── document.py
│       │   ├── project.py
│       │   ├── jobs.py
│       │   └── enums.py
│       ├── pdf/
│       │   ├── analyzer.py
│       │   ├── renderer.py
│       │   └── native_parser.py
│       ├── parsers/
│       │   ├── base.py
│       │   ├── registry.py
│       │   ├── paddle_adapter.py
│       │   ├── mineru_adapter.py
│       │   └── unlimited_ocr_adapter.py
│       ├── structure/
│       │   ├── reading_order.py
│       │   ├── paragraph_merge.py
│       │   ├── header_footer.py
│       │   └── ai_repair.py
│       ├── translation/
│       │   ├── base.py
│       │   ├── service.py
│       │   ├── cache.py
│       │   ├── prompts.py
│       │   └── providers/
│       ├── epub/
│       │   ├── builder.py
│       │   ├── xhtml.py
│       │   ├── css.py
│       │   └── validator.py
│       ├── persistence/
│       │   ├── project_store.py
│       │   └── migrations.py
│       ├── gui/
│       │   ├── main_window.py
│       │   ├── models/
│       │   ├── widgets/
│       │   ├── dialogs/
│       │   └── workers/
│       └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/
│   └── golden/
├── scripts/
│   ├── make_fixture.py
│   └── validate_epub.py
└── docs/
    ├── architecture.md
    ├── document-ir.md
    └── decisions/
```

原则：domain 层绝不 import PySide6；GUI 可以依赖 application/domain service，但核心解析逻辑必须可在命令行测试。

---

# 20. 建议的关键接口

## 20.1 PDF Analyzer

```python
class PdfAnalyzer:
    def inspect_document(self, path: Path) -> PdfInspection: ...
    def inspect_page(self, page_index: int) -> PageClassification: ...
```

## 20.2 Parse Service

```python
class ParseService:
    def parse_page(self, page_index: int, parser_id: str) -> PageParseResult: ...
    def parse_range(self, pages: list[int], parser_id: str) -> list[PageParseResult]: ...
```

## 20.3 Structure Service

```python
class StructureService:
    def normalize_page(self, result: PageParseResult) -> list[Block]: ...
    def reconstruct_document(self, pages: list[Page]) -> BookDocument: ...
```

## 20.4 Translation Service

```python
class TranslationService:
    async def translate_paragraph(self, paragraph_id: str) -> TranslationResult: ...
    async def translate_selection(self, paragraph_ids: list[str]) -> BatchResult: ...
```

## 20.5 EPUB Service

```python
class EpubService:
    def build(self, document: BookDocument, options: EpubOptions, output: Path) -> Path: ...
    def validate(self, epub_path: Path) -> ValidationReport: ...
```

---

# 21. 日志、provenance 与可重现性

每次 parse 记录：

- parser id；
- parser version；
- model version（如适用）；
- options；
- page index；
- elapsed time；
- warning/error；
- source file hash。

每次 translation 记录：

- provider；
- model；
- prompt version；
- glossary version；
- paragraph hash；
- token/usage metadata（如果 provider 返回）；
- 时间；
- error。

GUI 日志默认对普通用户友好，同时提供“复制诊断信息”。

---

# 22. 测试策略

这个项目不能只测“代码有没有报错”，必须测文档质量。

## 22.1 Fixture corpus

仓库维护小型、可合法分发的测试 PDF：

1. 单栏数字 PDF；
2. 双栏数字 PDF；
3. 扫描页；
4. 扫描 + hidden text layer；
5. 中间有图片和 caption；
6. 跨页段落；
7. 带页眉页脚；
8. 带 hyphenation；
9. 有旋转页；
10. 提取乱码或异常字体的小样本。

避免把受版权保护的完整商业电子书放进公开 repo。

## 22.2 Golden tests

对固定 fixture 保存期望的结构摘要：

```json
{
  "headings": ["Chapter 1"],
  "paragraph_count": 14,
  "image_count": 1,
  "first_paragraph": "...",
  "last_paragraph": "..."
}
```

不要要求 OCR 输出每个 bbox 浮点坐标完全一致；对不稳定字段使用容差。

## 22.3 内容完整性检查

对于数字 PDF，可以构造：

- normalized extracted text 与 EPUB source text 的字符/词覆盖率；
- 是否出现大段缺失；
- 是否异常重复；
- heading count 变化；
- paragraph count 极端变化。

出现明显内容缺失时 export 应显示 warning。

## 22.4 EPUB tests

每个生成的 test EPUB：

- EPUBCheck pass；
- ZIP/MIME 结构正确；
- manifest/spine/toc 完整；
- XHTML parse 正常；
- 所有图片引用存在；
- paragraph IDs 唯一；
- source/translation 对应关系稳定。

## 22.5 GUI tests

MVP 重点做业务层测试，GUI 只做关键 smoke tests：

- 打开 PDF；
- 切换 page；
- parser override；
- 编辑 paragraph；
- export。

---

# 23. 性能与缓存

## 23.1 页面渲染缓存

根据：

```text
source_pdf_hash + page + dpi + rotation
```

缓存预览。

## 23.2 Parse cache

根据：

```text
source_pdf_hash + page + parser_id + parser_version + options_hash
```

缓存。

## 23.3 Translation cache

见第 12 节。

## 23.4 UI 性能

- 不预先渲染整本 1000 页 PDF 的所有高分辨率页面；
- 当前页附近预取；
- 页面缩略图低分辨率；
- OCR/AI 在 worker 执行；
- 大批量任务显示进度和 cancel。

---

# 24. 错误处理

错误必须分层，不要统一弹“转换失败”。

示例：

```text
SourceOpenError
PageRenderError
NativeTextExtractionError
ParserUnavailableError
OcrRuntimeError
TranslationProviderError
TranslationRateLimitError
EpubBuildError
EpubValidationError
ProjectPersistenceError
```

用户消息示例：

> 第 47 页 PaddleOCR 处理失败。原 PDF 未受影响。你可以重试、切换 Native/MinerU，或暂时跳过这一页。

这比“任务失败：Exception”更有用。

---

# 25. 隐私与安全

- 默认本地处理；
- 在线 provider 首次使用前提示“所选文本会发送到第三方服务”；
- API key 不进入 `project.json`；
- crash log 不记录完整书籍正文；
- diagnostic bundle 默认只含版本、配置和错误堆栈，不含正文；
- 外部命令路径和参数要正确转义；
- 不执行 PDF 内嵌脚本；
- 将 PDF 视为不可信输入；
- 解压/打包 EPUB 时防止 path traversal；
- 对超大页面/超大图片设置合理资源限制。

---

# 26. 配置

用户级配置与项目级配置分开。

## 用户级

- 默认目标语言；
- 默认翻译 provider；
- API key reference；
- 默认 parser；
- OCR 设备（CPU/GPU）；
- cache size；
- UI settings。

## 项目级

- source/target language；
- page overrides；
- glossary；
- EPUB metadata；
- export style；
- parser options。

---

# 27. 里程碑规划

不要从“所有功能”同时开始。

## M0：仓库与基础设施

完成：

- Python/PySide6 repo scaffold；
- `AGENTS.md`；
- Ruff + pytest + type checker；
- Pydantic Document IR；
- project save/load；
- fixture corpus；
- CLI debug entry point。

**Done when：** `pytest` 可运行，能创建一个空 project 并 round-trip 保存 Document IR。

## M1：数字 PDF → 单语 EPUB

完成：

- PyMuPDF import；
- page analyzer；
- page render；
- native block extraction；
- 初版 reading order；
- paragraph merge；
- heading heuristic；
- image extraction；
- basic GUI；
- XHTML preview；
- EPUB export；
- EPUBCheck。

**Done when：** 给定一份普通英文数字 PDF，用户能从 GUI 打开、查看解析结果、修正少量段落并导出一个可验证的 reflowable EPUB。

## M2：数字 PDF → 双语 EPUB

完成：

- Translator interface；
- FakeTranslator；
- 一个真实 provider；
- translation context；
- cache；
- batch translation；
- translated/stale/failed 状态；
- bilingual preview；
- bilingual EPUB export。

**Done when：** 同一份数字 PDF 可得到原文+译文逐段交替的 EPUB，重复导出不会重复调用已缓存翻译。

## M3：扫描/混合 PDF

完成：

- page classification；
- per-page parser override；
- PaddleOCR/PP-Structure adapter；
- OCR bbox overlay；
- mixed document handling；
- OCR result cache；
- parser failure fallback。

**Done when：** 一本包含数字页和扫描页的 PDF 可逐页选择策略并最终进入同一 Document IR。

## M4：结构编辑工作台

完成：

- merge/split；
- type change；
- heading level；
- running header/footer；
- local region reparse；
- undo/redo；
- provenance inspector；
- warning center。

## M5：多解析器与高级能力

再评估：

- MinerU adapter；
- Unlimited-OCR；
- Docling；
- table semantics；
- equations；
- footnote links；
- epub.js/Readium；
- packaging/installers；
- macOS/Windows GPU packaging。

---

# 28. 首轮技术 Spike（在写大量 GUI 前完成）

Codex 应先做以下小实验并记录结论：

## Spike A：PyMuPDF

对 3–5 个 fixture 输出：

- blocks；
- words；
- spans；
- images；
- bbox overlay preview。

回答：哪种 extraction representation 最适合 Document IR？

## Spike B：EPUB

从硬编码的 3 段中英文本 + 1 张图片生成 EPUB，EPUBCheck 必须通过。

回答：EbookLib 是否足够，还是自定义薄 packager 更清晰？

## Spike C：PySide6 preview

显示：

- 左侧页面列表；
- 中间 PDF page image；
- 右侧 block list；
- 点击 block 高亮 bbox。

回答：交互性能是否足够？

## Spike D：PaddleOCR / MinerU（M3 前）

只在少量扫描/复杂页面对比，不要一开始把两者都做成生产代码。

M3 implementation note (2026-08-16): the empirical target-device spike is limited to
PaddleOCR/PP-StructureV3. MinerU is desk research only and remains an M5 candidate; installing its
dependencies or downloading its models requires a separate explicit approval. This is the minimum
scope correction needed to honor the M3 local-environment constraint without adding a second
production parser.

---

# 29. 产品验收标准

第一阶段不要用“已经实现 PDF 转 EPUB”作为验收语句，而要用可测试行为。

## M1 验收

- 可以打开至少 100 页的普通数字 PDF；
- 页面切换时 UI 不冻结；
- 原生文字块在 PDF 页中有可视 bbox；
- block 与右侧文本可互相定位；
- 用户可以编辑一个段落；
- 用户可以合并/拆分至少基础段落；
- 图片被正常放进导出的 EPUB；
- EPUBCheck 无 error；
- 关闭项目后重新打开，用户编辑仍存在；
- 重新导出不会重新解析未变化页面。

## M2 验收

- 可设置源语言/目标语言；
- 可选择一组段落翻译；
- API 失败时不丢失项目；
- 已翻译段落第二次运行命中 cache；
- 修改原文后对应译文进入 stale；
- EPUB 为逐段原文→译文；
- EPUBCheck 无 error。

## M3 验收

- 页面自动标注 Native / OCR / Suspect；
- 用户可对页范围 override；
- 扫描页 OCR 后生成可编辑 block；
- 原生页不被强制 OCR；
- mixed PDF 最终输出为统一文档。

---

# 30. 需要避免的架构错误

开发代理必须避免：

1. **直接 PDF → LLM → EPUB。**
2. **把 EPUB 当数据库。**
3. **GUI 直接调用 PaddleOCR 并解析其返回结构。**
4. **一个 `convert_pdf()` 巨型函数完成所有事情。**
5. **OCR 结果直接覆盖 raw 数据。**
6. **每次导出都重新翻译。**
7. **解析器升级导致所有 paragraph id 变化。**
8. **为了“未来可能需要”过早上微服务、Redis、Celery、Electron + Python daemon。**
9. **第一版同时实现 4 个 OCR/VLM engine。**
10. **只用人工肉眼验证，不建立 fixture/golden tests。**
11. **只以“EPUB 能打开”为成功标准，不跑 EPUBCheck。**
12. **把 API key 写进项目或 git。**

---

# 31. 决策记录（ADR）建议

`docs/decisions/` 中维护简短 ADR：

- ADR-001：为什么 EPUB 不是中间格式；
- ADR-002：Document IR 设计；
- ADR-003：为什么使用 PySide6；
- ADR-004：EPUB builder 选择；
- ADR-005：translation cache key；
- ADR-006：第一 OCR engine；
- ADR-007：project persistence JSON → SQLite 的触发条件。

每个 ADR 记录 context / decision / consequences。

---

# 32. 推荐的 Codex 工作方式

对于这个项目，**第一次进入仓库时使用 Plan mode，而不是直接让 Codex 开始写完整项目。**

推荐节奏：

```text
PROJECT_SPEC.md
      ↓
Codex Plan mode
      ↓
只规划 M0 + M1
      ↓
你审阅计划
      ↓
正常 Codex 执行模式实现
      ↓
测试 / 运行 / 手动体验
      ↓
Codex /review
      ↓
修复
      ↓
再进入 Plan mode 规划 M2
```

不要让 Codex 第一次任务就是：

> “按照文档把整个软件做完。”

更好的任务粒度是一个可验证 milestone。

对于复杂 milestone，可以维护一个 `.agent/PLANS.md` / ExecPlan 约定，把计划当成 living document。

---

# 33. Codex 推理强度建议

- **High**：仓库 bootstrap、Document IR、parser abstraction、reading order、EPUB 架构、复杂 bug；
- **Medium**：普通 UI、简单 adapter、常规 tests、样式调整；
- **Extra High**：难以复现的解析错误、复杂跨页结构、设计重大重构时再使用；
- **Low**：机械性、范围非常清晰的小改动。

不要一直最高档；更重要的是给明确目标、上下文、约束和 Done when。

---

# 34. ChatGPT Work 与 Codex 的分工

推荐：

## ChatGPT Work

更适合：

- 继续完善产品需求；
- 阅读测试报告；
- 比较 OCR 输出样例；
- 编写架构/设计文档；
- 根据截图给 GUI 反馈；
- 整理 release notes / user guide；
- 做研究型工作。

## Codex

更适合：

- 直接打开本地 repo；
- 改代码；
- 跑 pytest / Ruff / type checker；
- 安装/验证依赖；
- 调试 PySide6；
- 跑 PDF fixtures；
- 生成/验证 EPUB；
- review diff。

因此，本项目进入本地开发后以 **Codex 为主，Work 为产品/研究/文档协作者**。

---

# 35. 第一条交给 Codex 的指令

将本文件保存为 repo 根目录 `PROJECT_SPEC.md`，同时加入 `AGENTS.md`，然后在 Codex **Plan mode** 中发送：

```text
Read AGENTS.md and PROJECT_SPEC.md completely.

This is a new local project. Do not try to implement the entire product.
For this turn, stay in planning mode and focus only on M0 and M1.

First inspect the repository and local development environment. Then produce a concrete implementation plan that:

1. establishes the Python/PySide6 project and test/tooling baseline;
2. defines the versioned Document IR;
3. implements project save/load;
4. creates a small legal fixture corpus or fixture-generation utilities;
5. performs the PyMuPDF extraction spike;
6. performs the minimal EPUB + EPUBCheck spike;
7. implements the first vertical slice: digital PDF -> parsed blocks -> editable preview -> valid monolingual EPUB;
8. keeps GUI, domain model, parsers, and EPUB code separated as required by the spec;
9. includes explicit tests and “done when” checks for each step;
10. calls out any dependency or packaging risk before implementation.

Prefer the smallest architecture that satisfies PROJECT_SPEC.md. Do not add OCR, MinerU, Unlimited-OCR, full translation, cloud services, or a full EPUB reader in M0/M1.

If you find a design conflict in PROJECT_SPEC.md, explain it in the plan and propose the smallest correction. Do not silently reinterpret the spec.

End with the exact commands you expect to use to verify M0/M1 (tests, lint/type checks, app smoke run, and EPUB validation).
```

计划经过审阅后，再让 Codex 开始实现。

---

# 36. 建议的 `AGENTS.md`

仓库根目录可使用：

```markdown
# Repository instructions

## Mission
Build the local-first PDF-to-bilingual-EPUB desktop application described in PROJECT_SPEC.md.
Treat PROJECT_SPEC.md as the product and architecture source of truth.

## Scope discipline
Work milestone by milestone. Do not implement future milestones unless the user explicitly asks.
Prefer a working vertical slice over speculative abstractions.

## Architecture rules
- EPUB is an output format, never the internal source of truth.
- The versioned Document IR is the source of truth.
- Domain/core modules must not depend on PySide6.
- GUI must not depend on raw OCR/parser response formats.
- Every parser is behind an adapter/interface and normalizes into Document IR.
- Preserve raw extraction data and provenance.
- Never silently rewrite source book content with an LLM.
- Translation is paragraph-addressable, cached, and invalidated when source text changes.

## Quality
Before declaring a task complete:
- run pytest;
- run Ruff;
- run the configured type checker;
- for EPUB work, run EPUBCheck on a generated fixture;
- for GUI work, perform the documented smoke test;
- report what was verified and what was not.

## Tests
Add or update tests with every behavior change.
Prefer small legal fixtures and generated PDFs over copyrighted full books.
Use fake providers in automated tests; do not call paid AI APIs from CI.

## Dependencies
Add a new dependency only when it materially reduces complexity.
Record important architectural choices in docs/decisions/.
Do not add services such as Redis, Celery, or a web backend unless a demonstrated requirement justifies them.

## Safety / privacy
Treat PDFs as untrusted input.
Never commit API keys or user book content.
Do not include book text in diagnostic logs by default.

## Git
Keep changes reviewable and scoped to the active milestone. Do not push or publish anything unless the user explicitly asks.
```

---

# 37. 开发时需要持续回答的开放问题

这些问题不应阻止 M0/M1，但要通过 spike/真实样本逐步决定：

1. PyMuPDF 的 `blocks`、`words`、`dict/rawdict` 哪一层最适合构建 IR？
2. paragraph ID 如何在“重新解析”与“用户编辑”之间保持尽量稳定？
3. 数字 PDF 的 reading order 规则能覆盖多少常见书籍？
4. 双栏版面何时应升级到结构模型而不是继续加 heuristic？
5. EPUB builder 用 EbookLib 还是内部 packager？
6. 微信读书对具体 EPUB CSS/metadata 的兼容边界如何建立回归样本？
7. PaddleOCR 在目标 Windows/macOS 设备上的打包成本如何？
8. GPU parser 是否作为可选扩展包而非主安装包？
9. 图片 caption 与正文之间的 association 如何建模？
10. footnote 是 MVP 后的语义链接，还是先降级成普通段落？
11. 用户编辑后重新 OCR 时，如何提示潜在冲突并避免覆盖人工修改？
12. 大书（500–1500 页）的内存和 project size 如何控制？

---

# 38. 参考技术与官方资料（截至 2026-08-16）

实现时应重新检查当前版本和兼容性，不要把本文档中的依赖建议理解为永久版本锁定。

- PyMuPDF documentation: https://pymupdf.readthedocs.io/
- PaddleOCR / PP-StructureV3: https://paddlepaddle.github.io/PaddleOCR/
- MinerU: https://github.com/opendatalab/MinerU
- Unlimited-OCR: https://github.com/baidu/Unlimited-OCR
- Docling: https://docling-project.github.io/docling/
- EPUB 3.3: https://www.w3.org/TR/epub-33/
- EPUBCheck: https://github.com/w3c/epubcheck
- Readium: https://readium.org/
- epub.js: https://github.com/futurepress/epub.js/
- OpenAI Codex best practices: https://learn.chatgpt.com/guides/best-practices
- OpenAI Codex CLI docs: https://learn.chatgpt.com/docs/codex/cli
- OpenAI ExecPlans / PLANS.md guide: https://developers.openai.com/cookbook/articles/codex_exec_plans

---

# 39. 最终产品判断标准

这个项目成功，不是因为：

> “它可以把一个 PDF 文件变成一个 `.epub` 文件。”

而是因为：

> 用户可以看到软件如何理解每一页，必要时纠正它；软件能把不同来源的页面恢复成结构化书籍；翻译与原文稳定对应；最终生成的双语 EPUB 在手机上真正比原 PDF 更适合阅读，而且任何异常都可以追踪、局部重做和验证。

这应该始终作为产品和工程决策的最高优先级。
