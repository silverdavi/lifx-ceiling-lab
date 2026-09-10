"""Frame file schema: load, validate, save.

A frame file is JSON:

.. code-block:: json

    {
      "name": "My animation",
      "width": 8,
      "height": 8,
      "frames": [
        {"durationMs": 50, "pixels": ["rrggbb", "... 64 entries, row-major ..."]},
        {"name": "optional", "durationMs": 50, "pixels": ["..."]}
      ]
    }

``pixels`` is 64 lowercase RGB hex strings in row-major protocol order
(``y = i // 8``, ``x = i % 8``). Pixel 63 addresses the uplight ring and is
normally masked at send time. Static frame collections may name their frames
so tools can pick one by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence


def load_frames(path: Path) -> list[tuple[list[str], int]]:
    """Load and validate a frame file into ``(pixels, duration_ms)`` tuples."""
    document = json.loads(path.read_text())
    width = int(document.get("width", 8))
    height = int(document.get("height", 8))
    if (width, height) != (8, 8):
        raise ValueError(f"Ceiling frames must be 8x8, got {width}x{height}")
    frames = []
    for index, frame in enumerate(document["frames"]):
        pixels = frame["pixels"]
        if len(pixels) != 64:
            raise ValueError(f"frame {index} has {len(pixels)} pixels, expected 64")
        for pixel in pixels:
            if len(pixel.removeprefix("#")) != 6:
                raise ValueError(f"frame {index} has invalid RGB value {pixel!r}")
        duration_ms = int(frame.get("durationMs", 100))
        if duration_ms <= 0:
            raise ValueError(f"frame {index} has non-positive duration")
        frames.append((pixels, duration_ms))
    if not frames:
        raise ValueError("frames file contains no frames")
    return frames


def load_named_frame(path: Path, name: str) -> list[str]:
    """Return the pixel list of one named frame from a static collection."""
    document = json.loads(path.read_text())
    load_frames(path)  # validation side effect
    for frame in document["frames"]:
        if frame.get("name") == name:
            return frame["pixels"]
    available = ", ".join(
        str(frame["name"]) for frame in document["frames"] if "name" in frame
    )
    raise ValueError(f"frame {name!r} not found; available: {available or 'none'}")


def save_frames(
    path: Path,
    frames: Sequence[dict[str, object]],
    *,
    name: str,
    compact: bool = True,
) -> None:
    """Write a valid frame file. Each frame dict needs ``pixels`` (+ optionals)."""
    document = {"name": name, "width": 8, "height": 8, "frames": list(frames)}
    path.parent.mkdir(parents=True, exist_ok=True)
    separators = (",", ":") if compact else None
    path.write_text(json.dumps(document, separators=separators) + "\n")
    # round-trip validation so a bad generator fails loudly at write time
    load_frames(path)
