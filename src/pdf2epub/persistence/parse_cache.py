from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pdf2epub.domain.errors import OcrCacheError
from pdf2epub.domain.models import Asset, Page

OCR_CACHE_SCHEMA = "paddle-parse-cache-v1"
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024


class OcrCacheKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_sha256: str
    page_index: int
    render_version: str
    dpi: int
    rotation: int
    parser_id: str
    parser_version: str
    package_versions: dict[str, str]
    model_names: dict[str, str]
    model_hashes: dict[str, str]
    language: str
    device: str
    precision: str
    engine: str
    options: dict[str, str | int | float | bool | None]
    normalization_schema: str

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OcrCacheRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = OCR_CACHE_SCHEMA
    key: OcrCacheKey
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_data: dict[str, Any]
    page: Page
    assets: list[Asset]
    checksum: str = ""

    def with_checksum(self) -> OcrCacheRecord:
        return self.model_copy(update={"checksum": _record_checksum(self)})


def _record_checksum(record: OcrCacheRecord) -> str:
    payload = record.model_dump(mode="json", exclude={"checksum"})
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


class OcrParseCache:
    def __init__(self, project_root: Path) -> None:
        self.directory = project_root / "cache" / "parse" / "paddle_ppstructure_v3"

    def path_for(self, key: OcrCacheKey) -> Path:
        return self.directory / f"{key.fingerprint}.json.gz"

    def load(self, key: OcrCacheKey) -> OcrCacheRecord | None:
        path = self.path_for(key)
        if not path.is_file():
            return None
        try:
            with gzip.open(path, "rb") as handle:
                raw = handle.read(MAX_UNCOMPRESSED_BYTES + 1)
            if len(raw) > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("uncompressed cache exceeds 64 MiB")
            record = OcrCacheRecord.model_validate_json(raw)
            if record.schema_version != OCR_CACHE_SCHEMA:
                raise ValueError("unsupported OCR cache schema")
            if record.key != key:
                raise ValueError("OCR cache key mismatch")
            if record.checksum != _record_checksum(record):
                raise ValueError("OCR cache checksum mismatch")
            return record
        except (OSError, ValueError, ValidationError, json.JSONDecodeError):
            self._preserve_corrupt(path)
            return None

    def store(self, record: OcrCacheRecord) -> Path:
        checked = record.with_checksum()
        raw = checked.model_dump_json(exclude_none=False).encode("utf-8")
        if len(raw) > MAX_UNCOMPRESSED_BYTES:
            raise OcrCacheError("OCR cache record exceeds the 64 MiB safety limit")
        path = self.path_for(checked.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                with gzip.GzipFile(fileobj=handle, mode="wb", mtime=0) as compressed:
                    compressed.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except OSError as exc:
            raise OcrCacheError(f"Could not write OCR cache: {type(exc).__name__}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return path

    @staticmethod
    def _preserve_corrupt(path: Path) -> None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        destination = path.with_name(f"{path.name}.corrupt-{timestamp}")
        with suppress(OSError):
            os.replace(path, destination)
