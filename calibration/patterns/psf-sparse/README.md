# Calibration pattern — sparse luminance PSF

Five isolated **3500 K** probes on black. Neighbours of every probe are dark,
so a photo of the disc is a direct sample of the **brightness** spread (not
hue mixing). Pair with `../color-fill-63/` for chroma / crosstalk.

Send raw, `Set64` index order (`--rotate 0`). Zone 63 uplight off.

```
. . . . . . . .
. . . . W . . .
. W . . . . . .
. . . . . . W .
. . . . . . . .
. . . . . . . .
. . W . . W . .
. . . . . . . #
```

Probes at `(x,y)` / index: `(4,1)/12`, `(1,2)/17`, `(6,3)/30`, `(2,6)/50`,
`(5,6)/53`. Peak brightness 0.70 so a phone camera should not clip.

Push:

```bash
python3 calibration/tools/push_pattern.py calibration/patterns/psf-sparse
```

Then fit your own kernel:

```bash
python3 calibration/tools/fit_from_photo.py photo.jpg \
    --pattern calibration/patterns/psf-sparse --out my-kernel.json
```
