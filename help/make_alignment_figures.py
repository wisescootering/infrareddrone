"""Figures of the technical appendix on multispectral alignment (help/irdrone_help*.tex).

The figures are computed with the functions of the alignment itself (registration/,
irdrone/semi_auto_registration.py), from two shoot points and the diagnostic traces of
their alignment, obtained with:

    python automatic_registration.py --images VIS_XXXX.dng NIR_YYYY.dng --outdir OUT --debug

Point A is a clean case (the manual uses VIS_0201 / NIR_0146 of the flight
FLY-20220125-1159, Blassac), point B a difficult one (the manual uses the sample pair of
the repository, samples/_visible.DNG and samples/_nir.RAW).

Usage:
    python help/make_alignment_figures.py \
        --vis VIS_0201.dng --nir NIR_0146.dng --traces OUT_A/VIS_0201_align_traces \
        --vis-b samples/_visible.DNG --nir-b samples/_nir.RAW --traces-b OUT_B/_visible_align_traces \
        [--out help/images] [--only stages polar ...]

Writes help/images/align_*.png / .jpg (then run make_images_light.py for the light manual).
"""
import argparse
import os.path as osp
import sys

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from skimage.transform import warp_polar  # noqa: E402

sys.path.insert(0, osp.join(osp.dirname(__file__), ".."))
import irdrone.process as pr  # noqa: E402
import irdrone.utils as ut  # noqa: E402
from irdrone.register import geometric_rigid_transform_estimation  # noqa: E402
from irdrone.semi_auto_registration import manual_warp  # noqa: E402
from registration.constants import LAPLACIAN_ENERGIES  # noqa: E402
from registration.cost import cost_surface_NTG, cost_surface_SSD, multispectral_representation  # noqa: E402
from registration.pyramid_wrapper import pyramid_reduce  # noqa: E402
from registration.rigid import brute_force_vector_field_search, hessian_determinant, minimum_cost  # noqa: E402
from registration.warp_flow import warp  # noqa: E402

DPI = 200
WIDTH = 6.3  # inches, text width of the manual
COLD, HOT = "#1f77b4", "#d62728"
plt.rcParams.update({
    "font.size": 8, "axes.titlesize": 8, "axes.labelsize": 8, "legend.fontsize": 7,
    "xtick.labelsize": 7, "ytick.labelsize": 7, "figure.dpi": DPI, "savefig.bbox": "tight",
    "image.cmap": "viridis",
})


# ------------------------------------------------------------------------------------------- helpers
def save(fig, out, name):
    path = osp.join(out, name)
    fig.savefig(path, dpi=DPI, pil_kwargs={"quality": 88} if name.endswith(".jpg") else {})
    plt.close(fig)
    print("written", path)


def gray(img):
    return cv2.cvtColor(np.ascontiguousarray(img), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255.


def stretch(img, low=1, high=99):
    lo, hi = np.percentile(img, [low, high])
    return ((img - lo) / max(hi - lo, 1e-6)).clip(0, 1)


def overlay(ref, mov):
    """False colour superimposition: reference in green, moving image in magenta.
    Where both agree the result is grey, a misalignment shows as green / magenta fringes."""
    g_ref, g_mov = stretch(gray(ref)), stretch(gray(mov))
    return np.dstack([g_mov, g_ref, g_mov])


def thumbnail(img, max_side=1400):
    scale = max_side / max(img.shape[:2])
    if scale >= 1:
        return img
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def costs_of(traces, name):
    return np.load(osp.join(traces, name), allow_pickle=True).item()


def tidy(ax):
    ax.set_xticks([])
    ax.set_yticks([])


# ------------------------------------------------------------------------------------------- data
class Point:
    def __init__(self, vis_path, nir_path, traces):
        self.traces = traces
        cal_ref = ut.cameracalibration(camera="DJI_RAW")
        cal_mov = ut.cameracalibration(camera="M20_RAW")
        self.cal_ref_raw = {k: (np.array(v).copy() if isinstance(v, (list, np.ndarray)) else v) for k, v in cal_ref.items()}
        self.cal_mov = cal_mov
        vis = pr.Image(vis_path)
        nir = pr.Image(nir_path)
        self.vis_raw = vis.data
        self.nir_raw = nir.data
        self.ref = warp(vis.data, cal_ref, np.eye(3))  # distortion of the visible image corrected
        cal_ref = dict(cal_ref)
        cal_ref["dist"] = np.array(cal_ref["dist"]) * 0.
        self.cal_ref = cal_ref
        self.model = np.load(osp.join(traces, "motion_model.npy"), allow_pickle=True).item()

    def nir_warp(self, yaw=0., pitch=0., roll=0., homography=None, vector_field=None, extension=None):
        return manual_warp(self.ref, self.nir_raw, yaw, pitch, roll,
                           refcalib=self.cal_ref, movingcalib=self.cal_mov,
                           refinement_homography=homography, vector_field=vector_field,
                           bigger_size_factor=extension)

    def stages(self):
        m = self.model
        return {
            "zero": self.nir_warp(),
            "coarse": self.nir_warp(m["yaw"], m["pitch"], m["roll"]),
            "global": self.nir_warp(m["yaw"], m["pitch"], m["roll"], homography=m["homography"]),
            "local": self.nir_warp(m["yaw"], m["pitch"], m["roll"], homography=m["previous_homography"],
                                   vector_field=m["vector_field"]),
        }


# ------------------------------------------------------------------------------------------- figures
def fig_pair(p, out):
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.4))
    axes[0].imshow(thumbnail(p.vis_raw))
    axes[0].set_title("Visible: DJI Mavic Air 2\n3992 x 2992 px, horizontal field 68 deg")
    axes[1].imshow(stretch(thumbnail(p.nir_raw).astype(np.float32)))
    axes[1].set_title("Near infrared: SJCam M20\n4600 x 3448 px, horizontal field over 110 deg")
    for ax in axes:
        tidy(ax)
    save(fig, out, "align_pair_raw.jpg")


def distort(cal, xy_u):
    """Pixel position in the raw image of the undistorted normalized coordinates xy_u (N, 2)."""
    pts = np.concatenate([xy_u, np.ones((len(xy_u), 1))], axis=1).astype(np.float64)
    img_pts, _ = cv2.projectPoints(pts, np.zeros(3), np.zeros(3), np.array(cal["mtx"]), np.array(cal["dist"]))
    return img_pts[:, 0, :]


def fig_distortion(p, out):
    cams = [("Visible DJI", p.cal_ref_raw), ("Near infrared SJCam M20", p.cal_mov)]
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 2.1), gridspec_kw={"width_ratios": [1, 1, 1.05]})
    r_max = {"Visible DJI": None, "Near infrared SJCam M20": 1.2}  # beyond, the M20 polynomial folds back
    vis_half = np.array([3992 / 2, 2992 / 2]) / np.array(p.cal_ref_raw["mtx"])[0, 0]
    for ax, (name, cal) in zip(axes[:2], cams):
        w, h = cal["size"]
        lim = r_max[name] or 1.0
        t = np.linspace(-lim, lim, 600)
        for v in np.linspace(-lim, lim, 17):
            for line in (np.stack([t, np.full_like(t, v)], 1), np.stack([np.full_like(t, v), t], 1)):
                pix = distort(cal, line)
                ok = (np.hypot(line[:, 0], line[:, 1]) <= lim) if r_max[name] else np.ones(len(line), bool)
                ok &= (pix[:, 0] >= 0) & (pix[:, 0] <= w) & (pix[:, 1] >= 0) & (pix[:, 1] <= h)
                ax.plot(np.where(ok, pix[:, 0], np.nan), np.where(ok, pix[:, 1], np.nan), color=COLD, lw=0.5)
        if "M20" in name:  # field of the visible camera seen by the infrared camera
            r = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1], [-1, -1]], float) * vis_half
            r = np.concatenate([np.linspace(r[i], r[i + 1], 50) for i in range(4)])
            pix = distort(cal, r)
            ax.plot(pix[:, 0], pix[:, 1], color=HOT, lw=1.2, label="visible field")
            ax.legend(loc="lower center", fontsize=6, framealpha=0.9)
        ax.add_patch(Rectangle((0, 0), w, h, fill=False, color="k", lw=1))
        ax.set_xlim(-0.05 * w, 1.05 * w)
        ax.set_ylim(1.05 * h, -0.05 * h)
        ax.set_aspect("equal")
        ax.set_title(name)
        tidy(ax)
    ax = axes[2]
    for (name, cal), color in zip(cams, [COLD, HOT]):
        k1, k2, _, _, k3 = np.array(cal["dist"]).ravel()
        f = np.array(cal["mtx"])[0, 0]
        w, h = cal["size"]
        corner = np.hypot(w / 2, h / 2) / f
        r_u = np.linspace(0, r_max[name] or corner * 1.02, 200)
        r_d = r_u * (1 + k1 * r_u**2 + k2 * r_u**4 + k3 * r_u**6)
        r_u = r_u[r_d <= corner]
        r_d = r_u * (1 + k1 * r_u**2 + k2 * r_u**4 + k3 * r_u**6)
        r_d = r_d[r_d <= corner]
        ax.plot(np.degrees(np.arctan(r_u)), (r_d - r_u) * f, color=color, label="DJI (visible)" if "DJI" in name else "M20 (infrared)")
    ax.axvline(np.degrees(np.arctan(np.hypot(*vis_half))), color="gray", ls="--", lw=0.7)
    ax.text(np.degrees(np.arctan(np.hypot(*vis_half))) + 0.5, -700, "corner of the\nvisible image", fontsize=6, color="gray")
    ax.set_xlabel("angle to the optical axis (deg)")
    ax.set_ylabel("radial shift (px)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=6)
    ax.set_title("Radial distortion")
    fig.subplots_adjust(wspace=0.5)
    save(fig, out, "align_distortion.png")


def fig_virtual_camera(p, out):
    ext = 1.4
    canvas = p.nir_warp(extension=ext)
    h, w = p.ref.shape[:2]
    ox, oy = (canvas.shape[1] - w) / 2, (canvas.shape[0] - h) / 2
    f = p.cal_ref["mtx"][0, 0]
    tx, ty = f * np.tan(np.radians(p.model["yaw"])), f * np.tan(np.radians(p.model["pitch"]))
    fig, axes = plt.subplots(1, 2, figsize=(WIDTH, 2.3), gridspec_kw={"width_ratios": [1.4, 1]})
    s = 1400 / max(canvas.shape[:2])
    axes[0].imshow(thumbnail(canvas))
    axes[0].add_patch(Rectangle((ox * s, oy * s), w * s, h * s, fill=False, color="w", ls="--", lw=1, label="yaw = pitch = 0"))
    axes[0].add_patch(Rectangle(((ox - tx) * s, (oy - ty) * s), w * s, h * s, fill=False, color=HOT, lw=1.2,
                                label="after the coarse search"))
    axes[0].legend(loc="lower right", fontsize=6)
    axes[0].set_title("NIR rectified in the virtual camera (field x %.1f)" % ext)
    axes[1].imshow(thumbnail(p.ref))
    axes[1].set_title("Visible reference (distortion corrected)")
    for ax in axes:
        tidy(ax)
    save(fig, out, "align_virtual_camera.jpg")


def crop_box(img_shape, cx=0.5, cy=0.5, size=700):
    h, w = img_shape[:2]
    x0, y0 = int(cx * w - size / 2), int(cy * h - size / 2)
    return slice(y0, y0 + size), slice(x0, x0 + size)


def fig_feature_maps(p, st, out, cx, cy, size=600):
    ys, xs = crop_box(p.ref.shape, cx, cy, size)
    rows = [("VIS", p.ref, 5.), ("NIR", st["local"], 3.)]
    titles = ["colour", "luminance", r"$E_{x}$ (|)", r"$E_{y}$ (-)", r"$E_{\nearrow}$", r"$E_{\searrow}$"]
    fig, axes = plt.subplots(2, 6, figsize=(WIDTH, 2.35))
    for r, (name, img, sigma) in enumerate(rows):
        msr = multispectral_representation(img, sigma_gaussian=sigma, mode=LAPLACIAN_ENERGIES)[ys, xs]
        panels = [img[ys, xs], gray(img)[ys, xs]] + [msr[:, :, c] for c in (1, 0, 2, 3)]
        for c, panel in enumerate(panels):
            ax = axes[r, c]
            if c == 0:
                ax.imshow(stretch(panel.astype(np.float32)))
            elif c == 1:
                ax.imshow(stretch(panel), cmap="gray")
            else:
                ax.imshow(np.sqrt(panel / np.percentile(msr, 99.5)).clip(0, 1), cmap="magma")
            tidy(ax)
            if r == 0:
                ax.set_title(titles[c])
        axes[r, 0].set_ylabel(name)
    fig.subplots_adjust(wspace=0.04, hspace=0.04)
    save(fig, out, "align_feature_maps.jpg")


def profile(ref, mov, ds, radius, mode, dist, sigma_ref, sigma_mov):
    """1D horizontal cost profile (vertical shift 0) of the whole image, as in the pipeline."""
    if mode == "gray":
        r = pyramid_reduce(gray(ref)[..., None], downscale=ds)
        m = pyramid_reduce(gray(mov)[..., None], downscale=ds)
        if r.ndim == 2:
            r, m = r[..., None], m[..., None]
    else:
        r = pyramid_reduce(multispectral_representation(ref, sigma_gaussian=sigma_ref), downscale=ds)
        m = pyramid_reduce(multispectral_representation(mov, sigma_gaussian=sigma_mov), downscale=ds)
    r, m = r.astype(np.float32), m.astype(np.float32)
    h, w = r.shape[:2]
    margin = radius + 2
    ref_patch = np.ascontiguousarray(r[margin:h - margin, margin - radius:w - margin + radius])
    mov_patch = np.ascontiguousarray(m[margin:h - margin, margin:w - margin])
    func = cost_surface_NTG if dist == "NTG" else cost_surface_SSD
    if dist == "NTG":
        ref_rows = np.ascontiguousarray(r[margin - 1:h - margin + 1, margin - radius - 1:w - margin + radius + 1])
        mov_rows = np.ascontiguousarray(m[margin - 1:h - margin + 1, margin - 1:w - margin + 1])
        cost = func(ref_rows, mov_rows, 0, radius)
    else:
        cost = func(ref_patch, mov_patch, 0, radius)
    c = cost[0].sum(axis=-1)
    return np.arange(-radius, radius + 1) * ds, c


def region(img, box, border):
    """Part of img inside box = (x0, y0, x1, y1) in fractions, with `border` extra pixels around."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = box
    return img[max(int(y0 * h) - border, 0):int(y1 * h) + border, max(int(x0 * w) - border, 0):int(x1 * w) + border]


def fig_cost_profiles(p, st, out, structured, vegetation):
    """1D cost profiles of one block, three criteria: same band, two bands on structures, two bands on vegetation."""
    ds, radius = 4, 25
    border = (radius + 3) * ds
    cases = [
        ("SSD on luminance", "gray", "SSD", "k", "--"),
        ("NTG on luminance", "gray", "NTG", "#7f7f7f", "-"),
        ("NTG on gradient energies (IRdrone)", "msr", "NTG", HOT, "-"),
    ]
    panels = [("(a) VIS vs VIS: trees, hedge", structured, p.ref),
              ("(b) VIS vs NIR: trees, hedge", structured, st["local"]),
              ("(c) VIS vs NIR: meadow only", vegetation, st["local"])]
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 2.0), sharey=True)
    for ax, (title, box, mov) in zip(axes, panels):
        ref_b, mov_b = region(p.ref, box, border), region(mov, box, border)
        for name, mode, dist, color, ls in cases:
            x, c = profile(ref_b, mov_b, ds, radius, mode, dist, 5., 3. if mov is not p.ref else 5.)
            c = (c - c.min()) / (c.max() - c.min())
            ax.plot(x, c, color=color, ls=ls, lw=1.1, label=name)
        ax.axvline(0, color="gray", lw=0.6)
        ax.set_xlabel("horizontal shift (px)")
        ax.set_title(title, fontsize=7)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("normalised cost")
    axes[0].legend(fontsize=5.5, loc="lower left")
    fig.subplots_adjust(wspace=0.08)
    save(fig, out, "align_cost_profiles.png")


def fig_coarse_search(p, out):
    d = costs_of(p.traces, "Full Search_blocks_y1x1_search_y37x37_NTG__cost_search_.npy")
    cost = d["costs"][0, 0]
    total = cost.sum(axis=-1)
    n = total.shape[0] // 2
    ds = 32
    concavity = hessian_determinant(cost[:, :, -1])
    amin = np.unravel_index(np.argmin(total), total.shape)
    amax = np.unravel_index(np.argmax(concavity), total.shape)
    z = 12  # zoom of the maps: +-12 cells around the centre
    ext = [(-z - .5) * ds, (z + .5) * ds, (z + .5) * ds, (-z - .5) * ds]
    zoomed = (slice(n - z, n + z + 1), slice(n - z, n + z + 1))
    fig = plt.figure(figsize=(WIDTH, 2.3))
    ax1 = fig.add_subplot(1, 3, 1, projection="3d")
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1] * ds
    ax1.plot_surface(xx, yy, total / total.max(), cmap="viridis", linewidth=0, antialiased=True, rcount=75, ccount=75)
    ax1.view_init(elev=35, azim=-60)
    ax1.set_title("NTG cost, exhaustive search")
    ax1.set_xlabel("x (px)", labelpad=-6)
    ax1.set_ylabel("y (px)", labelpad=-6)
    ax1.tick_params(pad=-3, labelsize=5)
    ax1.set_zticks([])
    for ax, img, title in [(fig.add_subplot(1, 3, 2), total[zoomed], "cost (sum of the 4 channels)"),
                           (fig.add_subplot(1, 3, 3), concavity[zoomed], "Hessian determinant (sharpness)")]:
        im = ax.imshow(img, extent=ext)
        ax.plot((amin[1] - n) * ds, (amin[0] - n) * ds, "w+", ms=9, mew=1.2, label="minimum of the cost")
        ax.plot((amax[1] - n) * ds, (amax[0] - n) * ds, "rx", ms=7, mew=1.2, label="sharpest point")
        ax.set_title(title)
        ax.set_xlabel("x shift (px)")
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02).ax.tick_params(labelsize=5)
    ax.legend(fontsize=5, loc="lower left")
    fig.subplots_adjust(wspace=0.35)
    save(fig, out, "align_coarse_search.png")


def vectors_and_fit(d):
    vpos, vf = brute_force_vector_field_search(costs=d["costs"], centers=d["centers"], downscale=d["downscale"])
    homog = geometric_rigid_transform_estimation(vpos, vf)
    pts = vpos.reshape(-1, 2)
    proj = cv2.perspectiveTransform(pts[None].astype(np.float64), homog)[0]
    return vpos, vf, (proj - pts).reshape(vf.shape)


def fig_block_costs(p, st, out, name, file_name, title, stage="coarse", scale=20):
    d = costs_of(p.traces, name)
    costs = d["costs"]
    ny, nx = costs.shape[:2]
    vpos, vf, fit = vectors_and_fit(d)
    fig = plt.figure(figsize=(WIDTH, 2.9))
    gs = fig.add_gridspec(ny, 2 * nx, wspace=0.08, hspace=0.08)
    ax = fig.add_subplot(gs[:, :nx])
    ax.imshow(thumbnail(overlay(p.ref, st[stage])), extent=[0, p.ref.shape[1], p.ref.shape[0], 0])
    bh, bw = p.ref.shape[0] / ny, p.ref.shape[1] / nx
    for i in range(1, ny):
        ax.axhline(i * bh, color="w", lw=0.6)
    for j in range(1, nx):
        ax.axvline(j * bw, color="w", lw=0.6)
    q = vpos.reshape(-1, 2)
    ax.quiver(q[:, 0], q[:, 1], vf[..., 0].ravel() * scale, vf[..., 1].ravel() * scale, color="#4fc3f7",
              angles="xy", scale_units="xy", scale=1, width=0.009, label="measured (x%d)" % scale)
    ax.quiver(q[:, 0], q[:, 1], fit[..., 0].ravel() * scale, fit[..., 1].ravel() * scale, color=HOT,
              angles="xy", scale_units="xy", scale=1, width=0.0035, label="homography fit")
    ax.legend(fontsize=6, loc="lower left")
    ax.set_title(title)
    tidy(ax)
    sy, sx = costs.shape[2] // 2, costs.shape[3] // 2
    for i in range(ny):
        for j in range(nx):
            a = fig.add_subplot(gs[i, nx + j])
            c = costs[i, j].sum(axis=-1)
            a.imshow(c)
            disp = minimum_cost(costs[i, j][sy - 5:sy + 6, sx - 5:sx + 6])[0]
            a.plot(sx + disp[0], sy + disp[1], "w+", ms=5, mew=0.8)
            a.plot(sx, sy, ".", color="k", ms=2)
            tidy(a)
    save(fig, out, file_name)


def convergence(traces):
    import glob
    files = sorted(glob.glob(osp.join(traces, "ds*_cost_search__it*.npy")), key=lambda f: int(f[-6:-4]))
    rows = []
    for f in files:
        d = costs_of(traces, osp.basename(f))
        _, vf, _ = vectors_and_fit(d)
        mag = np.linalg.norm(vf, axis=-1)
        label = "it %d\n1/%d\n%dx%d" % (int(f[-6:-4]), d["downscale"], d["costs"].shape[0], d["costs"].shape[1])
        rows.append((label, mag.mean(), mag.max()))
    return rows


def fig_convergence(points, out):
    fig, ax = plt.subplots(figsize=(WIDTH * 0.66, 2.1))
    for (name, p), color in zip(points, [COLD, HOT]):
        rows = convergence(p.traces)
        x = np.arange(len(rows))
        ax.semilogy(x, [r[1] for r in rows], "o-", color=color, ms=3.5, label=name + ": mean")
        ax.semilogy(x, [r[2] for r in rows], "s--", color=color, ms=3, alpha=0.7, label=name + ": largest")
    ax.set_xticks(x)
    ax.set_xticklabels([r[0] for r in rows], fontsize=5.5)
    ax.set_ylabel("block displacement (px)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=5.5, ncol=2)
    save(fig, out, "align_convergence.png")


def fig_stages(p, st, out, cx, cy, size=700):
    ys, xs = crop_box(p.ref.shape, cx, cy, size)
    m = p.model
    names = [("zero", "(a) rotation 0\n(calibrations only)"),
             ("coarse", "(b) coarse search\nyaw %.2f, pitch %.2f deg" % (m["yaw"], m["pitch"])),
             ("global", "(c) + homography\n(global alignment)"),
             ("local", "(d) + vector field\n(local alignment)")]
    fig, axes = plt.subplots(1, 4, figsize=(WIDTH, 1.85))
    for ax, (key, title) in zip(axes, names):
        ax.imshow(overlay(p.ref[ys, xs], st[key][ys, xs]))
        ax.set_title(title, fontsize=6.5)
        tidy(ax)
    fig.subplots_adjust(wspace=0.04)
    save(fig, out, "align_stages.jpg")


def fig_polar(p, st, out, roll=None, window=8, name="align_polar_roll.jpg"):
    """Polar resampling of the gradient energies: a roll becomes a vertical shift (experiment of issue #33).
    roll None: the NIR image after the coarse search (its actual roll), else the aligned NIR rolled by `roll` deg."""
    ds = 4
    ref = pyramid_reduce(multispectral_representation(p.ref, sigma_gaussian=5.), downscale=ds).astype(np.float32)
    if roll is None:
        mov_rolled = st["coarse"]
    else:
        h, w = st["local"].shape[:2]
        rot = cv2.getRotationMatrix2D((w / 2, h / 2), roll, 1.)
        mov_rolled = cv2.warpAffine(st["local"], rot, (w, h))
    mov = pyramid_reduce(multispectral_representation(mov_rolled, sigma_gaussian=3.), downscale=ds).astype(np.float32)
    radius = min(ref.shape[:2]) / 2. * 0.75
    pol_ref = warp_polar(ref, radius=radius, channel_axis=-1, output_shape=(360, int(radius)))
    pol_mov = warp_polar(mov, radius=radius, channel_axis=-1, output_shape=(360, int(radius)))
    # the angle axis is periodic: the reference is extended by `window` rows on both sides
    ref_ext = np.concatenate([pol_ref[-window:], pol_ref, pol_ref[:window]]).astype(np.float32)
    cost = cost_surface_NTG(np.ascontiguousarray(ref_ext), np.ascontiguousarray(pol_mov.astype(np.float32)), window, 0)
    prof = cost[:, 0].sum(axis=-1)
    angles = np.arange(-window, window + 1)
    k = int(np.argmin(prof))
    a, b, c = np.polyfit(angles[k - 1:k + 2], prof[k - 1:k + 2], 2)
    est = -b / (2 * a)
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 2.0), gridspec_kw={"width_ratios": [1, 1, 1.4]})
    for ax, pol, title in [(axes[0], pol_ref, "VIS, polar resampling"), (axes[1], pol_mov, "NIR, after the coarse search" if roll is None else "NIR, rolled by %.1f deg" % roll)]:
        ax.imshow(np.sqrt(pol[..., :3] / np.percentile(pol, 99.5)).clip(0, 1), aspect="auto")
        ax.set_xlabel("radius")
        ax.set_title(title)
        ax.set_yticks([0, 90, 180, 270, 359])
    axes[0].set_ylabel("angle (deg)")
    axes[1].set_yticklabels([])
    ax = axes[2]
    ax.plot(angles, prof, "o--", color=COLD, ms=3, label="NTG cost per 1 deg shift")
    xf = np.linspace(angles[k] - 1.5, angles[k] + 1.5, 50)
    ax.plot(xf, a * xf**2 + b * xf + c, color=HOT, label="parabola: %.2f deg" % est)
    ax.set_xlabel("polar shift (deg)")
    ax.set_title("roll estimate")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=6)
    save(fig, out, name)
    return est


def phase_surface(a, b):
    """Phase correlation (Kuglin and Hines): inverse FFT of the normalised cross-power spectrum."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa, fb = np.fft.fft2((a - a.mean()) * win), np.fft.fft2((b - b.mean()) * win)
    cross = fa * np.conj(fb)
    return np.fft.fftshift(np.real(np.fft.ifft2(cross / (np.abs(cross) + 1e-9))))


def fig_phase_correlation(points, out):
    """Phase correlation surfaces, luminance and gradient energies, VIS vs coarse aligned NIR."""
    ds, zoom = 8, 40
    fig, axes = plt.subplots(len(points), 2, figsize=(WIDTH * 0.62, 2.0 * len(points)))
    for row, (name, p, st) in enumerate(points):
        ref_g = cv2.resize(gray(p.ref), None, fx=1 / ds, fy=1 / ds, interpolation=cv2.INTER_AREA)
        mov_g = cv2.resize(gray(st["coarse"]), None, fx=1 / ds, fy=1 / ds, interpolation=cv2.INTER_AREA)
        ref_e = pyramid_reduce(multispectral_representation(p.ref, sigma_gaussian=5.), downscale=ds).sum(axis=-1)
        mov_e = pyramid_reduce(multispectral_representation(st["coarse"], sigma_gaussian=3.), downscale=ds).sum(axis=-1)
        for col, (a, b, title) in enumerate([(ref_g, mov_g, "luminance"), (np.sqrt(ref_e), np.sqrt(mov_e), "gradient energies")]):
            ax = axes[row, col]
            corr = phase_surface(a, b)
            cy, cx = np.array(corr.shape) // 2
            sub = corr[cy - zoom:cy + zoom + 1, cx - zoom:cx + zoom + 1]
            ratio = sub.max() / np.sort(sub.ravel())[-20:-1].mean()
            ax.imshow(sub, extent=[-zoom * ds, zoom * ds, zoom * ds, -zoom * ds])
            ax.set_title("%s, %s\npeak / next 19 values = %.1f" % (name, title, ratio), fontsize=6.5)
            ax.tick_params(labelsize=5.5)
    fig.subplots_adjust(hspace=0.45, wspace=0.3)
    save(fig, out, "align_phase_correlation.png")


def fig_shading(out):
    """Lens shading (vignetting) gains of both cameras, as applied to the RAW images before the alignment."""
    from irdrone.process import SJCAM_M20_PROFILE_CONTROL_POINTS
    dji = np.load(osp.join(osp.dirname(__file__), "..", "calibration", "DJI_RAW", "shading_calibration.npy"))
    m20_shape = (3448, 4600)  # RAW size of the SJCam M20
    half_diag = int(np.hypot(m20_shape[0] / 2, m20_shape[1] / 2))
    radius = np.arange(half_diag)
    m20 = {c: ut.get_shading_profile(SJCAM_M20_PROFILE_CONTROL_POINTS[c], radius) for c in "RGB"}
    m20_map = ut.get_polar_shading_map(img_shape=(m20_shape[0] // 8, m20_shape[1] // 8, 3), calib={
        c: [(x / 8, y) for x, y in SJCAM_M20_PROFILE_CONTROL_POINTS[c]] for c in "RGB"})
    # DJI: profile along the diagonal of the (10 times reduced) map, relative to the centre
    h, w = dji.shape[:2]
    t = np.linspace(0, 1, 200)
    ys, xs = (h - 1) / 2 * (1 + t), (w - 1) / 2 * (1 + t)
    dji_rel = dji / dji[h // 2, w // 2]
    dji_diag = {c: cv2.remap(dji_rel[:, :, i].astype(np.float32), xs.astype(np.float32)[None],
                             ys.astype(np.float32)[None], cv2.INTER_LINEAR)[0] for i, c in enumerate("RGB")}
    colors = {"R": HOT, "G": "#2ca02c", "B": COLD}
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 1.95), gridspec_kw={"width_ratios": [1.25, 1, 1]})
    ax = axes[0]
    for c in "RGB":
        ax.plot(radius / half_diag, m20[c], color=colors[c], lw=1.1, label="M20 (NIR) " + c)
        ax.plot(t, dji_diag[c], color=colors[c], lw=1.1, ls="--", label="DJI (VIS) " + c)
    ax.axhline(1, color="gray", lw=0.6)
    ax.set_xlabel("distance to the centre / half diagonal")
    ax.set_ylabel("gain (1 at the centre)")
    ax.set_title("(a) radial gain of the correction")
    ax.legend(fontsize=5, ncol=2, loc="lower left")
    ax.grid(alpha=0.3)
    for ax, img, title in [(axes[1], m20_map[:, :, 1], "(b) M20 gain map (G)"),
                           (axes[2], dji_rel[:, :, 1], "(c) DJI gain map (G)")]:
        im = ax.imshow(img, cmap="magma", vmin=0.3, vmax=1.4)
        ax.set_title(title)
        tidy(ax)
    fig.colorbar(im, ax=axes[1:], fraction=0.03, pad=0.02)
    save(fig, out, "align_shading.png")


def smooth1d(signal, sigma):
    return cv2.GaussianBlur(signal.astype(np.float64)[None], (0, 0), sigma, borderType=cv2.BORDER_REPLICATE)[0]


def fig_inversion(out):
    """Why intensities fail: a 1D cut of a field, a bare soil strip and a road, in both bands."""
    x = np.arange(640)
    # (start, end, material): vegetation, bare soil, road with bright verges, crop
    layout = [(0, 90, "veg"), (90, 190, "soil"), (190, 250, "veg"), (292, 300, "verge"), (300, 350, "road"),
              (350, 358, "verge"), (358, 460, "soil"), (460, 540, "veg2"), (540, 640, "soil")]

    def scene(levels):
        sig = np.full(x.shape, levels["soil"], dtype=float)
        for left, right, material in layout:
            sig[left:right] = levels[material]
        return sig
    vis = scene({"veg": 0.22, "soil": 0.62, "road": 0.3, "verge": 0.85, "veg2": 0.32})
    nir = scene({"veg": 0.75, "soil": 0.45, "road": 0.25, "verge": 0.45, "veg2": 0.62})
    rng = np.random.default_rng(1)
    vis = smooth1d(vis, 1.5) + rng.normal(0, 0.01, x.shape)
    nir = smooth1d(nir, 2.5) + rng.normal(0, 0.01, x.shape)

    def energy(sig, sigma):
        return np.gradient(smooth1d(sig, sigma)) ** 2

    e_vis, e_nir = energy(vis, 3.), energy(nir, 2.)
    radius, margin = 60, 70
    shifts = np.arange(-radius, radius + 1)
    sl = slice(margin, len(x) - margin)
    costs = {"SSD of the intensities": [], "1 - correlation of the intensities": [],
             "NTG of the gradient energies (IRdrone)": []}
    for s in shifts:
        v, n = vis[margin + s:len(x) - margin + s], nir[sl]
        costs["SSD of the intensities"].append(np.sum((v - n) ** 2))
        costs["1 - correlation of the intensities"].append(1 - np.corrcoef(v, n)[0, 1])
        ev, en = e_vis[margin + s:len(x) - margin + s], e_nir[sl]
        costs["NTG of the gradient energies (IRdrone)"].append(np.sum(np.abs(np.gradient(en - ev))))
    fig, axes = plt.subplots(1, 3, figsize=(WIDTH, 1.95))
    axes[0].plot(x, vis, color="#2ca02c", lw=1, label="VIS")
    axes[0].plot(x, nir, color=HOT, lw=1, label="NIR")
    axes[0].set_title("(a) intensities")
    axes[0].legend(fontsize=6)
    for name, sig in [("VIS", e_vis), ("NIR", e_nir)]:
        axes[1].plot(x, sig / sig.max(), color="#2ca02c" if name == "VIS" else HOT, lw=1, label=name)
    axes[1].set_title("(b) gradient energies (normalised)")
    for (name, c), color, ls in zip(costs.items(), ["k", "#7f7f7f", HOT], ["--", ":", "-"]):
        c = np.array(c)
        c = (c - c.min()) / (c.max() - c.min())
        axes[2].plot(shifts, c, color=color, ls=ls, lw=1.1, label=name)
        print(name, "minimum at", shifts[np.argmin(c)])
    axes[2].axvline(0, color="gray", lw=0.6)
    axes[2].set_title("(c) cost against the shift")
    axes[2].set_xlabel("shift (px)")
    axes[2].legend(fontsize=5, loc="lower left")
    for ax in axes[:2]:
        ax.set_xlabel("position (px)")
        for left, right, label in [(0, 90, "veg."), (90, 190, "soil"), (190, 250, "veg."), (292, 358, "road"),
                                   (358, 460, "soil"), (460, 540, "crop"), (540, 640, "soil")]:
            ax.text((left + right) / 2, 1.02, label, ha="center", fontsize=5,
                    transform=ax.get_xaxis_transform())
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.subplots_adjust(wspace=0.28)
    save(fig, out, "align_inversion.png")


def fig_aperture(out):
    """Aperture problem: NTG cost surfaces of a corner, a straight edge and a structureless block.
    The two images of each block have independent noise and, for the meadow, independent textures
    (the textures of two spectral bands do not correspond)."""
    size, radius = 120, 12
    side = size + 2 * radius + 2
    yy, xx = np.mgrid[:side, :side]
    centre = side / 2
    rng = np.random.default_rng(2)

    def meadow():
        return cv2.GaussianBlur(rng.normal(0, 1, (side, side)), (0, 0), 1.5) * 0.05 + 0.5

    cases = {
        "(a) a corner (field)": lambda: ((xx > centre) & (yy > centre)).astype(float),
        "(b) a straight edge (road)": lambda: (np.abs(xx + 0.4 * yy - 1.4 * centre) < 6).astype(float),
        "(c) textures only (meadow)": meadow,
    }

    def msr(img):
        img = img + rng.normal(0, 0.01, img.shape)
        rgb = np.repeat((img * 255)[..., None], 3, axis=2).astype(np.float32)
        return multispectral_representation(rgb, sigma_gaussian=2.).astype(np.float32)

    fig, axes = plt.subplots(1, 3, figsize=(WIDTH * 0.78, 2.0))
    for ax, (title, make) in zip(axes, cases.items()):
        big = np.ascontiguousarray(msr(make()))
        small = np.ascontiguousarray(msr(make())[radius:-radius, radius:-radius])
        cost = cost_surface_NTG(big, small, radius, radius).sum(axis=-1)
        cost = (cost - cost.min()) / (cost.max() - cost.min())
        # rise of the cost 3 pixels away from the right position, in the best and worst directions
        angles = np.linspace(0, np.pi, 36, endpoint=False)
        px = (radius + 3 * np.cos(angles)).astype(np.float32)[None]
        py = (radius + 3 * np.sin(angles)).astype(np.float32)[None]
        rise = cv2.remap(cost.astype(np.float32), px, py, cv2.INTER_LINEAR)[0] - cost[radius, radius]
        ax.imshow(cost, extent=[-radius - 0.5, radius + 0.5, radius + 0.5, -radius - 0.5])
        ax.plot(0, 0, "w+", ms=6)
        ax.set_title("%s\nrise at 3 px: %.2f to %.2f" % (title, rise.min(), rise.max()), fontsize=6.5)
        ax.set_xlabel("shift x (px)")
        ax.tick_params(labelsize=5.5)
        print(title, rise.min(), rise.max())
    axes[0].set_ylabel("shift y (px)")
    fig.subplots_adjust(wspace=0.35)
    save(fig, out, "align_aperture.png")


def radial_spectrum(img, bins=60):
    f = np.abs(np.fft.fftshift(np.fft.fft2((img - img.mean()) * np.outer(np.hanning(img.shape[0]),
                                                                      np.hanning(img.shape[1]))))) ** 2
    cy, cx = np.array(f.shape) // 2
    yy, xx = np.mgrid[:f.shape[0], :f.shape[1]]
    r = np.hypot((yy - cy) / f.shape[0], (xx - cx) / f.shape[1])
    edges = np.linspace(0, 0.5, bins + 1)
    idx = np.digitize(r.ravel(), edges) - 1
    ok = (idx >= 0) & (idx < bins)
    power = np.bincount(idx[ok], weights=f.ravel()[ok], minlength=bins) / np.maximum(
        np.bincount(idx[ok], minlength=bins), 1)
    return (edges[:-1] + edges[1:]) / 2, power


def fig_warp_once(p, out, cx=0.55, cy=0.3, size=512):
    """Four successive resamplings against a single one, on a detail of the visible image."""
    ys, xs = crop_box(p.ref.shape, cx, cy, size + 200)
    img = gray(p.ref)[ys, xs]
    c = (img.shape[1] / 2, img.shape[0] / 2)
    steps = [cv2.getRotationMatrix2D(c, 1.3, 1.01), cv2.getRotationMatrix2D(c, -0.4, 0.995),
             np.array([[1, 0, 0.37], [0, 1, -0.61]]), cv2.getRotationMatrix2D(c, 0.7, 1.004)]
    total = np.eye(3)
    chained = {"bilinear": img, "bicubic": img}
    for m in steps:
        total = np.vstack([m, [0, 0, 1]]) @ total
        for name, flag in [("bilinear", cv2.INTER_LINEAR), ("bicubic", cv2.INTER_CUBIC)]:
            chained[name] = cv2.warpAffine(chained[name], m, img.shape[::-1], flags=flag,
                                           borderMode=cv2.BORDER_REFLECT)
    once = cv2.warpAffine(img, total[:2], img.shape[::-1], flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    inner = slice(100, 100 + size), slice(100, 100 + size)
    panels = [("(a) 1 bicubic", "one bicubic resampling", once),
              ("(b) 4 bilinear", "four bilinear resamplings", chained["bilinear"]),
              ("(c) 4 bicubic", "four bicubic resamplings", chained["bicubic"])]
    fig, axes = plt.subplots(1, 4, figsize=(WIDTH, 1.75), gridspec_kw={"width_ratios": [1, 1, 1, 1.35]})
    zoom = slice(size // 2 - 64, size // 2 + 64)
    ref_power = radial_spectrum(once[inner])[1]
    for ax, (title, label, im) in zip(axes, panels):
        ax.imshow(im[inner][zoom, zoom], cmap="gray", vmin=0, vmax=1, interpolation="nearest")
        ax.set_title(title, fontsize=6.5)
        tidy(ax)
        freq, power = radial_spectrum(im[inner])
        axes[3].plot(freq, power / ref_power, lw=1.1, label=label)
    axes[3].set_xlabel("spatial frequency (cycles / pixel)")
    axes[3].set_ylabel("power / power of (a)")
    axes[3].set_title("(d) loss of fine details")
    axes[3].legend(fontsize=5, loc="lower left")
    axes[3].grid(alpha=0.3)
    axes[3].tick_params(labelsize=5.5)
    axes[3].yaxis.set_label_position("right")
    axes[3].yaxis.tick_right()
    fig.subplots_adjust(wspace=0.08)
    save(fig, out, "align_warp_once.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vis", required=True, help="point A (a clean case): visible DNG")
    parser.add_argument("--nir", required=True, help="point A: infrared DNG / RAW")
    parser.add_argument("--traces", required=True, help="point A: VIS_XXXX_align_traces folder of a --debug alignment")
    parser.add_argument("--vis-b", required=True, help="point B (a difficult case, e.g. samples/_visible.DNG)")
    parser.add_argument("--nir-b", required=True, help="point B: infrared (e.g. samples/_nir.RAW)")
    parser.add_argument("--traces-b", required=True, help="point B: alignment traces folder")
    parser.add_argument("--out", default=osp.join(osp.dirname(__file__), "images"))
    parser.add_argument("--crop", nargs=2, type=float, default=(0.55, 0.3), help="point A: centre of the zoomed crops")
    parser.add_argument("--crop-b", nargs=2, type=float, default=(0.42, 0.42), help="point B: centre of the zoomed crops")
    parser.add_argument("--structured", nargs=4, type=float, default=(0.3, 0.02, 0.75, 0.4),
                        help="point A: block with trees and a hedge, x0 y0 x1 y1 (fractions)")
    parser.add_argument("--vegetation", nargs=4, type=float, default=(0.08, 0.42, 0.42, 0.72),
                        help="point A: block of meadow only")
    parser.add_argument("--only", nargs="*", default=None)
    args = parser.parse_args()
    jobs = {
        "shading": lambda: fig_shading(args.out),
        "inversion": lambda: fig_inversion(args.out),
        "aperture": lambda: fig_aperture(args.out),
    }
    for key, job in jobs.items():
        if args.only is None or key in args.only:
            job()
    if args.only is not None and set(args.only) <= set(jobs):
        return  # synthetic figures only: the shoot points are not loaded
    a = Point(args.vis, args.nir, args.traces)
    b = Point(args.vis_b, args.nir_b, args.traces_b)
    st_a, st_b = a.stages(), b.stages()
    jobs = {
        "warp_once": lambda: fig_warp_once(a, args.out, *args.crop),
        "pair": lambda: fig_pair(b, args.out),
        "distortion": lambda: fig_distortion(a, args.out),
        "virtual": lambda: fig_virtual_camera(b, args.out),
        "features": lambda: fig_feature_maps(b, st_b, args.out, *args.crop_b),
        "profiles": lambda: fig_cost_profiles(a, st_a, args.out, args.structured, args.vegetation),
        "coarse": lambda: fig_coarse_search(a, args.out),
        "blocks16": lambda: fig_block_costs(
            a, st_a, args.out, "ds16_laplacian_energies_blocks_y4x4_search_y8x8_NTG__cost_search__it01.npy",
            "align_blocks_first.jpg", "iteration 1, scale 1/16 (after the coarse search)"),
        "blocks4": lambda: fig_block_costs(
            a, st_a, args.out, "ds4_laplacian_energies_blocks_y5x5_search_y6x6_NTG__cost_search__it09.npy",
            "align_blocks_last.jpg", "last iteration (9), scale 1/4", stage="global", scale=200),
        "blocks_hard": lambda: fig_block_costs(
            b, st_b, args.out, "ds16_laplacian_energies_blocks_y4x4_search_y8x8_NTG__cost_search__it01.npy",
            "align_blocks_hard.jpg", "difficult case: iteration 1, scale 1/16", scale=10),
        "convergence": lambda: fig_convergence([("A", a), ("B", b)], args.out),
        "stages": lambda: fig_stages(a, st_a, args.out, *args.crop),
        "polar": lambda: print("polar roll estimate", fig_polar(a, st_a, args.out, roll=2.4)),
        "polar_b": lambda: print("polar roll estimate, point B", fig_polar(b, st_b, args.out, window=12, name="align_polar_roll_b.jpg")),
        "phase": lambda: fig_phase_correlation([("A", a, st_a), ("B", b, st_b)], args.out),
    }
    for key, job in jobs.items():
        if args.only is None or key in args.only:
            job()


if __name__ == "__main__":
    main()
