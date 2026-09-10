#!/usr/bin/env python3
"""Fit a diffuser kernel from a photo of the psf-sparse pattern.

    python3 calibration/tools/fit_from_photo.py photo.jpg \
        --pattern calibration/patterns/psf-sparse --out my-kernel.json

Requires numpy and Pillow (``pip install lifx-ceiling-lab[examples]``).

What it does, and what it assumes:

1. **Find the disc.** Threshold the luminance image and take the centroid and
   RMS radius of lit pixels. Works because the pattern is bright probes on a
   dark panel in a dim-ish room. Crop to the disc.
2. **Locate probes.** Take local maxima well above the noise floor, greedily
   keep the five brightest maxima that are mutually separated, and match them
   to the five known probe positions by best rigid assignment (the photo is
   assumed roughly square-on; keystone is not corrected).
3. **Fit sigma.** For each probe, fit a 2-D Gaussian radius to the luminance
   falloff around the peak (least squares on log-luminance within 3 zones).
   Report the median across probes, converted to zone units using the scale
   implied by the matched probe positions.
4. **Estimate glare.** The luminance floor across the disc, far from every
   probe, divided by the total probe energy, gives the veiling glare fraction.

The result is written in the same schema as ``defaults/kernel.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import permutations
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

APERTURE_RADIUS_ZONES_DEFAULT = 4.318


def luminance(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float64) / 255.0
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def find_disc(lum: np.ndarray) -> tuple[float, float, float]:
    """Return (centre_x, centre_y, radius) of the lit disc in pixels."""
    threshold = lum.mean() + 0.5 * lum.std()
    mask = lum > threshold
    if mask.sum() < 100:
        raise ValueError("could not find a lit region; is the photo of the pattern?")
    ys, xs = np.nonzero(mask)
    cx, cy = xs.mean(), ys.mean()
    # RMS distance of a filled disc is R/sqrt(2); invert that
    rms = np.sqrt(((xs - cx) ** 2 + (ys - cy) ** 2).mean())
    return float(cx), float(cy), float(rms * np.sqrt(2.0))


def find_probes(lum: np.ndarray, count: int, min_separation: float) -> list[tuple[float, float]]:
    """Greedy brightest local maxima, mutually separated."""
    work = lum.copy()
    found: list[tuple[float, float]] = []
    for _ in range(count):
        index = int(np.argmax(work))
        y, x = divmod(index, work.shape[1])
        if work[y, x] <= 0:
            break
        found.append((float(x), float(y)))
        yy, xx = np.mgrid[0 : work.shape[0], 0 : work.shape[1]]
        work[(xx - x) ** 2 + (yy - y) ** 2 < min_separation**2] = 0
    if len(found) < count:
        raise ValueError(f"found only {len(found)} of {count} probes")
    return found


def match_probes(
    detected: list[tuple[float, float]],
    expected_zone_xy: list[tuple[int, int]],
    disc: tuple[float, float, float],
    aperture_radius_zones: float,
) -> list[tuple[tuple[float, float], tuple[int, int]]]:
    """Assign detected peaks to known probe zones by least total error."""
    cx, cy, radius = disc
    pixels_per_zone = radius / aperture_radius_zones
    predicted = [
        (cx + (zx - 3.5) * pixels_per_zone, cy + (zy - 3.5) * pixels_per_zone)
        for zx, zy in expected_zone_xy
    ]
    best, best_cost = None, float("inf")
    for order in permutations(range(len(detected))):
        cost = sum(
            (detected[i][0] - predicted[j][0]) ** 2
            + (detected[i][1] - predicted[j][1]) ** 2
            for j, i in enumerate(order)
        )
        if cost < best_cost:
            best, best_cost = order, cost
    assert best is not None
    return [(detected[i], expected_zone_xy[j]) for j, i in enumerate(best)]


def fit_sigma(lum: np.ndarray, peak: tuple[float, float], pixels_per_zone: float) -> float:
    """Least-squares Gaussian radius on log-luminance around one probe."""
    px, py = peak
    window = int(3 * pixels_per_zone)
    y0, y1 = max(0, int(py) - window), min(lum.shape[0], int(py) + window + 1)
    x0, x1 = max(0, int(px) - window), min(lum.shape[1], int(px) + window + 1)
    patch = lum[y0:y1, x0:x1]
    peak_value = patch.max()
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r2 = (xx - px) ** 2 + (yy - py) ** 2
    keep = (patch > 0.05 * peak_value) & (patch < 0.95 * peak_value)
    if keep.sum() < 20:
        raise ValueError("not enough falloff pixels around a probe to fit")
    # log(I/I0) = -r^2 / (2 sigma^2)  →  slope of log I vs r^2
    slope = np.polyfit(r2[keep], np.log(patch[keep] / peak_value), 1)[0]
    if slope >= 0:
        raise ValueError("probe falloff did not decrease with radius")
    sigma_pixels = float(np.sqrt(-1.0 / (2.0 * slope)))
    return sigma_pixels / pixels_per_zone


def main() -> int:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("photo", type=Path)
    argument_parser.add_argument(
        "--pattern",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "patterns" / "psf-sparse",
        help="pattern directory with pattern.json probe positions",
    )
    argument_parser.add_argument("--out", type=Path, default=Path("my-kernel.json"))
    argument_parser.add_argument(
        "--aperture-radius-zones",
        type=float,
        default=APERTURE_RADIUS_ZONES_DEFAULT,
        help="assumed visible radius in zones (from the default kernel)",
    )
    args = argument_parser.parse_args()

    pattern = json.loads((args.pattern / "pattern.json").read_text())
    expected = [(int(p["x"]), int(p["y"])) for p in pattern["probes"]]

    lum = luminance(Image.open(args.photo))
    disc = find_disc(lum)
    cx, cy, radius = disc
    pixels_per_zone = radius / args.aperture_radius_zones
    print(
        f"disc centre ({cx:.0f}, {cy:.0f}), radius {radius:.0f} px, "
        f"{pixels_per_zone:.1f} px/zone"
    )

    detected = find_probes(lum, len(expected), min_separation=1.5 * pixels_per_zone)
    matched = match_probes(detected, expected, disc, args.aperture_radius_zones)

    sigmas = []
    for peak, zone in matched:
        try:
            sigma = fit_sigma(lum, peak, pixels_per_zone)
            sigmas.append(sigma)
            print(f"probe at zone {zone}: sigma {sigma:.2f} zones")
        except ValueError as error:
            print(f"probe at zone {zone}: skipped ({error})")
    if not sigmas:
        raise ValueError("no probe could be fitted")
    sigma_zones = float(np.median(sigmas))

    # veiling glare: luminance floor far from probes vs total probe energy
    yy, xx = np.mgrid[0 : lum.shape[0], 0 : lum.shape[1]]
    in_disc = (xx - cx) ** 2 + (yy - cy) ** 2 < radius**2
    far = in_disc.copy()
    for (px, py), _zone in matched:
        far &= (xx - px) ** 2 + (yy - py) ** 2 > (2.5 * pixels_per_zone) ** 2
    glare = float(
        np.clip(np.median(lum[far]) * far.sum() / max(lum[in_disc].sum(), 1e-9), 0, 1)
    )

    kernel = {
        "name": f"fitted from {args.photo.name}",
        "fixture": pattern.get("device", {}),
        "fit": {
            "method": "fit_from_photo.py: threshold disc, greedy maxima, "
            "log-luminance Gaussian fit per probe, median sigma",
            "patterns": [args.pattern.name],
            "probes_fitted": len(sigmas),
        },
        "kernel": {
            "psf_sigma_zones": round(sigma_zones, 3),
            "aperture_radius_zones": args.aperture_radius_zones,
            "veiling_glare": round(glare, 3),
            "corner_zones_outside_aperture": [0, 7, 56],
        },
    }
    args.out.write_text(json.dumps(kernel, indent=2) + "\n")
    print(f"sigma {sigma_zones:.2f} zones, glare {glare:.3f} → wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
