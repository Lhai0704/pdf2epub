from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from pydantic import ValidationError

from pdf2epub.domain.errors import ProjectPersistenceError
from pdf2epub.domain.models import (
    BookDocument,
    BookMetadata,
    LoadedProject,
    ProjectManifest,
    ProjectSource,
    SourceDocument,
)

MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(payload)
            if not payload.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ProjectPersistenceError(f"Could not atomically save {path.name}: {exc}") from exc


def _resolve_project_path(root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ProjectPersistenceError("Project-relative path escapes the project directory")
    root_resolved = root.resolve()
    candidate = root.joinpath(*relative.parts).resolve()
    if root_resolved != candidate and root_resolved not in candidate.parents:
        raise ProjectPersistenceError("Project-relative path escapes the project directory")
    return candidate


class ProjectStore:
    def create(self, root: Path, source_pdf: Path, *, title: str | None = None) -> LoadedProject:
        root = root.resolve()
        source_pdf = source_pdf.resolve()
        if root.suffix != ".bepub-project":
            raise ProjectPersistenceError("Project directory must end in .bepub-project")
        if not source_pdf.is_file():
            raise ProjectPersistenceError(f"Source PDF does not exist: {source_pdf}")
        if source_pdf.stat().st_size > MAX_SOURCE_BYTES:
            raise ProjectPersistenceError("Source PDF exceeds the M1 2 GiB safety limit")
        if root.exists() and any(root.iterdir()):
            raise ProjectPersistenceError(f"Project directory is not empty: {root}")

        source_hash = sha256_file(source_pdf)
        source_size = source_pdf.stat().st_size
        now = datetime.now(UTC)
        manifest = ProjectManifest(
            project_id=f"project-{uuid.uuid4()}",
            source=ProjectSource(
                original_name=source_pdf.name,
                sha256=source_hash,
                size_bytes=source_size,
            ),
            created_at=now,
            updated_at=now,
        )
        document = BookDocument(
            document_id=f"doc-{source_hash[:20]}",
            metadata=BookMetadata(title=title or source_pdf.stem),
            source=SourceDocument(
                original_name=source_pdf.name,
                sha256=source_hash,
                size_bytes=source_size,
            ),
            created_at=now,
            updated_at=now,
        )

        try:
            for relative in (
                "source",
                "assets/images",
                "assets/page_previews",
                "cache/parse",
                "exports",
                "logs",
            ):
                root.joinpath(*PurePosixPath(relative).parts).mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_pdf, _resolve_project_path(root, manifest.source.relative_path))
            self._save_models(root, manifest, document)
        except (OSError, ProjectPersistenceError) as exc:
            raise ProjectPersistenceError(f"Could not create project: {exc}") from exc

        return LoadedProject(root=str(root), manifest=manifest, document=document)

    def load(self, root: Path) -> LoadedProject:
        root = root.resolve()
        try:
            manifest_path = root / "project.json"
            manifest = ProjectManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            document_path = _resolve_project_path(root, manifest.document_path)
            document = BookDocument.model_validate_json(document_path.read_text(encoding="utf-8"))
            source_path = _resolve_project_path(root, manifest.source.relative_path)
            source_changed = (
                not source_path.is_file() or sha256_file(source_path) != manifest.source.sha256
            )
        except (OSError, ValidationError, ValueError, ProjectPersistenceError) as exc:
            raise ProjectPersistenceError(f"Could not load project {root}: {exc}") from exc

        if source_changed:
            pages = [
                page.model_copy(update={"parse_status": "stale"})
                if page.parse_status == "parsed"
                else page
                for page in document.pages
            ]
            document = document.model_copy(update={"pages": pages})
        return LoadedProject(
            root=str(root),
            manifest=manifest,
            document=document,
            source_changed=source_changed,
        )

    def save(self, project: LoadedProject) -> LoadedProject:
        root = Path(project.root).resolve()
        now = datetime.now(UTC)
        manifest = project.manifest.model_copy(update={"updated_at": now})
        document = project.document.model_copy(update={"updated_at": now})
        self._save_models(root, manifest, document)
        return project.model_copy(update={"manifest": manifest, "document": document})

    @staticmethod
    def source_path(project: LoadedProject) -> Path:
        return _resolve_project_path(Path(project.root), project.manifest.source.relative_path)

    def _save_models(self, root: Path, manifest: ProjectManifest, document: BookDocument) -> None:
        document_path = _resolve_project_path(root, manifest.document_path)
        atomic_write_json(
            document_path, document.model_dump_json(indent=2, exclude_computed_fields=True)
        )
        atomic_write_json(root / "project.json", manifest.model_dump_json(indent=2))
