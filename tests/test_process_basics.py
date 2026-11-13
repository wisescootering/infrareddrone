"""Image helpers of irdrone.process / irdrone.utils and the interactive image pipe.

Headless versions of the checks of the former test.py (which opened windows):
the figures are drawn with the Agg backend and the pipes run without their GUI.
"""
import copy
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402
import unittest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import interactive.imagepipe as imagepipe  # noqa: E402
import irdrone.process as process  # noqa: E402
import irdrone.utils as utils  # noqa: E402

SAMPLES = ["*Full*", "*IR760*"]


@pytest.fixture(autouse=True)
def close_figures():
    yield
    plt.close("all")


# ------------------------------------------------------------------ sample files
def test_imagepath_lists_existing_samples():
    paths = utils.imagepath(imgname="*")
    assert len(paths) > 5
    assert all(Path(p).is_file() for p in paths)


def test_loadimage_single_and_list():
    image = process.loadimage(utils.imagepath())
    assert image[0].shape == (3024, 4032, 3)
    assert image[0].dtype == np.uint8
    images = process.loadimage(utils.imagepath(imgname=SAMPLES))
    assert len(images) == 2


def test_testimage_is_a_color_wheel():
    wheel = utils.testimage(xsize=120, ysize=50, sat=1.)
    assert wheel.shape == (50, 120, 3) and wheel.dtype == np.uint8
    assert wheel[0].max() == 0          # first row: zero luminance, black
    assert wheel[-1].max() >= 254       # last row: full luminance (255 truncated)
    gray = utils.testimage(xsize=20, ysize=20, sat=0.)
    assert np.all(gray[..., 0] == gray[..., 1]) and np.all(gray[..., 1] == gray[..., 2])


# ------------------------------------------------------------------ color matrix
@pytest.fixture
def wheel():
    return utils.testimage(xsize=200, ysize=200, sat=0.7)


def test_colormatrix_identity_keeps_the_image(wheel):
    np.testing.assert_array_equal(process.applycolormatrix(wheel), wheel)


def test_colormatrix_gain_scales_and_clips(wheel):
    darker = process.applycolormatrix(wheel, cm=0.5)
    np.testing.assert_allclose(darker, (wheel * 0.5).astype(np.uint8), atol=1)
    brighter = process.applycolormatrix(wheel, cm=1.5)
    assert brighter.dtype == np.uint8
    np.testing.assert_allclose(brighter, np.clip(wheel * 1.5, 0, 255).astype(np.uint8), atol=1)


def test_colormatrix_white_balance_is_per_channel(wheel):
    balanced = process.applycolormatrix(wheel, cm=[0.8, 1., 0.9])
    for channel, gain in enumerate([0.8, 1., 0.9]):
        np.testing.assert_allclose(balanced[..., channel], (wheel[..., channel] * gain).astype(np.uint8), atol=1)


def test_colormatrix_permutation_swaps_red_and_blue(wheel):
    swap = np.array([[0., 0., 1.], [0., 1., 0.], [1., 0., 0.]])
    np.testing.assert_array_equal(process.applycolormatrix(wheel, cm=swap), wheel[..., ::-1])


# ------------------------------------------------------------------ show
def test_show_single_row_and_grid():
    process.show((utils.testimage(100, 100), "color wheel"), block=False)
    process.show(
        [(utils.testimage(int(s ** 2 * 200), int(s * 200), sat=s), "wheel %.1f" % s) for s in [0.1, 0.5, 1.]],
        compare=False, suptitle="row", block=False,
    )
    grid = [[(utils.testimage(100, 100, sat=s), "sat %.1f" % s) for s in [0., 0.4]],
            [(utils.testimage(150, 100, sat=s), "sat %.1f" % s) for s in [0.5, 1.]]]
    process.show(grid, block=False)
    process.show([[image for image, _ in row] for row in grid], compare=True, block=False)
    assert plt.get_fignums()


def test_show_image_objects_and_save(tmp_path):
    paths = utils.imagepath(imgname=SAMPLES)
    process.show([[process.Image(p, name=Path(p).name[:12]) for p in paths]], block=False,
                 save=str(tmp_path / "grid.png"))
    assert (tmp_path / "grid.png").stat().st_size > 0


# ------------------------------------------------------------------ image pipe
def test_imagepipe_runs_without_gui_and_saves(tmp_path):
    sliders = [imagepipe.WB, imagepipe.GAMMA, imagepipe.BRIGHTNESS, imagepipe.TRANSLATION]
    # Float input, as the real callers do (WB multiplies in place).
    image = utils.testimage(xsize=400, ysize=400).astype(np.float64)
    pipe = imagepipe.ImagePipe([image], sliders=sliders, rescale=2.)
    pipe.set()  # every slider to its default value
    neutral = pipe.getbuffer()
    assert neutral.shape == (400, 400, 3)
    pipe.set(WB=[0.121569, 0.219608], GAMMA=[0.105882], BRIGHTNESS=[-0.137255],
             TRANSLATION=[-372., -377.])
    tuned = pipe.getbuffer()
    assert tuned.shape == neutral.shape and not np.array_equal(tuned, neutral)
    pipe.save(str(tmp_path / "pipe.jpg"))
    assert (tmp_path / "pipe.jpg").stat().st_size > 0


def test_imagepipe_on_signals():
    class Amplify(imagepipe.ProcessBlock):
        def apply(self, sig, ampli, **kwargs):
            out = copy.deepcopy(sig)
            out.y = sig.y * ampli
            return out

    class Addition(imagepipe.ProcessBlock):
        def apply(self, sig1, sig2, **kwargs):
            out = copy.deepcopy(sig1)
            out.y = sig1.y + sig2.y
            return out

    signal_mode = [imagepipe.ProcessBlock.SIGNAL, imagepipe.ProcessBlock.SIGNAL]
    amplify = Amplify("Amplification", vrange=[(0.5, 3., 1.)], mode=signal_mode)
    add = Addition("Addition", slidersName=[], inputs=[0, 2], outputs=[0], mode=signal_mode)
    x = 2. * np.arange(100) / 100.
    signals = [imagepipe.Signal(x, x, "-b", "base"), imagepipe.Signal(x, np.sin(x), "-r", "sinus")]
    pipe = imagepipe.ImagePipe(signals, sliders=[amplify, add])

    pipe.set(Amplification=[2.])
    result = pipe.getbuffer()
    np.testing.assert_allclose(result.y, 2. * x + np.sin(x))


class ContrastStretching8bitTests(unittest.TestCase):
    def test_same_image_as_the_float_version(self):
        import numpy as np
        import irdrone.utils as ut
        image = np.random.default_rng(0).random((60, 1000, 3)) ** 2
        for data in (image, image.astype(np.float32)):
            expected = (ut.contrast_stretching(data)[0] * 255).astype(np.uint8)
            stretched, (low, high) = ut.contrast_stretching_8bit(data)
            self.assertEqual(stretched.dtype, np.uint8)
            self.assertLessEqual(np.abs(stretched.astype(int) - expected.astype(int)).max(), 1)
            self.assertLess(low, high)
            # the 2% of pixels above the high percentile are white, as before
            self.assertTrue((stretched[data >= high] == 255).all())
            self.assertEqual((stretched == 255).sum(), (expected == 255).sum())

    def test_given_percentiles_and_flat_image(self):
        import numpy as np
        import irdrone.utils as ut
        image = np.full((4, 4, 3), 0.5, dtype=np.float32)
        stretched, _ = ut.contrast_stretching_8bit(image, percentiles=(0.25, 0.75))
        self.assertTrue((stretched == 127).all())
        flat, _ = ut.contrast_stretching_8bit(image, crop_black_circle=None)
        self.assertTrue((flat == 127).all())


class MetadataBatchTests(unittest.TestCase):
    def test_commands_of_a_batch_run_in_one_exiftool_process(self):
        from unittest import mock
        import irdrone.process as pr
        with mock.patch.object(pr.subprocess, "run") as run:
            with pr.metadata_batch():
                pr._run_exiftool(["exiftool", "-TagsFromFile", "a.dng", "a.jpg"])
                pr._run_exiftool(["exiftool", "-config", "xmp.config", "-m", "b.tif"])
                with pr.metadata_batch():            # nested: the outer block writes
                    pr._run_exiftool(["exiftool", "c.tif"])
                run.assert_not_called()
            run.assert_called_once_with([
                "exiftool", "-config", "xmp.config",
                "-TagsFromFile", "a.dng", "a.jpg", "-execute",
                "-m", "b.tif", "-execute",
                "c.tif",
            ])
            run.reset_mock()
            with pr.metadata_batch():
                pass
            run.assert_not_called()                  # nothing to write: ExifTool not started
            pr._run_exiftool(["exiftool", "d.jpg"])  # outside a batch: at once
            run.assert_called_once_with(["exiftool", "d.jpg"])

    def test_the_batch_is_written_when_the_block_fails(self):
        from unittest import mock
        import irdrone.process as pr
        with mock.patch.object(pr.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                with pr.metadata_batch():
                    pr._run_exiftool(["exiftool", "a.jpg"])
                    raise RuntimeError("write failed")
            run.assert_called_once_with(["exiftool", "a.jpg"])
            self.assertIsNone(pr._exiftool_batch)


def test_multispectral_bands_are_written_uncompressed(tmp_path, monkeypatch):
    """One uncompressed 16 bit TIFF per band (LZW made these noisy images larger and slow to write)."""
    import cv2
    monkeypatch.setattr(process, "copy_metadata", lambda *a, **k: None)
    monkeypatch.setattr(process, "xmp_band_metadata", lambda *a, **k: None)
    data = np.random.default_rng(0).random((40, 60, 4)).astype(np.float32) * 1.2 - 0.1
    image = process.Image(data)
    image.save_multispectral(tmp_path / "IRD_0001")
    for band in range(4):
        path = tmp_path / f"IRD_0001_{band + 1}.tif"
        written = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        assert written.dtype == np.uint16 and written.shape == (40, 60)
        expected = (65535 * data[:, :, band].clip(0, 1)).astype(np.uint16)
        assert np.abs(written.astype(int) - expected.astype(int)).max() <= 1
        assert path.stat().st_size >= 40 * 60 * 2        # not compressed
