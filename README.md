# System One Arena

**Sol vs Jev** in a Clash Royale–style tower battle. In a live match every move is a real model call through OpenRouter, and the match clock keeps running while a model thinks, so a slow model plays on a board that has already moved.

- **Jev**: TypeSafe's "System One" decision model (`typesafe/jev-1.13`), called through OpenRouter's Decisions endpoint.
- **Sol**: an OpenRouter chat model (default slug `openai/gpt-6-sol`; change it with `SOL_MODEL`), called through chat completions with a strict JSON schema.

Both are called the same way [Aven](https://github.com/matt-nann/aven) calls them (`packages/llm/decisions.py` and `packages/llm/service.py`).

## Run it

Needs Node 20 or later. There are no dependencies to install.

```sh
cp .env.example .env      # add OPENROUTER_API_KEY, check SOL_MODEL
npm start                 # http://localhost:8787
```

To test the full pipeline without calling any model:

```sh
npm run dry               # canned answers: Jev after 350 ms, Sol after 6 s
```

Opening `arena/index.html` directly as a file (or as the published artifact) plays the **scripted preview** instead: both sides run a built-in playbook with assumed decision times.

## How a live match works

1. Whenever a side has no decision in flight and can afford at least one card, the page sends a snapshot of the board to `POST /api/decide/{jev|sol}`. The snapshot is from that side's point of view: time left, its elixir and hand, tower HP, troops per lane and crowns.
2. The server turns the snapshot into **the same two questions for both models**: which card to play (only affordable cards, plus `wait`) and which lane. Jev gets them as Decisions `choice` questions. Sol gets them as enum fields in a strict JSON schema, with `provider.require_parameters` so OpenRouter only routes to upstreams that enforce the schema.
3. The answer is played on the board when it arrives. Where the card goes (in front of your own tower when defending, otherwise at the bridge) is fixed by the board at the moment the question was asked, so a slow answer can be a late defence.
4. A failed or timed-out call counts as a wait and appears on the nameplate and in the result card.

The API key stays in the server. The page never sees it.

Every decision is written to `logs/<match>.jsonl`, with the snapshot, the exact request body, the answer, the model latency and usage. The final scoreboard is written there too. These logs are the evidence behind any numbers you post.

Keep the tab visible during a match: browsers pause animation in background tabs, which pauses the match clock.

## Cost

Jev answers in roughly 70–500 ms, so it makes around 100–200 calls in a 60-second match. Sol makes one call per decision, which is far fewer if it is slow. Check OpenRouter's pricing for both models before running many matches.

## Other commands

```sh
npm test                              # request/response handling, no network
npm run check-sim                     # scripted preview result, headless
node scripts/check-sim.js 0.36 0.98   # scripted preview with other latencies
```

## Layout

| Path | What it is |
| --- | --- |
| `arena/index.html` | The arena page: simulation, rendering, live/scripted switch |
| `server/server.js` | Local server: serves the page, `/api/config`, `/api/decide/:player`, `/api/result` |
| `server/players.js` | OpenRouter calls for Jev (Decisions) and Sol (chat completions), plus the dry run |
| `server/game.js` | The shared question, options and board state both models receive |
| `test/` | `node --test` suite |
