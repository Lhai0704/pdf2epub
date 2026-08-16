from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from pdf2epub.domain.errors import (
    TranslationConfigurationError,
    TranslationProviderError,
)
from pdf2epub.domain.models import TranslationUsage
from pdf2epub.translation.base import TranslationRequest, TranslationResult

LONGCAT_ENDPOINT = "https://api.longcat.chat/openai/v1/chat/completions"


class _Message(BaseModel):
    model_config = ConfigDict(extra="ignore")
    content: str | None = None


class _Choice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message: _Message
    finish_reason: str | None = None


class _Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str | None = None
    model: str
    choices: list[_Choice]
    usage: _Usage | None = None


def _default_key_resolver() -> str | None:
    return os.getenv("LONGCAT_API_KEY")


def _context_message(request: TranslationRequest) -> str:
    glossary = "\n".join(f"{entry.source} => {entry.target}" for entry in request.glossary)
    return "\n".join(
        (
            f"SOURCE_LANGUAGE: {request.source_language}",
            f"TARGET_LANGUAGE: {request.target_language}",
            "CHAPTER_HEADING:",
            request.chapter_heading or "",
            "PREVIOUS_CONTEXT:",
            request.previous_paragraph or "",
            "CURRENT_TRANSLATE_ONLY:",
            request.source_text,
            "NEXT_CONTEXT:",
            request.next_paragraph or "",
            "GLOSSARY:",
            glossary,
            "STYLE:",
            request.style_instructions or "",
        )
    )


class LongCatProvider:
    provider_id = "longcat"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        key_resolver: Callable[[], str | None] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_retries: int = 2,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10, read=120, write=30, pool=10)
        )
        self.key_resolver = key_resolver or _default_key_resolver
        self.sleep = sleep
        self.max_retries = max_retries

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        key = (self.key_resolver() or "").strip()
        if not key:
            raise TranslationConfigurationError("LONGCAT_API_KEY is not set")
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Translate only CURRENT_TRANSLATE_ONLY into the target language. "
                        "Use the other fields only as context. Return only the translation, "
                        "without explanations or labels. Do not alter facts."
                    ),
                },
                {"role": "user", "content": _context_message(request)},
            ],
            "stream": False,
            "max_tokens": 4096,
            "temperature": 0.2,
            "thinking": {"type": "disabled"},
        }
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.post(LONGCAT_ENDPOINT, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                if attempt < self.max_retries:
                    await self.sleep(min(2**attempt, 8))
                    continue
                raise TranslationProviderError(
                    "LongCat request failed after retries", code="network_error"
                ) from exc

            if response.status_code in {401, 403}:
                raise TranslationProviderError(
                    "LongCat rejected the API credentials",
                    code="authentication_error",
                    fatal=True,
                )
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < self.max_retries:
                    await self.sleep(self._retry_delay(response, attempt))
                    continue
                code = "rate_limit" if response.status_code == 429 else "server_error"
                raise TranslationProviderError(
                    f"LongCat {code.replace('_', ' ')} after retries", code=code
                )
            if response.status_code >= 400:
                raise TranslationProviderError(
                    f"LongCat rejected the request with HTTP {response.status_code}",
                    code="request_rejected",
                    fatal=True,
                )

            try:
                parsed = _Response.model_validate(response.json())
                choice = parsed.choices[0]
            except (ValueError, IndexError, ValidationError) as exc:
                raise TranslationProviderError(
                    "LongCat returned an invalid response", code="invalid_response"
                ) from exc
            if choice.finish_reason != "stop":
                raise TranslationProviderError(
                    "LongCat did not return a complete translation", code="incomplete_response"
                )
            text = (choice.message.content or "").strip()
            if not text:
                raise TranslationProviderError(
                    "LongCat returned an empty translation", code="empty_response"
                )
            usage = (
                TranslationUsage(
                    prompt_tokens=parsed.usage.prompt_tokens,
                    completion_tokens=parsed.usage.completion_tokens,
                    total_tokens=parsed.usage.total_tokens,
                )
                if parsed.usage is not None
                else None
            )
            return TranslationResult(
                text=text,
                provider_id=self.provider_id,
                model=parsed.model,
                request_id=parsed.id or response.headers.get("x-request-id"),
                usage=usage,
            )
        raise AssertionError("retry loop exhausted unexpectedly")

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0), 30)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    return min(max((retry_at - datetime.now(UTC)).total_seconds(), 0), 30)
                except (TypeError, ValueError, OverflowError):
                    pass
        return float(min(2**attempt, 8))
