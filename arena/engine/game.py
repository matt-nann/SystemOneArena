"""The question both players answer.

The engine's snapshot of the board, from the asking side's point of view, is
turned into the same options and wording for Jev and for Sol, so the only
thing that differs between them is the model.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .sim import CARDS

LANE_NAMES = ("left", "right")

CARD_TEXT = {
    "knight": "Knight (3 elixir): one sturdy melee tank, good all-round defender.",
    "archers": "Archers (3 elixir): two ranged attackers, good behind a tank and against swarms.",
    "swarm": "Swarm (2 elixir): four fast, fragile melee units; shreds a Giant, dies to splash.",
    "giant": "Giant (5 elixir): huge HP, only attacks towers; the main way to push.",
    "bomber": "Bomber (3 elixir): splash damage from range; best answer to Swarm.",
}

RULES = (
    "Real-time two-lane tower battle. Elixir regenerates at 1 per second and caps at 10; "
    "elixir gained while capped is wasted. The match clock does not pause while you decide, "
    "so a slow answer is played on a board that has already moved. "
    "Destroy the enemy king tower to win; otherwise the side with more towers destroyed wins at 0:00. "
    "A defensive card is placed in front of your own tower in that lane; otherwise it is placed at the bridge."
)


class InvalidMove(ValueError):
    """A model answered outside the options it was given."""


def affordable(snap: Dict[str, Any]) -> List[str]:
    return [c for c in snap["hand"] if c in CARDS and CARDS[c]["cost"] <= snap["elixir"]]


def questions(snap: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The two questions, as {name: {instructions, options: {value: meaning}}}."""
    card = {"wait": "Play nothing now and keep saving elixir."}
    for c in affordable(snap):
        card[c] = CARD_TEXT[c]
    return {
        "card": {"instructions": "Which card do you play right now, if any? " + RULES, "options": card},
        "lane": {
            "instructions": "Which lane does the card go in? Ignored if you play nothing.",
            "options": {
                "left": "The left lane, as seen from your king tower.",
                "right": "The right lane, as seen from your king tower.",
            },
        },
    }


def state(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The board as a model sees it. The hand is carried by the card options, not repeated here."""
    return {
        "time_left_seconds": snap["timeLeft"],
        "your_elixir": snap["elixir"],
        "crowns": snap["crowns"],
        "king_towers": snap["kings"],
        "lanes": {LANE_NAMES[i]: lane for i, lane in enumerate(snap["lanes"])},
    }


def to_move(snap: Dict[str, Any], card: Any, lane: Any) -> Tuple[Optional[str], Optional[int]]:
    """Normalise an answer into (card or None for wait, lane index). Raises InvalidMove outside the options."""
    q = questions(snap)
    if card not in q["card"]["options"]:
        raise InvalidMove(f"card {card!r} is not one of the options")
    if card == "wait":
        return None, None
    if lane not in q["lane"]["options"]:
        raise InvalidMove(f"lane {lane!r} is not one of the options")
    return card, LANE_NAMES.index(lane)
