"""Mock OpenRouter: the same paths and wire format as the real API.

Follows Aven's ``tests/stubs/llm`` pattern (FIFO scripts plus ``/admin/*``),
but speaks OpenRouter itself, so any OpenRouter client works against it
unchanged, the arena's and Aven's ``packages/llm`` alike:

    POST /api/v1/chat/completions    OpenAI-compatible chat (json_schema honoured)
    POST /api/alpha/decisions        Decisions (noul / choice / score)
    GET  /api/v1/models              the models it has profiles for

Two ways in:

* In-process: ``transport()`` returns an httpx transport; hand it to the
  client and no request leaves the process (what ``OPENROUTER_MOCK=true`` does).
* Over HTTP: ``python -m mock_openrouter`` and point the client at it with
  ``OPENROUTER_BASE_URL=http://localhost:8790/api/v1`` and
  ``OPENROUTER_DECISIONS_URL=http://localhost:8790/api/alpha/decisions``.

How it answers, per request:

1. The next scripted response for that model, if any (``POST /admin/script``).
2. Otherwise the model's profile: a sampled latency, then an injected error
   with probability ``error_rate``, else an answer from ``strategy``.
   ``playbook`` plays the arena sensibly; ``first`` picks the first option;
   ``random`` picks any option; ``wait`` always waits.

Every call is recorded (``GET /admin/calls``).
"""
from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from arena.engine import playbook

STATE_MARKER = "Board state (JSON):\n"


class Profile(BaseModel):
    latency_ms: float = 0.0
    jitter_ms: float = 0.0
    error_rate: float = Field(0.0, ge=0.0, le=1.0)
    # Which error an injected failure is: an HTTP status, or "timeout" (never answers).
    error: str = "502"
    strategy: str = "playbook"


class MockSettings(BaseSettings):
    """``MOCK_*`` env vars. Endpoint defaults apply to any model without its own profile."""

    SEED: int = 7
    PORT: int = 8790
    DECISIONS_LATENCY_MS: float = 350.0  # Jev answers in ~70-500 ms
    DECISIONS_JITTER_MS: float = 120.0
    CHAT_LATENCY_MS: float = 6000.0
    CHAT_JITTER_MS: float = 1500.0
    ERROR_RATE: float = 0.0
    STRATEGY: str = "playbook"
    # Per-model overrides as JSON, e.g. {"openai/gpt-6-sol": {"latency_ms": 2500, "error_rate": 0.05}}
    PROFILES: Dict[str, Profile] = Field(default_factory=dict)

    model_config = SettingsConfigDict(env_prefix="MOCK_", env_file=".env", extra="ignore")


class ScriptBody(BaseModel):
    model: str = "*"
    # Each entry is one response: {"card": "brute", "lane": "left"} or any answer object,
    # {"error": {"status": 429, "message": "..."}}, {"timeout": true}, {"malformed": true},
    # optionally with "latency_ms".
    responses: List[Dict[str, Any]]


class MockState:
    def __init__(self, settings: MockSettings) -> None:
        self.settings = settings
        self.rand = random.Random(settings.SEED)
        self.profiles: Dict[str, Profile] = dict(settings.PROFILES)
        self.scripts: Dict[str, Deque[Dict[str, Any]]] = {}
        self.calls: List[Dict[str, Any]] = []

    def default_profile(self, endpoint: str) -> Profile:
        s = self.settings
        if endpoint == "decisions":
            return Profile(latency_ms=s.DECISIONS_LATENCY_MS, jitter_ms=s.DECISIONS_JITTER_MS, error_rate=s.ERROR_RATE, strategy=s.STRATEGY)
        return Profile(latency_ms=s.CHAT_LATENCY_MS, jitter_ms=s.CHAT_JITTER_MS, error_rate=s.ERROR_RATE, strategy=s.STRATEGY)

    def profile(self, model: str, endpoint: str) -> Profile:
        return self.profiles.get(model) or self.default_profile(endpoint)

    def next_scripted(self, model: str) -> Optional[Dict[str, Any]]:
        for key in (model, "*"):
            q = self.scripts.get(key)
            if q:
                return q.popleft()
        return None

    def latency(self, p: Profile) -> float:
        return max(0.0, self.rand.gauss(p.latency_ms, p.jitter_ms)) if p.jitter_ms else p.latency_ms


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "code": status}}, status_code=status)


# ── answering ───────────────────────────────────────────────────────

def _pick(options: List[str], strategy: str, rand: random.Random) -> str:
    if strategy == "random":
        return rand.choice(options)
    if strategy == "wait" and "wait" in options:
        return "wait"
    return options[0]


def _arena_move(state: Dict[str, Any], card_options: List[str], strategy: str, rand: random.Random) -> Dict[str, str]:
    if strategy == "playbook":
        card, lane = playbook.play(state, card_options)
        return {"card": card, "lane": lane}
    return {"card": _pick(card_options, strategy, rand), "lane": rand.choice(["left", "right"]) if strategy == "random" else "left"}


def _decision_answers(body: Dict[str, Any], strategy: str, rand: random.Random, scripted: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    questions: Dict[str, Any] = body.get("questions") or {}
    arena = None
    card_q = questions.get("card")
    if card_q and card_q.get("type") == "choice" and "wait" in (card_q.get("criteria") or {}):
        arena = scripted or _arena_move(body.get("state") or {}, list(card_q["criteria"]), strategy, rand)
    answers: Dict[str, Any] = {}
    for name, q in questions.items():
        kind, criteria = q.get("type"), q.get("criteria")
        if kind == "choice":
            opts = list(criteria or {})
            choice = (arena or scripted or {}).get(name) or _pick(opts, strategy, rand)
            answers[name] = {"type": "choice", "choice": choice, "confidence": 0.9,
                             "probabilities": {o: (0.9 if o == choice else round(0.1 / max(1, len(opts) - 1), 4)) for o in opts}}
        elif kind == "noul":
            answers[name] = {"type": "noul", "noul": float((scripted or {}).get(name, 0.5))}
        elif kind == "score":
            levels = list(criteria or [])
            score = float((scripted or {}).get(name, (len(levels) - 1) / 2))
            answers[name] = {"type": "score", "score": score, "confidence": 0.9,
                             "probabilities": {str(i): (1.0 if i == round(score) else 0.0) for i in range(len(levels))},
                             "legend": {str(i): lvl for i, lvl in enumerate(levels)}}
    return answers


def _value_for(schema: Dict[str, Any], rand: random.Random, strategy: str) -> Any:
    """A schema-valid value for a generic structured request."""
    if "enum" in schema:
        return _pick(list(schema["enum"]), strategy, rand)
    t = schema.get("type")
    if t == "object":
        return {k: _value_for(v, rand, strategy) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return []
    return {"string": "mock", "integer": 0, "number": 0.0, "boolean": False}.get(t if isinstance(t, str) else "string")


def _chat_content(body: Dict[str, Any], strategy: str, rand: random.Random, scripted: Optional[Dict[str, Any]]) -> str:
    rf = body.get("response_format") or {}
    schema = (rf.get("json_schema") or {}).get("schema") if rf.get("type") == "json_schema" else None
    if not schema:
        return (scripted or {}).get("content", "Mock response.")
    if scripted:
        return json.dumps({k: v for k, v in scripted.items() if k != "latency_ms"})
    props = schema.get("properties") or {}
    last = next((m.get("content") for m in reversed(body.get("messages") or []) if m.get("role") == "user"), "") or ""
    if "card" in props and "lane" in props and STATE_MARKER in last:
        try:
            state = json.loads(last.split(STATE_MARKER, 1)[1])
        except ValueError:
            state = {}
        return json.dumps(_arena_move(state, list(props["card"].get("enum") or ["wait"]), strategy, rand))
    return json.dumps(_value_for(schema, rand, strategy))


# ── app ─────────────────────────────────────────────────────────────

def build_app(settings: Optional[MockSettings] = None) -> FastAPI:
    app = FastAPI(title="Mock OpenRouter")
    st = MockState(settings or MockSettings())
    app.state.mock = st

    async def handle(request: Request, endpoint: str) -> Any:
        if not request.headers.get("authorization", "").startswith("Bearer "):
            return _error(401, "No auth credentials found")
        body = await request.json()
        model = body.get("model") or ""
        profile = st.profile(model, endpoint)
        scripted = st.next_scripted(model)
        call = {"at": time.time(), "endpoint": endpoint, "model": model, "body": body, "scripted": scripted is not None}
        st.calls.append(call)

        delay = (scripted or {}).get("latency_ms", st.latency(profile))
        fault: Optional[Dict[str, Any]] = None
        if scripted and ("error" in scripted or scripted.get("timeout") or scripted.get("malformed")):
            fault = scripted
            scripted = None
        elif scripted is None and profile.error_rate and st.rand.random() < profile.error_rate:
            fault = {"timeout": True} if profile.error == "timeout" else {"error": {"status": int(profile.error), "message": "Mock upstream error"}}
        await asyncio.sleep(delay / 1000)

        if fault and fault.get("timeout"):
            call["status"] = "timeout"
            await asyncio.sleep(3600)  # the client's timeout ends it
        if fault and "error" in fault:
            err = fault["error"]
            call["status"] = int(err.get("status", 500))
            return _error(call["status"], err.get("message", "Mock error"))
        call["status"] = 200
        call["latency_ms"] = delay

        if endpoint == "decisions":
            if fault and fault.get("malformed"):
                return JSONResponse({"model": model})  # no answers
            answers = _decision_answers(body, profile.strategy, st.rand, scripted)
            return {"id": f"gen-dec-{uuid.uuid4().hex[:12]}", "model": model, "provider": "Mock", "answers": answers,
                    "usage": {"cost": 0.0, "input_tokens": len(json.dumps(body)) // 4, "output_tokens": 8 * len(answers)}}

        content = "{not json" if fault and fault.get("malformed") else _chat_content(body, profile.strategy, st.rand, scripted)
        prompt_tokens = len(json.dumps(body.get("messages") or [])) // 4
        return {
            "id": f"gen-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()), "model": model,
            "provider": "Mock",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": len(content) // 4,
                      "total_tokens": prompt_tokens + len(content) // 4},
        }

    @app.post("/api/v1/chat/completions")
    async def chat_completions(request: Request) -> Any:
        return await handle(request, "chat")

    @app.post("/api/alpha/decisions")
    async def decisions(request: Request) -> Any:
        return await handle(request, "decisions")

    @app.get("/api/v1/models")
    async def models() -> Dict[str, Any]:
        return {"data": [{"id": m, "name": f"{m} (mock)"} for m in st.profiles]}

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    # ── admin (Aven stub pattern) ────────────────────────────────────
    @app.post("/admin/script")
    async def script(body: ScriptBody) -> Dict[str, Any]:
        q = st.scripts.setdefault(body.model, deque())
        q.extend(body.responses)
        return {"model": body.model, "queued": len(q)}

    @app.put("/admin/profiles/{model:path}")
    async def set_profile(model: str, profile: Profile) -> Dict[str, Any]:
        st.profiles[model] = profile
        return {"model": model, "profile": profile.model_dump()}

    @app.get("/admin/profiles")
    async def get_profiles() -> Dict[str, Any]:
        return {"profiles": {m: p.model_dump() for m, p in st.profiles.items()},
                "defaults": {e: st.default_profile(e).model_dump() for e in ("decisions", "chat")}}

    @app.get("/admin/calls")
    async def calls(endpoint: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
        out = [c for c in st.calls if (not endpoint or c["endpoint"] == endpoint) and (not model or c["model"] == model)]
        return {"calls": out}

    @app.post("/admin/reset")
    async def reset() -> Dict[str, str]:
        st.scripts.clear()
        st.calls.clear()
        st.profiles = dict(st.settings.PROFILES)
        return {"status": "reset"}

    return app


def transport(app: Optional[FastAPI] = None, settings: Optional[MockSettings] = None) -> httpx.ASGITransport:
    """An httpx transport that answers every OpenRouter request in-process."""
    return httpx.ASGITransport(app=app or build_app(settings))
