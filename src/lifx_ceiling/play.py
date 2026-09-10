#!/usr/bin/env python3
"""Play 8x8 frame files on a LIFX Ceiling. Installed as ``lifx-play``.

Examples::

    lifx-play --frames examples/dynamic/frames/firefly.json --loop
    lifx-play --static face --rotate 180
    lifx-play --restore-only
    lifx-play --frames examples/dynamic/frames/firefly.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from .client import DEFAULT_STATE_FILE, connect, hex_to_hsbk, load_config
from .frames import load_frames, load_named_frame
from .transform import UPLIGHT_INDEX, VALID_ROTATIONS, transform_zones

running = True
DEFAULT_STATIC_FRAMES = (
    Path(__file__).resolve().parents[2]
    / "examples"
    / "static"
    / "mario_portrait.json"
)


def stop_requested(_signum: int, _frame: object) -> None:
    global running
    running = False


def apply_display_options(pixels: list[str], args: argparse.Namespace) -> list[str]:
    transformed = transform_zones(
        pixels,
        rotate=args.rotate,
        flip_h=args.flip_h,
        flip_v=args.flip_v,
    )
    if not args.include_uplight:
        transformed[UPLIGHT_INDEX] = "000000"
    return transformed


def print_frame(index: int, pixels: list[str], duration_ms: int) -> None:
    print(f"frame {index + 1} ({duration_ms} ms)")
    for y in range(8):
        row = []
        for value in pixels[y * 8 : (y + 1) * 8]:
            red, green, blue = bytes.fromhex(value.removeprefix("#"))
            luminance = (299 * red + 587 * green + 114 * blue) // 1000
            row.append("##" if luminance >= 24 else "  ")
        print("".join(row))


def sleep_interruptibly(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while running and time.monotonic() < deadline:
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))


def parser() -> argparse.ArgumentParser:
    config = load_config()
    result = argparse.ArgumentParser(
        description="Play an 8x8 frame file on a LIFX Ceiling."
    )
    result.add_argument("--frames", type=Path, help="JSON frame data to play")
    result.add_argument(
        "--static",
        nargs="?",
        const="face",
        metavar="NAME",
        help="show one named frame and leave it in place (default: face)",
    )
    repetitions = result.add_mutually_exclusive_group()
    repetitions.add_argument("--loop", action="store_true", help="repeat until stopped")
    repetitions.add_argument("--cycles", type=int, default=1, help="cycles to play")
    result.add_argument(
        "--fps",
        type=float,
        help="override per-frame durations with a fixed frame rate",
    )
    result.add_argument(
        "--duration",
        type=int,
        default=300,
        help="static-frame transition duration in milliseconds (default: 300)",
    )
    result.add_argument(
        "--rotate",
        type=int,
        choices=VALID_ROTATIONS,
        default=config["rotate"],
        help="clockwise rotation before Set64 (0 is protocol index order)",
    )
    result.add_argument("--flip-h", action="store_true", help="flip frames horizontally")
    result.add_argument("--flip-v", action="store_true", help="flip frames vertically")
    result.add_argument(
        "--include-uplight",
        action="store_true",
        help="allow frame pixel 63 to control the uplight",
    )
    result.add_argument(
        "--restore",
        action="store_true",
        help="restore the saved matrix and power after playback stops",
    )
    result.add_argument(
        "--restore-only",
        action="store_true",
        help="restore saved state without playing frames",
    )
    result.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"saved matrix and power (default: {DEFAULT_STATE_FILE})",
    )
    result.add_argument("--ip", default=config["ip"], help="skip discovery and use this device IP")
    result.add_argument("--serial", default=config["serial"], help="target device serial")
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="print frames as ASCII without opening a network socket",
    )
    return result


def validate_args(args: argparse.Namespace) -> None:
    if not args.restore_only and args.frames is None and args.static is None:
        raise ValueError("--frames is required unless --static or --restore-only is used")
    if args.restore_only and args.dry_run:
        raise ValueError("--dry-run cannot be combined with --restore-only")
    if args.restore_only and args.static is not None:
        raise ValueError("--static cannot be combined with --restore-only")
    if args.static is not None and args.loop:
        raise ValueError("--static cannot be combined with --loop")
    if args.cycles < 1:
        raise ValueError("--cycles must be at least 1")
    if args.fps is not None and args.fps <= 0:
        raise ValueError("--fps must be greater than zero")
    if args.duration < 0:
        raise ValueError("--duration cannot be negative")


def play(args: argparse.Namespace) -> int:
    frames = load_frames(args.frames)
    effective = [
        (
            apply_display_options(pixels, args),
            round(1000 / args.fps) if args.fps else duration_ms,
        )
        for pixels, duration_ms in frames
    ]
    cycle_seconds = sum(duration for _, duration in effective) / 1000
    print(
        f"playing {len(effective)} frames, {cycle_seconds:.2f}s per cycle"
        + (" until stopped" if args.loop else f", {args.cycles} cycle(s)"),
        flush=True,
    )

    if args.dry_run:
        client = None
        packed_frames = []
    else:
        client = connect(
            ip=args.ip,
            serial=args.serial,
            rotate=args.rotate,
            flip_h=args.flip_h,
            flip_v=args.flip_v,
        )
        saved = client.save_state(args.state_file)
        print(
            (
                f"saved pre-animation state to {args.state_file}"
                if saved
                else f"preserving existing state at {args.state_file}"
            ),
            flush=True,
        )
        client.set_light_power(0xFFFF, duration_ms=150)
        sleep_interruptibly(0.2)
        packed_frames = [
            [hex_to_hsbk(pixel) for pixel in pixels] for pixels, _ in frames
        ]

    completed = 0
    try:
        while running and (args.loop or completed < args.cycles):
            for index, (pixels, duration_ms) in enumerate(effective):
                if not running:
                    break
                if client is None:
                    print_frame(index, pixels, duration_ms)
                else:
                    client.set64(
                        packed_frames[index],
                        mask_uplight=not args.include_uplight,
                    )
                sleep_interruptibly(duration_ms / 1000)
            completed += 1
    finally:
        if client is not None:
            try:
                if args.restore:
                    client.restore_state(args.state_file)
                    print(f"restored state from {args.state_file}", flush=True)
            finally:
                client.close()

    disposition = "restored saved state" if args.restore else "left last frame in place"
    print(f"stopped after {completed} cycle(s); {disposition}", flush=True)
    return 0


def show_static(args: argparse.Namespace) -> int:
    path = args.frames or DEFAULT_STATIC_FRAMES
    source = load_named_frame(path, args.static)
    pixels = apply_display_options(source, args)
    print(
        f"showing static frame {args.static!r} from {path} "
        f"rotate={args.rotate} flip_h={args.flip_h} flip_v={args.flip_v}",
        flush=True,
    )
    if args.dry_run:
        print_frame(0, pixels, args.duration)
        print("dry run; no network socket opened", flush=True)
        return 0

    with connect(
        ip=args.ip,
        serial=args.serial,
        rotate=args.rotate,
        flip_h=args.flip_h,
        flip_v=args.flip_v,
    ) as client:
        saved = client.save_state(args.state_file)
        print(
            (
                f"saved pre-display state to {args.state_file}"
                if saved
                else f"preserving existing state at {args.state_file}"
            ),
            flush=True,
        )
        client.set_light_power(0xFFFF, duration_ms=150)
        sleep_interruptibly(0.2)
        client.set64(
            [hex_to_hsbk(pixel) for pixel in source],
            duration_ms=args.duration,
            mask_uplight=not args.include_uplight,
        )
    print("left static frame in place", flush=True)
    return 0


def restore_only(args: argparse.Namespace) -> int:
    with connect(ip=args.ip, serial=args.serial) as client:
        client.restore_state(args.state_file)
    print(f"restored matrix and power from {args.state_file}", flush=True)
    return 0


def main() -> int:
    signal.signal(signal.SIGTERM, stop_requested)
    signal.signal(signal.SIGINT, stop_requested)
    args = parser().parse_args()
    try:
        validate_args(args)
        if args.restore_only:
            return restore_only(args)
        if args.static is not None:
            return show_static(args)
        return play(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, TimeoutError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
