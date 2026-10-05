# System One Arena

A Clash Royale–style arena that pits **Jev** (a fast "System 1" model) against **Opus 5.5 · high** to show what decision latency costs in a real-time loop.

Open [`arena/index.html`](arena/index.html) in a browser and press **Start match**. No build step or dependencies.

## What it shows

- Two lanes, three towers per side, elixir that regenerates at 1/s and caps at 10.
- Each side's nameplate shows a live "thinking… Ns" / "✓ decided in Ns" status, its elixir bar, elixir wasted at cap, and decisions made.
- The match ends on a king tower kill or after 60 seconds, followed by a result card.

With the default settings Jev wins 3 crowns to 0 in about 38 seconds: 100 decisions to 6, 0 elixir wasted to 20.6.

## How it works

This is a **scripted, deterministic simulation**, not live model calls. Both sides run the same rule-based playbook (defend a threatened lane, support an existing push, otherwise push at 7+ elixir). The only difference between them is the time each decision takes:

| Side | Mean decision time |
| --- | --- |
| Jev | 0.36s |
| Opus 5.5 · high | 5.99s |

The latencies come from the earlier Tetris side-by-side. A decision is chosen from the board state at the moment thinking *starts*, so a slow side acts on a stale view, defends too late, and wastes elixir while capped.

The simulation is a pure function of its config (seed 13), so every playback is identical and safe to re-record.

## Checking the result headlessly

```sh
node scripts/check-sim.js            # Jev 0.36s vs Opus 5.99s
node scripts/check-sim.js 0.36 0.98  # try a different opponent latency
```

## Next steps

- Replace the scripted playbook with real model calls so the latencies and choices are measured, not assumed.
