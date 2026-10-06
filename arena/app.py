"""HTTP surface. The service owns the game; browsers only watch.

    GET  /                       the viewer (web/index.html)
    GET  /static/*               viewer script, demo engine, Tiny Swords art (web/)
    GET  /health, /ready
    GET  /api/config             players, models, whether this viewer may start a match
    GET  /api/stream             SSE: one `frame` event per streamed frame
    POST /api/matches            start a match (Bearer ARENA_ADMIN_TOKEN when one is set)
    GET  /api/matches            recorded matches and their results
    GET  /api/matches/{id}/frames    a recorded match's frames, for replay
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .engine.sim import CARDS
from .match import MatchInProgress, MatchRunner

WEB = Path(__file__).resolve().parent.parent / "web"
PING_SECONDS = 15


def _sse(event: str, data_json: str) -> str:
    return f"event: {event}\ndata: {data_json}\n\n"


def build_app(settings: Settings, runner: MatchRunner, *, lifespan: Any = None) -> FastAPI:
    app = FastAPI(title="System One Arena", lifespan=lifespan)

    def may_start(authorization: Optional[str]) -> bool:
        token = settings.ARENA_ADMIN_TOKEN
        return not token or authorization == f"Bearer {token}"

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict:
        return {"status": "ready", "running": runner.running}

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/api/config")
    async def config(authorization: Optional[str] = Header(None)) -> dict:
        return {
            "players": runner.players.roster,
            "cards": {k: {"name": c["name"], "cost": c["cost"]} for k, c in CARDS.items()},
            "mock": settings.is_mock,
            "admin_required": bool(settings.ARENA_ADMIN_TOKEN),
            "can_start": may_start(authorization),
            "running": runner.running,
            "match": runner.match_id,
        }

    @app.post("/api/matches", status_code=201)
    async def start(authorization: Optional[str] = Header(None)) -> dict:
        if not may_start(authorization):
            raise HTTPException(401, "starting a match needs the admin token")
        try:
            return {"id": runner.start()}
        except MatchInProgress as exc:
            raise HTTPException(409, f"match {exc} is still running")

    @app.get("/api/matches")
    async def matches() -> dict:
        return {"matches": runner.matches()}

    @app.get("/api/matches/{match_id}/frames")
    async def frames(match_id: str) -> FileResponse:
        if not re.fullmatch(r"[\w-]{1,64}", match_id):
            raise HTTPException(404, "no such match")
        path = next((d / f"{match_id}.frames.jsonl" for d in (Path(settings.LOG_DIR), Path(settings.MATCH_ARCHIVE_DIR))
                     if (d / f"{match_id}.frames.jsonl").exists()), None)
        if path is None:
            raise HTTPException(404, "no such match")
        return FileResponse(path, media_type="application/x-ndjson")

    @app.get("/api/stream")
    async def stream() -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            q = runner.add_subscriber()
            try:
                yield _sse("hello", json.dumps({"players": runner.players.roster, "match": runner.match_id}))
                while True:
                    try:
                        msg = await asyncio.wait_for(q.get(), PING_SECONDS)
                    except TimeoutError:
                        yield ": ping\n\n"  # keep the connection alive between matches
                        continue
                    yield _sse("frame", json.dumps(msg, separators=(",", ":")))
            finally:
                runner.remove_subscriber(q)

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app
