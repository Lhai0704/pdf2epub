from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from pdf2epub.domain.errors import EpubValidationError


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    passed: bool
    fatals: int = Field(ge=0)
    errors: int = Field(ge=0)
    warnings: int = Field(ge=0)
    output: str
    exit_code: int


class EpubValidator:
    _SUMMARY = re.compile(
        r"Messages:\s*(\d+)\s+fatals?\s*/\s*(\d+)\s+errors?\s*/\s*(\d+)\s+warnings?",
        re.IGNORECASE,
    )

    def __init__(self, jar_path: Path | None = None) -> None:
        configured = jar_path or (Path(value) if (value := os.getenv("EPUBCHECK_JAR")) else None)
        self.jar_path = configured

    def validate(self, epub_path: Path, *, timeout_seconds: int = 120) -> ValidationReport:
        if self.jar_path is None or not self.jar_path.is_file():
            raise EpubValidationError(
                "EPUBCheck is unavailable; set EPUBCHECK_JAR or pass --epubcheck-jar"
            )
        if not epub_path.is_file():
            raise EpubValidationError(f"EPUB does not exist: {epub_path}")
        try:
            completed = subprocess.run(
                ["java", "-jar", str(self.jar_path), str(epub_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EpubValidationError(f"EPUBCheck could not run: {exc}") from exc
        output = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        summary = self._SUMMARY.search(output)
        if summary:
            fatals, errors, warnings = (int(value) for value in summary.groups())
        else:
            fatals = len(re.findall(r"\bFATAL\b", output))
            errors = len(re.findall(r"\bERROR\b", output))
            warnings = len(re.findall(r"\bWARNING\b", output))
        return ValidationReport(
            passed=completed.returncode == 0 and fatals == 0 and errors == 0,
            fatals=fatals,
            errors=errors,
            warnings=warnings,
            output=output,
            exit_code=completed.returncode,
        )
