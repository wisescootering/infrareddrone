# IGN orthophoto registration

`irdrone.ign_registration` registers an already-georeferenced GeoTIFF to the IGN
`HR.ORTHOIMAGERY.ORTHOPHOTOS` WMS layer. It creates a new raster and does not
modify the input. For directory inputs, the default search pattern is
`*_georef.tif`.

## Usage

Run from the repository root:

```powershell
python -m irdrone.ign_registration "C:\path\to\images"
```

For a single file:

```powershell
python -m irdrone.ign_registration "C:\path\to\image_georef.tif" --matcher sift
```

Results are written to an `ign_registration` subdirectory beside the input
directory. Each image produces:

- `*_ign_aligned.tif` only when registration passes the quality gates;
- `*_ign_overlay.png` for visual review;
- `*_ign_report.json` with the fit, control-point coverage, reference request,
  and any rejection reason.

The default `--matcher auto` prefers SuperPoint + LightGlue when the optional
packages are installed; otherwise it reports the fallback and uses SIFT.
Install the optional CPU or GPU PyTorch build, Kornia, and LightGlue separately
if learned matching is needed. Their pretrained weights are fetched by the
libraries into the PyTorch cache: LightGlue/SuperPoint/ALIKED weights come from
their upstream GitHub releases/repository, and Kornia's LoFTR checkpoint comes
from its upstream model host. The implementation does not use Hugging Face.
The project environment does not require these large optional dependencies.

Useful options include `--matcher lightglue`, `--matcher sift`,
`--output-dir PATH`, `--margin-m 40`, `--min-coverage 0.2`,
`--min-inliers 20`, `--max-feature-dimension 1200`, and `--verbose`. WMS
access requires an internet connection.

## Acceptance criteria and limitations

The implementation uses a RANSAC similarity transform, then rejects fits that
do not meet the configured minimum inlier count and ratio, residual threshold,
two-dimensional image coverage, and occupied-quadrant count. Rejected images
still receive a report, but no aligned GeoTIFF.

The result is an experimental global affine correction. IGN imagery can differ
in date and orthorectification; roof-height displacement, relief, and local
distortion are not modeled. Inspect every overlay and validate independent
ground control points before using an aligned raster for measurement.
