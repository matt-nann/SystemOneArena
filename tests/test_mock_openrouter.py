"""The mock plugged into the real client: same code path as a live match, no network."""
from __future__ import annotations

import httpx
import pytest

from arena.openrouter import OpenRouterClient, OpenRouterError
from arena.players import Players
from mock_openrouter.app import MockSettings, build_app, transport


def players(settings, app):
    client = OpenRouterClient(settings, transport=transport(app))
    return Players(settings, client), client


@pytest.mark.asyncio
async def test_both_players_get_valid_moves_through_the_client(settings, snap, mock_app):
    p, client = players(settings, mock_app)
    for who in ("jev", "sol"):
        move = await p.decide(who, snap)
        # The playbook defends the left lane against the Brute with Goblins.
        assert (move.card, move.lane) == ("goblins", 0), who
    calls = mock_app.state.mock.calls
    assert [c["endpoint"] for c in calls] == ["decisions", "chat"]
    assert calls[1]["body"]["provider"] == {"require_parameters": True}
    await client.aclose()


@pytest.mark.asyncio
async def test_scripted_responses_and_faults(settings, snap, mock_app):
    st = mock_app.state.mock
    st.scripts["openai/gpt-6-sol"] = __import__("collections").deque([
        {"card": "archers", "lane": "right"},
        {"error": {"status": 429, "message": "Rate limited"}},
        {"malformed": True},
    ])
    p, client = players(settings, mock_app)
    move = await p.decide("sol", snap)
    assert (move.card, move.lane) == ("archers", 1)
    with pytest.raises(OpenRouterError, match="429"):
        await p.decide("sol", snap)
    with pytest.raises(OpenRouterError, match="not valid JSON"):
        await p.decide("sol", snap)
    await client.aclose()


@pytest.mark.asyncio
async def test_a_mocked_timeout_times_out_like_a_real_one(settings, snap, mock_app):
    settings.JEV_TIMEOUT_SECONDS = 0.05
    mock_app.state.mock.scripts["*"] = __import__("collections").deque([{"timeout": True}])
    p, client = players(settings, mock_app)
    with pytest.raises(OpenRouterError, match="timed out"):
        await p.decide("jev", snap)
    await client.aclose()


@pytest.mark.asyncio
async def test_profiles_set_latency_and_error_rate(settings, snap):
    app = build_app(MockSettings(_env_file=None, PROFILES={"openai/gpt-6-sol": {"latency_ms": 30, "error_rate": 1.0, "error": "503"}},
                                 DECISIONS_LATENCY_MS=0, DECISIONS_JITTER_MS=0))
    p, client = players(settings, app)
    with pytest.raises(OpenRouterError, match="503"):
        await p.decide("sol", snap)
    move = await p.decide("jev", snap)
    assert move.ms < 30
    await client.aclose()


@pytest.mark.asyncio
async def test_admin_api_and_generic_requests(mock_app):
    """Admin endpoints, auth, and requests that are not arena moves (so any OpenRouter client works)."""
    async with httpx.AsyncClient(transport=transport(mock_app), base_url="http://mock") as http:
        assert (await http.post("/api/v1/chat/completions", json={"model": "m"})).status_code == 401
        auth = {"Authorization": "Bearer k"}
        r = await http.post("/admin/script", json={"model": "m", "responses": [{"content": "hello"}]})
        assert r.json()["queued"] == 1
        chat = await http.post("/api/v1/chat/completions", headers=auth, json={"model": "m", "messages": [{"role": "user", "content": "hi"}]})
        assert chat.json()["choices"][0]["message"]["content"] == "hello"
        dec = await http.post("/api/alpha/decisions", headers=auth, json={"model": "typesafe/jev-1.13", "state": "ticket", "questions": {
            "is_bug": {"type": "noul", "instructions": "?", "criteria": {"true": "a", "false": "b"}},
            "team": {"type": "choice", "instructions": "?", "criteria": {"account": "a", "payments": "b"}},
            "urgency": {"type": "score", "instructions": "?", "criteria": ["low", "mid", "high"]}}})
        a = dec.json()["answers"]
        assert a["is_bug"]["noul"] == 0.5 and a["team"]["choice"] == "account" and a["urgency"]["score"] == 1.0
        assert len((await http.get("/admin/calls", params={"endpoint": "decisions"})).json()["calls"]) == 1
        await http.post("/admin/reset")
        assert (await http.get("/admin/calls")).json()["calls"] == []
