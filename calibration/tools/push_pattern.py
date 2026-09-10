#!/usr/bin/env python3
"""Push a calibration pattern to the fixture, raw (rotate 0, no flips).

Usage:

    python3 calibration/tools/push_pattern.py calibration/patterns/psf-sparse
    python3 calibration/tools/push_pattern.py calibration/patterns/color-fill-63 --verify

Patterns are always sent in protocol index order so photos map directly to
zone indices. The previous fixture state is snapshotted first; restore it with
``lifx-play --restore-only`` when you are done photographing.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# allow running from a source checkout without installing
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lifx_ceiling import connect, hex_to_hsbk, load_frames  # noqa: E402


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "pattern",
        type=Path,
        help="pattern directory (containing frames.json) or a frame file",
    )
    argument_parser.add_argument("--ip", help="skip discovery and use this device IP")
    argument_parser.add_argument("--serial", help="target device serial")
    argument_parser.add_argument(
        "--verify",
        action="store_true",
        help="read the zone map back with Get64 and report mismatches",
    )
    args = argument_parser.parse_args()

    frames_path = args.pattern / "frames.json" if args.pattern.is_dir() else args.pattern
    pixels, _duration = load_frames(frames_path)[0]

    with connect(ip=args.ip, serial=args.serial, rotate=0) as client:
        saved = client.save_state()
        print(
            "saved previous state" if saved else "previous state already saved",
            "- restore later with: lifx-play --restore-only",
        )
        client.set_light_power(0xFFFF, duration_ms=150)
        time.sleep(0.3)
        expected = [hex_to_hsbk(pixel) for pixel in pixels]
        client.set64(expected, duration_ms=300, rotate=0, mask_uplight=True)
        print(f"pushed {frames_path} raw (rotate 0), uplight masked")

        if args.verify:
            time.sleep(0.6)
            actual = client.get64()
            mismatches = [
                index
                for index in range(63)  # uplight zone excluded
                if actual[index][:3] != expected[index][:3]
            ]
            if mismatches:
                print(f"Get64 mismatches at zones: {mismatches}")
                return 1
            print("Get64 readback matches all 63 visible zones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
