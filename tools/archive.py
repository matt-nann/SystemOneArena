"""Copy a match from logs/ into matches/, the folder committed to the repo.

    uv run python tools/archive.py <match id>

matches/<id>.jsonl holds every decision (the board each model saw, the exact request, what it
answered, how long it took, usage and cost) and matches/<id>.frames.jsonl every frame. The server
lists and replays matches/ alongside logs/ (/?replay=<id>), and tools/rerun.py replays the
decisions through the engine without calling a model. Logs never contain the API key.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(match_id: str) -> None:
    src, dest = ROOT / "logs", ROOT / "matches"
    files = [src / f"{match_id}.jsonl", src / f"{match_id}.frames.jsonl"]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        sys.exit(f"not in logs/: {', '.join(missing)}")
    if "sk-or-" in files[0].read_text():
        sys.exit("the log contains something that looks like an API key: not archiving")
    dest.mkdir(exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    print(f"archived {match_id} to matches/ ({sum((dest / f.name).stat().st_size for f in files) // 1024} KB)")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
