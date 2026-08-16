from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pdf2epub.domain.models import LoadedProject, Page
from pdf2epub.parsers.base import PageContext, ParseOptions
from pdf2epub.parsers.native_pdf import NativePdfParser
from pdf2epub.pdf.analyzer import PdfAnalyzer
from pdf2epub.pdf.renderer import PdfRenderer
from pdf2epub.persistence.project_store import ProjectStore

ProgressCallback = Callable[[int, int], None]
CancelCallback = Callable[[], bool]


class BookWorkflow:
    def __init__(
        self,
        *,
        store: ProjectStore | None = None,
        analyzer: PdfAnalyzer | None = None,
        parser: NativePdfParser | None = None,
        renderer: PdfRenderer | None = None,
    ) -> None:
        self.store = store or ProjectStore()
        self.analyzer = analyzer or PdfAnalyzer()
        self.parser = parser or NativePdfParser()
        self.renderer = renderer or PdfRenderer()

    def create_project(
        self, project_root: Path, source_pdf: Path, *, title: str | None = None
    ) -> LoadedProject:
        project = self.store.create(project_root, source_pdf, title=title)
        source_path = self.store.source_path(project)
        inspection = self.analyzer.inspect_document(source_path)
        pages = [
            Page(
                page_index=item.page_index,
                width=item.width,
                height=item.height,
                rotation=item.rotation,
                quality=item.quality,
            )
            for item in inspection.pages
        ]
        metadata = project.document.metadata
        if inspection.title and title is None:
            metadata = metadata.model_copy(update={"title": inspection.title})
        document = project.document.model_copy(update={"pages": pages, "metadata": metadata})
        return self.store.save(project.model_copy(update={"document": document}))

    def load_project(self, project_root: Path) -> LoadedProject:
        return self.store.load(project_root)

    def parse_page(
        self,
        project: LoadedProject,
        page_index: int,
        *,
        options: ParseOptions | None = None,
    ) -> tuple[LoadedProject, bool]:
        options = options or ParseOptions()
        source_path = self.store.source_path(project)
        context = PageContext(
            source_path=source_path,
            project_root=Path(project.root),
            source_sha256=project.document.source.sha256,
            page_index=page_index,
        )
        fingerprint, _ = self.parser.fingerprint(context, options)
        existing = next(page for page in project.document.pages if page.page_index == page_index)
        if existing.parse_status == "parsed" and existing.parse_fingerprint == fingerprint:
            return project, True

        result = self.parser.parse_page(context, options)
        pages = [
            result.page if page.page_index == page_index else page
            for page in project.document.pages
        ]
        assets = project.document.assets.copy()
        assets.update({asset.id: asset for asset in result.assets})
        document = project.document.model_copy(update={"pages": pages, "assets": assets})
        saved = self.store.save(project.model_copy(update={"document": document}))
        return saved, False

    def parse_all(
        self,
        project: LoadedProject,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ) -> tuple[LoadedProject, int]:
        parsed_count = 0
        total = len(project.document.pages)
        for index, page in enumerate(project.document.pages):
            if cancelled is not None and cancelled():
                break
            project, cache_hit = self.parse_page(project, page.page_index)
            if not cache_hit:
                parsed_count += 1
            if progress is not None:
                progress(index + 1, total)
        return project, parsed_count

    def render_page(self, project: LoadedProject, page_index: int, *, dpi: int = 120) -> Path:
        return self.renderer.render_page(
            self.store.source_path(project),
            project.document.source.sha256,
            page_index,
            Path(project.root) / "assets" / "page_previews",
            dpi=dpi,
        )
