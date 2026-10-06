# Recorded matches

## Jev vs Sol (the match in the video)

One real match between **Jev** (`typesafe/jev-1.13`) and **Sol** (`openai/gpt-6-sol`, a frontier model with
reasoning, through chat completions with a strict JSON schema), played on 6 October 2026. Jev took the king tower.

| Match | Winner | Towers | Avg decision | Decisions | Cost |
| --- | --- | --- | --- | --- | --- |
| `20261006T033204917151Z` | Jev, king tower at 28.7s | 3–0 | 0.20s vs 4.0s | 20 vs 6 | Jev $0.0013, Sol $0.0274 |

Per call Jev cost $0.000065 and Sol $0.0039 (61×); for the whole match Jev cost 21× less. Settings: a 45-second
cap, world pace 1.25 (`MATCH_PACE`: troops, attacks, tower fire and elixir 25% faster, while the clock and every
latency stay in real seconds), at most one decision per side per second, and a 1.5-second pre-roll for the
start banner (now 2 seconds).

## Jev vs Luna

Three earlier real matches between **Jev** (`typesafe/jev-1.13`, OpenRouter's Decisions endpoint) and
**Luna** (`openai/gpt-6-luna`, a reasoning model, through chat completions with a strict JSON
schema), played on 6 October 2026. Every move was a live model call. Jev won all three.

| Match | Winner | Towers | Avg decision | Decisions | Cards played | Elixir leaked | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `20261006T024736887518Z` | Jev, on time | 1–0 | 0.17s vs 5.46s | 21 vs 5 | 9 vs 5 | 1.2 vs 9.0 | $0.0026 |
| `20261006T024808453292Z` | Jev, on time | 1–0 | 0.17s vs 4.18s | 14 vs 7 | 11 vs 7 | 0.0 vs 6.5 | $0.0026 |
| `20261006T024840021297Z` | Jev, king tower at 29.8s | 3–0 | 0.18s vs 5.44s | 20 vs 5 | 7 vs 5 | 2.8 vs 9.2 | $0.0025 |

## Settings

Both sides got the same brief, the same card descriptions and the same board, worded by
`arena/engine/game.py`; only the model and how long it took to answer differed.

| | |
| --- | --- |
| Match length | 30 seconds (`MATCH_SECONDS=30`) |
| Decision rate | at most one decision per side per second (`DECISION_MIN_INTERVAL=1`). Luna's ~5s answers never reach the cap; it only holds Jev back, so Jev did not win on volume. |
| Call budget | 60 per match (`MAX_CALLS_PER_MATCH=60`), never reached |
| Seed, ticks | `MATCH_SEED=13`, engine at 30 Hz, frames at 20 Hz |

## What is in each match

- `<id>.jsonl`: one JSON object per line.
  - `start`: the players, whether OpenRouter was mocked, and the engine settings (`config`).
  - `decision`: per model call, the board snapshot, the exact request (`sent`), the model's raw
    answer (`received`), the move it became, the latency, the engine time it was asked and
    answered, token usage and cost.
  - `result`: winner, per-side stats, calls and cost.
- `<id>.frames.jsonl`: every frame the viewer drew, 20 per second.

No API key is in any of these files.

## Watch, rerun, record (no model calls, no key)

```sh
uv sync
uv run python -m arena                              # then open http://localhost:8000/?replay=<id>
uv run python tools/rerun.py <id>                   # replay the decisions through the engine and check the result
uv run --group tools python tools/record.py <id>    # write <id>.mp4, 1080x1920, with the server running
```

`tools/rerun.py` runs a fresh engine with the logged settings and hands each logged answer back
at the engine time it originally landed. The engine is deterministic, so it reproduces the logged
result exactly: what the video shows is what the engine did with those answers.
