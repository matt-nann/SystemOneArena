"""Copy the art the viewer uses out of Pixel Frog's Tiny Swords, the CC0 release.

    uv run python tools/tinyswords.py "~/Downloads/Tiny Swords.zip"

Use the download labelled "TS_old version_CC0 Licensed" (Update 010) from
https://pixelfrog-assets.itch.io/tiny-swords. That release is CC0, so the files
are committed under web/tinyswords/. The current Tiny Swords release has a
different license that forbids redistribution: do not import it here.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "tinyswords"
ROOT = "Tiny Swords (Update 010)/"

FILES = {
    "Factions/Knights/Troops/Warrior/Blue/Warrior_Blue.png": "blue/warrior",
    "Factions/Knights/Troops/Warrior/Red/Warrior_Red.png": "red/warrior",
    "Factions/Knights/Troops/Archer/Blue/Archer_Blue.png": "blue/archer",
    "Factions/Knights/Troops/Archer/Red/Archer_Red.png": "red/archer",
    "Factions/Goblins/Troops/Torch/Blue/Torch_Blue.png": "blue/torch",
    "Factions/Goblins/Troops/Torch/Red/Torch_Red.png": "red/torch",
    "Factions/Goblins/Troops/TNT/Blue/TNT_Blue.png": "blue/tnt",
    "Factions/Goblins/Troops/TNT/Red/TNT_Red.png": "red/tnt",
    "Factions/Knights/Troops/Pawn/Blue/Pawn_Blue.png": "blue/pawn",
    "Factions/Knights/Troops/Pawn/Red/Pawn_Red.png": "red/pawn",
    "Factions/Knights/Buildings/Tower/Tower_Blue.png": "blue/tower",
    "Factions/Knights/Buildings/Tower/Tower_Red.png": "red/tower",
    "Factions/Knights/Buildings/Castle/Castle_Blue.png": "blue/castle",
    "Factions/Knights/Buildings/Castle/Castle_Red.png": "red/castle",
    "Factions/Knights/Buildings/Tower/Tower_Destroyed.png": "ruins/tower",
    "Factions/Knights/Buildings/Castle/Castle_Destroyed.png": "ruins/castle",
    "Factions/Knights/Troops/Archer/Arrow/Arrow.png": "fx/arrow",
    "Factions/Goblins/Troops/TNT/Dynamite/Dynamite.png": "fx/dynamite",
    "Factions/Knights/Troops/Dead/Dead.png": "fx/dead",
    "Effects/Explosion/Explosions.png": "fx/explosion",
    "Effects/Fire/Fire.png": "fx/fire",
    "Terrain/Water/Water.png": "terrain/water",
    "Terrain/Water/Foam/Foam.png": "terrain/foam",
    "Terrain/Water/Rocks/Rocks_01.png": "terrain/water_rocks",
    "Terrain/Bridge/Bridge_All.png": "terrain/bridge",
    "Resources/Trees/Tree.png": "decor/tree",
    "Resources/Sheep/HappySheep_Idle.png": "decor/sheep",
    **{f"Deco/{i:02d}.png": f"decor/{i:02d}" for i in range(1, 19)},
}

LICENSE = """Tiny Swords (Update 010) by Pixel Frog
https://pixelfrog-assets.itch.io/tiny-swords

Released under CC0 1.0 (public domain) as the download "TS_old version_CC0 Licensed".
Copied here by tools/tinyswords.py. Credit is not required but is given gladly.
"""


def main(zip_path: str) -> None:
    files = {ROOT + k: v for k, v in FILES.items()}
    with zipfile.ZipFile(Path(zip_path).expanduser()) as z:
        missing = sorted(set(files) - set(z.namelist()))
        if missing:
            sys.exit("not in the zip (is this the CC0 Update 010 release?):\n  " + "\n  ".join(missing))
        for src, dest in files.items():
            path = OUT / f"{dest}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(z.read(src))
    (OUT / "LICENSE.txt").write_text(LICENSE)
    print(f"copied {len(files)} files to {OUT}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
