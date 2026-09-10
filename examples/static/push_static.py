#!/usr/bin/env python3
"""Push one named static frame from mario_portrait.json to the fixture.

    python3 examples/static/push_static.py            # the default 'face'
    python3 examples/static/push_static.py brim --rotate 180
    python3 examples/static/push_static.py --list

Equivalent to ``lifx-play --static NAME``; kept here as a minimal example of
the library API. Restore whatever was on the fixture before with
``lifx-play --restore-only``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lifx_ceiling import connect, hex_to_hsbk, load_named_frame  # noqa: E402

FRAMES = Path(__file__).parent / "mario_portrait.json"


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("name", nargs="?", default="face")
    argument_parser.add_argument("--list", action="store_true", help="list frame names")
    argument_parser.add_argument("--rotate", type=int, default=None)
    argument_parser.add_argument("--ip")
    argument_parser.add_argument("--serial")
    args = argument_parser.parse_args()

    if args.list:
        document = json.loads(FRAMES.read_text())
        print("\n".join(str(frame["name"]) for frame in document["frames"]))
        return 0

    pixels = load_named_frame(FRAMES, args.name)
    with connect(ip=args.ip, serial=args.serial, rotate=args.rotate) as client:
        client.save_state()
        client.set_light_power(0xFFFF, duration_ms=150)
        time.sleep(0.2)
        client.set64([hex_to_hsbk(pixel) for pixel in pixels], duration_ms=300)
    print(f"showing {args.name!r}; undo with: lifx-play --restore-only")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
