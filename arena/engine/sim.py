"""The match engine: the single source of truth for a game.

Pure and synchronous. ``Sim.step(dt)`` advances the board by ``dt`` seconds.
The engine never calls a model itself: when a side has a decision to make it
queues a ``DecisionRequest`` in ``Sim.outbox``; whoever runs the match asks
the model and hands the answer back with ``Sim.resolve``. The clock keeps
running in between, which is the whole point of the arena.

Coordinates are in tiles on an 18 x 28 board. Side 0 (Jev, blue) is at the
bottom, side 1 (Sol, red) at the top.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

W, H, RIVER = 18, 28, 14.0
LANES = (4, 14)

CARDS: Dict[str, Dict[str, Any]] = {
    "knight": dict(name="Knight", cost=3, count=1, hp=900, dmg=120, cd=1.0, range=0.6, speed=2.0, r=0.55),
    "archers": dict(name="Archers", cost=3, count=2, hp=220, dmg=70, cd=0.9, range=4.5, speed=2.0, r=0.38),
    "swarm": dict(name="Swarm", cost=2, count=4, hp=70, dmg=45, cd=0.8, range=0.5, speed=2.8, r=0.26),
    "giant": dict(name="Giant", cost=5, count=1, hp=2200, dmg=170, cd=1.4, range=0.6, speed=1.4, r=0.8, bo=True),
    "bomber": dict(name="Bomber", cost=3, count=1, hp=200, dmg=130, cd=1.5, range=4.0, speed=2.0, r=0.4, splash=1.6),
}
DECK = ["knight", "archers", "giant", "swarm", "bomber"]
# How long a side with nothing affordable waits before checking again (no model call).
IDLE_RECHECK = 0.25
# A troop this many tiles from its own king, or closer, is on its own half (river + 2.5).
OWN_HALF = 25.6 - RIVER + 2.5


def mulberry32(seed: int) -> Callable[[], float]:
    """Small seeded PRNG (same algorithm as the original page)."""
    a = seed & 0xFFFFFFFF

    def imul(x: int, y: int) -> int:
        return (x * y) & 0xFFFFFFFF

    def nxt() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = imul(a ^ (a >> 15), 1 | a)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return nxt


@dataclass
class SimConfig:
    seed: int = 13
    duration: float = 60.0
    elixir_rate: float = 1.0
    tower_hp: int = 3800
    king_hp: int = 6000


@dataclass
class DecisionRequest:
    id: int
    side: int
    asked_at: float
    snapshot: Dict[str, Any]


@dataclass
class Side:
    elixir: float = 5.0
    wasted: float = 0.0
    decisions: int = 0
    plays: int = 0
    late: int = 0
    crowns: int = 0
    errors: int = 0
    invalid: int = 0
    hand: List[str] = field(default_factory=lambda: DECK[:4])
    queue: List[str] = field(default_factory=lambda: DECK[4:])
    pending: Optional[Dict[str, Any]] = None
    last: Optional[Dict[str, Any]] = None
    lats: List[float] = field(default_factory=list)
    model_ms: List[float] = field(default_factory=list)
    last_error: Optional[str] = None
    # Recent answers as {s: asked at, a: applied at, c: card or None}, for the viewer's decision rail.
    log: List[Dict[str, Any]] = field(default_factory=list)


def _dist(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def _facing(vx: float, vy: float, current: str) -> str:
    """Which way a sprite faces for a movement or aim vector: up / down / left / right."""
    if abs(vx) < 1e-6 and abs(vy) < 1e-6:
        return current
    if abs(vx) > abs(vy) * 1.3:
        return "right" if vx > 0 else "left"
    return "down" if vy > 0 else "up"


class Sim:
    def __init__(self, cfg: Optional[SimConfig] = None) -> None:
        self.cfg = cfg or SimConfig()
        self.rand = mulberry32(self.cfg.seed)
        self.t = 0.0
        self.over = False
        self.winner: Optional[int] = None
        self.reason = ""
        self.units: List[Dict[str, Any]] = []
        self.shots: List[Dict[str, Any]] = []
        self.fx: List[Dict[str, Any]] = []
        self.sides = [Side(), Side()]
        self.towers: List[Dict[str, Any]] = []
        self.outbox: List[DecisionRequest] = []
        self._nid = 1
        self._rid = 0
        self._hurt: List[tuple] = []
        for side, kind, x, y in ((0, "L", LANES[0], 22.5), (0, "R", LANES[1], 22.5), (0, "K", 9, 25.6),
                                 (1, "L", LANES[0], 5.5), (1, "R", LANES[1], 5.5), (1, "K", 9, 2.4)):
            k = kind == "K"
            hp = self.cfg.king_hp if k else self.cfg.tower_hp
            self.towers.append(dict(side=side, kind=kind, x=x, y=y, hp=float(hp), max=hp, alive=True, cd=0.0,
                                    r=1.4 if k else 1.1, range=6 if k else 6.5, dmg=70 if k else 60,
                                    rate=0.9 if k else 0.8, hit=0.0, aim=None))

    # ── lookups ─────────────────────────────────────────────────────
    def tower(self, side: int, kind: str) -> Dict[str, Any]:
        return next(t for t in self.towers if t["side"] == side and t["kind"] == kind)

    def princess(self, side: int, lane: int) -> Dict[str, Any]:
        return self.tower(side, "L" if lane == 0 else "R")

    @staticmethod
    def _fwd(side: int) -> int:
        return -1 if side == 0 else 1

    @staticmethod
    def _on_own_half(side: int, u: Dict[str, Any]) -> bool:
        return u["y"] > RIVER - 2.5 if side == 0 else u["y"] < RIVER + 2.5

    def affordable(self, side: int) -> List[str]:
        s = self.sides[side]
        return [c for c in s.hand if CARDS[c]["cost"] <= s.elixir]

    # ── what a model sees ───────────────────────────────────────────
    def lane_ctx(self, side: int, lane: int) -> Dict[str, Any]:
        """Where a card would go in ``lane``: in front of your tower if enemies are on your half, else support or bridge."""
        foe = 1 - side
        enemies = [u for u in self.units if u["side"] == foe and u["lane"] == lane and self._on_own_half(side, u)]
        if enemies:
            return {"spot": "defend", "ids": [u["id"] for u in enemies]}
        if any(u["side"] == side and u["lane"] == lane and u["type"] in ("giant", "knight") for u in self.units):
            return {"spot": "support"}
        return {"spot": "bridge"}

    def snapshot(self, side: int) -> Dict[str, Any]:
        """The board from ``side``'s point of view; distances are measured from its own king, so both sides read the same way."""
        foe, me, king = 1 - side, self.sides[side], self.tower(side, "K")

        def troop(u: Dict[str, Any]) -> Dict[str, Any]:
            return {"type": u["type"], "hp": math.ceil(u["hp"]), "tiles_from_your_king": round(abs(u["y"] - king["y"]), 1)}

        lanes = []
        for lane in (0, 1):
            ctx = self.lane_ctx(side, lane)
            lanes.append({
                "your_tower_hp": math.ceil(self.princess(side, lane)["hp"]),
                "their_tower_hp": math.ceil(self.princess(foe, lane)["hp"]),
                "your_troops": [troop(u) for u in self.units if u["side"] == side and u["lane"] == lane],
                "their_troops": [troop(u) for u in self.units if u["side"] == foe and u["lane"] == lane],
                "enemy_troops_on_your_side": len(ctx["ids"]) if ctx["spot"] == "defend" else 0,
            })
        return {
            "timeLeft": max(0, math.ceil(self.cfg.duration - self.t)),
            "elixir": math.floor(me.elixir + 1e-6),
            "hand": list(me.hand),
            "crowns": {"you": me.crowns, "opponent": self.sides[foe].crowns},
            "kings": {"your_hp": math.ceil(king["hp"]), "their_hp": math.ceil(self.tower(foe, "K")["hp"])},
            "lanes": lanes,
        }

    # ── decisions ───────────────────────────────────────────────────
    def _ask(self, side: int) -> None:
        s = self.sides[side]
        if not self.affordable(side):
            s.pending = {"auto": True, "start": self.t, "due": self.t + IDLE_RECHECK}
            return
        self._rid += 1
        # Placement is fixed by the board at the moment of asking, so a slow answer is a late answer.
        # The troops as they stood when asked: the board a slow answer is still responding to.
        ghosts = [{"id": u["id"], "side": u["side"], "type": u["type"], "x": round(u["x"], 2), "y": round(u["y"], 2), "dir": u["dir"]}
                  for u in self.units]
        s.pending = {"id": self._rid, "start": self.t, "ctx": [self.lane_ctx(side, 0), self.lane_ctx(side, 1)], "ready": False,
                     "ghosts": ghosts}
        self.outbox.append(DecisionRequest(self._rid, side, self.t, self.snapshot(side)))

    def take_requests(self) -> List[DecisionRequest]:
        out, self.outbox = self.outbox, []
        return out

    def resolve(self, side: int, request_id: int, *, card: Optional[str] = None, lane: Optional[int] = None,
                model_ms: Optional[float] = None, error: Optional[str] = None) -> bool:
        """Hand a model's answer back. Returns False if the request is stale (match over or superseded)."""
        s = self.sides[side]
        p = s.pending
        if self.over or not p or p.get("id") != request_id or p.get("ready"):
            return False
        if error is not None:
            s.errors += 1
            s.last_error = error
            p["action"] = {"card": None, "lane": None, "why": "error"}
        elif card:
            ctx = p["ctx"][lane]
            p["action"] = {"card": card, "lane": lane, "spot": ctx["spot"],
                           "why": "defend" if ctx["spot"] == "defend" else "push", "ids": ctx.get("ids", [])}
        else:
            p["action"] = {"card": None, "lane": None, "why": "wait"}
        p["model_ms"] = model_ms
        p["ready"] = True
        return True

    def _apply(self, i: int) -> None:
        s = self.sides[i]
        p, s.pending = s.pending, None
        if p.get("auto"):
            return
        a = p["action"]
        lat = self.t - p["start"]
        # A model may only pick cards it could afford when asked; elixir only rises while it thinks.
        if a["card"] and not (a["card"] in s.hand and CARDS[a["card"]]["cost"] <= s.elixir):
            s.invalid += 1
            a["card"] = None
        late = False
        if a["card"] and a["why"] == "defend":
            alive = {u["id"] for u in self.units}
            late = not any(uid in alive for uid in a["ids"])
            s.late += late
        if a["card"]:
            self._deploy(i, a, lat)
        s.decisions += 1
        s.lats.append(lat)
        s.log.append({"s": round(p["start"], 2), "a": round(self.t, 2), "c": a["card"]})
        del s.log[:-60]
        if p.get("model_ms") is not None:
            s.model_ms.append(p["model_ms"])
        s.last = {"card": a["card"], "lane": a["lane"], "why": a["why"], "lat": lat, "at": self.t, "late": late}

    # ── placement ───────────────────────────────────────────────────
    def _spot_pos(self, side: int, lane: int, spot: str) -> tuple:
        f, lx = self._fwd(side), LANES[lane]
        p, k = self.princess(side, lane), self.tower(side, "K")
        if spot == "defend":
            if p["alive"]:
                return lx, p["y"] + f * 2.6
            return 9 + (lx - 9) * 0.45, k["y"] + f * 3.2
        if spot == "support":
            leads = [u for u in self.units if u["side"] == side and u["lane"] == lane and u["type"] in ("giant", "knight")]
            if leads:
                lead = leads[0]
                for u in leads:
                    if f * (u["y"] - lead["y"]) > 0:
                        lead = u
                y = lead["y"] - f * 2.2
                y = max(y, RIVER + 1.2) if side == 0 else min(y, RIVER - 1.2)
                return lx, y
        return lx, RIVER - f * 1.8

    def _deploy(self, side: int, a: Dict[str, Any], lat: float = 0.0) -> None:
        me, c = self.sides[side], CARDS[a["card"]]
        me.elixir -= c["cost"]
        me.plays += 1
        i = me.hand.index(a["card"])
        me.queue.append(a["card"])
        me.hand[i] = me.queue.pop(0)
        px, py = self._spot_pos(side, a["lane"], a["spot"])
        n_units = c["count"]
        for n in range(n_units):
            ox = ((n % 2) - 0.5) * 1.0 + (self.rand() - 0.5) * 0.2 if n_units > 1 else (self.rand() - 0.5) * 0.3
            oy = (n // 2 - 0.5) * 0.9 if n_units > 2 else 0.0
            self.units.append(dict(id=self._nid, side=side, type=a["card"], lane=a["lane"], x=px + ox, y=py + oy,
                                   hp=float(c["hp"]), max=c["hp"], cd=0.4, val=c["cost"] / n_units, hit=0.0,
                                   born=self.t, atk=None, dir="up" if side == 0 else "down", act="walk"))
            self._nid += 1
        self.fx.append(dict(kind="deploy", side=side, type=a["card"], x=px, y=py, t=self.t, label=c["name"], lat=lat))

    # ── the tick ────────────────────────────────────────────────────
    def step(self, dt: float) -> None:
        if self.over:
            return
        self.t += dt
        for s in self.sides:
            s.elixir += self.cfg.elixir_rate * dt
            if s.elixir > 10:
                s.wasted += s.elixir - 10
                s.elixir = 10.0
        for i, s in enumerate(self.sides):
            p = s.pending
            if p and (p.get("ready") or self.t >= p.get("due", math.inf)):
                self._apply(i)
            if not s.pending:
                self._ask(i)

        self._move_and_fight(dt)
        self._separate()
        self._towers_fire(dt)

        for o, d in self._hurt:
            o["hp"] -= d
            o["hit"] = self.t
        self._hurt = []
        for u in self.units:
            if u["hp"] <= 0:
                self.fx.append(dict(kind="pop", side=u["side"], x=u["x"], y=u["y"], t=self.t))
        self.units = [u for u in self.units if u["hp"] > 0]
        for tw in self.towers:
            if tw["alive"] and tw["hp"] <= 0:
                tw["alive"], tw["hp"] = False, 0.0
                taker = self.sides[1 - tw["side"]]
                taker.crowns += 3 - taker.crowns if tw["kind"] == "K" else 1
                self.fx.append(dict(kind="fall", side=tw["side"], x=tw["x"], y=tw["y"], t=self.t))
                if tw["kind"] == "K":
                    self.over, self.winner, self.reason = True, 1 - tw["side"], "king"
        self.shots = [s for s in self.shots if self.t - s["t"] < 0.25]
        self.fx = [f for f in self.fx if self.t - f["t"] < 1.4]
        if not self.over and self.t >= self.cfg.duration:
            self.over, self.reason = True, "time"
            a, b = self.sides[0].crowns, self.sides[1].crowns
            if a != b:
                self.winner = 0 if a > b else 1
            else:
                hp = [sum(t["hp"] for t in self.towers if t["side"] == s) for s in (0, 1)]
                self.winner = 0 if hp[0] >= hp[1] else 1
        if self.over:
            self.outbox = []

    def _move_and_fight(self, dt: float) -> None:
        for u in self.units:
            if u["hp"] <= 0:
                continue
            c, foe = CARDS[u["type"]], 1 - u["side"]
            tg, bd = None, 1e9
            if not c.get("bo"):
                for e in self.units:
                    if e["side"] != foe or e["hp"] <= 0:
                        continue
                    d = _dist(u, e)
                    if d < 5.5 and d < bd:
                        bd, tg = d, e
            is_tower = False
            if tg is None:
                p = self.princess(foe, u["lane"])
                tg = p if p["alive"] else self.tower(foe, "K")
                is_tower, bd = True, _dist(u, tg)
            tr = tg["r"] if is_tower else CARDS[tg["type"]]["r"]
            u["cd"] -= dt
            if bd - tr - c["r"] <= c["range"]:
                u["act"] = "attack"
                u["dir"] = _facing(tg["x"] - u["x"], tg["y"] - u["y"], u["dir"])
                if u["cd"] <= 0:
                    u["cd"] = c["cd"]
                    if c.get("splash"):
                        for e in self.units:
                            if e["side"] == foe and e["hp"] > 0 and math.hypot(e["x"] - tg["x"], e["y"] - tg["y"]) <= c["splash"]:
                                self._hurt.append((e, c["dmg"]))
                        if is_tower:
                            self._hurt.append((tg, c["dmg"]))
                        self.fx.append(dict(kind="boom", side=u["side"], x=tg["x"], y=tg["y"], t=self.t, r=c["splash"]))
                    else:
                        self._hurt.append((tg, c["dmg"]))
                    if c["range"] > 1:
                        self.shots.append(dict(side=u["side"], k="bomb" if c.get("splash") else "arrow",
                                               x1=u["x"], y1=u["y"], x2=tg["x"], y2=tg["y"], t=self.t))
                    u["atk"] = self.t
            else:
                tx, ty = tg["x"], tg["y"]
                crossing = (u["y"] - RIVER) * (ty - RIVER) < 0 or abs(u["y"] - RIVER) < 1.4
                if crossing:
                    lx = LANES[u["lane"]]
                    if abs(u["x"] - lx) > 0.9:
                        tx, ty = lx, u["y"]
                    else:
                        tx = u["x"] + (lx - u["x"]) * 0.5
                d = math.hypot(tx - u["x"], ty - u["y"]) or 1
                u["act"] = "walk"
                u["dir"] = _facing(tx - u["x"], ty - u["y"], u["dir"])
                u["x"] += (tx - u["x"]) / d * c["speed"] * dt
                u["y"] += (ty - u["y"]) / d * c["speed"] * dt

    def _separate(self) -> None:
        us = self.units
        for i in range(len(us)):
            for j in range(i + 1, len(us)):
                a, b = us[i], us[j]
                if a["side"] != b["side"]:
                    continue
                m = (CARDS[a["type"]]["r"] + CARDS[b["type"]]["r"]) * 0.9
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                d = math.hypot(dx, dy)
                if 0.001 < d < m:
                    p = (m - d) / 2
                    a["x"] -= dx / d * p
                    a["y"] -= dy / d * p
                    b["x"] += dx / d * p
                    b["y"] += dy / d * p

    def _towers_fire(self, dt: float) -> None:
        for tw in self.towers:
            if not tw["alive"]:
                continue
            tw["cd"] -= dt
            if tw["cd"] > 0:
                continue
            tg, bd = None, tw["range"]
            for e in self.units:
                if e["side"] == tw["side"] or e["hp"] <= 0:
                    continue
                d = _dist(tw, e)
                if d < bd:
                    bd, tg = d, e
            if tg:
                tw["cd"] = tw["rate"]
                self._hurt.append((tg, tw["dmg"]))
                tw["aim"] = math.atan2(tg["y"] - tw["y"], tg["x"] - tw["x"])
                self.shots.append(dict(side=tw["side"], k="ball", x1=tw["x"], y1=tw["y"], x2=tg["x"], y2=tg["y"], t=self.t))

    # ── what viewers see ────────────────────────────────────────────
    def side_summary(self, i: int) -> Dict[str, Any]:
        s = self.sides[i]
        avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
        return {"decisions": s.decisions, "plays": s.plays, "elixir_wasted": round(s.wasted, 1), "crowns": s.crowns,
                "late_defences": s.late, "failed_calls": s.errors, "invalid_moves": s.invalid,
                "avg_decision_s": avg(s.lats), "avg_model_ms": avg(s.model_ms)}

    def frame(self) -> Dict[str, Any]:
        """Everything a viewer needs to draw the current moment. Viewers never run the engine."""
        r = lambda v: round(v, 3)  # noqa: E731
        sides = []
        for i, s in enumerate(self.sides):
            thinking = s.pending is not None and not s.pending.get("auto") and not s.pending.get("ready")
            sides.append({
                "elixir": r(s.elixir), "wasted": round(s.wasted, 2), "decisions": s.decisions, "crowns": s.crowns,
                "errors": s.errors, "thinking_since": r(s.pending["start"]) if thinking else None,
                "last": {"card": s.last["card"], "why": s.last["why"], "lat": r(s.last["lat"])} if s.last else None,
                "last_error": s.last_error,
                "avg": r(sum(s.lats[-6:]) / len(s.lats[-6:])) if s.lats else None,
                "recent": [d for d in s.log if self.t - d["a"] <= 10.5],
                "ghosts": s.pending["ghosts"] if thinking else None,
            })
        return {
            "t": r(self.t), "dur": self.cfg.duration, "over": self.over, "winner": self.winner, "reason": self.reason,
            "units": [{k: (r(v) if isinstance(v, float) else v) for k, v in u.items() if k in
                       ("id", "side", "type", "x", "y", "hp", "max", "atk", "hit", "cd", "dir", "act")} for u in self.units],
            "towers": [{k: (r(v) if isinstance(v, float) else v) for k, v in tw.items() if k in
                        ("side", "kind", "x", "y", "hp", "max", "alive", "aim", "hit")} for tw in self.towers],
            "shots": [{k: (r(v) if isinstance(v, float) else v) for k, v in s.items()} for s in self.shots],
            "fx": [{k: (r(v) if isinstance(v, float) else v) for k, v in f.items()} for f in self.fx],
            "sides": sides,
            "result": self.result() if self.over else None,
        }

    def result(self) -> Dict[str, Any]:
        return {"winner": self.winner, "reason": self.reason, "seconds": round(self.t, 1),
                "sides": [self.side_summary(0), self.side_summary(1)]}
