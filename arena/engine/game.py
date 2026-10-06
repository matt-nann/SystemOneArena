"""The question both players answer.

The engine's snapshot of the board, from the asking side's point of view, is
turned into the same options and wording for Jev and for Sol, so the only
thing that differs between them is the model.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .sim import CARDS

LANE_NAMES = ("left", "right")

# Our unit vocabulary, after the archetypes players use: every unit has a class, a weight, an attack
# (melee or ranged, single target or splash) and what it targets. Matchups are written between classes,
# so a model reasons "splash beats swarm" rather than memorising card names. Numbers come from CARDS.
UNIT_CLASS = {
    "warrior": {"class": "mini tank", "weight": "medium",
                "job": "Sturdy all-rounder: stops pushes and shields ranged support behind it.",
                "strong": "ranged support, splash", "weak": "swarm"},
    "archers": {"class": "ranged support", "weight": "light",
                "job": "Damage from behind a tank; picks off light units before they arrive.",
                "strong": "swarm, splash (it outranges them)", "weak": "mini tank up close"},
    "goblins": {"class": "swarm", "weight": "light",
                "job": "Fast pack of many small hitters that shreds one big target.",
                "strong": "win condition, mini tank", "weak": "splash, ranged support"},
    "brute": {"class": "win condition", "weight": "heavy",
              "job": "Slow, huge-HP push unit that ignores troops and only hits buildings, so it cannot defend.",
              "strong": "towers", "weak": "swarm, mini tank (it never fights back)"},
    "dynamiter": {"class": "splash", "weight": "light",
                  "job": "Throws dynamite from range; every enemy troop near the blast takes the damage.",
                  "strong": "swarm, ranged support, any group", "weak": "mini tank"},
}


def unit_class(name: str) -> str:
    """Short tag for a troop on the board, e.g. "heavy win condition"."""
    u = UNIT_CLASS[name]
    return f"{u['weight']} {u['class']}"


def _card_text(name: str) -> str:
    c, u = CARDS[name], UNIT_CLASS[name]
    units = f"{c['count']} units, {c['hp']} HP each" if c["count"] > 1 else f"1 unit, {c['hp']} HP"
    attack = ("melee" if c["range"] <= 1 else f"ranged {c['range']:g} tiles") + (
        f", splash {c['splash']:g} tiles" if c.get("splash") else ", single target")
    targets = "buildings only" if c.get("bo") else "troops and buildings"
    return (f"{c['name']}: {u['class']}. {u['weight'].capitalize()}, {attack}, targets {targets}. "
            f"Costs {c['cost']} elixir; {units}; {c['dmg']} damage every {c['cd']:g}s; moves {c['speed']:g} tiles/s. "
            f"{u['job']} Strong against {u['strong']}. Weak against {u['weak']}.")


CARD_TEXT = {name: _card_text(name) for name in CARDS}

# The brief every model gets with the card question, in a fixed order: the board, the goal, elixir,
# what a choice controls, towers, placement, the clock, the task. It assumes no knowledge of the genre.
RULES = (
    "The board: you command one side of a real-time battle on a board with two lanes, left and right. "
    "Each side has a king tower at the back and two princess towers in front of it, one guarding each lane. "
    "The goal: destroy the enemy king tower to win at once. If the clock runs out first, the side that destroyed "
    "more enemy towers wins; if that is tied, the side with more tower HP left wins. "
    "Elixir is the energy you spend to deploy troops. You gain 1 elixir per second up to a maximum of 10, and "
    "elixir gained while you are at 10 is lost. Every card costs elixir, and you can only play cards you can "
    "afford right now. "
    "Your choice: once deployed, troops walk down their lane and fight on their own. You only choose which card "
    "to deploy and in which lane. "
    "Towers: princess towers (3800 HP) shoot the nearest enemy troop within 6.5 tiles for 60 damage every 0.8s; "
    "the king tower (6000 HP) does 70 every 0.9s. "
    "Placement: if enemy troops are on your side of that lane, the card lands in front of your princess tower to "
    "defend, or in front of your king tower if that princess tower is destroyed. Otherwise, if you have a mini tank "
    "or win condition in that lane, it lands just behind it to support the push. Otherwise it lands at the bridge. "
    "The clock: it keeps running while you decide, so a slow answer is played on a board that has already moved. "
    "Your task: pick the card to deploy right now and its lane. Deploying troops is how you take towers; waiting "
    "only helps when you are saving for a card you cannot afford yet."
)


class InvalidMove(ValueError):
    """A model answered outside the options it was given."""


def affordable(snap: Dict[str, Any]) -> List[str]:
    return [c for c in snap["hand"] if c in CARDS and CARDS[c]["cost"] <= snap["elixir"]]


def questions(snap: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The two questions, as {name: {instructions, options: {value: meaning}}}."""
    # Cards first and "wait" last, with "wait" described for the elixir actually held: a fast model
    # takes the safest-sounding option, and "keep saving elixir" sounded safe even at 10/10.
    card = {c: CARD_TEXT[c] for c in affordable(snap)}
    e = snap["elixir"]
    card["wait"] = (f"Play nothing. You hold {e}/10 elixir, so waiting now wastes elixir every second."
                    if e >= 9 else "Play nothing yet, to save up for a stronger card you cannot afford.")
    return {
        "card": {"instructions": RULES,
                 "options": card},
        "lane": {
            "instructions": "Which lane does the card go in? Ignored if you play nothing.",
            "options": {
                "left": "The left lane, as seen from your king tower.",
                "right": "The right lane, as seen from your king tower.",
            },
        },
    }


# Where a troop is, in words, from its distance to your king (your towers at ~3, the river at ~11.6,
# theirs at ~20). A fast model reads "at your tower" far better than a raw tile count, and a fallen
# tower changes what "at your tower" means: the troop is then on its way to the king.
def where(tiles: float, my_tower_down: bool = False, their_tower_down: bool = False) -> str:
    if tiles <= 7.5:
        return "past your fallen tower, near your king" if my_tower_down else "at your tower"
    if tiles <= 10.5:
        return "on your side"
    if tiles <= 13.5:
        return "at the bridge"
    if tiles <= 17:
        return "on their side"
    return "past their fallen tower, near their king" if their_tower_down else "at their tower"


def state(snap: Dict[str, Any]) -> Dict[str, Any]:
    """The board as a model sees it. The hand is carried by the card options, not repeated here, and tower
    standing is given per lane in words (no separate crown count, which only restated it)."""
    def lane(d: Dict[str, Any]) -> Dict[str, Any]:
        mine_down, theirs_down = d["your_tower_hp"] <= 0, d["their_tower_hp"] <= 0
        tag = lambda ts: [{"type": t["type"], "class": unit_class(t["type"]), "hp": t["hp"],  # noqa: E731
                           "where": where(t["tiles_from_your_king"], mine_down, theirs_down)}
                          for t in ts if t["type"] in UNIT_CLASS]
        return {"your_tower": "destroyed" if mine_down else f"standing, {d['your_tower_hp']} HP",
                "their_tower": "destroyed" if theirs_down else f"standing, {d['their_tower_hp']} HP",
                "your_troops": tag(d["your_troops"]), "their_troops": tag(d["their_troops"]),
                "enemy_troops_on_your_side": d["enemy_troops_on_your_side"]}
    return {
        "time_left_seconds": snap["timeLeft"],
        "your_elixir": snap["elixir"],
        "king_towers": {"yours": f"{snap['kings']['your_hp']} HP", "theirs": f"{snap['kings']['their_hp']} HP"},
        "lanes": {LANE_NAMES[i]: lane(l) for i, l in enumerate(snap["lanes"])},
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
