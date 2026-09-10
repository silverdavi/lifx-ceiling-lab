#!/usr/bin/env python3
"""Firefly for the Ceiling: real dynamics, comet trail, colour on impact.

Physics, not easing. The firefly is integrated under constant gravity with
sub-stepping, and bounces inside a circular arena because the fixture's
visible area is a disc — a square box would put the floor and corners off the
glass (arena radius 3.55 zones vs the fitted aperture of 4.318, see
``calibration/defaults/kernel.json``).

Three things stop it from degenerating into a ball orbiting the rim:

- strong tangential friction at every impact, so tangential energy cannot
  accumulate into an orbit;
- Gaussian scatter of the rebound direction (geometric noise), so repeated
  impacts never settle into a closed polygonal orbit;
- a minimum-inward-angle floor: reflection off a curved wall preserves grazing
  incidence, so a shallow arrival would leave shallow and hug the rim.
  Rotating the rebound at least 34 degrees off the wall tangent forces real
  interior crossings.

Each wall impact picks a new hue (forced at least ~70 degrees away from the
current one so consecutive bounces read as different colours). Colour changes
happen **only on contact**. The trail is an exponentially decaying
accumulation buffer at 24x the zone resolution, with the firefly splatted at
every physics sub-step, so fast motion produces real motion blur rather than
a stuttering dot. Energy is re-injected at impacts only — a speed floor
applied every sub-step would flatten the apex of every arc.

Requires numpy and Pillow (``pip install lifx-ceiling-lab[examples]``).
Reproducible: the default seed regenerates ``frames/firefly.json``
byte-for-byte. Play the result with::

    lifx-play --frames examples/dynamic/frames/firefly.json --loop
"""

from __future__ import annotations

import argparse
import colorsys
import math
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from lifx_ceiling.frames import save_frames  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).parent / "frames" / "firefly.json"

FPS = 20
SECONDS = 45
SUBSTEPS = 12

ARENA = 3.55          # zones, radius travelled by the firefly centre
BODY = 0.42           # zones, splat sigma
GRAVITY = 26.0        # zones / s^2
RESTITUTION = 0.92
TANGENT_FRICTION = 0.82   # strong, so tangential energy cannot accumulate into an orbit
ENERGY_FLOOR = 115.0      # applied at impacts only, keeps it lively
CONTACT_SPEED = 0.4       # below this a wall touch is contact, not an impact
SCATTER_DEGREES = 14.0    # random perturbation of the rebound direction
MIN_INWARD_DEGREES = 34.0 # minimum angle off the wall tangent, forces interior crossings

SUP = 24              # render supersampling, pixels per zone
N = 8 * SUP
CENTRE = N / 2
DECAY = 0.55          # trail persistence per frame
APERTURE_ZONES = 4.318


def linear_to_srgb(a: np.ndarray) -> np.ndarray:
    a = np.clip(a, 0, 1)
    return np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def rotate(vector: np.ndarray, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([c * vector[0] - s * vector[1], s * vector[0] + c * vector[1]])


def push_inward(vector: np.ndarray, inward: np.ndarray, min_degrees: float) -> np.ndarray:
    """Rotate a rebound until it clears the wall tangent by min_degrees."""
    speed = math.hypot(*vector)
    if speed < 1e-9:
        return vector
    cosine = float(vector @ inward) / speed
    limit = math.cos(math.radians(90 - min_degrees))
    if cosine >= limit:
        return vector
    delta = math.acos(max(-1.0, min(1.0, cosine))) - math.radians(90 - min_degrees)
    a, b = rotate(vector, delta), rotate(vector, -delta)
    return a if (a @ inward) > (b @ inward) else b


def simulate(seed: int, seconds: float) -> tuple[list[np.ndarray], int, np.ndarray]:
    rng = np.random.default_rng(seed)

    def new_hue(previous: float | None) -> float:
        while True:
            hue = float(rng.random())
            if previous is None or min(abs(hue - previous), 1 - abs(hue - previous)) > 0.19:
                return hue

    hue = new_hue(None)
    colour = np.array(colorsys.hsv_to_rgb(hue, 1.0, 1.0))
    position = np.array([-1.6, -2.2])
    velocity = np.array([9.5, 2.0])

    buffer = np.zeros((N, N, 3))
    yy, xx = np.mgrid[0:N, 0:N]
    radius_zones = np.hypot(xx - CENTRE, yy - CENTRE) / SUP
    aperture = radius_zones <= APERTURE_ZONES

    total_frames = int(round(seconds * FPS))
    frames_8x8: list[np.ndarray] = []
    bounces = 0
    radii = []
    dt = 1.0 / (FPS * SUBSTEPS)

    for _frame_index in range(total_frames):
        buffer *= DECAY
        for _ in range(SUBSTEPS):
            velocity[1] += GRAVITY * dt
            position += velocity * dt

            distance = math.hypot(*position)
            if distance > ARENA:
                normal = position / distance
                position = normal * ARENA
                normal_speed = float(velocity @ normal)
                if normal_speed > 0:
                    tangent = velocity - normal_speed * normal
                    rebound = RESTITUTION * normal_speed
                    if rebound < CONTACT_SPEED:
                        # Resting or grazing contact: absorb the normal
                        # component without registering an impact.
                        velocity = TANGENT_FRICTION * tangent
                    else:
                        velocity = TANGENT_FRICTION * tangent - rebound * normal
                        position = normal * (ARENA - 1e-3)
                        velocity = rotate(
                            velocity, math.radians(rng.normal(0.0, SCATTER_DEGREES))
                        )
                        velocity = push_inward(velocity, -normal, MIN_INWARD_DEGREES)

                        bounces += 1
                        hue = new_hue(hue)
                        colour = np.array(colorsys.hsv_to_rgb(hue, 1.0, 1.0))
                        if rng.random() < 0.18:  # occasional smash
                            velocity *= 1.25
                        height = ARENA - position[1]
                        needed = 2 * (ENERGY_FLOOR - GRAVITY * height)
                        current = float(velocity @ velocity)
                        if needed > current:
                            velocity *= math.sqrt(needed / max(current, 1e-6))

            radii.append(math.hypot(*position) / ARENA)

            # splat this sub-step
            px = CENTRE + position[0] * SUP
            py = CENTRE + position[1] * SUP
            sigma = BODY * SUP
            half = int(3 * sigma)
            x0, x1 = max(0, int(px) - half), min(N, int(px) + half + 1)
            y0, y1 = max(0, int(py) - half), min(N, int(py) + half + 1)
            if x1 <= x0 or y1 <= y0:
                continue
            wy, wx = np.mgrid[y0:y1, x0:x1]
            blob = np.exp(-0.5 * ((wx - px) ** 2 + (wy - py) ** 2) / sigma**2)
            buffer[y0:y1, x0:x1] += (blob / SUBSTEPS)[..., None] * colour

        visible = np.clip(buffer, 0, 1) * aperture[..., None]
        cell = visible.reshape(8, SUP, 8, SUP, 3).mean(axis=(1, 3))
        cell = np.clip(cell * 2.6, 0, 1)  # area-average dims the splat; restore punch
        frames_8x8.append(cell)

    return frames_8x8, bounces, np.array(radii)


def write_frames(frames_8x8: list[np.ndarray], output: Path) -> None:
    frames = []
    for cell in frames_8x8:
        srgb = linear_to_srgb(cell)
        hexes = [
            "".join(f"{int(round(c * 255)):02x}" for c in srgb[y, x])
            for y in range(8)
            for x in range(8)
        ]
        hexes[63] = "000000"  # uplight zone stays dark
        frames.append({"durationMs": int(round(1000 / FPS)), "pixels": hexes})
    save_frames(output, frames, name="Firefly")


def write_preview_gif(frames_8x8: list[np.ndarray], path: Path) -> None:
    from PIL import Image, ImageFilter

    grid = 40
    images = []
    for cell in frames_8x8[: 9 * FPS]:
        srgb = (linear_to_srgb(cell) * 255).astype(np.uint8)
        image = Image.fromarray(srgb).resize((8 * grid, 8 * grid), Image.Resampling.NEAREST)
        soft = image.filter(ImageFilter.GaussianBlur(grid * 0.8))
        images.append(soft.quantize(colors=128))
    images[0].save(
        path,
        save_all=True,
        append_images=images[1:],
        duration=int(1000 / FPS),
        loop=0,
        optimize=True,
    )


def main() -> int:
    argument_parser = argparse.ArgumentParser(description="Bake the firefly animation.")
    argument_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    argument_parser.add_argument(
        "--seed",
        type=int,
        default=20260826,
        help="physics RNG seed; the default regenerates the committed file exactly",
    )
    argument_parser.add_argument(
        "--seconds", type=float, default=SECONDS, help="animation length (default 45)"
    )
    argument_parser.add_argument(
        "--preview",
        action="store_true",
        help="also write a diffuser-blurred preview GIF next to the temp dir",
    )
    args = argument_parser.parse_args()

    frames_8x8, bounces, radii = simulate(args.seed, args.seconds)
    print(
        f"{len(frames_8x8)} frames, {bounces} bounces, "
        f"{len(frames_8x8) / FPS:.1f}s at {FPS} fps"
    )
    print(
        f"radius/arena: mean {radii.mean():.2f}, "
        f"time inside half-radius {100 * (radii < 0.5).mean():.0f}%, "
        f"hugging rim (>0.9) {100 * (radii > 0.9).mean():.0f}%"
    )
    write_frames(frames_8x8, args.output)
    print(f"wrote {args.output}")

    if args.preview:
        preview_path = Path(tempfile.gettempdir()) / "firefly-preview.gif"
        write_preview_gif(frames_8x8, preview_path)
        print(f"wrote {preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
