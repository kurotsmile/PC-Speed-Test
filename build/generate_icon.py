#!/usr/bin/env python3
"""Generate modern 3D rounded-square icons for macOS and Windows builds."""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "build" / "assets"
ICONSET_DIR = ASSETS_DIR / "pc_speed_test.iconset"
PNG_PATH = ASSETS_DIR / "pc_speed_test_1024.png"
ICO_PATH = ASSETS_DIR / "pc_speed_test.ico"
ICNS_PATH = ASSETS_DIR / "pc_speed_test.icns"


def rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    return mask


def generate_base_icon(size: int = 1024) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Soft outer shadow
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (92, 112, size - 92, size - 72),
        radius=220,
        fill=(0, 0, 0, 160),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(38))
    image.alpha_composite(shadow)

    # Main rounded tile with layered gradient bands
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    tile_draw = ImageDraw.Draw(tile)
    for index in range(size):
        blend = index / (size - 1)
        top = (36, 208, 255)
        bottom = (44, 86, 205)
        r = int(top[0] * (1 - blend) + bottom[0] * blend)
        g = int(top[1] * (1 - blend) + bottom[1] * blend)
        b = int(top[2] * (1 - blend) + bottom[2] * blend)
        tile_draw.line((0, index, size, index), fill=(r, g, b, 255))

    tile_mask = rounded_mask(size, 220)
    tile.putalpha(tile_mask)
    image.alpha_composite(tile)

    # Glass highlight
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    highlight_draw = ImageDraw.Draw(highlight)
    highlight_draw.rounded_rectangle(
        (88, 86, size - 88, int(size * 0.46)),
        radius=180,
        fill=(255, 255, 255, 58),
    )
    highlight = highlight.filter(ImageFilter.GaussianBlur(18))
    highlight.putalpha(ImageChops.multiply(highlight.getchannel("A"), tile_mask))
    image.alpha_composite(highlight)

    # Inner panel shadow
    inner = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    inner_draw = ImageDraw.Draw(inner)
    inner_draw.rounded_rectangle(
        (190, 210, size - 190, size - 190),
        radius=150,
        fill=(7, 18, 34, 255),
    )
    image.alpha_composite(inner)

    # Floating 3D bars
    bars = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bars_draw = ImageDraw.Draw(bars)
    base_x = 270
    widths = [92, 92, 92]
    heights = [280, 390, 500]
    colors = [(49, 208, 255), (67, 242, 176), (255, 183, 71)]
    for idx, (width, height, color) in enumerate(zip(widths, heights, colors)):
        x = base_x + idx * 150
        y = size - 245 - height
        bars_draw.rounded_rectangle(
            (x, y, x + width, size - 245),
            radius=36,
            fill=(*color, 255),
        )
        bars_draw.polygon(
            [
                (x + width, y + 18),
                (x + width + 30, y - 12),
                (x + width + 30, size - 257),
                (x + width, size - 245),
            ],
            fill=(max(color[0] - 30, 0), max(color[1] - 30, 0), max(color[2] - 30, 0), 255),
        )
        bars_draw.polygon(
            [
                (x + 14, y + 20),
                (x + width - 14, y + 20),
                (x + width + 18, y - 12),
                (x + 32, y - 12),
            ],
            fill=(255, 255, 255, 34),
        )
    bars = bars.filter(ImageFilter.GaussianBlur(0.2))
    image.alpha_composite(bars)

    # Circular speed ring
    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    ring_draw.ellipse((168, 150, size - 168, size - 168), outline=(255, 255, 255, 28), width=28)
    ring_draw.arc((168, 150, size - 168, size - 168), start=210, end=28, fill=(255, 255, 255, 135), width=30)
    ring_draw.arc((206, 188, size - 206, size - 206), start=218, end=330, fill=(9, 23, 43, 220), width=24)
    image.alpha_composite(ring)

    # Center glyph
    glyph = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glyph_draw = ImageDraw.Draw(glyph)
    glyph_draw.rounded_rectangle((384, 302, 640, 368), radius=28, fill=(255, 255, 255, 28))
    glyph_draw.rounded_rectangle((384, 398, 700, 464), radius=28, fill=(255, 255, 255, 22))
    glyph_draw.rounded_rectangle((384, 494, 580, 560), radius=28, fill=(255, 255, 255, 18))
    glyph_draw.ellipse((716, 450, 790, 524), fill=(255, 255, 255, 220))
    glyph_draw.line((752, 486, 828, 410), fill=(255, 255, 255, 220), width=26)
    image.alpha_composite(glyph)

    # Final subtle vignette
    vignette = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=220, outline=(255, 255, 255, 26), width=8)
    image.alpha_composite(vignette)

    return image


def save_icon_variants(base: Image.Image) -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    base.save(PNG_PATH)
    base.save(ICO_PATH, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    if ICONSET_DIR.exists():
        shutil.rmtree(ICONSET_DIR)
    base.save(
        ICNS_PATH,
        format="ICNS",
        sizes=[(1024, 1024), (512, 512), (256, 256), (128, 128), (64, 64), (32, 32), (16, 16)],
    )


def main() -> int:
    base = generate_base_icon()
    save_icon_variants(base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
