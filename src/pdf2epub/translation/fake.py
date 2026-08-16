from __future__ import annotations

import asyncio

from pdf2epub.domain.errors import TranslationProviderError
from pdf2epub.translation.base import TranslationRequest, TranslationResult


class FakeTranslator:
    provider_id = "fake"

    def __init__(
        self,
        *,
        failures: set[str] | None = None,
        delay_seconds: float = 0,
        prefix: str = "译文:",
    ) -> None:
        self.failures = failures or set()
        self.delay_seconds = delay_seconds
        self.prefix = prefix
        self.requests: list[TranslationRequest] = []

    @property
    def call_count(self) -> int:
        return len(self.requests)

    async def translate(self, request: TranslationRequest) -> TranslationResult:
        self.requests.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if request.paragraph_id in self.failures:
            raise TranslationProviderError("Simulated translation failure", code="fake_failure")
        return TranslationResult(
            text=f"{self.prefix}{request.source_text}",
            provider_id=self.provider_id,
            model=request.model,
            request_id=f"fake-{self.call_count}",
        )
