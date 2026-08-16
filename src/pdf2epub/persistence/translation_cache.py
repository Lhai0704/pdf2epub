from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pdf2epub.domain.errors import TranslationCacheError
from pdf2epub.persistence.project_store import atomic_write_json
from pdf2epub.translation.base import CachedTranslation


class TranslationCacheIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default="1.0", pattern=r"^1\.0$")
    entries: dict[str, CachedTranslation] = Field(default_factory=dict)


class JsonTranslationCache:
    def __init__(self, project_root: Path) -> None:
        self.path = project_root / "cache" / "translation" / "index.json"
        self._index = self._load()

    def _load(self) -> TranslationCacheIndex:
        if not self.path.exists():
            return TranslationCacheIndex()
        try:
            return TranslationCacheIndex.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as exc:
            raise TranslationCacheError(
                "Translation cache is unreadable; the project document was not changed"
            ) from exc

    def get(self, key: str) -> CachedTranslation | None:
        return self._index.entries.get(key)

    def put(self, key: str, value: CachedTranslation) -> None:
        entries = dict(self._index.entries)
        entries[key] = value
        updated = self._index.model_copy(update={"entries": entries})
        try:
            atomic_write_json(self.path, updated.model_dump_json(indent=2))
        except Exception as exc:
            raise TranslationCacheError("Could not save the translation cache") from exc
        self._index = updated
