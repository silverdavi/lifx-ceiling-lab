#!/usr/bin/env python3
"""Turn any image into a single 8x8 Ceiling frame. Installed as ``lifx-image``.

Requires Pillow (``pip install lifx-ceiling-lab[examples]``).

Pipeline:

1. optional center square crop (default on — the visible disc is round);
2. linear-light downscale to 8x8 (averaging in sRGB darkens edges; convert to
   linear, box-average, convert back);
3. optional saturation and brightness boost — a 64-zone thumbnail behind a
   diffuser reads better slightly over-saturated;
4. write a one-frame frame file for ``lifx-play --static`` or the widget.

Zone 63 (uplight) is written black; the send path masks it anyway.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance

from .frames import save_frames


def downscale_linear(image: Image.Image) -> Image.Image:
    """Average to 8x8 in linear light, then re-encode to sRGB.

    Box-averaging directly in sRGB darkens edges and mid-tones; converting to
    linear light first is what makes an 8x8 thumbnail keep its apparent
    brightness.
    """
    srgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    linear = np.where(
        srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4
    )
    height, width = linear.shape[:2]
    row_edges = np.linspace(0, height, 9).astype(int)
    column_edges = np.linspace(0, width, 9).astype(int)
    cells = np.zeros((8, 8, 3))
    for y in range(8):
        for x in range(8):
            cells[y, x] = linear[
                row_edges[y] : max(row_edges[y + 1], row_edges[y] + 1),
                column_edges[x] : max(column_edges[x + 1], column_edges[x] + 1),
            ].mean(axis=(0, 1))
    back = np.where(
        cells <= 0.0031308, cells * 12.92, 1.055 * cells ** (1 / 2.4) - 0.055
    )
    return Image.fromarray(
        (np.clip(back, 0, 1) * 255).round().astype(np.uint8), mode="RGB"
    )


def image_to_pixels(
    image: Image.Image,
    *,
    crop_square: bool = True,
    saturation: float = 1.25,
    brightness: float = 1.0,
) -> list[str]:
    """Return 64 row-major hex pixels for one image."""
    frame = image.convert("RGB")
    if crop_square:
        width, height = frame.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        frame = frame.crop((left, top, left + side, top + side))
    small = downscale_linear(frame)
    if saturation != 1.0:
        small = ImageEnhance.Color(small).enhance(saturation)
    if brightness != 1.0:
        small = ImageEnhance.Brightness(small).enhance(brightness)
    flat = np.asarray(small.convert("RGB")).reshape(64, 3)
    pixels = ["%02x%02x%02x" % tuple(int(v) for v in pixel) for pixel in flat]
    pixels[63] = "000000"  # uplight zone carries no picture content
    return pixels


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Convert an image to a one-frame 8x8 Ceiling frame file."
    )
    result.add_argument("input", type=Path)
    result.add_argument("output", type=Path, help="frame JSON path to write")
    result.add_argument("--name", help="frame file name (default: input stem)")
    result.add_argument(
        "--no-crop",
        action="store_true",
        help="squash to 8x8 instead of center-cropping a square first",
    )
    result.add_argument(
        "--saturation",
        type=float,
        default=1.25,
        help="saturation multiplier (default 1.25; 1.0 leaves it alone)",
    )
    result.add_argument(
        "--brightness",
        type=float,
        default=1.0,
        help="brightness multiplier (default 1.0)",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    image = Image.open(args.input)
    pixels = image_to_pixels(
        image,
        crop_square=not args.no_crop,
        saturation=args.saturation,
        brightness=args.brightness,
    )
    name = args.name or args.input.stem
    save_frames(
        args.output,
        [{"name": name, "durationMs": 300, "pixels": pixels}],
        name=name,
    )
    print(f"wrote 1 frame to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
