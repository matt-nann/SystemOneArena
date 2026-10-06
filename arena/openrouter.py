"""OpenRouter client: the two calls the arena makes.

* ``decide`` — OpenRouter's Decisions endpoint (alpha), for Jev. Mirrors
  Aven's ``packages/llm/decisions.py`` (httpx, Bearer key, attribution headers).
* ``chat_structured`` — chat completions with a strict JSON schema and
  ``provider.require_parameters``, for Sol. Mirrors the OpenRouter structured
  path in Aven's ``packages/llm/service.py`` (openai SDK pointed at OpenRouter).

Both go through one ``httpx.AsyncClient``. Pass a ``transport`` to swap the
network out: ``mock_openrouter.transport()`` answers every request in-process.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

import httpx
import openai

from .config import Settings


class OpenRouterError(Exception):
    """A refused, failed or malformed call. ``status`` is the HTTP status (0 = no response)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"openrouter {status}: {message}" if status else f"openrouter: {message}")
        self.status = status
        self.message = message


class OpenRouterClient:
    def __init__(self, settings: Settings, transport: Optional[httpx.AsyncBaseTransport] = None) -> None:
        if not settings.OPENROUTER_API_KEY and transport is None:
            raise OpenRouterError(0, "OPENROUTER_API_KEY is not set")
        self.settings = settings
        self.api_key = settings.OPENROUTER_API_KEY or "mock"
        self.headers = {"HTTP-Referer": settings.OPENROUTER_APP_URL, "X-Title": settings.OPENROUTER_APP_NAME}
        self.http = httpx.AsyncClient(transport=transport, headers=self.headers)
        self.openai = openai.AsyncOpenAI(
            api_key=self.api_key,
            base_url=settings.OPENROUTER_BASE_URL,
            http_client=self.http,
            default_headers=self.headers,
            # A retry would hide the real latency and failure rate, which is what the arena measures.
            max_retries=0,
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def decide(self, body: Dict[str, Any], *, timeout: float) -> Dict[str, Any]:
        """POST a Decisions request; returns the parsed JSON response."""
        try:
            # asyncio deadline as well as httpx's: an in-process transport enforces no timeouts itself.
            async with asyncio.timeout(timeout):
                resp = await self.http.post(
                    self.settings.OPENROUTER_DECISIONS_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=timeout,
                )
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise OpenRouterError(0, "timed out") from exc
        except httpx.HTTPError as exc:
            raise OpenRouterError(0, f"unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise OpenRouterError(resp.status_code, _error_message(resp))
        try:
            return resp.json()
        except ValueError as exc:
            raise OpenRouterError(resp.status_code, "response was not JSON") from exc

    async def chat_structured(self, *, model: str, messages: list, schema: Dict[str, Any], max_tokens: int,
                              reasoning_effort: str = "", timeout: float) -> Dict[str, Any]:
        """One chat completion constrained to ``schema``; returns {output, model, usage}."""
        extra_body: Dict[str, Any] = {"provider": {"require_parameters": True}}
        if reasoning_effort:
            extra_body["reasoning"] = {"effort": reasoning_effort}
        try:
            async with asyncio.timeout(timeout):
                resp = await self.openai.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    response_format={"type": "json_schema", "json_schema": {"name": "move", "strict": True, "schema": schema}},
                    extra_body=extra_body,
                    timeout=timeout,
                )
        except (openai.APITimeoutError, TimeoutError) as exc:
            raise OpenRouterError(0, "timed out") from exc
        except openai.APIStatusError as exc:
            raise OpenRouterError(exc.status_code, _sdk_error_message(exc)) from exc
        except openai.APIConnectionError as exc:
            raise OpenRouterError(0, f"unreachable: {type(exc).__name__}") from exc
        if not resp.choices:
            raise OpenRouterError(200, "chat response had no choices")
        choice = resp.choices[0]
        if choice.finish_reason == "length":
            raise OpenRouterError(200, "answer was cut off at max_tokens")
        try:
            output = json.loads(choice.message.content or "")
        except ValueError as exc:
            raise OpenRouterError(200, "answer was not valid JSON") from exc
        return {"output": output, "model": resp.model, "usage": resp.usage.model_dump() if resp.usage else {}}


def _error_message(resp: httpx.Response) -> str:
    try:
        err = resp.json().get("error") or {}
        return str(err.get("message") or resp.reason_phrase)
    except ValueError:
        return resp.reason_phrase or "error"


def _sdk_error_message(exc: openai.APIStatusError) -> str:
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error", body) if isinstance(body, dict) else {}
    return str((err or {}).get("message") or exc.message)
