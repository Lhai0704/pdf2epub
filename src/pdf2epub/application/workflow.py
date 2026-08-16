from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from pdf2epub.application.parsing import BatchParseSummary, ParseProgress, reparse_conflict
from pdf2epub.domain.errors import (
    OcrError,
    ParserUnavailableError,
    ProjectPersistenceError,
    ReparseConflictError,
)
from pdf2epub.domain.models import LoadedProject, Page, PageParseError, ParserOverride
from pdf2epub.parsers.base import DocumentParser, OcrParseOptions, PageContext, ParseOptions
from pdf2epub.parsers.native_pdf import NativePdfParser
from pdf2epub.parsers.registry import (
    NATIVE_PARSER_ID,
    OCR_PARSER_ID,
    ParserRegistry,
    ParserRouter,
)
from pdf2epub.pdf.analyzer import PdfAnalyzer
from pdf2epub.pdf.renderer import PdfRenderer
from pdf2epub.persistence.project_store import ProjectStore

ProgressCallback = Callable[[int, int], None]
StageProgressCallback = Callable[[ParseProgress], None]
CancelCallback = Callable[[], bool]


class BookWorkflow:
    def __init__(
        self,
        *,
        store: ProjectStore | None = None,
        analyzer: PdfAnalyzer | None = None,
        parser: DocumentParser | None = None,
        renderer: PdfRenderer | None = None,
        registry: ParserRegistry | None = None,
    ) -> None:
        self.store = store or ProjectStore()
        self.analyzer = analyzer or PdfAnalyzer()
        self.renderer = renderer or PdfRenderer()
        self.registry = registry or ParserRegistry()
        if registry is None:
            native = parser or NativePdfParser()

            def native_factory() -> DocumentParser:
                return native

            self.registry.register(native.parser_id, native_factory)

            def paddle_factory() -> DocumentParser:
                from pdf2epub.parsers.paddle_structure import PaddleStructureParser

                return PaddleStructureParser(renderer=self.renderer)

            self.registry.register(OCR_PARSER_ID, paddle_factory)
            self.parser = native
        else:
            self.parser = parser or self.registry.get(NATIVE_PARSER_ID)
        self.router = ParserRouter(self.registry)

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
                classification=item.classification,
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

    def analyze_project(self, project: LoadedProject) -> LoadedProject:
        inspection = self.analyzer.inspect_document(self.store.source_path(project))
        inspected = {page.page_index: page for page in inspection.pages}
        pages = [
            page.model_copy(
                update={
                    "width": inspected[page.page_index].width,
                    "height": inspected[page.page_index].height,
                    "rotation": inspected[page.page_index].rotation,
                    "quality": inspected[page.page_index].quality,
                    "classification": inspected[page.page_index].classification,
                }
            )
            for page in project.document.pages
        ]
        document = project.document.model_copy(update={"pages": pages})
        return self.store.save(project.model_copy(update={"document": document}))

    def set_page_override(
        self,
        project: LoadedProject,
        page_indexes: Iterable[int],
        override: ParserOverride,
    ) -> LoadedProject:
        selected = set(page_indexes)
        known = {page.page_index for page in project.document.pages}
        missing = selected - known
        if missing:
            raise KeyError(f"Pages not found: {sorted(missing)}")
        pages: list[Page] = []
        for page in project.document.pages:
            if page.page_index not in selected:
                pages.append(page)
                continue
            candidate = page.model_copy(update={"parser_override": override})
            target = ParserRouter.parser_id_for_page(candidate)
            status = page.parse_status
            if page.blocks and page.parser_id != target:
                status = "stale"
            pages.append(candidate.model_copy(update={"parse_status": status, "parse_error": None}))
        document = project.document.model_copy(update={"pages": pages})
        return self.store.save(project.model_copy(update={"document": document}))

    def parse_page(
        self,
        project: LoadedProject,
        page_index: int,
        *,
        options: ParseOptions | None = None,
        reparse: bool = False,
        confirm_conflicts: bool = False,
    ) -> tuple[LoadedProject, bool]:
        existing = self._page(project, page_index)
        conflict = reparse_conflict(existing)
        if reparse and conflict.has_conflicts and not confirm_conflicts:
            raise ReparseConflictError(
                "Reparse requires confirmation: "
                f"{conflict.user_edited_blocks} edited blocks, "
                f"{conflict.derived_blocks} merged/split blocks, "
                f"{conflict.translations} translations"
            )
        parser = self.router.parser_for_page(existing)
        if options is None:
            options = OcrParseOptions() if parser.parser_id == OCR_PARSER_ID else ParseOptions()
        elif parser.parser_id == OCR_PARSER_ID and not isinstance(options, OcrParseOptions):
            options = OcrParseOptions(**options.model_dump())
        elif parser.parser_id != OCR_PARSER_ID and isinstance(options, OcrParseOptions):
            options = ParseOptions(
                include_images=options.include_images,
                max_page_pixels=options.max_page_pixels,
            )
        if reparse and isinstance(options, OcrParseOptions):
            options = options.model_copy(update={"bypass_cache": True})

        context = PageContext(
            source_path=self.store.source_path(project),
            project_root=Path(project.root),
            source_sha256=project.document.source.sha256,
            page_index=page_index,
            language=project.document.metadata.language,
        )
        fingerprint, _ = parser.fingerprint(context, options)
        if (
            not reparse
            and existing.parse_status == "parsed"
            and existing.parse_fingerprint == fingerprint
            and existing.parser_id == parser.parser_id
        ):
            return project, True

        result = parser.parse_page(context, options)
        replacement = result.page.model_copy(
            update={
                "parser_override": existing.parser_override,
                "classification": existing.classification or result.page.classification,
                "quality": existing.quality or result.page.quality,
                "parse_error": None,
            }
        )
        pages = [
            replacement if page.page_index == page_index else page
            for page in project.document.pages
        ]
        assets = project.document.assets.copy()
        assets.update({asset.id: asset for asset in result.assets})
        document = project.document.model_copy(update={"pages": pages, "assets": assets})
        saved = self.store.save(project.model_copy(update={"document": document}))
        return saved, result.cache_hit

    def parse_pages(
        self,
        project: LoadedProject,
        page_indexes: Iterable[int],
        *,
        options: ParseOptions | None = None,
        progress: StageProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
        reparse: bool = False,
        confirm_conflicts: bool = False,
    ) -> tuple[LoadedProject, BatchParseSummary]:
        indexes = tuple(dict.fromkeys(page_indexes))
        parsed_count = 0
        cache_hits = 0
        failed: list[int] = []
        was_cancelled = False
        total = len(indexes)
        for current, page_index in enumerate(indexes, start=1):
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            self._emit(progress, current, total, page_index, "classify")
            self._emit(progress, current, total, page_index, "render")
            self._emit(progress, current, total, page_index, "parse")
            try:
                project, cache_hit = self.parse_page(
                    project,
                    page_index,
                    options=options,
                    reparse=reparse,
                    confirm_conflicts=confirm_conflicts,
                )
            except ReparseConflictError:
                raise
            except Exception as exc:
                project = self._record_parse_failure(project, page_index, exc)
                failed.append(page_index)
                if isinstance(exc, (ProjectPersistenceError, ParserUnavailableError)) or (
                    isinstance(exc, OcrError) and exc.fatal
                ):
                    break
            else:
                cache_hits += int(cache_hit)
                parsed_count += int(not cache_hit)
                self._emit(progress, current, total, page_index, "normalize")
            self._emit(progress, current, total, page_index, "save")
        return project, BatchParseSummary(
            parsed_count=parsed_count,
            cache_hits=cache_hits,
            failed_pages=tuple(failed),
            cancelled=was_cancelled,
        )

    def parse_all(
        self,
        project: LoadedProject,
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancelCallback | None = None,
    ) -> tuple[LoadedProject, int]:
        def stage(event: ParseProgress) -> None:
            if progress is not None and event.stage == "save":
                progress(event.current, event.total)

        project, summary = self.parse_pages(
            project,
            (page.page_index for page in project.document.pages),
            progress=stage,
            cancelled=cancelled,
        )
        return project, summary.parsed_count

    def render_page(self, project: LoadedProject, page_index: int, *, dpi: int = 120) -> Path:
        return self.renderer.render_page(
            self.store.source_path(project),
            project.document.source.sha256,
            page_index,
            Path(project.root) / "assets" / "page_previews",
            dpi=dpi,
        )

    def _record_parse_failure(
        self, project: LoadedProject, page_index: int, exc: Exception
    ) -> LoadedProject:
        page = self._page(project, page_index)
        error = PageParseError(
            code=str(getattr(exc, "code", type(exc).__name__)),
            message=str(exc),
            fatal=bool(getattr(exc, "fatal", False)),
        )
        replacement = page.model_copy(
            update={
                "parse_status": "stale" if page.blocks else "failed",
                "parse_error": error,
            }
        )
        pages = [
            replacement if candidate.page_index == page_index else candidate
            for candidate in project.document.pages
        ]
        document = project.document.model_copy(update={"pages": pages})
        return self.store.save(project.model_copy(update={"document": document}))

    @staticmethod
    def _page(project: LoadedProject, page_index: int) -> Page:
        try:
            return next(page for page in project.document.pages if page.page_index == page_index)
        except StopIteration as exc:
            raise KeyError(f"Page not found: {page_index}") from exc

    @staticmethod
    def _emit(
        callback: StageProgressCallback | None,
        current: int,
        total: int,
        page_index: int,
        stage: str,
    ) -> None:
        if callback is not None:
            callback(ParseProgress(current, total, page_index, stage))
