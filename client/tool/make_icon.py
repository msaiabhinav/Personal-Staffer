"""Render the Personal Staffer application icon (teal rounded square, four-point spark).

Run from client/:  py -3.12 tool/make_icon.py
Writes windows/runner/resources/app_icon.ico with 16-256 px sizes. Requires Pillow.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

TEAL = (11, 122, 131, 255)
TEAL_LIGHT = (63, 193, 203, 255)
WHITE = (255, 255, 255, 255)


def spark(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, waist: float, fill):
    points = []
    for i in range(8):
        angle = math.pi / 4 * i - math.pi / 2
        radius = r if i % 2 == 0 else r * waist
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    draw.polygon(points, fill=fill)


def render(size: int) -> Image.Image:
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(s * 0.24)
    # Vertical gradient background.
    for y in range(s):
        t = y / s
        color = tuple(int(TEAL[i] * (1 - t) + TEAL_LIGHT[i] * t * 0.55) for i in range(3)) + (255,)
        draw.line([(0, y), (s, y)], fill=color)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=255)
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)
    spark(draw, s * 0.46, s * 0.50, s * 0.30, 0.34, WHITE)
    spark(draw, s * 0.74, s * 0.28, s * 0.12, 0.36, WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "windows" / "runner" / "resources" / "app_icon.ico"
    sizes = [256, 128, 64, 48, 32, 24, 16]
    images = [render(size) for size in sizes]
    images[0].save(out, format="ICO", sizes=[(size, size) for size in sizes], append_images=images[1:])
    print(f"wrote {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
