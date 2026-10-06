"""Runs matches on the server clock and fans frames out to viewers.

One match at a time. The engine ticks at ``TICK_HZ`` in real time; each
decision request goes to its model as an asyncio task and is resolved back
into the engine whenever the answer lands, while the clock keeps running.
Frames go to every subscriber at ``FRAME_HZ`` and to ``logs/<id>.frames.jsonl``
for replay; decisions and the result go to ``logs/<id>.jsonl``.
"""
from __future__ import annotations

import asyncio
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

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── control ─────────────────────────────────────────────────────
    def start(self, duration: Optional[float] = None) -> str:
        if self.running:
            raise MatchInProgress(self.match_id)
        self.match_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.sim = Sim(SimConfig(seed=self.settings.MATCH_SEED, duration=duration or self.settings.MATCH_SECONDS))
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._log({"event": "start", "players": self.players.roster, "duration": self.sim.cfg.duration,
                   "mock": self.settings.is_mock})
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
        start = last_frame = loop.time()
        try:
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
            self._log({"event": "result", "result": result})
            logger.info("match {} over: {}", match_id, result)
        finally:
            frames.close()
            for t in list(self._calls):
                t.cancel()

    async def _decide(self, sim: Sim, match_id: str, req: DecisionRequest) -> None:
        who = self.players.roster[req.side]["id"]
        t0 = time.perf_counter()
        try:
            move = await self.players.decide(who, req.snapshot)
        except (OpenRouterError, InvalidMove) as exc:
            ms = (time.perf_counter() - t0) * 1000
            fresh = sim.resolve(req.side, req.id, error=str(exc))
            self._log({"event": "decision", "player": who, "request": req.id, "asked_at": req.asked_at, "ms": ms,
                       "snapshot": req.snapshot, "error": str(exc), "applied": fresh}, match_id)
            return
        fresh = sim.resolve(req.side, req.id, card=move.card, lane=move.lane, model_ms=move.ms)
        self._log({"event": "decision", "player": who, "request": req.id, "asked_at": req.asked_at,
                   "answered_at": sim.t, "ms": move.ms, "card": move.card, "lane": move.lane,
                   "confidence": move.confidence, "model": move.model, "usage": move.usage,
                   "snapshot": req.snapshot, "sent": move.request, "applied": fresh}, match_id)

    def _log(self, entry: Dict[str, Any], match_id: Optional[str] = None) -> None:
        mid = match_id or self.match_id
        with (self.log_dir / f"{mid}.jsonl").open("a") as f:
            f.write(json.dumps({"at": time.time(), **entry}, default=str) + "\n")

    # ── history ─────────────────────────────────────────────────────
    def matches(self) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(self.log_dir.glob("*.jsonl"), reverse=True):
            if p.name.endswith(".frames.jsonl"):
                continue
            result, mock = None, None
            for line in p.read_text().splitlines():
                e = json.loads(line)
                if e.get("event") == "start":
                    mock = e.get("mock")
                elif e.get("event") == "result":
                    result = e["result"]
            out.append({"id": p.stem, "mock": mock, "result": result,
                        "replay": (self.log_dir / f"{p.stem}.frames.jsonl").exists()})
        return out
