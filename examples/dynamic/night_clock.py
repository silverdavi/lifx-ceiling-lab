#!/usr/bin/env python3
"""Night clock for the Ceiling: rim n-gon for the hour, centre dot for the half hour.

Readable at ~2% brightness. The disc centre sits on the corner of the four
middle cells, so each rim vertex is one whole cell (a split vertex reads dim
and can vanish). Colours switch when the dot count resets to 1:

  7 pm → 12 am   green-yellow rim, dots 1→6
  1 am → 6 am    red-purple rim,   dots 1→6

Centre: red for :00–:29, green for :30–:59.

Bake a demo loop, write the README GIF, or stream the live wall clock::

    python3 examples/dynamic/night_clock.py            # frames + GIF
    python3 examples/dynamic/night_clock.py --live     # stream until Ctrl-C
    lifx-play --frames examples/dynamic/frames/night_clock.json --loop
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lifx_ceiling.client import connect, hex_to_hsbk  # noqa: E402
from lifx_ceiling.frames import save_frames  # noqa: E402
from lifx_ceiling.transform import UPLIGHT_INDEX  # noqa: E402

Band = Literal["evening", "night"]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRAMES = Path(__file__).parent / "frames" / "night_clock.json"
DEFAULT_GIF = ROOT / "docs" / "assets" / "night-clock.gif"
DEFAULT_STRIP = ROOT / "docs" / "assets" / "night-clock-strip.png"

COLOR_EVENING = "b0c248"
COLOR_NIGHT = "c04a8c"
COLOR_FIRST_HALF = "d0302a"
COLOR_SECOND_HALF = "2fae4a"

# Cell (x, y) is centred at (x, y). Vertices are single cells on the ring at
# radius 2.55–2.92, searched for near-regular angles with every pair ≥2.2 cells
# apart and none next to the centre blob.
POLYGON_CELLS: dict[int, list[tuple[int, int]]] = {
    1: [(4, 1)],
    2: [(4, 1), (3, 6)],
    3: [(6, 4), (2, 6), (2, 1)],
    4: [(4, 1), (6, 4), (3, 6), (1, 3)],
    5: [(3, 1), (6, 2), (6, 5), (3, 6), (1, 4)],
    6: [(5, 1), (6, 4), (5, 6), (2, 6), (1, 4), (2, 1)],
}
CENTRE_CELLS = [(3, 3), (4, 3), (3, 4), (4, 4)]
CENTRE_WEIGHT = 0.5

# One face per wall hour in the night window (6 pm … 6 am).
DEMO_HOURS = [18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6]
DEMO_DURATION_MS = 900


def _face_hour(hour_24: int) -> int:
    return hour_24 % 12 or 12


def _face_band(hour_24: int) -> Band:
    return "evening" if _face_hour(hour_24) >= 7 else "night"


def band_for_hour(hour_24: int) -> Band | None:
    if hour_24 >= 18 or hour_24 <= 6:
        return _face_band(hour_24)
    return None


def vertex_count(hour_24: int) -> int:
    return (_face_hour(hour_24) - 1) % 6 + 1


def _mix(hex_value: str, weight: float) -> str:
    weight = max(0.0, min(1.0, weight))
    red, green, blue = bytes.fromhex(hex_value.removeprefix("#"))
    return (
        f"{int(round(red * weight)):02x}"
        f"{int(round(green * weight)):02x}"
        f"{int(round(blue * weight)):02x}"
    )


def pixels_for_time(
    when: datetime,
    brightness: float = 1.0,
    *,
    daytime_test: bool = False,
) -> tuple[list[str], Band | None, int]:
    """Return 64 RGB hex pixels for ``when`` (brightness 0–1)."""
    band = band_for_hour(when.hour)
    if band is None and daytime_test:
        band = _face_band(when.hour)
    out = ["000000"] * 64
    if band is None:
        return out, None, 0

    factor = max(0.01, min(1.0, brightness))
    count = vertex_count(when.hour)
    rim = COLOR_EVENING if band == "evening" else COLOR_NIGHT
    centre = COLOR_FIRST_HALF if when.minute < 30 else COLOR_SECOND_HALF

    for x, y in POLYGON_CELLS[count]:
        out[y * 8 + x] = _mix(rim, factor)
    for x, y in CENTRE_CELLS:
        out[y * 8 + x] = _mix(centre, factor * CENTRE_WEIGHT)
    out[UPLIGHT_INDEX] = "000000"
    return out, band, count


def demo_sequence() -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for hour in DEMO_HOURS:
        for minute in (10, 40):
            when = datetime(2026, 1, 1, hour, minute)
            pixels, band, count = pixels_for_time(when, brightness=1.0)
            face = _face_hour(hour)
            ampm = "am" if hour < 12 else "pm"
            if hour == 0:
                ampm = "am"
            label = f"{face}:{minute:02d}{ampm}"
            frames.append(
                {
                    "name": f"{label} · {band} · {count} dots",
                    "durationMs": DEMO_DURATION_MS,
                    "pixels": pixels,
                }
            )
    return frames


def write_preview_gif(frames: list[dict[str, object]], path: Path, *, size: int = 224) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    cell = size // 8
    disc = size
    images = []
    for frame in frames:
        crisp = Image.new("RGB", (disc, disc), (0, 0, 0))
        draw = ImageDraw.Draw(crisp)
        for index, hex_value in enumerate(frame["pixels"]):  # type: ignore[arg-type]
            if index == UPLIGHT_INDEX:
                continue
            x, y = index % 8, index // 8
            red, green, blue = bytes.fromhex(str(hex_value))
            if red == green == blue == 0:
                continue
            draw.rectangle(
                [x * cell, y * cell, x * cell + cell - 1, y * cell + cell - 1],
                fill=(red, green, blue),
            )
        soft = crisp.filter(ImageFilter.GaussianBlur(cell * 0.55))
        mask = Image.new("L", (disc, disc), 0)
        ImageDraw.Draw(mask).ellipse([2, 2, disc - 3, disc - 3], fill=255)
        canvas = Image.new("RGB", (disc, disc), (8, 8, 10))
        canvas.paste(soft, (0, 0), mask)
        images.append(canvas.convert("P", palette=Image.Palette.ADAPTIVE, colors=64))

    path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=DEMO_DURATION_MS,
        loop=0,
        optimize=True,
    )


def write_strip(frames: list[dict[str, object]], path: Path, *, cell: int = 18) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    # One tile per wall hour (use the :10 / first-half frame of each pair).
    hour_frames = frames[::2]
    tile = 8 * cell
    gap = 10
    label_h = 22
    width = len(hour_frames) * (tile + gap) - gap
    strip = Image.new("RGB", (width, tile + label_h + 8), (8, 8, 10))
    draw = ImageDraw.Draw(strip)
    try:
        font = ImageFont.load_default(size=12)
    except TypeError:
        font = ImageFont.load_default()

    for index, frame in enumerate(hour_frames):
        crisp = Image.new("RGB", (tile, tile), (0, 0, 0))
        td = ImageDraw.Draw(crisp)
        for z, hex_value in enumerate(frame["pixels"]):  # type: ignore[arg-type]
            if z == UPLIGHT_INDEX:
                continue
            x, y = z % 8, z // 8
            red, green, blue = bytes.fromhex(str(hex_value))
            if red | green | blue:
                td.rectangle(
                    [x * cell, y * cell, x * cell + cell - 1, y * cell + cell - 1],
                    fill=(red, green, blue),
                )
        soft = crisp.filter(ImageFilter.GaussianBlur(cell * 0.5))
        mask = Image.new("L", (tile, tile), 0)
        ImageDraw.Draw(mask).ellipse([1, 1, tile - 2, tile - 2], fill=255)
        ox = index * (tile + gap)
        strip.paste(soft, (ox, 0), mask)
        name = str(frame.get("name", "")).split(" · ")[0]
        draw.text((ox + 4, tile + 4), name, fill=(200, 200, 200), font=font)

    path.parent.mkdir(parents=True, exist_ok=True)
    strip.save(path)


def run_live(brightness_pct: float, *, daytime_test: bool) -> int:
    client = connect()
    print(
        f"night clock live on {client.ip} at {brightness_pct:.0f}% "
        f"(Ctrl-C to stop; daytime_test={daytime_test})"
    )
    client.set_light_power(0xFFFF, duration_ms=150)
    try:
        while True:
            now = datetime.now()
            pixels, band, count = pixels_for_time(
                now,
                brightness=brightness_pct / 100.0,
                daytime_test=daytime_test,
            )
            colors = [hex_to_hsbk(value) for value in pixels]
            client.set64(colors, duration_ms=200)
            half = "first" if now.minute < 30 else "second"
            print(
                f"\r{now.strftime('%H:%M:%S')}  "
                f"band={band!s}  dots={count}  half={half}   ",
                end="",
                flush=True,
            )
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        client.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_FRAMES)
    parser.add_argument("--gif", type=Path, default=DEFAULT_GIF)
    parser.add_argument("--strip", type=Path, default=DEFAULT_STRIP)
    parser.add_argument(
        "--live",
        action="store_true",
        help="stream the wall clock to the fixture instead of baking frames",
    )
    parser.add_argument(
        "--brightness",
        type=float,
        default=2.0,
        help="peak brightness percent when --live (default 2)",
    )
    parser.add_argument(
        "--daytime-test",
        action="store_true",
        help="with --live, show a face outside 6 pm–7 am",
    )
    parser.add_argument(
        "--no-assets",
        action="store_true",
        help="skip writing the README GIF and strip PNG",
    )
    args = parser.parse_args()

    if args.live:
        return run_live(args.brightness, daytime_test=args.daytime_test)

    frames = demo_sequence()
    save_frames(args.output, frames, name="Night clock", compact=True)
    print(f"wrote {args.output} ({len(frames)} frames)")

    if not args.no_assets:
        write_preview_gif(frames, args.gif)
        print(f"wrote {args.gif}")
        write_strip(frames, args.strip)
        print(f"wrote {args.strip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
