"""Ask Jev about hand-made board states and score its answers.

    uv run python tools/jev_probe.py            # one real call per scenario (about $0.00004 each)
    uv run python tools/jev_probe.py --show 2   # print what scenario 2 sends, no call

Each scenario is a snapshot in the engine's shape plus the answers a sensible
player would accept. Use it to tune the wording in arena/engine/game.py
without paying for whole matches.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict, List, Optional, Set

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from arena.config import Settings  # noqa: E402
from arena.engine import game  # noqa: E402
from arena.openrouter import OpenRouterClient, OpenRouterError  # noqa: E402
from arena.players import jev_request  # noqa: E402

# Distances are tiles from your own king: your princess towers stand at 3.1, the river is at 11.6,
# the enemy princess towers at 20.1. Anything at 14.1 or less is on your half.
OWN_TOWER, RIVER, ENEMY_TOWER = 3.1, 11.6, 20.1


def troop(kind: str, k: float, hp: Optional[int] = None) -> Dict[str, Any]:
    full = {"warrior": 900, "archers": 220, "goblins": 70, "brute": 2200, "dynamiter": 200}[kind]
    return {"type": kind, "hp": hp or full, "tiles_from_your_king": k}


def board(elixir: int, hand: List[str], left: Dict[str, Any] = None, right: Dict[str, Any] = None,
          time_left: int = 40) -> Dict[str, Any]:
    def lane(d: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        d = d or {}
        theirs = d.get("theirs", [])
        return {"your_tower_hp": d.get("my_hp", 3800), "their_tower_hp": d.get("their_hp", 3800),
                "your_troops": d.get("mine", []), "their_troops": theirs,
                "enemy_troops_on_your_side": sum(1 for t in theirs if t["tiles_from_your_king"] <= 14.1)}
    return {"timeLeft": time_left, "elixir": elixir, "hand": hand, "crowns": {"you": 0, "opponent": 0},
            "kings": {"your_hp": 6000, "their_hp": 6000}, "lanes": [lane(left), lane(right)]}


HAND = ["warrior", "archers", "brute", "goblins"]
SCENARIOS = [
    ("Enemy Brute at your left tower, Goblins in hand",
     board(6, HAND, left={"theirs": [troop("brute", 5.0)]}), {"goblins", "warrior"}, "left"),
    ("Enemy Brute just crossed the right bridge",
     board(4, ["warrior", "archers", "dynamiter", "goblins"], right={"theirs": [troop("brute", 10.5)]}), {"goblins", "warrior"}, "right"),
    ("Four enemy Goblins units at your right tower, Dynamiter in hand",
     board(5, ["warrior", "dynamiter", "brute", "archers"], right={"theirs": [troop("goblins", 5.0)] * 4}), {"dynamiter", "archers"}, "right"),
    ("Enemy Archers at your left tower",
     board(5, HAND, left={"theirs": [troop("archers", 5.5), troop("archers", 5.8)]}), {"warrior", "goblins"}, "left"),
    ("Your Brute is at the enemy right tower: support it",
     board(4, ["warrior", "archers", "dynamiter", "goblins"], right={"mine": [troop("brute", 18.0)]}), {"archers", "dynamiter", "goblins", "warrior"}, "right"),
    ("Enemy right tower nearly down, empty board, full elixir",
     board(10, HAND, right={"their_hp": 400}), {"brute", "warrior", "goblins", "archers"}, "right"),
    ("Full elixir, empty board", board(10, HAND), {"brute", "warrior", "archers", "goblins"}, None),
    ("2 elixir, empty board: save up", board(2, HAND), {"wait"}, None),
    ("Enemy Warrior at your right tower, 3 elixir",
     board(3, ["warrior", "brute", "dynamiter", "archers"], right={"theirs": [troop("warrior", 5.0)]}), {"warrior", "archers", "dynamiter"}, "right"),
    ("Your left tower is down; enemy Warrior heading for your king",
     board(5, HAND, left={"my_hp": 0, "theirs": [troop("warrior", 4.0)]}), {"warrior", "goblins", "archers"}, "left"),
    ("Enemy Goblins at your left tower, no Dynamiter in hand",
     board(6, HAND, left={"theirs": [troop("goblins", 5.0)] * 4}), {"archers"}, "left"),
    ("Your Warrior pushing left, enemy Brute at your right tower",
     board(4, ["archers", "goblins", "dynamiter", "brute"], left={"mine": [troop("warrior", 16.0)]},
           right={"theirs": [troop("brute", 5.0)]}), {"goblins"}, "right"),
    ("Enemy Dynamiter at your right tower: do not feed it Goblins",
     board(5, HAND, right={"theirs": [troop("dynamiter", 6.0)]}), {"warrior", "archers"}, "right"),
    ("Left tower down: Brute and Archers heading for your king, your Warrior pushing right",
     board(7, ["warrior", "dynamiter", "goblins", "archers"], time_left=23,
           left={"my_hp": 0, "their_hp": 2650,
                 "theirs": [troop("brute", 6.2, 1840), troop("archers", 8.9), troop("archers", 9.3, 140)]},
           right={"my_hp": 2210, "mine": [troop("warrior", 15.4, 610)],
                  "theirs": [troop("goblins", 14.8, 70), troop("goblins", 15.1, 25)]}),
     {"goblins", "warrior"}, "left"),
]


async def run() -> None:
    s = Settings()
    client = OpenRouterClient(s)
    passed, cost = 0, 0.0
    try:
        for i, (name, snap, good, lane) in enumerate(SCENARIOS):
            raw = await client.decide(jev_request(s, snap), timeout=20)
            a = raw.get("answers") or {}
            card, where = a.get("card", {}).get("choice"), a.get("lane", {}).get("choice")
            conf = a.get("card", {}).get("confidence")
            ok = card in good and (card == "wait" or lane is None or where == lane)
            passed += ok
            cost += float((raw.get("usage") or {}).get("cost") or 0)
            want = "/".join(sorted(good)) + (f" {lane}" if lane else "")
            print(f"{'PASS' if ok else 'FAIL'} {i:>2} {name:<58} {card} {where if card != 'wait' else ''}"
                  f"  (conf {conf})  want {want}")
    except OpenRouterError as exc:
        print("error:", exc)
    finally:
        await client.aclose()
    print(f"{passed}/{len(SCENARIOS)} passed, cost ${cost:.6f}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--show":
        print(json.dumps(jev_request(Settings(), SCENARIOS[int(sys.argv[2])][1]), indent=1))
    else:
        asyncio.run(run())
