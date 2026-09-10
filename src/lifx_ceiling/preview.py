#!/usr/bin/env python3
"""Render Ceiling frame data at pixel and diffuser scale. Installed as
``lifx-preview``. Requires Pillow (``pip install lifx-ceiling-lab[examples]``).

The right-hand panel of each preview approximates the milky diffuser with a
Gaussian blur; the fitted point-spread sigma for the fixture is about 0.8
zones (see ``calibration/defaults/kernel.json``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .frames import load_frames
from .transform import DEFAULT_ROTATE, UPLIGHT_INDEX, VALID_ROTATIONS, transform_zones


def font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def image_from_pixels(pixels: list[str], *, mask_uplight: bool) -> Image.Image:
    effective = list(pixels)
    if mask_uplight:
        effective[UPLIGHT_INDEX] = "000000"
    image = Image.new("RGB", (8, 8))
    image.putdata(
        [tuple(bytes.fromhex(value.removeprefix("#"))) for value in effective]
    )
    return image


def render_panel(
    pixels: list[str],
    *,
    cell: int,
    mask_uplight: bool,
) -> Image.Image:
    image = image_from_pixels(pixels, mask_uplight=mask_uplight)
    size = cell * 8
    crisp = image.resize((size, size), Image.Resampling.NEAREST)
    soft = crisp.filter(ImageFilter.GaussianBlur(cell * 0.42))
    panel = Image.new("RGB", (size * 2 + 18, size), (24, 24, 26))
    panel.paste(crisp, (0, 0))
    panel.paste(soft, (size + 18, 0))

    draw = ImageDraw.Draw(panel)
    for index in range(1, 8):
        draw.line([(index * cell, 0), (index * cell, size)], fill=(70, 70, 74))
        draw.line([(0, index * cell), (size, index * cell)], fill=(70, 70, 74))
    if mask_uplight:
        x = (UPLIGHT_INDEX % 8) * cell
        y = (UPLIGHT_INDEX // 8) * cell
        draw.rectangle(
            [x, y, x + cell - 1, y + cell - 1],
            outline=(220, 90, 90),
            width=2,
        )
    return panel


def load_named_pixels(path: Path) -> list[tuple[str, list[str]]]:
    document = json.loads(path.read_text())
    load_frames(path)
    return [
        (str(frame.get("name", index + 1)), frame["pixels"])
        for index, frame in enumerate(document["frames"])
    ]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Preview an 8x8 Ceiling design without opening a network socket."
    )
    result.add_argument("output", type=Path, help="PNG path to write")
    result.add_argument("--frames", type=Path, required=True)
    selection = result.add_mutually_exclusive_group()
    selection.add_argument("--frame", default="face", help="named frame to render")
    selection.add_argument("--all", action="store_true", help="render every named frame")
    result.add_argument(
        "--rotate",
        type=int,
        choices=VALID_ROTATIONS,
        default=DEFAULT_ROTATE,
        help="clockwise rotation to match the physical disc (0 is protocol index order)",
    )
    result.add_argument("--flip-h", action="store_true")
    result.add_argument("--flip-v", action="store_true")
    result.add_argument("--include-uplight", action="store_true")
    result.add_argument("--cell-size", type=int, default=52)
    return result


def main() -> int:
    args = parser().parse_args()
    if args.cell_size < 8:
        raise ValueError("--cell-size must be at least 8")
    named_pixels = load_named_pixels(args.frames)
    if not args.all:
        named_pixels = [
            (name, pixels) for name, pixels in named_pixels if name == args.frame
        ]
        if not named_pixels:
            raise ValueError(f"frame {args.frame!r} not found in {args.frames}")

    panels = []
    for name, pixels in named_pixels:
        oriented = transform_zones(
            pixels,
            rotate=args.rotate,
            flip_h=args.flip_h,
            flip_v=args.flip_v,
        )
        panels.append(
            (
                name,
                render_panel(
                    oriented,
                    cell=args.cell_size,
                    mask_uplight=not args.include_uplight,
                ),
            )
        )

    padding, heading = 16, 66
    width = max(panel.width for _, panel in panels) + padding * 2
    height = heading + sum(panel.height + heading for _, panel in panels)
    sheet = Image.new("RGB", (width, height), (24, 24, 26))
    draw = ImageDraw.Draw(sheet)
    draw.text(
        (padding, 20),
        "LIFX Ceiling 8x8 preview",
        font=font(24),
        fill=(240, 240, 240),
    )
    y = heading
    for name, panel in panels:
        draw.text(
            (padding, y + 8),
            f"{name}   left: pixels   right: diffuser approximation",
            font=font(20),
            fill=(235, 235, 235),
        )
        sheet.paste(panel, (padding, y + heading - 28))
        y += panel.height + heading

    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output)
    print(f"wrote {len(panels)} preview(s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
