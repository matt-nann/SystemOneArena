"""Run the arena service: `python -m arena` (same shape as Aven's sandbox-service)."""
from __future__ import annotations

import contextlib
import socket
import sys

import uvicorn
from loguru import logger

from arena.app import build_app
from arena.config import get_settings
from arena.match import MatchRunner
from arena.openrouter import OpenRouterClient, OpenRouterError
from arena.players import Players

settings = get_settings()
logger.remove()
logger.add(sys.stderr, level=settings.LOG_LEVEL.upper())


def create_app():
    transport = None
    if settings.OPENROUTER_MOCK:
        from mock_openrouter.app import MockSettings, transport as mock_transport

        transport = mock_transport(settings=MockSettings())
        logger.warning("OPENROUTER_MOCK is on: every OpenRouter request is answered in-process by mock_openrouter")
    try:
        client = OpenRouterClient(settings, transport=transport)
    except OpenRouterError as exc:
        sys.exit(f"{exc}. Put it in .env, or set OPENROUTER_MOCK=true to play without calling any model.")
    runner = MatchRunner(settings, Players(settings, client))

    @contextlib.asynccontextmanager
    async def lifespan(app):
        for p in runner.players.roster:
            logger.info("{}: {}{}", p["name"], p["model"], f" · {p['effort']}" if p["effort"] else "")
        yield
        await runner.stop()
        await client.aclose()

    return build_app(settings, runner, lifespan=lifespan)


def main() -> None:
    logger.info("System One Arena on http://localhost:{}", settings.PORT)
    try:
        # Dual-stack, so the service accepts both IPv4 and IPv6 connections.
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError:
        uvicorn.run(create_app(), host="0.0.0.0", port=settings.PORT)
        return
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
    sock.bind(("::", settings.PORT))
    uvicorn.run(create_app(), fd=sock.fileno())


if __name__ == "__main__":
    main()
