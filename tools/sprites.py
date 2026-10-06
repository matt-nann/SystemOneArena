"""Pixel-art sprite generator for every troop. Run: `uv run --group tools python tools/sprites.py`.

Each troop is drawn from code, pixel by pixel, on a 32x32 cell with its feet on
row 30. For every team (blue, red) and facing (down = toward the camera, up =
away, side = facing right; the viewer mirrors it for left) there is a 4-frame
walk and a 3-frame attack (wind-up, strike, follow-through).

Writes:
  web/sprites/units.png    the atlas: one 7-column block of 6 rows per troop
  web/sprites/units.json   where each troop, team, facing and frame lives
  web/sprites/preview.png  the atlas scaled up with labels, for looking at
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from PIL import Image, ImageDraw

CELL = 32
GROUND = 30  # feet rest on this row
DIRS = ("down", "up", "side")
WALK, ATTACK = 4, 3
OUT = Path(__file__).resolve().parent.parent / "web" / "sprites"

RGBA = Tuple[int, int, int, int]


def rgb(hex_: str, a: int = 255) -> RGBA:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a


OUTLINE = rgb("#1b1530")
TEAMS = {
    0: {"m": rgb("#3d7bea"), "d": rgb("#23489e"), "l": rgb("#8fc0ff"), "x": rgb("#d6ebff")},
    1: {"m": rgb("#e0403a"), "d": rgb("#962226"), "l": rgb("#ff9a8c"), "x": rgb("#ffe0d8")},
}
C = {
    "skin": rgb("#f2c29a"), "skin_d": rgb("#cf8f6a"), "skin_l": rgb("#ffe0c4"),
    "steel": rgb("#c3cbd9"), "steel_d": rgb("#7e889e"), "steel_l": rgb("#f2f6fb"),
    "iron": rgb("#4a5066"), "iron_l": rgb("#6d7590"),
    "leather": rgb("#8a5a2e"), "leather_d": rgb("#5b3a1f"), "leather_l": rgb("#b07a44"),
    "pants": rgb("#3c4057"), "pants_d": rgb("#2a2c3e"), "boot": rgb("#4a3020"),
    "gold": rgb("#ffcb45"), "gold_d": rgb("#c58b12"),
    "hair": rgb("#7a4a24"), "hair_d": rgb("#53301a"),
    "gob": rgb("#7fcf55"), "gob_d": rgb("#4f9a36"), "gob_l": rgb("#b6ef8e"),
    "white": rgb("#ffffff"), "eye": rgb("#1b1530"),
    "wood": rgb("#a8743e"), "wood_d": rgb("#6e4823"),
    "bomb": rgb("#4a4a66"), "bomb_l": rgb("#9a9ab8"), "fuse": rgb("#ffd23a"), "spark": rgb("#ff7a1a"),
    "swoosh": rgb("#ffffff", 200), "swoosh2": rgb("#ffffff", 110),
    "beard": rgb("#8a5a2e"),
}


class Canvas:
    def __init__(self) -> None:
        self.px: Dict[Tuple[int, int], RGBA] = {}

    def set(self, x: int, y: int, c: RGBA) -> None:
        if 0 <= x < CELL and 0 <= y < CELL:
            self.px[(x, y)] = c

    def rect(self, x: int, y: int, w: int, h: int, c: RGBA) -> None:
        for yy in range(y, y + h):
            for xx in range(x, x + w):
                self.set(xx, yy, c)

    def block(self, x: int, y: int, w: int, h: int, base: RGBA, light: Optional[RGBA] = None,
              dark: Optional[RGBA] = None) -> None:
        """A filled rectangle lit from the top-left: light top/left edge, dark bottom/right edge."""
        self.rect(x, y, w, h, base)
        if dark:
            for yy in range(y, y + h):
                self.set(x + w - 1, yy, dark)
            for xx in range(x, x + w):
                self.set(xx, y + h - 1, dark)
        if light:
            for xx in range(x, x + w - 1):
                self.set(xx, y, light)
            for yy in range(y, y + h - 1):
                self.set(x, yy, light)

    def line(self, x0: float, y0: float, x1: float, y1: float, c: RGBA) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) or 1
        for i in range(steps + 1):
            t = i / steps
            self.set(round(x0 + (x1 - x0) * t), round(y0 + (y1 - y0) * t), c)

    def blade(self, x: float, y: float, angle: float, length: int, body: RGBA, edge: RGBA) -> Tuple[int, int]:
        """A 2-pixel blade from (x, y) along angle (radians, 0 = right, -pi/2 = up). Returns the tip."""
        dx, dy = math.cos(angle), math.sin(angle)
        # The second pixel row sits on the side facing the light.
        ox, oy = (0, 1) if abs(dx) > abs(dy) else (1, 0)
        tx, ty = x + dx * length, y + dy * length
        self.line(x + ox, y + oy, tx + ox, ty + oy, body)
        self.line(x, y, tx, ty, edge)
        return round(tx), round(ty)

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float, c: RGBA, c2: Optional[RGBA] = None) -> None:
        """A swoosh: an arc of pixels, with an inner fainter arc."""
        steps = max(4, int(abs(a1 - a0) * r * 1.5))
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            self.set(round(cx + math.cos(a) * r), round(cy + math.sin(a) * r), c)
            if c2:
                self.set(round(cx + math.cos(a) * (r - 1)), round(cy + math.sin(a) * (r - 1)), c2)

    def outline(self, c: RGBA = OUTLINE) -> None:
        """Ring every opaque shape in a 1-pixel outline (4-neighbour), the usual pixel-art edge."""
        solid = {p for p, v in self.px.items() if v[3] >= 200}
        add = set()
        for (x, y) in solid:
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if (nx, ny) not in self.px:
                    add.add((nx, ny))
        for p in add:
            self.set(*p, c)

    def flip(self) -> "Canvas":
        out = Canvas()
        for (x, y), v in self.px.items():
            out.px[(CELL - 1 - x, y)] = v
        return out

    def image(self) -> Image.Image:
        img = Image.new("RGBA", (CELL, CELL), (0, 0, 0, 0))
        for (x, y), v in self.px.items():
            img.putpixel((x, y), v)
        return img


# ── shared body parts ───────────────────────────────────────────────

def walk_pose(anim: str, f: int) -> Dict[str, int]:
    """Leg lift / stride and arm swing for walk frame f. Attack frames stand planted."""
    if anim != "walk":
        return {"bob": 0, "lift": (0, 0), "stride": 0, "swing": 0}
    return [
        {"bob": 0, "lift": (0, 0), "stride": 0, "swing": 0},
        {"bob": 1, "lift": (2, 0), "stride": 2, "swing": 1},
        {"bob": 0, "lift": (0, 0), "stride": 0, "swing": 0},
        {"bob": 1, "lift": (0, 2), "stride": -2, "swing": -1},
    ][f]


def legs_front(cv: Canvas, xs: Tuple[int, int], hip: int, w: int, lift: Tuple[int, int],
               pants: RGBA, pants_d: RGBA, boot: RGBA) -> None:
    for x, up in zip(xs, lift):
        bottom = GROUND - up
        cv.block(x, hip, w, bottom - hip - 1, pants, None, pants_d)
        cv.rect(x, bottom - 1, w, 2, boot)
        cv.set(x, bottom - 1, C["leather_l"] if boot == C["boot"] else boot)


def legs_side(cv: Canvas, x: int, hip: int, w: int, stride: int, pants: RGBA, pants_d: RGBA, boot: RGBA) -> None:
    """Two legs seen from the side: back leg first (darker), front leg over it."""
    for k, shade in ((-1, pants_d), (1, pants)):
        off = stride * k
        mid = hip + (GROUND - hip) // 2
        cv.rect(x + off // 2, hip, w, mid - hip, shade)
        cv.rect(x + off, mid, w, GROUND - mid - 1, shade)
        cv.rect(x + off, GROUND - 1, w + 1, 2, boot)


# ── troops ──────────────────────────────────────────────────────────

def knight(cv: Canvas, t: dict, d: str, anim: str, f: int) -> None:
    p = walk_pose(anim, f)
    b = p["bob"]
    atk = f if anim == "attack" else None
    if d in ("down", "up"):
        legs_front(cv, (12, 17), 24, 3, p["lift"], C["pants"], C["pants_d"], C["boot"])
        front = d == "down"
        sx = 9 if front else 21          # sword arm column (character's right hand)
        hx = 21 if front else 9          # shield arm column
        # sword (behind the arm when facing away)
        def sword() -> None:
            hand = (sx + 1, 22 - b)
            if atk is None:
                cv.blade(hand[0] - 1, hand[1] - 1, -math.pi / 2, 10, C["steel"], C["steel_l"])
                cv.rect(hand[0] - 3, hand[1] - 1, 5, 1, C["gold"])
            elif atk == 0:   # wind-up: raised high over the shoulder
                cv.blade(hand[0] - 1, 12, -math.pi / 2 - (0.35 if front else -0.35), 11, C["steel"], C["steel_l"])
                cv.rect(hand[0] - 3, 12, 5, 1, C["gold"])
            elif atk == 1:   # strike: chopped down toward the facing direction
                if front:
                    cv.arc(16, 15, 11, math.pi * 1.05, math.pi * 0.62, C["swoosh"], C["swoosh2"])
                    cv.blade(14, 23, math.pi / 2 - 0.65, 8, C["steel"], C["steel_l"])
                    cv.rect(12, 22, 4, 2, C["steel"])
                    cv.rect(13, 22, 3, 2, C["leather"])
                    cv.rect(13, 21, 1, 4, C["gold"])
                else:
                    cv.blade(16, 12, -math.pi / 2, 11, C["steel"], C["steel_l"])
                    cv.arc(16, 12, 9, -math.pi * 0.05, -math.pi * 0.45, C["swoosh"], C["swoosh2"])
                    cv.rect(14, 12, 5, 1, C["gold"])
            else:            # follow-through: blade low
                ang = math.pi / 2 + (0.7 if front else -0.7)
                cv.blade(hand[0], 23, ang, 7, C["steel"], C["steel_l"])
        if not front:
            sword()
        # torso: chainmail under a team tabard
        cv.block(11, 17 - b, 10, 7, C["steel"], C["steel_l"], C["steel_d"])
        cv.block(12, 17 - b, 8, 7, t["m"], t["l"], t["d"])
        cv.rect(11, 22 - b, 10, 1, C["leather"])
        if front:
            cv.rect(15, 22 - b, 2, 1, C["gold"])
        # arms
        sy = 17 - b + (p["swing"] if front else -p["swing"])
        if atk in (0,) or (atk == 1 and not front):
            cv.block(sx, 12, 2, 8, C["steel"], C["steel_l"], C["steel_d"])  # raised arm
            cv.rect(sx, 12, 2, 2, C["leather"])
        else:
            cv.block(sx, sy, 2, 6, C["steel"], C["steel_l"], C["steel_d"])
            cv.rect(sx, sy + 5, 2, 2, C["leather"])
        hy = 17 - b - (p["swing"] if front else -p["swing"])
        cv.block(hx, hy, 2, 6, C["steel"], C["steel_l"], C["steel_d"])
        # head: full helm with a plume in team colour
        cv.block(12, 9 - b, 8, 8, C["steel"], C["steel_l"], C["steel_d"])
        if front:
            cv.rect(13, 12 - b, 6, 2, C["iron"])
            cv.set(14, 12 - b, C["steel_l"]); cv.set(17, 12 - b, C["steel_l"])
            cv.rect(15, 14 - b, 2, 2, C["iron"])
        else:
            cv.rect(15, 10 - b, 2, 6, C["steel_d"])
        cv.block(14, 5 - b, 4, 4, t["m"], t["l"], t["d"])
        cv.set(13 if front else 18, 6 - b, t["m"])
        # shield (front) or its strapped back (away)
        if front:
            cv.block(19, 17 - b, 6, 8, t["m"], t["l"], t["d"])
            cv.rect(20, 18 - b, 4, 1, t["x"])
            cv.block(21, 20 - b, 2, 2, C["gold"], None, C["gold_d"])
        else:
            cv.block(7, 17 - b, 5, 7, C["wood"], None, C["wood_d"])
            cv.rect(7, 20 - b, 5, 1, C["leather_d"])
        if front:
            sword()
    else:  # side, facing right
        legs_side(cv, 15, 24, 3, p["stride"], C["pants"], C["pants_d"], C["boot"])
        # shield on the far arm, held out in front
        cv.block(20, 16 - b, 3, 9, t["m"], t["l"], t["d"])
        cv.block(13, 17 - b, 8, 7, C["steel"], C["steel_l"], C["steel_d"])
        cv.block(14, 17 - b, 6, 7, t["m"], t["l"], t["d"])
        cv.rect(13, 22 - b, 8, 1, C["leather"])
        # helm, visor on the facing side, plume streaming back
        cv.block(13, 9 - b, 8, 8, C["steel"], C["steel_l"], C["steel_d"])
        cv.rect(18, 12 - b, 3, 2, C["iron"])
        cv.set(19, 12 - b, C["steel_l"])
        cv.block(12, 6 - b, 6, 3, t["m"], t["l"], t["d"])
        cv.set(11, 7 - b, t["d"]); cv.set(11, 8 - b, t["d"])
        # near arm and sword
        ax = 16 + (p["swing"] if anim == "walk" else 0)
        if atk is None:
            cv.block(ax, 17 - b, 2, 6, C["steel"], C["steel_l"], C["steel_d"])
            cv.rect(ax, 22 - b, 2, 2, C["leather"])
            cv.blade(ax + 2, 23 - b, 0.55, 7, C["steel"], C["steel_l"])
            cv.rect(ax + 2, 21 - b, 1, 4, C["gold"])
        elif atk == 0:  # raised back over the head
            cv.block(14, 13, 2, 6, C["steel"], C["steel_l"], C["steel_d"])
            cv.rect(14, 12, 2, 2, C["leather"])
            cv.blade(14, 12, -math.pi / 2 - 0.9, 11, C["steel"], C["steel_l"])
            cv.rect(13, 13, 3, 1, C["gold"])
        elif atk == 1:  # swung forward
            cv.block(18, 17, 5, 2, C["steel"], C["steel_l"], C["steel_d"])
            cv.rect(22, 17, 2, 2, C["leather"])
            cv.blade(23, 17, -0.05, 7, C["steel"], C["steel_l"])
            cv.rect(23, 15, 1, 5, C["gold"])
            cv.arc(18, 18, 11, -math.pi * 0.55, -math.pi * 0.05, C["swoosh"], C["swoosh2"])
        else:           # follow-through low
            cv.block(17, 18, 4, 2, C["steel"], C["steel_l"], C["steel_d"])
            cv.rect(20, 19, 2, 2, C["leather"])
            cv.blade(21, 20, 0.75, 7, C["steel"], C["steel_l"])


def bow(cv: Canvas, x: int, top: int, bottom: int, facing: int, drawn_to: Optional[Tuple[int, int]] = None) -> None:
    """A vertical bow whose belly bulges toward ``facing`` (+1 right, -1 left); string straight or drawn back."""
    mid = (top + bottom) / 2
    for y in range(top, bottom + 1):
        bulge = 2 - round(2 * abs(y - mid) / ((bottom - top) / 2))
        cv.set(x + facing * bulge, y, C["wood"])
    cv.set(x, top, C["wood_d"]); cv.set(x, bottom, C["wood_d"])
    if drawn_to:
        cv.line(x, top, *drawn_to, C["steel_l"])
        cv.line(x, bottom, *drawn_to, C["steel_l"])
    else:
        cv.line(x - facing, top + 1, x - facing, bottom - 1, C["steel_l"])


def archer(cv: Canvas, t: dict, d: str, anim: str, f: int) -> None:
    p = walk_pose(anim, f)
    b = p["bob"]
    atk = f if anim == "attack" else None
    if d in ("down", "up"):
        front = d == "down"
        legs_front(cv, (13, 17), 25, 2, p["lift"], C["leather_d"], C["boot"], C["boot"])
        if not front:  # quiver on the back
            cv.block(17, 14 - b, 3, 8, C["leather"], C["leather_l"], C["leather_d"])
            for x, c in ((17, t["l"]), (18, C["white"]), (19, t["l"])):
                cv.set(x, 12 - b, c); cv.set(x, 13 - b, c)
        cv.block(12, 19 - b, 8, 6, t["m"], t["l"], t["d"])
        cv.rect(12, 23 - b, 8, 1, C["leather"])
        if front:
            cv.rect(15, 23 - b, 2, 1, C["gold"])
        aim = atk in (0, 1)
        if aim:
            cv.block(13, 18 - b, 2, 4, t["m"], t["l"], t["d"])
            cv.block(17, 18 - b, 2, 4, t["m"], t["l"], t["d"])
        else:
            sw = p["swing"] if front else -p["swing"]
            cv.block(10, 19 - b + sw, 2, 5, t["m"], t["l"], t["d"])
            cv.rect(10, 23 - b + sw, 2, 1, C["skin"])
            cv.block(20, 19 - b - sw, 2, 5, t["m"], t["l"], t["d"])
            cv.rect(20, 23 - b - sw, 2, 1, C["skin"])
        # hooded head
        cv.block(12, 11 - b, 8, 8, t["m"], t["l"], t["d"])
        cv.rect(14, 10 - b, 4, 1, t["m"])
        if front:
            cv.block(13, 13 - b, 6, 5, C["skin"], C["skin_l"], C["skin_d"])
            cv.set(14, 15 - b, C["eye"]); cv.set(17, 15 - b, C["eye"])
            cv.set(11, 11 - b, t["l"]); cv.set(10, 10 - b, C["white"])  # fletching over the shoulder
        else:
            cv.rect(15, 12 - b, 2, 6, t["d"])
        bx = 22 if front else 9  # the bow hand: character's left
        if front and aim:        # aiming at the camera: bow upright in front of the chest
            bow(cv, 16, 18, 28, 1)
            if atk == 0:
                cv.rect(15, 22, 2, 2, C["steel_l"])
                cv.set(16, 23, C["steel_d"])
            else:
                for dx, dy in ((0, -3), (0, 3), (-3, 0), (3, 0), (-2, -2), (2, 2), (2, -2), (-2, 2)):
                    cv.set(16 + dx, 23 + dy, C["swoosh"])
        elif aim:                # aiming away: bow raised ahead of the head
            for x in range(10, 23):
                cv.set(x, 7 + round(abs(x - 16) / 3), C["wood"])
            cv.line(10, 9, 16, 12 if atk == 0 else 9, C["steel_l"])
            cv.line(22, 9, 16, 12 if atk == 0 else 9, C["steel_l"])
            if atk == 0:
                cv.line(16, 4, 16, 12, C["steel"]); cv.set(16, 3, C["steel_l"])
            else:
                cv.line(16, 0, 16, 4, C["swoosh"])
        else:
            bow(cv, bx, 14 - b, 26 - b, 1 if front else -1)
    else:
        legs_side(cv, 15, 25, 2, p["stride"], C["leather_d"], C["boot"], C["boot"])
        cv.block(11, 15 - b, 3, 8, C["leather"], C["leather_l"], C["leather_d"])  # quiver
        for y, c in ((12, t["l"]), (13, C["white"]), (14, t["l"])):
            cv.set(10, y - b, c); cv.set(11, y - b, c)
        cv.block(13, 19 - b, 7, 6, t["m"], t["l"], t["d"])
        cv.rect(13, 23 - b, 7, 1, C["leather"])
        cv.block(13, 11 - b, 7, 8, t["m"], t["l"], t["d"])
        cv.block(17, 13 - b, 3, 5, C["skin"], C["skin_l"], C["skin_d"])
        cv.set(18, 15 - b, C["eye"])
        cv.set(12, 12 - b, t["d"]); cv.set(12, 13 - b, t["d"])
        if atk in (0, 1):
            cv.block(17, 18, 5, 2, t["m"], t["l"], t["d"])   # bow arm out front
            cv.rect(21, 18, 1, 2, C["skin"])
            if atk == 0:
                bow(cv, 22, 13, 24, 1, drawn_to=(15, 18))
                cv.block(14, 17, 2, 3, t["m"], t["l"], t["d"])
                cv.line(15, 18, 25, 18, C["steel"]); cv.set(26, 18, C["steel_l"])
            else:
                bow(cv, 22, 13, 24, 1)
                cv.line(25, 18, 30, 18, C["swoosh"]); cv.line(26, 17, 29, 17, C["swoosh2"])
        else:
            ax = 16 + p["swing"]
            cv.block(ax, 19 - b, 2, 5, t["m"], t["l"], t["d"])
            cv.rect(ax, 23 - b, 2, 1, C["skin"])
            bow(cv, ax + 3, 16 - b, 27 - b, 1)


def goblin(cv: Canvas, t: dict, d: str, anim: str, f: int) -> None:
    p = walk_pose(anim, f)
    b = p["bob"]
    atk = f if anim == "attack" else None
    g, gl, gd = C["gob"], C["gob_l"], C["gob_d"]

    def dagger(x: int, y: int, angle: float, n: int = 4) -> None:
        cv.blade(x, y, angle, n, C["steel"], C["steel_l"])
        cv.set(x, y, C["leather"])

    if d in ("down", "up"):
        front = d == "down"
        legs_front(cv, (13, 17), 26, 2, p["lift"], gd, gd, C["leather_d"])
        cv.block(13, 22 - b, 6, 5, t["m"], t["l"], t["d"])
        cv.rect(13, 25 - b, 6, 1, C["leather"])
        hand_x = 11 if front else 19   # dagger hand: character's right
        other_x = 19 if front else 11
        sw = p["swing"] if front else -p["swing"]
        cv.block(other_x, 22 - b - sw, 2, 4, g, gl, gd)
        if atk == 0:
            cv.block(hand_x, 17, 2, 5, g, gl, gd)
            dagger(hand_x, 17, -math.pi / 2)
        elif atk == 1:
            if front:
                cv.block(14, 23, 4, 2, g, gl, gd)
                dagger(15, 25, math.pi / 2, 4)
                cv.arc(16, 22, 7, math.pi * 1.0, math.pi * 0.55, C["swoosh"], C["swoosh2"])
            else:
                cv.block(15, 11, 2, 5, g, gl, gd)
                dagger(15, 11, -math.pi / 2, 4)
                cv.arc(16, 14, 8, -math.pi * 0.95, -math.pi * 0.55, C["swoosh"], C["swoosh2"])
        else:
            cv.block(hand_x, 22 - b + sw, 2, 4, g, gl, gd)
            dagger(hand_x + (0 if front else 1), 26 - b + sw, math.pi / 2 + (0.5 if front else -0.5), 3)
        # big head, ears out, team bandana
        cv.block(12, 14 - b, 8, 8, g, gl, gd)
        for k, x0 in ((-1, 11), (1, 20)):
            cv.set(x0, 17 - b, g); cv.set(x0 + k, 16 - b, g); cv.set(x0 + 2 * k, 15 - b, gl)
            cv.set(x0, 16 - b, g)
        cv.rect(12, 14 - b, 8, 2, t["m"])
        cv.rect(12, 15 - b, 8, 1, t["d"])
        if front:
            for x in (13, 17):
                cv.rect(x, 17 - b, 2, 2, C["white"]); cv.set(x + (1 if x == 13 else 0), 18 - b, C["eye"])
            cv.rect(14, 20 - b, 4, 1, C["eye"]); cv.set(15, 20 - b, C["white"])
        else:
            cv.set(19, 16 - b, t["l"]); cv.set(20, 16 - b, t["m"]); cv.set(20, 17 - b, t["m"])
    else:
        legs_side(cv, 15, 26, 2, p["stride"], gd, gd, C["leather_d"])
        cv.block(14, 22 - b, 5, 5, t["m"], t["l"], t["d"])
        cv.rect(14, 25 - b, 5, 1, C["leather"])
        cv.block(13, 14 - b, 8, 8, g, gl, gd)
        cv.set(12, 16 - b, g); cv.set(11, 15 - b, g); cv.set(10, 14 - b, gl)   # ear swept back
        cv.set(21, 18 - b, g)                                                 # nose
        cv.rect(13, 14 - b, 8, 2, t["m"]); cv.rect(13, 15 - b, 8, 1, t["d"])
        cv.set(12, 14 - b, t["m"]); cv.set(11, 13 - b, t["l"])               # bandana tail
        cv.rect(18, 17 - b, 2, 2, C["white"]); cv.set(19, 18 - b, C["eye"])
        cv.rect(18, 20 - b, 2, 1, C["eye"])
        if atk == 0:
            cv.block(13, 19, 2, 4, g, gl, gd)
            dagger(13, 19, -math.pi / 2 - 0.6)
        elif atk == 1:
            cv.block(17, 22, 4, 2, g, gl, gd)
            dagger(21, 22, 0.0, 5)
            cv.arc(17, 22, 8, -math.pi * 0.5, math.pi * 0.05, C["swoosh"], C["swoosh2"])
        else:
            ax = 16 + p["swing"]
            cv.block(ax, 22 - b, 2, 4, g, gl, gd)
            dagger(ax + 1, 25 - b, 0.6, 3)


def giant(cv: Canvas, t: dict, d: str, anim: str, f: int) -> None:
    p = walk_pose(anim, f)
    b = p["bob"]
    atk = f if anim == "attack" else None
    sk, skl, skd = C["skin"], C["skin_l"], C["skin_d"]

    def fist(x: int, y: int, w: int = 5, h: int = 4) -> None:
        cv.block(x, y, w, h, sk, skl, skd)
        cv.set(x + 1, y + 1, skd); cv.set(x + 3, y + 1, skd)

    def star(x: int, y: int) -> None:
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (2, 0), (-2, 0), (0, 2), (0, -2), (2, 2), (-2, -2), (2, -2), (-2, 2)):
            cv.set(x + dx, y + dy, C["swoosh"] if abs(dx) + abs(dy) < 3 else C["gold"])

    if d in ("down", "up"):
        front = d == "down"
        legs_front(cv, (11, 17), 23, 4, p["lift"], C["leather"], C["leather_d"], C["boot"])
        # torso: team tunic, belt with gold buckle
        cv.block(9, 13 - b, 14, 10, t["m"], t["l"], t["d"])
        cv.rect(9, 20 - b, 14, 2, C["leather_d"])
        if front:
            cv.block(15, 20 - b, 2, 2, C["gold"], None, C["gold_d"])
            cv.rect(13, 13 - b, 6, 2, sk)  # open collar
        sw = p["swing"] if front else -p["swing"]
        punch_x = 5 if front else 23   # punching arm: character's right
        other_x = 23 if front else 5
        cv.block(other_x + (1 if front else 0), 14 - b - sw, 3, 6, sk, skl, skd)
        fist(other_x - (0 if front else 1), 19 - b - sw)
        if atk == 0:
            cv.block(punch_x + (1 if front else 0), 7, 3, 7, sk, skl, skd)
            fist(punch_x - (0 if front else 1), 3)
        elif atk == 1:
            if front:
                cv.block(12, 17, 3, 4, sk, skl, skd)
                fist(12, 19, 8, 6)
                star(16, 27)
            else:
                fist(13, 0, 6, 4)
                star(16, 1)
        else:
            cv.block(punch_x + (1 if front else 0), 15 - b + sw, 3, 6, sk, skl, skd)
            fist(punch_x - (0 if front else 1), 20 - b + sw)
        # head
        if front:
            cv.block(11, 4 - b, 10, 9, sk, skl, skd)
            cv.rect(11, 3 - b, 10, 3, C["hair"]); cv.rect(11, 6 - b, 1, 3, C["hair"]); cv.rect(20, 6 - b, 1, 3, C["hair"])
            cv.rect(13, 7 - b, 2, 1, C["hair_d"]); cv.rect(17, 7 - b, 2, 1, C["hair_d"])
            cv.set(14, 8 - b, C["eye"]); cv.set(17, 8 - b, C["eye"])
            cv.rect(15, 9 - b, 2, 1, skd)
            cv.rect(14, 11 - b, 4, 1, C["hair_d"])
        else:
            cv.block(11, 4 - b, 10, 9, C["hair"], None, C["hair_d"])
            cv.rect(11, 11 - b, 10, 2, skd)
            cv.set(10, 8 - b, sk); cv.set(21, 8 - b, sk)
    else:
        legs_side(cv, 14, 23, 4, p["stride"], C["leather"], C["leather_d"], C["boot"])
        fist(19, 19 - b)  # far fist peeking out in front
        cv.block(11, 13 - b, 10, 10, t["m"], t["l"], t["d"])
        cv.rect(11, 20 - b, 10, 2, C["leather_d"])
        cv.block(13, 4 - b, 9, 9, sk, skl, skd)
        cv.rect(12, 3 - b, 8, 3, C["hair"]); cv.rect(12, 5 - b, 3, 5, C["hair"])
        cv.rect(18, 7 - b, 2, 1, C["hair_d"]); cv.set(19, 8 - b, C["eye"])
        cv.set(22, 9 - b, sk); cv.rect(18, 11 - b, 3, 1, C["hair_d"])
        if atk == 0:
            cv.block(10, 11, 3, 6, sk, skl, skd)
            fist(7, 9)
        elif atk == 1:
            cv.block(17, 15, 7, 3, sk, skl, skd)
            fist(23, 14, 6, 5)
            star(30, 16)
        else:
            ax = 15 + p["swing"]
            cv.block(ax, 14 - b, 3, 6, sk, skl, skd)
            fist(ax, 20 - b)


def bomb(cv: Canvas, x: int, y: int, phase: int) -> None:
    for dy in range(-3, 4):
        for dx in range(-3, 4):
            if dx * dx + dy * dy <= 7:
                cv.set(x + dx, y + dy, C["bomb"])
    cv.set(x - 1, y - 1, C["bomb_l"]); cv.set(x - 2, y - 1, C["bomb_l"]); cv.set(x - 1, y - 2, C["bomb_l"])
    cv.set(x + 1, y - 4, C["fuse"]); cv.set(x + 2, y - 5, C["fuse"])
    cv.set(x + 2 + phase % 2, y - 6, C["spark"]); cv.set(x + 3 - phase % 2, y - 6 - phase % 2, C["fuse"])


def bomber(cv: Canvas, t: dict, d: str, anim: str, f: int) -> None:
    p = walk_pose(anim, f)
    b = p["bob"]
    atk = f if anim == "attack" else None
    lens, rim = rgb("#bff1ff"), C["iron"]
    if d in ("down", "up"):
        front = d == "down"
        legs_front(cv, (13, 17), 25, 2, p["lift"], C["pants"], C["pants_d"], C["boot"])
        cv.block(12, 19 - b, 8, 6, t["m"], t["l"], t["d"])
        cv.line(12, 19 - b, 19, 24 - b, C["leather"])  # bandolier
        hand_x = 10 if front else 20     # throwing hand: character's right
        other_x = 20 if front else 10
        sw = p["swing"] if front else -p["swing"]
        cv.block(other_x, 19 - b - sw, 2, 5, t["m"], t["l"], t["d"])
        cv.rect(other_x, 23 - b - sw, 2, 1, C["skin"])
        if atk == 0:
            cv.block(hand_x, 12, 2, 7, t["m"], t["l"], t["d"])
            bomb(cv, hand_x + 1, 8, f)
        elif atk == 1:
            if front:
                cv.block(13, 19, 6, 2, t["m"], t["l"], t["d"])
                bomb(cv, 16, 25, f)
            else:
                cv.block(15, 9, 2, 6, t["m"], t["l"], t["d"])
                bomb(cv, 16, 4, f)
        else:
            cv.block(hand_x, 19 - b + sw, 2, 5, t["m"], t["l"], t["d"])
            cv.rect(hand_x, 23 - b + sw, 2, 1, C["skin"])
            if anim == "walk":
                bomb(cv, hand_x + (0 if front else 1), 26 - b + sw, f)
        # head: team cap, goggles
        if front:
            cv.block(12, 11 - b, 8, 8, C["skin"], C["skin_l"], C["skin_d"])
            cv.rect(12, 13 - b, 8, 1, rim)
            for x in (13, 17):
                cv.rect(x, 13 - b, 2, 2, lens); cv.set(x + 1, 14 - b, rgb("#7fc9e0"))
            cv.rect(15, 17 - b, 2, 1, C["skin_d"])
        else:
            cv.block(12, 11 - b, 8, 8, C["hair"], None, C["hair_d"])
            cv.rect(12, 13 - b, 8, 1, rim)
        cv.block(12, 9 - b, 8, 4, t["m"], t["l"], t["d"])
        cv.rect(15, 8 - b, 2, 1, t["l"])
    else:
        legs_side(cv, 15, 25, 2, p["stride"], C["pants"], C["pants_d"], C["boot"])
        cv.block(13, 19 - b, 7, 6, t["m"], t["l"], t["d"])
        cv.block(13, 11 - b, 7, 8, C["skin"], C["skin_l"], C["skin_d"])
        cv.rect(13, 12 - b, 3, 6, C["hair"])
        cv.rect(13, 13 - b, 7, 1, rim)
        cv.rect(18, 13 - b, 2, 2, lens)
        cv.block(13, 9 - b, 7, 4, t["m"], t["l"], t["d"]); cv.rect(20, 11 - b, 2, 1, t["d"])
        if atk == 0:
            cv.block(13, 13, 2, 6, t["m"], t["l"], t["d"])
            bomb(cv, 11, 9, f)
        elif atk == 1:
            cv.block(18, 14, 5, 2, t["m"], t["l"], t["d"])
            bomb(cv, 25, 12, f)
        else:
            ax = 16 + p["swing"]
            cv.block(ax, 19 - b, 2, 5, t["m"], t["l"], t["d"])
            cv.rect(ax, 23 - b, 2, 1, C["skin"])
            if anim == "walk":
                bomb(cv, ax + 4, 24 - b, f)


TROOPS: Dict[str, Callable] = {"knight": knight, "archers": archer, "swarm": goblin, "giant": giant, "bomber": bomber}


def frame(kind: str, team: int, d: str, anim: str, f: int) -> Image.Image:
    cv = Canvas()
    TROOPS[kind](cv, TEAMS[team], d, anim, f)
    cv.outline()
    return cv.image()


def build() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cols = WALK + ATTACK
    rows_per = 2 * len(DIRS)
    atlas = Image.new("RGBA", (cols * CELL, rows_per * CELL * len(TROOPS)), (0, 0, 0, 0))
    meta = {"cell": CELL, "ground": GROUND, "dirs": list(DIRS), "anims": {"walk": [0, WALK], "attack": [WALK, ATTACK]},
            "troops": {}}
    for i, kind in enumerate(TROOPS):
        base = i * rows_per
        meta["troops"][kind] = {"row": base}
        for team in (0, 1):
            for di, d in enumerate(DIRS):
                row = base + team * len(DIRS) + di
                for f in range(WALK):
                    atlas.paste(frame(kind, team, d, "walk", f), (f * CELL, row * CELL))
                for f in range(ATTACK):
                    atlas.paste(frame(kind, team, d, "attack", f), ((WALK + f) * CELL, row * CELL))
        # Highest opaque row of the walk frames: where the HP bar goes.
        block = atlas.crop((0, base * CELL, WALK * CELL, (base + rows_per) * CELL))
        meta["troops"][kind]["top"] = min(
            next(y for y in range(CELL) if any(block.getpixel((x, r * CELL + y))[3] for x in range(WALK * CELL)))
            for r in range(rows_per))
    atlas.save(OUT / "units.png")
    (OUT / "units.json").write_text(json.dumps(meta, indent=1))
    preview(atlas, meta)


def preview(atlas: Image.Image, meta: dict, scale: int = 4) -> None:
    """The atlas on a dark background, scaled up, with a label per row."""
    label_w = 150
    w, h = atlas.size
    img = Image.new("RGBA", (label_w + w * scale, h * scale), rgb("#262b36"))
    img.paste(atlas.resize((w * scale, h * scale), Image.NEAREST), (label_w, 0), atlas.resize((w * scale, h * scale), Image.NEAREST))
    dr = ImageDraw.Draw(img)
    for kind, m in meta["troops"].items():
        for team in (0, 1):
            for di, d in enumerate(DIRS):
                y = (m["row"] + team * len(DIRS) + di) * CELL * scale
                dr.text((8, y + 8), f"{kind}\n{'blue' if team == 0 else 'red'} {d}", fill=(220, 225, 235, 255))
                dr.line((0, y, img.width, y), fill=(60, 66, 80, 255))
    for c in range(WALK + ATTACK):
        x = label_w + c * CELL * scale
        dr.text((x + 6, 4), f"walk {c}" if c < WALK else f"attack {c - WALK}", fill=(150, 160, 180, 255))
    img.save(OUT / "preview.png")


if __name__ == "__main__":
    build()
    print(f"wrote {OUT / 'units.png'}, units.json, preview.png")
