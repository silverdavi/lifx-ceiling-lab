# Calibrating a LIFX Ceiling

The Ceiling's 8x8 zones sit behind a milky round diffuser. What you see on
the glass is not 64 crisp squares — it is the zone map convolved with the
diffuser's point-spread function (PSF), cropped by a circular aperture, and
washed by veiling glare that grows with how much of the panel is lit. If you
want frames you author to look right on the fixture, you need three numbers:

1. **orientation** — which way the protocol's `y = 0` row points on your
   ceiling (rotation, possibly a flip);
2. **PSF sigma** — how far one zone's light spreads, in zone units;
3. **aperture radius** — how much of the 8x8 square the round window shows.

This directory ships the two test patterns we used, the tools to push them
and fit a photo, and the values fitted for our unit as a usable default.

## Default calibration (measured on one Ceiling, product id 176)

`defaults/kernel.json`:

| parameter | value | meaning |
| --- | --- | --- |
| `psf_sigma_zones` | 0.80 | Gaussian blur radius of the diffuser, in zones |
| `aperture_radius_zones` | 4.318 | visible disc radius from panel centre |
| `veiling_glare` | 0.06 | fraction of total lit energy spread across the disc |
| `uplight_index` | 63 | the 64th zone is the uplight ring, not a pixel |

If you own a Ceiling and just want to play animations, the defaults are
almost certainly close enough — start there and only calibrate if things
look smeared or misplaced.

## Step 1 — orientation

Push a recognisable static frame raw and look up:

```bash
lifx-play --static face --rotate 0
```

Try `--rotate 90/180/270` (and `--flip-h` if you can never make it match —
that means the panel is mirrored relative to the reference mounting) until
the image is upright from your usual viewpoint. Put the winning values in
`config.yaml` under `display:` and every tool will apply them.

## Step 2 — photograph the patterns

Two patterns, both pushed **raw** (`--rotate 0`) so the photo maps directly
to protocol indices:

- **`patterns/psf-sparse/`** — five isolated 3500 K probes on black.
  Neighbours of every probe are dark, so the photo is a direct sample of the
  brightness spread. This is the pattern the PSF sigma is fitted from.
- **`patterns/color-fill-63/`** — 63 unique colours chosen and placed for
  maximum neighbour contrast (farthest-point palette in CIELAB, simulated
  annealing on the placement). Use it to verify orientation zone-by-zone and
  to sanity-check chroma crosstalk. Its `pattern.json` carries the full
  ground truth per zone: RGB, HSBK, CIELAB, OKLab.

```bash
python3 calibration/tools/push_pattern.py patterns/psf-sparse
```

Photograph the disc as square-on as you can, with exposure locked low enough
that the probes do not clip (the patterns cap brightness at 70-72 % for this
reason). Phone cameras are fine.

## Step 3 — fit

```bash
python3 calibration/tools/fit_from_photo.py photo.jpg \
    --pattern patterns/psf-sparse --out my-kernel.json
```

The fitter finds the lit disc, locates the probe blobs, fits a shared
Gaussian sigma in zone units, and writes a kernel file in the same format as
`defaults/kernel.json`. Compare; if your sigma differs from 0.80 by more
than ~0.1 the preview tools will noticeably better match your glass with
your own kernel.

## Using the kernel

`lifx-preview` renders each frame twice — crisp pixels and the diffuser
approximation — so you can iterate on designs without staring at the
ceiling. The firefly generator (`examples/dynamic/firefly.py`) bakes the
aperture radius into its arena size: the ball bounces off the *visible*
rim, not the invisible square edge.
