"""A simple rule-based player that reads only what a model reads.

It takes the model-facing state and options (see ``game.state`` and
``game.questions``) and returns a move. The mock OpenRouter answers with it by
default, so a mocked match looks like a real game rather than random clicks.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from .sim import CARDS, OWN_HALF

LANES = ("left", "right")


def _value(troops: Iterable[Dict[str, Any]]) -> float:
    return sum(CARDS[t["type"]]["cost"] / CARDS[t["type"]]["count"] for t in troops if t["type"] in CARDS)


def play(state: Dict[str, Any], card_options: Iterable[str]) -> Tuple[str, str]:
    """Return (card or "wait", lane name)."""
    options = [c for c in card_options if c != "wait"]
    elixir = state.get("your_elixir", 0)
    lanes = state.get("lanes", {})

    def first(prefs: Iterable[str]) -> str | None:
        return next((c for c in prefs if c in options), None)

    # Defend the lane where enemies on our half outweigh our defenders the most.
    best, best_gap = None, 0.4
    for name in LANES:
        lane = lanes.get(name, {})
        enemies = [t for t in lane.get("their_troops", []) if t["tiles_from_your_king"] <= OWN_HALF]
        if not enemies:
            continue
        ours = [t for t in lane.get("your_troops", []) if t["tiles_from_your_king"] <= OWN_HALF]
        gap = _value(enemies) - _value(ours)
        if gap > best_gap:
            best, best_gap = (name, enemies), gap
    if best:
        name, enemies = best
        kinds = [t["type"] for t in enemies]
        if kinds.count("swarm") >= 3:
            prefs = ["bomber", "archers", "knight", "swarm"]
        elif "giant" in kinds:
            prefs = ["swarm", "knight", "archers", "bomber"]
        elif "archers" in kinds or "bomber" in kinds:
            prefs = ["knight", "swarm", "archers", "bomber"]
        else:
            prefs = ["swarm", "archers", "knight", "bomber"]
        card = first(prefs)
        return (card, name) if card else ("wait", name)

    # Support a push that already has a tank in front.
    for name in LANES:
        lane = lanes.get(name, {})
        mine = lane.get("your_troops", [])
        has_tank = any(t["type"] in ("giant", "knight") for t in mine)
        support = sum(t["type"] not in ("giant", "knight") for t in mine)
        if has_tank and support < 3 and elixir >= 4:
            card = first(["archers", "bomber", "swarm", "knight"])
            if card:
                return card, name

    # Start a push at the weaker enemy tower once elixir is high.
    if elixir >= 7:
        left = lanes.get("left", {}).get("their_tower_hp", 0)
        right = lanes.get("right", {}).get("their_tower_hp", 0)
        name = "left" if left <= right else "right"
        card = first(["giant", "knight", "archers", "bomber", "swarm"])
        if card:
            return card, name

    return "wait", "left"
