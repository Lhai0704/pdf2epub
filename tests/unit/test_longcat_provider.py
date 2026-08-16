from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from pdf2epub.domain.errors import TranslationConfigurationError, TranslationProviderError
from pdf2epub.domain.models import TranslationSettings
from pdf2epub.translation.base import TranslationRequest
from pdf2epub.translation.providers.longcat import LONGCAT_ENDPOINT, LongCatProvider


def _request() -> TranslationRequest:
    settings = TranslationSettings()
    return TranslationRequest(
        paragraph_id="p1",
        source_text="Hello",
        source_language="en",
        target_language="zh-CN",
        provider_id="longcat",
        model="LongCat-2.0",
        prompt_version="translate-v1",
        glossary_version=settings.glossary_version,
    )


def test_longcat_request_and_response_are_normalized() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "request-1",
                "model": "LongCat-2.0",
                "choices": [
                    {
                        "message": {
                            "content": "你好",
                            "reasoning_content": "must not persist",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = LongCatProvider(client=client, key_resolver=lambda: "secret")
    result = asyncio.run(provider.translate(_request()))
    asyncio.run(client.aclose())
    assert seen["url"] == LONGCAT_ENDPOINT
    assert seen["authorization"] == "Bearer secret"
    payload = seen["payload"]
    assert isinstance(payload, dict) and payload["stream"] is False
    assert payload["thinking"] == {"type": "disabled"}
    assert result.text == "你好"
    assert result.request_id == "request-1"
    assert "must not persist" not in result.model_dump_json()


def test_longcat_missing_key_and_auth_error_are_fatal() -> None:
    missing = LongCatProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200))),
        key_resolver=lambda: None,
    )
    with pytest.raises(TranslationConfigurationError):
        asyncio.run(missing.translate(_request()))
    asyncio.run(missing.client.aclose())

    auth = LongCatProvider(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(401, text="do not log body"))
        ),
        key_resolver=lambda: "secret",
    )
    with pytest.raises(TranslationProviderError) as caught:
        asyncio.run(auth.translate(_request()))
    asyncio.run(auth.client.aclose())
    assert caught.value.fatal
    assert "secret" not in str(caught.value)
    assert "do not log body" not in str(caught.value)


def test_longcat_retries_rate_limit_and_rejects_incomplete_result() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "model": "LongCat-2.0",
                "choices": [{"message": {"content": "partial"}, "finish_reason": "length"}],
            },
        )

    provider = LongCatProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        key_resolver=lambda: "secret",
        sleep=lambda _: asyncio.sleep(0),
    )
    with pytest.raises(TranslationProviderError, match="complete"):
        asyncio.run(provider.translate(_request()))
    asyncio.run(provider.client.aclose())
    assert calls == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": True},
        {
            "model": "LongCat-2.0",
            "choices": [{"message": {"content": ""}, "finish_reason": "stop"}],
        },
    ],
)
def test_longcat_rejects_invalid_or_empty_responses(payload: dict[str, object]) -> None:
    provider = LongCatProvider(
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
        key_resolver=lambda: "secret",
    )
    with pytest.raises(TranslationProviderError):
        asyncio.run(provider.translate(_request()))
    asyncio.run(provider.client.aclose())


def test_longcat_retries_connect_timeout() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("timeout", request=request)
        return httpx.Response(
            200,
            json={
                "model": "LongCat-2.0",
                "choices": [{"message": {"content": "你好"}, "finish_reason": "stop"}],
            },
        )

    provider = LongCatProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        key_resolver=lambda: "secret",
        sleep=lambda _: asyncio.sleep(0),
    )
    assert asyncio.run(provider.translate(_request())).text == "你好"
    asyncio.run(provider.client.aclose())
    assert calls == 2


def test_longcat_retry_after_accepts_http_date() -> None:
    response = httpx.Response(
        429,
        headers={"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"},
        request=httpx.Request("POST", LONGCAT_ENDPOINT),
    )
    assert LongCatProvider._retry_delay(response, 0) == 30
