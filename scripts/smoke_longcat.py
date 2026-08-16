from __future__ import annotations

import argparse
import asyncio
import json

from pdf2epub.domain.models import TranslationSettings
from pdf2epub.translation.base import TranslationRequest
from pdf2epub.translation.providers.longcat import LongCatProvider


async def _run(source_language: str, target_language: str) -> dict[str, object]:
    settings = TranslationSettings(target_language=target_language)
    request = TranslationRequest(
        paragraph_id="synthetic-smoke",
        source_text="This synthetic sentence is used to verify the translation connection.",
        source_language=source_language,
        target_language=target_language,
        provider_id=settings.provider_id,
        model=settings.model,
        prompt_version=settings.prompt_version,
        glossary_version=settings.glossary_version,
    )
    provider = LongCatProvider()
    try:
        result = await provider.translate(request)
    finally:
        await provider.aclose()
    return {
        "provider": result.provider_id,
        "model": result.model,
        "request_id": result.request_id,
        "usage": result.usage.model_dump() if result.usage else None,
        "translation": result.text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional paid LongCat connectivity smoke")
    parser.add_argument("--confirm-network", action="store_true")
    parser.add_argument("--source-language", default="en")
    parser.add_argument("--target-language", default="zh-CN")
    arguments = parser.parse_args()
    if not arguments.confirm_network:
        raise SystemExit("Refusing network call without --confirm-network")
    print(
        json.dumps(
            asyncio.run(_run(arguments.source_language, arguments.target_language)),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
