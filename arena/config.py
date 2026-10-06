"""Every environment variable the arena reads (pydantic-settings, as in Aven).

The OpenRouter names match Aven's ``packages/llm/config.py`` so one ``.env``
works for both.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── OpenRouter (same names as Aven) ──────────────────────────────
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_DECISIONS_URL: str = "https://openrouter.ai/api/alpha/decisions"
    OPENROUTER_APP_NAME: str = "System One Arena"
    OPENROUTER_APP_URL: str = "https://github.com/matt-nann/SystemOneArena"

    # Mock every OpenRouter request in-process (mock_openrouter, mounted as an
    # httpx transport). No key needed, nothing leaves the machine.
    OPENROUTER_MOCK: bool = False

    # ── Players ──────────────────────────────────────────────────────
    JEV_NAME: str = "Jev"
    JEV_MODEL: str = "typesafe/jev-1.13"
    JEV_TIMEOUT_SECONDS: float = 20.0
    SOL_NAME: str = "Sol"
    SOL_MODEL: str = "openai/gpt-6-sol"
    # OpenRouter reasoning.effort (low / medium / high). Empty sends nothing.
    SOL_REASONING_EFFORT: str = ""
    SOL_MAX_TOKENS: int = 4000
    SOL_TIMEOUT_SECONDS: float = 60.0
    # How Sol is asked: "chat" (structured chat completion) or "decisions" (the Decisions endpoint,
    # like Jev). SOL_API=decisions with SOL_MODEL=typesafe/jev-1.13 plays Jev against Jev.
    SOL_API: str = "chat"
    # Sol's label in the viewer. Empty picks one from SOL_API: "Fast decision model" or "Frontier model".
    SOL_ROLE: str = ""

    # ── Match ────────────────────────────────────────────────────────
    MATCH_SECONDS: float = 60.0
    MATCH_SEED: int = 13
    # Engine ticks and frames streamed to viewers, per second.
    TICK_HZ: int = 30
    FRAME_HZ: int = 20
    # Seconds the board is shown frozen at 0:00 before the clock starts, for the viewer's start banner.
    # No model is asked anything until the clock starts, and these frames are not written to the replay.
    MATCH_PREROLL_SECONDS: float = 1.5
    # Cost controls. A gap between one side's calls (0 asks again as soon as an answer lands),
    # and a cap on calls per match: when it is reached no more requests go out and the match ends.
    DECISION_MIN_INTERVAL: float = 0.0
    MAX_CALLS_PER_MATCH: int = 0

    # ── Service ──────────────────────────────────────────────────────
    PORT: int = 8000
    # Set in any deployment: starting a match then needs `Authorization: Bearer <token>`.
    ARENA_ADMIN_TOKEN: str = ""
    LOG_DIR: Path = Path("logs")
    # Matches committed to the repo (tools/archive.py): listed and replayable like the ones in LOG_DIR.
    MATCH_ARCHIVE_DIR: Path = Path("matches")
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_mock(self) -> bool:
        """True unless every request goes to the real OpenRouter (in-process mock, or a URL pointed elsewhere)."""
        real = "https://openrouter.ai/"
        return self.OPENROUTER_MOCK or not (self.OPENROUTER_BASE_URL.startswith(real)
                                            and self.OPENROUTER_DECISIONS_URL.startswith(real))


@lru_cache
def get_settings() -> Settings:
    return Settings()
