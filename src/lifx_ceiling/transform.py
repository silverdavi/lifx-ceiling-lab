"""Orientation and uplight helpers for the 64-zone Ceiling matrix.

The LIFX Ceiling reports 64 zones through ``Set64``/``Get64`` in row-major
order: index ``i`` is ``(x, y) = (i % 8, i // 8)``. Zones 0-62 are the visible
downlight disc; zone 63 is the uplight ring around the rim and is **not** part
of the picture — mask it unless you mean to drive it.

Rotation is clockwise and applied before sending, so frame files can always be
authored "y = 0 at the top" and rotated to match however the disc happens to
be mounted.
"""

from __future__ import annotations

from typing import Sequence, TypeVar

T = TypeVar("T")

UPLIGHT_INDEX = 63
DEFAULT_ROTATE = 0
VALID_ROTATIONS = (0, 90, 180, 270)


def transform_zones(
    zones: Sequence[T],
    *,
    rotate: int = DEFAULT_ROTATE,
    flip_h: bool = False,
    flip_v: bool = False,
) -> list[T]:
    """Rotate/flip a 64-entry row-major zone list. Works on any element type."""
    if len(zones) != 64:
        raise ValueError(f"Ceiling matrix requires 64 zones, got {len(zones)}")
    if rotate not in VALID_ROTATIONS:
        raise ValueError(f"rotate must be one of {VALID_ROTATIONS}, got {rotate}")
    grid = [list(zones[index : index + 8]) for index in range(0, 64, 8)]
    for _ in range(rotate // 90):
        grid = [list(row) for row in zip(*grid[::-1])]
    if flip_h:
        grid = [row[::-1] for row in grid]
    if flip_v:
        grid = grid[::-1]
    return [cell for row in grid for cell in row]


def with_uplight_masked(colors: Sequence[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    """Zero the brightness of zone 63 (the uplight) in an HSBK zone list."""
    if len(colors) != 64:
        raise ValueError(f"Ceiling matrix requires 64 colors, got {len(colors)}")
    masked = list(colors)
    hue, saturation, _brightness, kelvin = masked[UPLIGHT_INDEX]
    masked[UPLIGHT_INDEX] = (hue, saturation, 0, kelvin)
    return masked
