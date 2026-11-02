#!/usr/bin/env python3
"""Render the ArenaVeritas brand mark as a crisp 512x512 PNG.

Cyber-Obsidian plate, Signal-Lime integrity chevron, single rose anomaly tick.
Drawn at 4x supersampling and Lanczos-downsampled so every edge stays crisp.
Writes the identical asset to frontend/public/logo.png and docs/logo.png.
"""
from __future__ import annotations

import hashlib
import os

from PIL import Image, ImageDraw

SS = 4
SIZE = 512
CANVAS = SIZE * SS

OBSIDIAN = (7, 9, 14)
PANEL = (16, 21, 32)
LIME = (163, 230, 53)
ROSE = (244, 63, 94)
STEEL = (94, 110, 140)
WHITE = (232, 240, 238)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TARGETS = [
    os.path.join(ROOT, "frontend", "public", "logo.png"),
    os.path.join(ROOT, "docs", "logo.png"),
]


def px(v: int) -> int:
    return v * SS


def plate(draw: ImageDraw.ImageDraw) -> None:
    """Obsidian background with a subtle vertical panel gradient."""
    draw.rectangle([0, 0, CANVAS, CANVAS], fill=OBSIDIAN)
    for i in range(0, 64):
        alpha_step = 255
        shade = tuple(
            min(255, OBSIDIAN[c] + int((PANEL[c] - OBSIDIAN[c]) * (1 - i / 64)))
            for c in range(3)
        )
        draw.rectangle([px(48 + i * 2), px(48), px(48 + i * 2 + 1), CANVAS - px(48)], fill=shade + (alpha_step,))


def octagon(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, cut: float) -> list[tuple[int, int]]:
    """Flat-topped octagon used as the integrity shield outline."""
    k = r * cut
    return [
        (cx - k, cy - r), (cx + k, cy - r),
        (cx + r, cy - k), (cx + r, cy + k),
        (cx + k, cy + r), (cx - k, cy + r),
        (cx - r, cy + k), (cx - r, cy - k),
    ]


def shield(draw: ImageDraw.ImageDraw) -> None:
    c = CANVAS // 2
    r = px(214)
    draw.polygon(octagon(draw, c, c, r, 0.29), fill=PANEL, outline=STEEL, width=px(2))
    draw.polygon(octagon(draw, c, c, px(196), 0.29), outline=LIME, width=px(9))
    draw.polygon(octagon(draw, c, c, px(178), 0.29), outline=STEEL, width=px(2))


def scanlines(draw: ImageDraw.ImageDraw) -> None:
    """Broadcast scan sweep inside the shield."""
    c = CANVAS // 2
    for i in range(9):
        y = px(120 + i * 34)
        half = px(150 - i * 6)
        draw.line([(c - half, y), (c + half, y)], fill=(30, 40, 58), width=px(3))


def chevron(draw: ImageDraw.ImageDraw) -> None:
    """Double integrity chevron: the bracket that settles a match."""
    c = CANVAS // 2
    left = [
        (px(196), px(150)), (px(120), px(256)), (px(196), px(362)),
    ]
    right = [(CANVAS - x, y) for x, y in left]
    draw.line(left, fill=WHITE, width=px(14), joint="curve")
    draw.line(right, fill=STEEL, width=px(10), joint="curve")


def tick(draw: ImageDraw.ImageDraw) -> None:
    """Signal-lime verification tick with a rose anomaly flag on its tail."""
    c = CANVAS // 2
    pts = [(px(168), px(262)), (px(232), px(326)), (px(372), px(160))]
    draw.line(pts, fill=LIME, width=px(30), joint="curve")
    draw.ellipse([CANVAS - px(188), px(112), CANVAS - px(124), px(176)], fill=ROSE, outline=OBSIDIAN, width=px(4))
    draw.line([(c + px(120), px(340)), (c + px(150), px(340))], fill=ROSE, width=px(8))


def wordmark(draw: ImageDraw.ImageDraw) -> None:
    """AV monogram block anchored bottom-left for small-size legibility."""
    draw.rounded_rectangle([px(58), px(410), px(150), px(452)], radius=px(10), fill=LIME)
    draw.rounded_rectangle([px(162), px(410), px(206), px(452)], radius=px(10), outline=STEEL, width=px(4))


def render() -> Image.Image:
    img = Image.new("RGBA", (CANVAS, CANVAS), OBSIDIAN + (255,))
    draw = ImageDraw.Draw(img)
    plate(draw)
    shield(draw)
    scanlines(draw)
    chevron(draw)
    tick(draw)
    wordmark(draw)
    return img.resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def main() -> None:
    logo = render()
    for target in TARGETS:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        logo.save(target, format="PNG", optimize=True)
        size = os.path.getsize(target)
        digest = hashlib.sha256(open(target, "rb").read()).hexdigest()
        print(f"{os.path.relpath(target, ROOT)}  {size} bytes  {logo.size[0]}x{logo.size[1]}  sha256 {digest[:16]}")
        if size > 500_000:
            raise SystemExit("logo exceeds the 500 KB asset ceiling")


if __name__ == "__main__":
    main()
