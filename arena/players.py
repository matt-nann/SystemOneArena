"""The two players: how each is asked for a move.

Jev gets the questions as Decisions ``choice`` questions; Sol gets the same
options as enum fields in a strict JSON schema. Both get the same state.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .config import Settings
from .engine import game
from .openrouter import OpenRouterClient, OpenRouterError

SOL_SYSTEM = "You are playing a real-time tower battle. Answer with your move only."
STATE_MARKER = "Board state (JSON):\n"


@dataclass
class Move:
    card: Optional[str]
    lane: Optional[int]
    ms: float
    model: Optional[str] = None
    usage: Dict[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
    request: Dict[str, Any] = field(default_factory=dict)


def jev_request(settings: Settings, snap: Dict[str, Any], model: Optional[str] = None) -> Dict[str, Any]:
    q = game.questions(snap)
    return {
        "model": model or settings.JEV_MODEL,
        "state": game.state(snap),
        "questions": {name: {"type": "choice", "instructions": v["instructions"], "criteria": v["options"]}
                      for name, v in q.items()},
    }


def sol_messages(snap: Dict[str, Any]) -> list:
    q = game.questions(snap)
    options = "\n".join(f"- {k}: {v}" for k, v in q["card"]["options"].items())
    prompt = (f"{q['card']['instructions']}\n\nCard options:\n{options}\n\n{q['lane']['instructions']}\n\n"
              f"{STATE_MARKER}{json.dumps(game.state(snap))}")
    return [{"role": "system", "content": SOL_SYSTEM}, {"role": "user", "content": prompt}]


def sol_schema(snap: Dict[str, Any]) -> Dict[str, Any]:
    q = game.questions(snap)
    return {
        "type": "object",
        "properties": {
            "card": {"type": "string", "enum": list(q["card"]["options"])},
            "lane": {"type": "string", "enum": list(q["lane"]["options"])},
        },
        "required": ["card", "lane"],
        "additionalProperties": False,
    }


class Players:
    def __init__(self, settings: Settings, client: OpenRouterClient) -> None:
        self.settings = settings
        self.client = client

    @property
    def roster(self) -> list:
        """Index 0 is the bottom (blue) side, index 1 the top (red) side."""
        s = self.settings
        sol_fast = s.SOL_API == "decisions"
        return [
            {"id": "jev", "name": s.JEV_NAME, "model": s.JEV_MODEL, "effort": None, "role": "Fast decision model"},
            {"id": "sol", "name": s.SOL_NAME, "model": s.SOL_MODEL, "effort": None if sol_fast else (s.SOL_REASONING_EFFORT or None),
             "role": "Fast decision model" if sol_fast else "Frontier model"},
        ]

    async def decide(self, who: str, snap: Dict[str, Any]) -> Move:
        """Ask one player for a move. Raises OpenRouterError or game.InvalidMove."""
        if not game.affordable(snap):
            raise game.InvalidMove("no affordable card: nothing to decide")
        if who == "jev":
            return await self._decisions(snap, self.settings.JEV_MODEL, self.settings.JEV_TIMEOUT_SECONDS)
        if who == "sol":
            if self.settings.SOL_API == "decisions":
                return await self._decisions(snap, self.settings.SOL_MODEL, self.settings.SOL_TIMEOUT_SECONDS)
            return await self._sol(snap)
        raise ValueError(f"unknown player {who!r}")

    async def _decisions(self, snap: Dict[str, Any], model: str, timeout: float) -> Move:
        body = jev_request(self.settings, snap, model)
        t0 = time.perf_counter()
        raw = await self.client.decide(body, timeout=timeout)
        ms = (time.perf_counter() - t0) * 1000
        answers = raw.get("answers") or {}
        if "card" not in answers or "lane" not in answers:
            raise OpenRouterError(200, "decisions response did not answer every question")
        card, lane = game.to_move(snap, answers["card"].get("choice"), answers["lane"].get("choice"))
        return Move(card, lane, ms, raw.get("model"), raw.get("usage") or {}, answers["card"].get("confidence"), body)

    async def _sol(self, snap: Dict[str, Any]) -> Move:
        s = self.settings
        messages, schema = sol_messages(snap), sol_schema(snap)
        t0 = time.perf_counter()
        out = await self.client.chat_structured(model=s.SOL_MODEL, messages=messages, schema=schema,
                                                max_tokens=s.SOL_MAX_TOKENS, reasoning_effort=s.SOL_REASONING_EFFORT,
                                                timeout=s.SOL_TIMEOUT_SECONDS)
        ms = (time.perf_counter() - t0) * 1000
        move = out["output"] if isinstance(out["output"], dict) else {}
        card, lane = game.to_move(snap, move.get("card"), move.get("lane"))
        return Move(card, lane, ms, out["model"], out["usage"], None,
                    {"model": s.SOL_MODEL, "messages": messages, "schema": schema})
