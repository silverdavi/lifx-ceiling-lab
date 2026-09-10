#!/usr/bin/env python3
"""Turn an animated GIF (or multi-frame image) into a Ceiling frame file.
Installed as ``lifx-gif``. Requires Pillow.

Two modes:

- **resize** (default): every source frame is downscaled to 8x8 in linear
  light, like ``lifx-image``. Works on any GIF.
- **grid sample** (``--origin-x/--origin-y/--cell-size``): sample one source
  pixel per zone on a fixed grid. This is the right tool when the source is
  pixel art whose cells are larger than one pixel — sampling keeps edges
  crisp where resizing would smear them.

Duplicate consecutive frames are dropped; their duration folds into the
survivor via the source's own frame timing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from .frames import save_frames
from .images import image_to_pixels


def sample_grid(
    rgb: Image.Image, *, origin_x: int, origin_y: int, cell_size: int
) -> list[str]:
    pixels = [
        "%02x%02x%02x"
        % rgb.getpixel((origin_x + x * cell_size, origin_y + y * cell_size))
        for y in range(8)
        for x in range(8)
    ]
    pixels[63] = "000000"
    return pixels


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Convert a GIF into 8x8 animation JSON (resize or grid sample)."
    )
    result.add_argument("input", type=Path)
    result.add_argument("output", type=Path)
    result.add_argument("--name")
    result.add_argument("--origin-x", type=int, help="grid-sample mode: first sample x")
    result.add_argument("--origin-y", type=int, help="grid-sample mode: first sample y")
    result.add_argument("--cell-size", type=int, help="grid-sample mode: pixels per zone")
    result.add_argument("--max-frame-ms", type=int)
    result.add_argument("--default-frame-ms", type=int, default=100)
    result.add_argument(
        "--saturation",
        type=float,
        default=1.25,
        help="resize mode saturation multiplier (default 1.25)",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    grid_args = (args.origin_x, args.origin_y, args.cell_size)
    grid_mode = any(value is not None for value in grid_args)
    if grid_mode and None in grid_args:
        raise ValueError(
            "grid-sample mode needs all of --origin-x, --origin-y, --cell-size"
        )
    if grid_mode and args.cell_size <= 0:
        raise ValueError("--cell-size must be positive")

    image = Image.open(args.input)
    frame_count = getattr(image, "n_frames", 1)
    sampled: list[dict[str, object]] = []
    previous: list[str] | None = None

    for index in range(frame_count):
        image.seek(index)
        if grid_mode:
            pixels = sample_grid(
                image.convert("RGB"),
                origin_x=args.origin_x,
                origin_y=args.origin_y,
                cell_size=args.cell_size,
            )
        else:
            pixels = image_to_pixels(image, saturation=args.saturation)
        if pixels == previous:
            continue
        duration_ms = int(image.info.get("duration") or args.default_frame_ms)
        if args.max_frame_ms is not None:
            duration_ms = min(duration_ms, args.max_frame_ms)
        sampled.append({"durationMs": duration_ms, "pixels": pixels})
        previous = pixels

    name = args.name or args.input.stem
    save_frames(args.output, sampled, name=name)
    total_ms = sum(int(frame["durationMs"]) for frame in sampled)
    print(f"wrote {len(sampled)} frames ({total_ms / 1000:.2f}s) to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
