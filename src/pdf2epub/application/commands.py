from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pdf2epub.application.editing import DocumentEditor
from pdf2epub.domain.errors import ProjectPersistenceError, TranslationConflictError
from pdf2epub.domain.models import (
    Asset,
    BBox,
    BookDocument,
    CaptionBlock,
    EditAuditEvent,
    ImageBlock,
    LoadedProject,
    Page,
    ParagraphBlock,
    ProjectWarning,
)
from pdf2epub.persistence.project_store import ProjectStore

CommandKind = Literal["edit_block", "merge_blocks", "split_block", "region_replace"]


@dataclass(frozen=True, slots=True)
class TranslationConflict:
    count: int
    block_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommandEntry:
    command_id: str
    kind: CommandKind
    page_index: int
    before_page: Page
    after_page: Page
    before_assets: dict[str, Asset]
    after_assets: dict[str, Asset]
    before_warnings: tuple[ProjectWarning, ...]
    after_warnings: tuple[ProjectWarning, ...]
    translation_disposition: Literal["none", "preserved", "staled", "removed"]
    region: BBox | None = None


@dataclass(frozen=True, slots=True)
class CommandResult:
    project: LoadedProject
    command_id: str
    selected_block_id: str | None
    translation_disposition: str


class SessionCommandStack:
    def __init__(self, *, limit: int = 100) -> None:
        if limit < 1:
            raise ValueError("Command stack limit must be positive")
        self.limit = limit
        self._undo: deque[CommandEntry] = deque(maxlen=limit)
        self._redo: list[CommandEntry] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, entry: CommandEntry) -> None:
        self._undo.append(entry)
        self._redo.clear()

    def peek_undo(self) -> CommandEntry:
        if not self._undo:
            raise ValueError("Nothing to undo")
        return self._undo[-1]

    def commit_undo(self) -> CommandEntry:
        entry = self._undo.pop()
        self._redo.append(entry)
        return entry

    def peek_redo(self) -> CommandEntry:
        if not self._redo:
            raise ValueError("Nothing to redo")
        return self._redo[-1]

    def commit_redo(self) -> CommandEntry:
        entry = self._redo.pop()
        self._undo.append(entry)
        return entry

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()


class StructureCommandService:
    """Atomic structure commands with session-only inverse snapshots and persistent audit."""

    def __init__(
        self,
        *,
        store: ProjectStore | None = None,
        editor: DocumentEditor | None = None,
        stack: SessionCommandStack | None = None,
    ) -> None:
        self.store = store or ProjectStore()
        self.editor = editor or DocumentEditor()
        self.stack = stack or SessionCommandStack()

    def translation_conflict(
        self, document: BookDocument, page_index: int, block_ids: list[str]
    ) -> TranslationConflict:
        page = self._page(document, page_index)
        affected = tuple(
            block.id
            for block in page.blocks
            if block.id in block_ids
            and isinstance(block, ParagraphBlock)
            and block.translation is not None
        )
        return TranslationConflict(len(affected), affected)

    def execute_edit(
        self,
        project: LoadedProject,
        page_index: int,
        block_id: str,
        *,
        text: str,
        block_type: str,
        heading_level: int = 1,
        confirm_translation_loss: bool = False,
    ) -> CommandResult:
        before_page = self._page(project.document, page_index)
        block = next((item for item in before_page.blocks if item.id == block_id), None)
        if block is None or isinstance(block, ImageBlock):
            raise KeyError(f"Editable block not found: {block_id}")
        if isinstance(block, CaptionBlock):
            if block_type != "caption":
                raise ValueError("Captions cannot be converted to another structure type")
        elif block_type not in {"paragraph", "heading", "page_header", "page_footer"}:
            raise ValueError(f"Unsupported structure type: {block_type}")
        destructive = (
            isinstance(block, ParagraphBlock)
            and block.translation is not None
            and block_type != "paragraph"
        )
        if destructive and not confirm_translation_loss:
            raise TranslationConflictError(
                "Changing this paragraph type would detach 1 translation; confirmation required"
            )
        command_id = f"cmd-{uuid.uuid4()}"
        candidate = self.editor.edit_text(
            project.document,
            page_index,
            block_id,
            text,
            operation_id=command_id,
        )
        if not isinstance(block, CaptionBlock):
            candidate = self.editor.change_type(
                candidate,
                page_index,
                block_id,
                block_type,
                heading_level,
                operation_id=command_id,
            )
        return self._commit(
            project,
            candidate,
            command_id=command_id,
            kind="edit_block",
            page_index=page_index,
            selected_block_id=block_id,
        )

    def execute_merge(
        self,
        project: LoadedProject,
        page_index: int,
        first_block_id: str,
        *,
        confirm_translation_loss: bool = False,
    ) -> CommandResult:
        page = self._page(project.document, page_index)
        index = next((i for i, block in enumerate(page.blocks) if block.id == first_block_id), -1)
        affected = (
            [page.blocks[index].id, page.blocks[index + 1].id]
            if 0 <= index < len(page.blocks) - 1
            else [first_block_id]
        )
        conflict = self.translation_conflict(project.document, page_index, affected)
        if conflict.count and not confirm_translation_loss:
            raise TranslationConflictError(
                f"Merging would detach {conflict.count} translation(s); confirmation required"
            )
        command_id = f"cmd-{uuid.uuid4()}"
        candidate = self.editor.merge_adjacent(
            project.document,
            page_index,
            first_block_id,
            operation_id=command_id,
        )
        before_ids = {block.id for block in page.blocks}
        selected = next(
            block.id
            for block in self._page(candidate, page_index).blocks
            if block.id not in before_ids
        )
        return self._commit(
            project,
            candidate,
            command_id=command_id,
            kind="merge_blocks",
            page_index=page_index,
            selected_block_id=selected,
        )

    def execute_split(
        self,
        project: LoadedProject,
        page_index: int,
        block_id: str,
        offset: int,
        *,
        confirm_translation_loss: bool = False,
    ) -> CommandResult:
        conflict = self.translation_conflict(project.document, page_index, [block_id])
        if conflict.count and not confirm_translation_loss:
            raise TranslationConflictError(
                "Splitting would detach 1 translation; confirmation required"
            )
        command_id = f"cmd-{uuid.uuid4()}"
        candidate = self.editor.split_block(
            project.document,
            page_index,
            block_id,
            offset,
            operation_id=command_id,
        )
        before_ids = {block.id for block in self._page(project.document, page_index).blocks}
        selected = next(
            block.id
            for block in self._page(candidate, page_index).blocks
            if block.id not in before_ids
        )
        return self._commit(
            project,
            candidate,
            command_id=command_id,
            kind="split_block",
            page_index=page_index,
            selected_block_id=selected,
        )

    def commit_region_candidate(
        self,
        project: LoadedProject,
        candidate: BookDocument,
        *,
        page_index: int,
        command_id: str,
        region: BBox,
        selected_block_id: str | None,
        confirm_translation_loss: bool = False,
    ) -> CommandResult:
        before_ids = {block.id for block in self._page(project.document, page_index).blocks}
        after_ids = {block.id for block in self._page(candidate, page_index).blocks}
        removed = list(before_ids - after_ids)
        conflict = self.translation_conflict(project.document, page_index, removed)
        if conflict.count and not confirm_translation_loss:
            raise TranslationConflictError(
                f"Region replacement would detach {conflict.count} translation(s); "
                "confirmation required"
            )
        return self._commit(
            project,
            candidate,
            command_id=command_id,
            kind="region_replace",
            page_index=page_index,
            region=region,
            selected_block_id=selected_block_id,
        )

    def undo(self, project: LoadedProject) -> CommandResult:
        entry = self.stack.peek_undo()
        current_page = self._page(project.document, entry.page_index)
        if current_page != entry.after_page:
            raise ValueError("Document changed since this command; undo stack was invalidated")
        document = self._restore(
            project.document,
            entry.before_page,
            entry.before_assets,
            list(entry.before_warnings),
        )
        document = self._append_audit(document, entry, "undo")
        saved = self.store.save(project.model_copy(update={"document": document}))
        self.stack.commit_undo()
        return CommandResult(
            saved,
            entry.command_id,
            entry.before_page.blocks[0].id if entry.before_page.blocks else None,
            entry.translation_disposition,
        )

    def redo(self, project: LoadedProject) -> CommandResult:
        entry = self.stack.peek_redo()
        current_page = self._page(project.document, entry.page_index)
        if current_page != entry.before_page:
            raise ValueError("Document changed since undo; redo stack was invalidated")
        document = self._restore(
            project.document,
            entry.after_page,
            entry.after_assets,
            list(entry.after_warnings),
        )
        document = self._append_audit(document, entry, "redo")
        saved = self.store.save(project.model_copy(update={"document": document}))
        self.stack.commit_redo()
        return CommandResult(
            saved,
            entry.command_id,
            entry.after_page.blocks[0].id if entry.after_page.blocks else None,
            entry.translation_disposition,
        )

    def clear(self) -> None:
        self.stack.clear()

    def _commit(
        self,
        project: LoadedProject,
        candidate: BookDocument,
        *,
        command_id: str,
        kind: CommandKind,
        page_index: int,
        selected_block_id: str | None,
        region: BBox | None = None,
    ) -> CommandResult:
        before_page = self._page(project.document, page_index)
        candidate = self._resolve_dangling_warnings(candidate)
        after_page = self._page(candidate, page_index)
        disposition = self._translation_disposition(before_page, after_page)
        entry = CommandEntry(
            command_id=command_id,
            kind=kind,
            page_index=page_index,
            before_page=before_page,
            after_page=after_page,
            before_assets=project.document.assets.copy(),
            after_assets=candidate.assets.copy(),
            before_warnings=tuple(project.document.warnings),
            after_warnings=tuple(candidate.warnings),
            translation_disposition=disposition,
            region=region,
        )
        candidate = self._append_audit(candidate, entry, "execute")
        try:
            saved = self.store.save(project.model_copy(update={"document": candidate}))
        except ProjectPersistenceError:
            raise
        self.stack.push(entry)
        return CommandResult(saved, command_id, selected_block_id, disposition)

    @staticmethod
    def _append_audit(
        document: BookDocument, entry: CommandEntry, action: Literal["execute", "undo", "redo"]
    ) -> BookDocument:
        before_ids = [block.id for block in entry.before_page.blocks]
        after_ids = [block.id for block in entry.after_page.blocks]
        if action == "undo":
            before_ids, after_ids = after_ids, before_ids
        event = EditAuditEvent(
            event_id=f"event-{uuid.uuid4()}",
            command_id=entry.command_id,
            action=action,
            kind=entry.kind,
            page_index=entry.page_index,
            region=entry.region,
            before_block_ids=before_ids,
            after_block_ids=after_ids,
            translation_disposition=entry.translation_disposition,
        )
        return document.model_copy(
            update={
                "edit_audit": [*document.edit_audit, event],
                "updated_at": datetime.now(UTC),
            }
        )

    @staticmethod
    def _restore(
        document: BookDocument,
        page: Page,
        assets: dict[str, Asset],
        warnings: list[ProjectWarning],
    ) -> BookDocument:
        pages = [page if item.page_index == page.page_index else item for item in document.pages]
        return document.model_copy(update={"pages": pages, "assets": assets, "warnings": warnings})

    @staticmethod
    def _resolve_dangling_warnings(document: BookDocument) -> BookDocument:
        block_ids = {block.id for page in document.pages for block in page.blocks}
        now = datetime.now(UTC)
        warnings = [
            warning.model_copy(update={"resolved_at": now, "block_id": None})
            if warning.active and warning.block_id is not None and warning.block_id not in block_ids
            else warning
            for warning in document.warnings
        ]
        return document.model_copy(update={"warnings": warnings})

    @staticmethod
    def _translation_disposition(
        before: Page, after: Page
    ) -> Literal["none", "preserved", "staled", "removed"]:
        before_records = {
            block.id: block.translation
            for block in before.blocks
            if isinstance(block, ParagraphBlock) and block.translation is not None
        }
        after_records = {
            block.id: block.translation
            for block in after.blocks
            if isinstance(block, ParagraphBlock) and block.translation is not None
        }
        if not before_records:
            return "none"
        if set(before_records) - set(after_records):
            return "removed"
        if any(
            record is not None and record.status == "stale" for record in after_records.values()
        ):
            return "staled"
        return "preserved"

    @staticmethod
    def _page(document: BookDocument, page_index: int) -> Page:
        try:
            return next(page for page in document.pages if page.page_index == page_index)
        except StopIteration as exc:
            raise KeyError(f"Page not found: {page_index}") from exc
