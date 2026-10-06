"""The engine on its own, then a whole match through the service with the mock."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from arena.app import build_app
from arena.engine import game, playbook
from arena.engine.sim import Sim, SimConfig
from arena.match import MatchInProgress, MatchRunner
from arena.openrouter import OpenRouterClient
from arena.players import Players
from mock_openrouter.app import transport


def play(latency, cfg=None):
    """Run a match with the playbook answering after a fixed latency per side."""
    sim, due = Sim(cfg or SimConfig()), []
    while not sim.over:
        sim.step(1 / 30)
        due += [(sim.t + latency[r.side], r) for r in sim.take_requests()]
        for item in [d for d in due if d[0] <= sim.t]:
            due.remove(item)
            r = item[1]
            card, lane = playbook.play(game.state(r.snapshot), game.questions(r.snapshot)["card"]["options"])
            c, l = game.to_move(r.snapshot, card, lane)
            sim.resolve(r.side, r.id, card=c, lane=l, model_ms=latency[r.side] * 1000)
    return sim


def test_slow_side_loses_and_wastes_elixir():
    sim = play([0.36, 5.99])
    r = sim.result()
    assert r["winner"] == 0
    assert r["sides"][0]["decisions"] > 10 * r["sides"][1]["decisions"]
    assert r["sides"][0]["elixir_wasted"] == 0 and r["sides"][1]["elixir_wasted"] > 10


def test_engine_is_deterministic():
    assert play([0.36, 5.99]).result() == play([0.36, 5.99]).result()


def test_errors_stale_answers_and_unaffordable_moves():
    sim = Sim()
    sim.step(1 / 30)
    reqs = sim.take_requests()
    assert [r.side for r in reqs] == [0, 1]
    assert sim.resolve(0, reqs[0].id, error="openrouter 502: boom")
    assert not sim.resolve(0, reqs[0].id, card="warrior", lane=0)  # already answered
    assert sim.resolve(1, reqs[1].id, card="brute", lane=0)  # 5 elixir needed, has ~5.03: fine
    sim.step(1 / 30)
    assert sim.sides[0].errors == 1 and sim.sides[0].last["why"] == "error"
    assert sim.sides[1].plays == 1
    new = [r for r in sim.take_requests() if r.side == 1]
    if new:  # side 1 now has ~0 elixir: no affordable card, so no request is made at all
        pytest.fail("asked a side with nothing affordable")


def test_frame_has_what_the_viewer_draws():
    sim = play([0.36, 5.99], SimConfig(duration=5))
    f = sim.frame()
    assert set(f) >= {"t", "dur", "units", "towers", "shots", "fx", "sides", "over", "result"}
    assert len(f["towers"]) == 6 and f["over"] and f["result"]["seconds"] == 5.0
    json.dumps(f)


def test_frame_carries_the_decision_rail():
    sim, due = Sim(SimConfig(duration=12)), []
    while not sim.over:
        sim.step(1 / 30)
        due += [(sim.t + [0.36, 5.99][r.side], r) for r in sim.take_requests()]
        for item in [d for d in due if d[0] <= sim.t]:
            due.remove(item)
            r = item[1]
            card, lane = playbook.play(game.state(r.snapshot), game.questions(r.snapshot)["card"]["options"])
            c, l = game.to_move(r.snapshot, card, lane)
            sim.resolve(r.side, r.id, card=c, lane=l)
        f = sim.frame()
        assert all(f["t"] - d["a"] <= 10.5 for s in f["sides"] for d in s["recent"])
    jev = sim.frame()["sides"][0]
    assert jev["recent"] and jev["avg"] < 1
    assert all("lat" in fx for fx in sim.fx if fx["kind"] == "deploy")


@pytest.mark.asyncio
async def test_a_short_match_runs_end_to_end_on_the_mock(settings, mock_app):
    client = OpenRouterClient(settings, transport=transport(mock_app))
    runner = MatchRunner(settings, Players(settings, client))
    match_id = runner.start(duration=2)
    with pytest.raises(MatchInProgress):
        runner.start()
    q, frames = runner.add_subscriber(), []
    while not frames or not frames[-1]["over"]:
        frames.append((await q.get())["frame"])
    runner.remove_subscriber(q)
    await runner.wait()
    await client.aclose()

    assert frames[-1]["result"]["seconds"] == 2.0
    log = [json.loads(l) for l in (settings.LOG_DIR / f"{match_id}.jsonl").read_text().splitlines()]
    decisions = [e for e in log if e["event"] == "decision"]
    assert {e["player"] for e in decisions} == {"jev", "sol"}
    assert all("error" not in e for e in decisions)
    assert log[-1]["event"] == "result"
    assert (settings.LOG_DIR / f"{match_id}.frames.jsonl").exists()
    assert runner.matches()[0]["id"] == match_id


def test_http_surface_and_admin_token(settings, mock_app):
    settings.ARENA_ADMIN_TOKEN = "secret"
    client = OpenRouterClient(settings, transport=transport(mock_app))
    app = build_app(settings, MatchRunner(settings, Players(settings, client)))
    with TestClient(app) as http:
        assert http.get("/health").json() == {"status": "ok"}
        cfg = http.get("/api/config").json()
        assert [p["id"] for p in cfg["players"]] == ["jev", "sol"]
        assert cfg["can_start"] is False
        assert http.get("/api/config", headers={"Authorization": "Bearer secret"}).json()["can_start"] is True
        assert http.post("/api/matches").status_code == 401
        assert http.get("/api/matches/nope/frames").status_code == 404
        assert "<canvas" in http.get("/").text


def test_pointing_at_anything_but_openrouter_counts_as_mock(settings):
    assert not settings.is_mock
    settings.OPENROUTER_BASE_URL = "http://localhost:8790/api/v1"
    assert settings.is_mock


def test_min_interval_spaces_out_each_sides_calls():
    sim, asked = Sim(SimConfig(duration=10, min_interval=1.0)), {0: [], 1: []}
    while not sim.over:
        sim.step(1 / 30)
        for r in sim.take_requests():
            asked[r.side].append(r.asked_at)
            sim.resolve(r.side, r.id)  # answer "wait" at once
    for times in asked.values():
        assert times and all(b - a >= 1.0 - 1e-9 for a, b in zip(times, times[1:]))
        assert len(times) <= 11


@pytest.mark.asyncio
async def test_the_call_budget_stops_requests_and_ends_the_match(settings, mock_app):
    settings.MAX_CALLS_PER_MATCH = 6
    client = OpenRouterClient(settings, transport=transport(mock_app))
    runner = MatchRunner(settings, Players(settings, client))
    runner.start(duration=30)
    await runner.wait()
    r = runner.sim.result()
    assert sum(runner.calls) == 6 and r["seconds"] < 30
    log = (settings.LOG_DIR / f"{runner.match_id}.jsonl").read_text()
    assert '"event": "budget"' in log and '"calls": [' in log
    await client.aclose()


@pytest.mark.asyncio
async def test_a_logged_match_reruns_to_the_same_result_without_models(settings, mock_app):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rerun", "tools/rerun.py")
    rerun = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rerun)
    settings.DECISION_MIN_INTERVAL = 0.5
    client = OpenRouterClient(settings, transport=transport(mock_app))
    runner = MatchRunner(settings, Players(settings, client))
    runner.start(duration=4)
    await runner.wait()
    events = [json.loads(line) for line in (settings.LOG_DIR / f"{runner.match_id}.jsonl").read_text().splitlines()]
    start = events[0]
    assert start["config"]["min_interval"] == 0.5 and start["config"]["tick_hz"] == settings.TICK_HZ
    decided = [e for e in events if e["event"] == "decision" and not e.get("error")]
    assert decided and all("received" in e and "side" in e for e in decided)
    logged = next(e["result"] for e in events if e["event"] == "result")
    got = rerun.rerun(events, {})
    assert (got["winner"], got["seconds"]) == (logged["winner"], logged["seconds"])
    assert [s["decisions"] for s in got["sides"]] == [s["decisions"] for s in logged["sides"]]
    await client.aclose()


def test_pace_speeds_the_world_but_not_the_clock():
    slow, fast = Sim(SimConfig(duration=5)), Sim(SimConfig(duration=5, pace=1.25))
    for s in (slow, fast):
        for _ in range(30):
            s.step(1 / 30)
    assert fast.t == slow.t  # the clock is real time either way
    assert fast.sides[0].elixir - 5 > (slow.sides[0].elixir - 5) * 1.2  # elixir comes in 25% faster
