# Calibration pattern — 63 unique contrasting colours

One static frame, pushed once with `Set64` (duration 300 ms), raw index order
(`y = i // 8`, `x = i % 8`), no rotation, no flips. Photograph it as-is.

Push it:

```bash
python3 calibration/tools/push_pattern.py calibration/patterns/color-fill-63
```

## Palette construction

1. **Candidate pool** — HSV grid: hue every 4 deg, saturation 0.45, 0.72,
   1.00, value 0.30, 0.44, 0.58, 0.72. Building the pool in HSV means every
   candidate is in-gamut and brightness-capped by construction, so no gamut
   mapping is needed. Minimum saturation 0.45 keeps every zone chromatic — no
   pure white, no neutral grey, so hue is always an identifying cue.
2. **Selection** — 63 colours picked by greedy farthest-point (max-min) search
   in CIELAB, then a swap-in refinement that repeatedly replaces one member of
   the closest pair whenever that raises the global minimum deltaE.
3. **Placement** — simulated annealing over the 63 visible slots minimising
   `sum w * exp(-dE / 22)` across all 8-adjacent pairs (orthogonal edges
   weighted 1.0, diagonals 0.5). The soft-min objective is a smooth proxy for
   maximising the weakest neighbour edge, which is what a kernel fit needs.
4. **Clipping headroom** — HSV value ceiling 0.72, so HSBK brightness never
   exceeds 72 % and no zone is white. Values span 0.30–0.72 so neighbours
   differ in *luminance* as well as chroma; luminance edges are the ones that
   pin down the kernel.

## Achieved contrast (CIELAB deltaE76)

| metric | value |
| --- | --- |
| neighbour min (8-adj) | 49.56 |
| neighbour mean (8-adj) | 91.53 |
| neighbour min (orthogonal only) | 52.40 |
| neighbour mean (orthogonal only) | 85.50 |
| global min pairwise | 16.85 |

OKLab equivalents: neighbour min 0.1294, mean 0.3083, global min 0.0328.

**The tension.** 63 unique colours inside a brightness-capped sRGB volume
forces the *global* minimum deltaE to be modest — some colour pairs are
necessarily similar. That is fine: the annealer spends the whole budget on
*local* separation, so every similar pair ends up far apart on the grid. Local
contrast is what the kernel fit uses; global separation only has to be enough
for zone identification, and hue plus value together still make each zone
distinguishable.

## Caveats

- **Zone 63 is the uplight** — forced to brightness 0, off the visible disc,
  so 63 zones carry colour.
- **The four square corners** (indices 0, 7, 56 and the 63 slot) sit at radius
  ~0.62 of half-width against an aperture of ~0.50, so they fall outside the
  round diffuser and probably will not appear. They are coloured anyway; treat
  them as expected-missing rather than as a registration failure.

## Files

- `pattern.json` — ground truth per zone: index, x, y, RGB hex, HSBK raw and
  normalised, CIELAB, OKLab, plus a `Get64` readback captured after pushing.
- `frames.json` — the same pattern as a playable frame file.
- `ideal.png` — 512 px nearest-neighbour render, protocol `y=0` at image top.
- `ideal-labeled.png` — same with zone indices; red box marks the uplight.
