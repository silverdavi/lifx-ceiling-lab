#!/usr/bin/env python3
"""Show any image (or GIF) on the Ceiling: convert, preview, push.

    # a photo or logo → one static frame
    python3 examples/images/image_to_frames.py cat.jpg
    # an animated GIF → an animation, then loop it
    python3 examples/images/image_to_frames.py nyan.gif --loop

This is a thin wrapper over the installed converters:

- ``lifx-image``  — any image → one 8x8 frame (linear-light downscale)
- ``lifx-gif``    — animated GIF → frame sequence (or crisp grid sampling
  for pixel art, see ``lifx-gif --help``)
- ``lifx-play``   — send it

Requires Pillow (``pip install lifx-ceiling-lab[examples]``).
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lifx_ceiling import gif as gif_tool  # noqa: E402
from lifx_ceiling import images as image_tool  # noqa: E402
from lifx_ceiling import play as play_tool  # noqa: E402


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("input", type=Path)
    argument_parser.add_argument(
        "--output",
        type=Path,
        help="frame JSON to write (default: temp file, then push)",
    )
    argument_parser.add_argument("--saturation", type=float, default=1.25)
    argument_parser.add_argument("--loop", action="store_true", help="loop animations")
    argument_parser.add_argument(
        "--no-push", action="store_true", help="convert only, do not touch the fixture"
    )
    argument_parser.add_argument("--rotate", type=int)
    args = argument_parser.parse_args()

    output = args.output or Path(tempfile.gettempdir()) / f"{args.input.stem}-8x8.json"

    from PIL import Image

    animated = getattr(Image.open(args.input), "n_frames", 1) > 1
    if animated:
        argv = [str(args.input), str(output), "--saturation", str(args.saturation)]
        sys.argv = ["lifx-gif", *argv]
        gif_tool.main()
    else:
        argv = [str(args.input), str(output), "--saturation", str(args.saturation)]
        sys.argv = ["lifx-image", *argv]
        image_tool.main()

    if args.no_push:
        return 0

    play_argv = ["lifx-play", "--frames", str(output)]
    if animated:
        play_argv += ["--loop"] if args.loop else ["--cycles", "3"]
    else:
        play_argv += ["--cycles", "1"]
    if args.rotate is not None:
        play_argv += ["--rotate", str(args.rotate)]
    sys.argv = play_argv
    return play_tool.main()


if __name__ == "__main__":
    raise SystemExit(main())
