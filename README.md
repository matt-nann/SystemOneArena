# System One Arena

**Sol vs Jev** in a Clash Royale–style tower battle. Every move is a real model call through OpenRouter, and the match clock keeps running while a model thinks, so a slow model plays on a board that has already moved.

- **Jev**: TypeSafe's "System One" decision model (`typesafe/jev-1.13`), called through OpenRouter's Decisions endpoint.
- **Sol**: an OpenRouter chat model (default `openai/gpt-6-sol`; set `SOL_MODEL`), called through chat completions with a strict JSON schema.

The stack follows [Aven](https://github.com/matt-nann/aven): Python with uv, a FastAPI service shaped like `services/sandbox-service`, pydantic-settings, httpx and the openai SDK for OpenRouter (mirroring `packages/llm`), SSE via `StreamingResponse` (as in `brain-backend`), pytest + respx, and a Dockerfile + `railway.toml` for Railway.

## Architecture

```
            ┌──────────────── arena service (source of truth) ────────────────┐
viewers ◀── │ SSE frames ◀─ MatchRunner ─ ticks ─▶ engine (arena/engine/sim.py) │
(browser,   │                    │                                              │
read-only)  │                    └─ decision requests ─▶ Players ─▶ OpenRouterClient ──▶ openrouter.ai
            └──────────────────────────────────────────────────────┬──────────┘
                                                                   └──▶ mock_openrouter (in-process or HTTP)
```

- **The engine runs on the server**, in `arena/engine/sim.py`. It is pure and synchronous. When a side has a decision to make, it queues a request; the runner sends it to the model as an asyncio task and hands the answer back when it lands. The clock does not wait.
- **The browser only watches.** `web/index.html` draws the frames the service streams over `GET /api/stream` (20 per second, interpolated to 60 fps). It holds no game state and cannot change a match. The only control is **Start match**, which needs the admin token once `ARENA_ADMIN_TOKEN` is set.
- **One match at a time**, and every viewer sees the same one.
- **Everything is recorded** under `LOG_DIR`. `<id>.jsonl` holds every decision (the board snapshot, the exact request, the answer, the latency, the usage, or the error) and the result. `<id>.frames.jsonl` holds every frame, so `/?replay=<id>` plays a match back exactly as it streamed. That is useful for recording a clean video.

## Run it

```sh
uv sync
cp .env.example .env                   # add OPENROUTER_API_KEY, check SOL_MODEL
uv run python -m arena                 # http://localhost:8000
```

Open `http://localhost:8000` and press **Start match**. With `ARENA_ADMIN_TOKEN` set, only `http://localhost:8000/?admin=<token>` shows the button. Everyone else just watches.

## Mock OpenRouter

`mock_openrouter/` stands in for OpenRouter itself. It serves the same paths and wire format (`POST /api/v1/chat/completions`, `POST /api/alpha/decisions`, `GET /api/v1/models`), so the real client code runs unchanged against it. It follows the pattern of Aven's `tests/stubs/llm`, scripted responses plus `/admin/*`, but speaks OpenRouter's format instead of Aven's internal one, and it also covers Decisions.

**In-process** (no second process, no key):

```sh
OPENROUTER_MOCK=true uv run python -m arena
```

The OpenRouter client gets an httpx transport that answers every request inside the process.

**Over HTTP** (for anything that speaks OpenRouter, including Aven's `packages/llm`):

```sh
uv run python -m mock_openrouter       # http://localhost:8790
OPENROUTER_BASE_URL=http://localhost:8790/api/v1 \
OPENROUTER_DECISIONS_URL=http://localhost:8790/api/alpha/decisions \
uv run python -m arena
```

**How it answers.** For each request, the mock uses the next scripted response for that model if one is queued. Otherwise it uses the model's profile:

1. It waits a sampled latency.
2. With probability `error_rate`, it fails, either with an HTTP status or with a timeout (it never answers).
3. Otherwise it answers with the profile's `strategy`. `playbook` plays the arena sensibly, `first` and `random` pick options, and `wait` always waits.

Requests that aren't arena moves get schema-valid defaults: `noul` / `choice` / `score` for Decisions, enum or typed values for `json_schema`. Defaults come from `MOCK_*` variables (see `.env.example`). By default Jev answers in about 350 ms and Sol in about 6 s.

| Admin endpoint | Does |
| --- | --- |
| `POST /admin/script` `{"model": "openai/gpt-6-sol", "responses": [...]}` | Queue responses: `{"card": "giant", "lane": "left"}`, `{"error": {"status": 429, "message": "..."}}`, `{"timeout": true}`, `{"malformed": true}`, each optionally with `"latency_ms"`. `"model": "*"` matches any model. |
| `PUT /admin/profiles/{model}` | Set a model's `latency_ms`, `jitter_ms`, `error_rate`, `error`, `strategy`. |
| `GET /admin/profiles` | The current profiles and endpoint defaults. |
| `GET /admin/calls?endpoint=&model=` | Every request received. |
| `POST /admin/reset` | Clear scripts, calls and profile changes. |

A match logs `"mock": true` whenever any OpenRouter URL is not openrouter.ai, and the viewer and replays say so on screen.

## Deploy

The service is one long-running process: it holds the match clock and the open SSE connections. That means it needs a container host, not serverless functions. It deploys to **Railway** the way Aven's services do: `railway.toml` builds the `Dockerfile` and health-checks `/health`. Keep one replica, because the match lives in that process's memory.

Set `OPENROUTER_API_KEY`, `SOL_MODEL` and `ARENA_ADMIN_TOKEN` in the service's variables. Logs go to `LOG_DIR` on the container's disk. Mount a volume there to keep matches and replays across deploys.

The same image runs the mock: start it with `python -m mock_openrouter`.

## API

| | |
| --- | --- |
| `GET /` | The viewer. `?replay=<id>` plays a recorded match; `?admin=<token>` enables Start. |
| `GET /api/config` | Players, models, mock flag, whether this caller may start a match. |
| `GET /api/stream` | SSE: `hello`, then a `frame` event per frame (`{match, players, frame}`). |
| `POST /api/matches` | Start a match (`Authorization: Bearer <ARENA_ADMIN_TOKEN>` when set). `409` if one is running. |
| `GET /api/matches` | Recorded matches with results. |
| `GET /api/matches/{id}/frames` | A recorded match's frames (NDJSON). |
| `GET /health`, `GET /ready` | Probes. |

## Tests

```sh
uv run pytest
```

The suite runs without network. It covers the requests each player sends (respx at OpenRouter's real URLs), the mock plugged into the real client (scripts, faults, timeouts, profiles, generic Decisions/chat requests), the engine (determinism, errors, stale answers), a full match through the runner, and the HTTP surface including the admin token.

## Layout

| Path | What it is |
| --- | --- |
| `arena/engine/sim.py` | The game engine: board, troops, towers, elixir, decision requests, frames |
| `arena/engine/game.py` | The question, options and state both models receive |
| `arena/engine/playbook.py` | Rule-based player on the model-facing state (the mock's default strategy) |
| `arena/openrouter.py` | OpenRouter client: Decisions (httpx) and structured chat (openai SDK) |
| `arena/players.py` | Jev and Sol: request building and answer parsing |
| `arena/match.py` | Runs a match on the server clock, fans frames out, writes logs |
| `arena/app.py`, `arena/__main__.py` | FastAPI app and entry point |
| `mock_openrouter/` | Mock OpenRouter (FastAPI) and its in-process transport |
| `web/index.html` | Read-only viewer |
