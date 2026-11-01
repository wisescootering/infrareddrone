# ODM mapping from Phase 5

The **ODM** button in the Phase 5 dialog now runs the complete OpenDroneMap
workflow through Docker Desktop. The long-running Docker process runs on a
background worker, so the dialog remains responsive. The dialog asks for
confirmation before starting and prevents closing while ODM is running.
Before confirmation, the user selects the maximum rank-1 NIR `|dt|` from 0.05 to
6 seconds and either one image every 1-4 eligible images (default: every 3) or
an overlap-based criterion. Overlap percentages can be configured from 0% to
100% on both image axes, but overlap-based selection is not implemented yet;
the interface warns the user and requires choosing the image-interval option.

## Workflow

The ODM module performs these steps:

1. Reads `ImgIRdrone/shoot_points.json`, generated at the end of Step 4. It
   contains only shoot points with all four multispectral TIFFs and the rank-1
   EXIF sidecar. When Step 4 regenerates this inventory, it preserves each
   existing point's `failed` status and other point fields if that point remains
   available; newly available points start with `failed: false`. If this
   inventory is absent (for older missions), the module reads
   `AerialPhotography/shoot_points.json` instead.
2. Excludes records marked `failed: true` (or `1`), then keeps records whose
   rank-1 NIR match has `abs(dt)` less than or equal to the selected threshold
   (default: 0.5 seconds).
3. Keeps only VIS filenames listed in
   `AerialPhotography/VIS/transfer_info_VIS_dng.json` under
   `fly.listCopiedImages`.
4. Selects every n-th eligible pair in original shoot-point order, starting
   with the first; n is selected from 1 to 4 and defaults to 3.
5. Resolves the four TIFF files `IRD_XXXX_1.tif` through `IRD_XXXX_4.tif` in
   `ImgIRdrone/imgMultispectral` and validates that each is readable, single-band,
   and has matching dimensions and data type.
6. Estimates the image GSD from each selected `IRD_XXXX_1.exif` sidecar,
   `DroneAltitudeGround`, image width, and the matching camera's normalized
   `focal_x`. The median GSD rounded up to the next 0.1 cm/pixel is passed to
   ODM as `--orthophoto-resolution`. If the sidecars or camera calibration
   cannot provide a valid estimate, the run stops with an error.
7. Writes the selection and resolution details to
   `mapping_MULTI/img_best_mappping.json`.
8. Prepares `mapping_MULTI/images_best_mapping/images` with only the selected
   TIFFs.    It may reuse an existing `images` folder only if its file names and TIFF
   contents match the selection byte-for-byte. Other dataset contents,
   including prior ODM outputs and cache folders, cause the run to stop. The
   application never deletes existing data.
9. Checks that Docker CLI is available and that the Docker Desktop
   `desktop-linux` engine responds before preparing inputs. If Docker is
   unavailable, the dialog asks the user to start Docker Desktop and offers to
   retry the check. It then runs the local image `opendronemap/odm:latest`
   against the prepared dataset. The camera file is supplied using
   `mapping_MULTI/camera/camera_IRdrone.json`.
10. Checks that the expected orthophoto exists, is georeferenced, and has
    Red, Green, Blue, and NIR bands before reporting success.

The command uses the estimated resolution, `--fast-orthophoto`,
`--skip-band-alignment`, and a maximum concurrency of four. It does not use
`--ignore-gsd` or request an extra `--orthophoto-png` export. ODM's original
GeoTIFF and processing outputs remain in the dataset folder.

## Outputs and logs

- Selection manifest: `mapping_MULTI/img_best_mappping.json`
- Prepared input: `mapping_MULTI/images_best_mapping/images`
- Orthophoto: `mapping_MULTI/images_best_mapping/odm_orthophoto/odm_orthophoto.tif`
- Complete Docker/ODM output: `mapping_MULTI/odm_run_<timestamp>.log`

ODM creates the georeferenced orthophoto as a GeoTIFF; it does not create a DNG.
The original DNG captures remain in the mission's `AerialPhotography/VIS`
folder. The separate GeoRef workflow may convert DNG inputs to TIFF, but does
not create new DNG files.

The manifest records the Docker command, status, log path, start/end times, and
exit code, including the elapsed time for the Docker/ODM process. The dialog
displays major progress messages, the final output path, and the ODM calculation
duration. After success, the dialog also displays a reduced RGB preview made
from the orthophoto's first three bands; it reads a downsampled raster rather
than loading the full GeoTIFF into memory. The NIR band remains available in
the output for QGIS. ODM may add a fifth alpha/mask band, and QGIS may initially
render only bands 1-3 as RGB.

To run another mapping on the same mission, first close the previous output in
QGIS and manually remove or rename the prior ODM result and cache directories
inside `mapping_MULTI/images_best_mapping`, keeping the exact selected
`images` folder if it is to be reused. The code will refuse to start if it
finds extra files or folders; it will not clean them up automatically.
