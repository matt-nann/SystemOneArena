"""Replay a recorded match through the engine, with no model calls, and check it ends the same way.

    uv run python tools/rerun.py <match id>        # looks in matches/ then logs/
    uv run python tools/rerun.py path/to/<id>.jsonl

Every decision the models made is in the match log with the engine time its answer landed. This
runs a fresh engine with the logged settings, steps it at the logged tick rate, and hands each
answer back at the same moment the live match did. The engine is deterministic, so the result
should match the logged one exactly: the video shows what the engine did with those answers.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from arena.engine.sim import Sim, SimConfig  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def find(arg: str) -> Path:
    p = Path(arg)
    if p.suffix == ".jsonl" and p.exists():
        return p
    for d in (ROOT / "matches", ROOT / "logs"):
        if (d / f"{arg}.jsonl").exists():
            return d / f"{arg}.jsonl"
    sys.exit(f"no log for {arg!r} in matches/ or logs/")


def rerun(events: List[Dict[str, Any]], overrides: Dict[str, Any]) -> Dict[str, Any]:
    start = next(e for e in events if e["event"] == "start")
    cfg = {**{"duration": start["duration"]}, **start.get("config", {}), **overrides}
    tick = cfg.pop("tick_hz", 30)
    cfg.pop("frame_hz", None)
    sim = Sim(SimConfig(**{k: v for k, v in cfg.items() if k in SimConfig.__dataclass_fields__}))
    answers = sorted((e for e in events if e["event"] == "decision"), key=lambda e: (e["answered_at"], e["request"]))
    budget = next((e for e in events if e["event"] == "budget"), None)
    i, asked = 0, set()
    while not sim.over:
        sim.step(1 / tick)
        asked |= {r.id for r in sim.take_requests()}
        if budget and sim.t >= budget["at"] - 1e-9:
            sim.cfg.duration = min(sim.cfg.duration, sim.t)
        while i < len(answers) and answers[i]["answered_at"] <= sim.t + 1e-6:
            a = answers[i]
            i += 1
            if a["request"] not in asked:
                raise SystemExit(f"request {a['request']} was never asked: the rerun has diverged at t={sim.t:.3f}")
            side = a.get("side", 0 if a["player"] == "jev" else 1)
            if a.get("error"):
                sim.resolve(side, a["request"], error=a["error"])
            else:
                sim.resolve(side, a["request"], card=a["card"], lane=a["lane"], model_ms=a.get("ms"))
    return sim.result()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = find(sys.argv[1])
    # Older logs did not record the settings; pass them as key=value (e.g. min_interval=1).
    overrides = {k: float(v) if "." in v else int(v) for k, v in (a.split("=", 1) for a in sys.argv[2:])}
    events = [json.loads(line) for line in path.read_text().splitlines()]
    logged = next((e["result"] for e in events if e["event"] == "result"), None)
    got = rerun(events, overrides)
    keys = ("winner", "reason", "seconds")
    side_keys = ("decisions", "plays", "crowns", "elixir_wasted")
    same = logged is not None and all(got[k] == logged[k] for k in keys) and all(
        g[k] == l[k] for g, l in zip(got["sides"], logged["sides"]) for k in side_keys)
    names = [p["name"] for p in next(e for e in events if e["event"] == "start")["players"]]
    print(f"{path.name}: {names[0]} vs {names[1]}, replayed {sum(1 for e in events if e['event'] == 'decision')} answers, no model calls")
    for i, s in enumerate(got["sides"]):
        print(f"  {names[i]:<6} decisions {s['decisions']:>3}  cards {s['plays']:>2}  towers {s['crowns']}  elixir leaked {s['elixir_wasted']}")
    print(f"  winner {names[got['winner']]} ({got['reason']}, {got['seconds']}s)")
    print("matches the logged result" if same else f"DIFFERS from the logged result: {logged}")
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
