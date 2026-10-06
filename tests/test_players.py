"""What each player is sent and how answers come back. HTTP is mocked with respx at OpenRouter's real URLs."""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from arena.engine.game import InvalidMove
from arena.openrouter import OpenRouterClient, OpenRouterError
from arena.players import Players, jev_request, sol_schema

DECISIONS = "https://openrouter.ai/api/alpha/decisions"
CHAT = "https://openrouter.ai/api/v1/chat/completions"


def jev_answer(card, lane):
    return {"model": "typesafe/jev-1.13-20260917", "usage": {"cost": 0.00002},
            "answers": {"card": {"type": "choice", "choice": card, "confidence": 0.8},
                        "lane": {"type": "choice", "choice": lane}}}


def sol_answer(content, finish="stop"):
    return {"id": "gen-1", "object": "chat.completion", "created": 0, "model": "openai/gpt-6-sol",
            "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}


def test_both_players_get_the_same_options(settings, snap):
    body = jev_request(settings, snap)
    assert body["model"] == "typesafe/jev-1.13"
    assert set(body["questions"]["card"]["criteria"]) == {"wait", "knight", "swarm", "archers"}  # no Giant at 4 elixir
    assert body["questions"]["card"]["type"] == "choice"
    assert body["state"]["lanes"]["left"]["their_tower_hp"] == 1200
    schema = sol_schema(snap)
    assert set(schema["properties"]["card"]["enum"]) == set(body["questions"]["card"]["criteria"])
    assert schema["properties"]["lane"]["enum"] == ["left", "right"]


@respx.mock
@pytest.mark.asyncio
async def test_jev_goes_to_decisions_with_the_openrouter_headers(settings, snap):
    route = respx.post(DECISIONS).mock(return_value=httpx.Response(200, json=jev_answer("swarm", "left")))
    client = OpenRouterClient(settings)
    move = await Players(settings, client).decide("jev", snap)
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer or-key"
    assert req.headers["x-title"] == "System One Arena"
    assert json.loads(req.content)["questions"]["lane"]["criteria"]["left"]
    assert (move.card, move.lane, move.confidence) == ("swarm", 0, 0.8)
    await client.aclose()


@respx.mock
@pytest.mark.asyncio
async def test_sol_sends_a_strict_schema_routed_to_upstreams_that_honour_it(settings, snap):
    settings.SOL_REASONING_EFFORT = "high"
    route = respx.post(CHAT).mock(return_value=httpx.Response(200, json=sol_answer('{"card":"knight","lane":"right"}')))
    client = OpenRouterClient(settings)
    move = await Players(settings, client).decide("sol", snap)
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "openai/gpt-6-sol"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True}
    assert body["reasoning"] == {"effort": "high"}
    assert (move.card, move.lane) == ("knight", 1)
    await client.aclose()


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("response, error", [
    (httpx.Response(200, json=jev_answer("giant", "left")), InvalidMove),       # not affordable
    (httpx.Response(200, json={"model": "x", "answers": {}}), OpenRouterError),  # unanswered
    (httpx.Response(429, json={"error": {"message": "Rate limited"}}), OpenRouterError),
])
async def test_jev_failures_are_errors_not_moves(settings, snap, response, error):
    respx.post(DECISIONS).mock(return_value=response)
    client = OpenRouterClient(settings)
    with pytest.raises(error):
        await Players(settings, client).decide("jev", snap)
    await client.aclose()


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize("response, message", [
    (httpx.Response(200, json=sol_answer('{"card":')), "not valid JSON"),
    (httpx.Response(200, json=sol_answer("{}", finish="length")), "cut off"),
    (httpx.Response(404, json={"error": {"message": "No endpoints found"}}), "No endpoints found"),
])
async def test_sol_failures_are_errors_not_moves(settings, snap, response, message):
    respx.post(CHAT).mock(return_value=response)
    client = OpenRouterClient(settings)
    with pytest.raises(OpenRouterError, match=message):
        await Players(settings, client).decide("sol", snap)
    await client.aclose()


def test_no_key_and_no_mock_refuses_to_build(settings):
    settings.OPENROUTER_API_KEY = None
    with pytest.raises(OpenRouterError, match="OPENROUTER_API_KEY"):
        OpenRouterClient(settings)
