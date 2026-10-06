"""Runs matches on the server clock and fans frames out to viewers.

One match at a time. The engine ticks at ``TICK_HZ`` in real time; each
decision request goes to its model as an asyncio task and is resolved back
into the engine whenever the answer lands, while the clock keeps running.
Frames go to every subscriber at ``FRAME_HZ`` and to ``logs/<id>.frames.jsonl``
for replay; decisions and the result go to ``logs/<id>.jsonl``.
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from .config import Settings
from .engine.game import InvalidMove
from .engine.sim import DecisionRequest, Sim, SimConfig
from .openrouter import OpenRouterError
from .players import Players


class MatchInProgress(Exception):
    pass


class MatchRunner:
    def __init__(self, settings: Settings, players: Players) -> None:
        self.settings = settings
        self.players = players
        self.sim: Optional[Sim] = None
        self.match_id: Optional[str] = None
        self.last_frame: Optional[Dict[str, Any]] = None
        self._task: Optional[asyncio.Task] = None
        self._calls: Set[asyncio.Task] = set()
        self._subscribers: Set[asyncio.Queue] = set()
        self.log_dir = Path(settings.LOG_DIR)
        self.calls, self.cost = [0, 0], [0.0, 0.0]

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── control ─────────────────────────────────────────────────────
    def start(self, duration: Optional[float] = None) -> str:
        if self.running:
            raise MatchInProgress(self.match_id)
        self.match_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.sim = Sim(SimConfig(seed=self.settings.MATCH_SEED, duration=duration or self.settings.MATCH_SECONDS,
                                 min_interval=self.settings.DECISION_MIN_INTERVAL, pace=self.settings.MATCH_PACE))
        self.calls, self.cost = [0, 0], [0.0, 0.0]
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # Everything tools/rerun.py needs to replay the match through the engine without the models.
        config = {**dataclasses.asdict(self.sim.cfg), "tick_hz": self.settings.TICK_HZ, "frame_hz": self.settings.FRAME_HZ}
        self._log({"event": "start", "players": self.players.roster, "duration": self.sim.cfg.duration,
                   "mock": self.settings.is_mock, "config": config})
        self._task = asyncio.create_task(self._run(self.sim, self.match_id))
        logger.info("match {} started", self.match_id)
        return self.match_id

    async def wait(self) -> None:
        if self._task:
            await self._task

    async def stop(self) -> None:
        for t in [self._task, *self._calls]:
            if t and not t.done():
                t.cancel()
        await asyncio.gather(*(t for t in [self._task, *self._calls] if t), return_exceptions=True)

    # ── viewers ─────────────────────────────────────────────────────
    def add_subscriber(self) -> asyncio.Queue:
        """A queue of frames as they happen, holding the current one first. It keeps only the
        newest frame, so a slow viewer skips frames rather than lagging. Pair with remove_subscriber."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        if self.last_frame is not None:
            q.put_nowait(self.envelope(self.last_frame))
        self._subscribers.add(q)
        return q

    def remove_subscriber(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def envelope(self, frame: Dict[str, Any]) -> Dict[str, Any]:
        return {"match": self.match_id, "players": self.players.roster, "frame": frame}

    def _broadcast(self, frame: Dict[str, Any]) -> None:
        self.last_frame = frame
        msg = self.envelope(frame)
        for q in list(self._subscribers):
            if q.full():
                q.get_nowait()
            q.put_nowait(msg)

    # ── the loop ────────────────────────────────────────────────────
    async def _run(self, sim: Sim, match_id: str) -> None:
        step = 1 / self.settings.TICK_HZ
        frame_every = 1 / self.settings.FRAME_HZ
        frames = (self.log_dir / f"{match_id}.frames.jsonl").open("w")
        loop = asyncio.get_running_loop()
        try:
            # Pre-roll: the starting board, frozen, while viewers show the start banner.
            ready_at = loop.time() + self.settings.MATCH_PREROLL_SECONDS
            while loop.time() < ready_at:
                self._broadcast({**sim.frame(), "preroll": True})
                await asyncio.sleep(frame_every)
            start = last_frame = loop.time()
            while not sim.over:
                # Catch the engine up to wall time, in fixed steps.
                target = loop.time() - start
                while sim.t + step <= target + 1e-9 and not sim.over:
                    sim.step(step)
                    for req in sim.take_requests():
                        task = asyncio.create_task(self._decide(sim, match_id, req))
                        self._calls.add(task)
                        task.add_done_callback(self._calls.discard)
                now = loop.time()
                if now - last_frame >= frame_every or sim.over:
                    last_frame = now
                    frame = sim.frame()
                    self._broadcast(frame)
                    frames.write(json.dumps(frame, separators=(",", ":")) + "\n")
                await asyncio.sleep(step / 2)
            result = sim.result()
            result["players"] = [p["id"] for p in self.players.roster]
            result["calls"], result["cost_usd"] = self.calls, [round(c, 6) for c in self.cost]
            self._log({"event": "result", "result": result})
            logger.info("match {} over: {}", match_id, result)
        finally:
            frames.close()
            for t in list(self._calls):
                t.cancel()

    async def _decide(self, sim: Sim, match_id: str, req: DecisionRequest) -> None:
        who = self.players.roster[req.side]["id"]
        cap = self.settings.MAX_CALLS_PER_MATCH
        if cap and sum(self.calls) >= cap:
            # Out of budget: send nothing more and end the match on the spot.
            if sim.cfg.duration > sim.t:
                sim.cfg.duration = sim.t
                self._log({"event": "budget", "calls": self.calls, "at": sim.t}, match_id)
                logger.warning("match {}: MAX_CALLS_PER_MATCH={} reached, ending the match", match_id, cap)
            sim.resolve(req.side, req.id, error="call budget reached")
            return
        self.calls[req.side] += 1
        t0 = time.perf_counter()
        try:
            move = await self.players.decide(who, req.snapshot)
        except (OpenRouterError, InvalidMove) as exc:
            ms = (time.perf_counter() - t0) * 1000
            fresh = sim.resolve(req.side, req.id, error=str(exc))
            self._log({"event": "decision", "player": who, "side": req.side, "request": req.id, "asked_at": req.asked_at,
                       "answered_at": sim.t, "ms": ms, "snapshot": req.snapshot, "error": str(exc), "applied": fresh}, match_id)
            return
        self.cost[req.side] += float((move.usage or {}).get("cost") or 0)
        fresh = sim.resolve(req.side, req.id, card=move.card, lane=move.lane, model_ms=move.ms)
        self._log({"event": "decision", "player": who, "side": req.side, "request": req.id, "asked_at": req.asked_at,
                   "answered_at": sim.t, "ms": move.ms, "card": move.card, "lane": move.lane,
                   "confidence": move.confidence, "model": move.model, "usage": move.usage,
                   "snapshot": req.snapshot, "sent": move.request, "received": move.answer, "applied": fresh}, match_id)

    def _log(self, entry: Dict[str, Any], match_id: Optional[str] = None) -> None:
        mid = match_id or self.match_id
        with (self.log_dir / f"{mid}.jsonl").open("a") as f:
            f.write(json.dumps({"at": time.time(), **entry}, default=str) + "\n")

    # ── history ─────────────────────────────────────────────────────
    def matches(self) -> List[Dict[str, Any]]:
        out = []
        archive = Path(self.settings.MATCH_ARCHIVE_DIR)
        paths = sorted([*self.log_dir.glob("*.jsonl"), *(archive.glob("*.jsonl") if archive.is_dir() else [])],
                       key=lambda p: p.name, reverse=True)
        seen = set()
        for p in paths:
            if p.stem in seen:
                continue
            seen.add(p.stem)
            if p.name.endswith(".frames.jsonl"):
                continue
            result, mock, config, players = None, None, None, None
            for line in p.read_text().splitlines():
                e = json.loads(line)
                if e.get("event") == "start":
                    mock, config = e.get("mock"), e.get("config")
                    players = [p.get("name") for p in e.get("players", [])]
                elif e.get("event") == "result":
                    result = e["result"]
            out.append({"id": p.stem, "mock": mock, "result": result, "config": config, "players": players,
                        "archived": (archive / p.name).exists(),
                        "replay": (p.parent / f"{p.stem}.frames.jsonl").exists()})
        return out
