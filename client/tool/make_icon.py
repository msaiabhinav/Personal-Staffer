"""Build the Personal Staffer application icon from the owner's logo artwork.

Run from client/:  py -3.12 tool/make_icon.py [path-to-logo.png]

The source is the owner's brand image (a dark rounded-square badge with the wordmark
underneath). The Windows icon uses the badge only - the script cropped wordmark is
unreadable at 16-48 px - and the full artwork is copied to assets/brand/logo.png for
in-app use. Writes windows/runner/resources/app_icon.ico with 16-256 px sizes.
Requires Pillow. Default source: assets/brand/logo_source.png.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "assets" / "brand" / "logo_source.png"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BADGE_DARK = (55, 43, 36)  # Sampled badge colour; used to find the badge's bounding box.


def badge_box(image: Image.Image) -> tuple[int, int, int, int]:
    """Bounding box of the dark rounded square (pixels close to the badge colour)."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    xs, ys = [], []
    step = max(1, width // 400)
    for y in range(0, height, step):
        for x in range(0, width, step):
            r, g, b = pixels[x, y]
            if abs(r - BADGE_DARK[0]) < 40 and abs(g - BADGE_DARK[1]) < 40 and abs(b - BADGE_DARK[2]) < 40:
                xs.append(x)
                ys.append(y)
    if not xs:
        raise SystemExit("Could not locate the dark badge in the logo artwork")
    # The wordmark below the badge is the same dark colour but only in a thin band; keep the
    # densest vertical span by trimming rows whose dark pixel count is far below the badge's.
    from collections import Counter

    rows = Counter(ys)
    peak = max(rows.values())
    sampled = sorted(rows)
    top = next(y for y in sampled if rows[y] >= peak * 0.5)
    bottom = top
    for y in sampled:
        if y < top:
            continue
        if rows[y] < peak * 0.25:
            break  # The gap between the badge and the wordmark.
        bottom = y
    xs_in = [x for x, y in zip(xs, ys, strict=True) if top <= y <= bottom]
    left, right = min(xs_in), max(xs_in)
    return left, top, right, bottom


def render(source: Image.Image, box: tuple[int, int, int, int], size: int) -> Image.Image:
    left, top, right, bottom = box
    side = max(right - left, bottom - top)
    # Square crop centred on the badge with a little breathing room, then a rounded mask so the
    # icon sits cleanly on light and dark taskbars.
    # Horizontal room for the figure's feet, which extend past the badge edge; vertically only a
    # sliver so the wordmark below the badge stays out. The crop is centred on a square cream
    # canvas so the icon keeps its aspect.
    rgba = source.convert("RGBA")
    crop = rgba.crop((int(left - side * 0.03), int(top - side * 0.02), int(right + side * 0.08), int(bottom + side * 0.03)))
    canvas_side = max(crop.width, crop.height)
    background = tuple(rgba.getpixel((5, 5)))
    canvas = Image.new("RGBA", (canvas_side, canvas_side), background)
    canvas.paste(crop, ((canvas_side - crop.width) // 2, (canvas_side - crop.height) // 2), crop)
    crop = canvas.resize((size * 4, size * 4), Image.LANCZOS)
    mask = Image.new("L", crop.size, 0)
    from PIL import ImageDraw

    ImageDraw.Draw(mask).rounded_rectangle([0, 0, crop.width - 1, crop.height - 1], radius=int(crop.width * 0.22), fill=255)
    crop.putalpha(mask)
    return crop.resize((size, size), Image.LANCZOS)


def main(argv: list[str]) -> None:
    source_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_SOURCE
    source = Image.open(source_path)
    brand = ROOT / "assets" / "brand"
    brand.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != DEFAULT_SOURCE.resolve():
        source.save(DEFAULT_SOURCE)
    box = badge_box(source)
    frames = [render(source, box, size) for size in SIZES]
    target = ROOT / "windows" / "runner" / "resources" / "app_icon.ico"
    frames[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    frames[-1].save(brand / "app_icon_256.png")
    # Full artwork (badge + wordmark) for in-app branding, trimmed of the outer margin.
    full = source.convert("RGBA")
    bbox = Image.eval(full.convert("L"), lambda v: 255 if v < 235 else 0).getbbox()
    if bbox:
        margin = int(0.03 * full.width)
        full = full.crop((max(0, bbox[0] - margin), max(0, bbox[1] - margin), min(full.width, bbox[2] + margin), min(full.height, bbox[3] + margin)))
    full.thumbnail((1024, 1024), Image.LANCZOS)
    full.save(brand / "logo.png")
    print(f"badge box={box}; wrote {target} ({', '.join(str(s) for s in SIZES)} px), {brand / 'logo.png'}")


if __name__ == "__main__":
    main(sys.argv)
