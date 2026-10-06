from __future__ import annotations

from typing import Any, Dict

import pytest

from arena.config import Settings
from mock_openrouter.app import MockSettings, build_app


@pytest.fixture
def snap() -> Dict[str, Any]:
    """A board snapshot from one side's point of view: 4 elixir, so Brute (5) is not an option."""
    return {
        "timeLeft": 42,
        "elixir": 4,
        "hand": ["warrior", "brute", "goblins", "archers"],
        "crowns": {"you": 0, "opponent": 1},
        "kings": {"your_hp": 6000, "their_hp": 6000},
        "lanes": [
            {"your_tower_hp": 3800, "their_tower_hp": 1200, "your_troops": [],
             "their_troops": [{"type": "brute", "hp": 2000, "tiles_from_your_king": 6.0}], "enemy_troops_on_your_side": 1},
            {"your_tower_hp": 0, "their_tower_hp": 3800, "your_troops": [], "their_troops": [], "enemy_troops_on_your_side": 0},
        ],
    }


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, OPENROUTER_API_KEY="or-key", LOG_DIR=tmp_path, MATCH_ARCHIVE_DIR=tmp_path / "archive",
                    MATCH_PREROLL_SECONDS=0)


@pytest.fixture
def mock_app():
    """Mock OpenRouter with no latency, so tests run fast."""
    return build_app(MockSettings(_env_file=None, DECISIONS_LATENCY_MS=0, DECISIONS_JITTER_MS=0,
                                  CHAT_LATENCY_MS=0, CHAT_JITTER_MS=0))
