"""A simple rule-based player that reads only what a model reads.

It takes the model-facing state and options (see ``game.state`` and
``game.questions``) and returns a move. The mock OpenRouter answers with it by
default, so a mocked match looks like a real game rather than random clicks.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Tuple

from .sim import CARDS

# The "where" labels (see game.where) that mean a troop is on your half of the board.
OWN_SIDE = {"at your tower", "past your fallen tower, near your king", "on your side", "at the bridge"}

LANES = ("left", "right")


def _tower_hp(text: str) -> int:
    """HP from a tower as the state words it: "standing, 3800 HP" or "destroyed"."""
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


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
        enemies = [t for t in lane.get("their_troops", []) if t.get("where") in OWN_SIDE]
        if not enemies:
            continue
        ours = [t for t in lane.get("your_troops", []) if t.get("where") in OWN_SIDE]
        gap = _value(enemies) - _value(ours)
        if gap > best_gap:
            best, best_gap = (name, enemies), gap
    if best:
        name, enemies = best
        kinds = [t["type"] for t in enemies]
        if kinds.count("goblins") >= 3:
            prefs = ["dynamiter", "archers", "warrior", "goblins"]
        elif "brute" in kinds:
            prefs = ["goblins", "warrior", "archers", "dynamiter"]
        elif "archers" in kinds or "dynamiter" in kinds:
            prefs = ["warrior", "goblins", "archers", "dynamiter"]
        else:
            prefs = ["goblins", "archers", "warrior", "dynamiter"]
        card = first(prefs)
        return (card, name) if card else ("wait", name)

    # Support a push that already has a tank in front.
    for name in LANES:
        lane = lanes.get(name, {})
        mine = lane.get("your_troops", [])
        has_tank = any(t["type"] in ("brute", "warrior") for t in mine)
        support = sum(t["type"] not in ("brute", "warrior") for t in mine)
        if has_tank and support < 3 and elixir >= 4:
            card = first(["archers", "dynamiter", "goblins", "warrior"])
            if card:
                return card, name

    # Start a push at the weaker enemy tower once elixir is high.
    if elixir >= 7:
        left, right = (_tower_hp(lanes.get(n, {}).get("their_tower", "destroyed")) for n in LANES)
        name = "left" if left <= right else "right"
        card = first(["brute", "warrior", "archers", "dynamiter", "goblins"])
        if card:
            return card, name

    return "wait", "left"
