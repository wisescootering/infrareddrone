import os
import sys
osp = os.path
root = osp.join(osp.dirname(__file__), "..")
sys.path.append(root)
import numpy as np
import logging
from scipy.interpolate import bisplrep, bisplev
import cv2
import irdrone.process as pr


def linear_spline_on_grid(tck, x, y):
    """Values (len(y), len(x)) float32 of a linear spline (bisplrep with
    kx=ky=1) on the grid x, y: same as ``bisplev(x, y, tck).T``.

    A linear spline is piecewise bilinear between its knots and bisplev holds
    it constant outside them: it is evaluated at the knots only, then
    interpolated along x and along y (3 times faster than bisplev on a full
    resolution grid, in float32 instead of float64)."""
    knots_x, knots_y = np.unique(tck[0]), np.unique(tck[1])
    at_knots = np.asarray(bisplev(knots_x, knots_y, tck), dtype=np.float64).reshape(len(knots_x), len(knots_y))
    rows = np.stack([np.interp(x, knots_x, at_knots[:, j]) for j in range(len(knots_y))]).astype(np.float32)
    if len(knots_y) == 1:
        return np.repeat(rows, len(y), axis=0)
    below = np.clip(np.searchsorted(knots_y, y, side="right")-1, 0, len(knots_y)-2)
    weight = np.clip((y-knots_y[below])/(knots_y[below+1]-knots_y[below]), 0., 1.).astype(np.float32)[:, np.newaxis]
    values = rows[below]
    values *= (1-weight)
    values += rows[below+1]*weight
    return values


def warp_from_sparse_vector_field(img, vector_field, debug=False, get_remap=False, padding=None):
    """
    # @TODO: support non sampling vectors (not regular grids)

    :param img: image (y_s, x_s, c_s)
    :param vector_field: (y_n, x_n, 2) - assumes that all blocks are regularly distributed
    :return: warped image using interpolation on the vector field
    """
    if padding is None:
        pad_x = 0
        pad_y = 0
    else:
        pad_x, pad_y = padding
    y_n, x_n = vector_field.shape[:2]
    y_s, x_s = img.shape[:2]
    p_size_x = int(np.floor((x_s - 2 * pad_x) / x_n))
    p_size_y = int(np.floor((y_s - 2 * pad_y) / y_n))

    x_coords = []
    y_coords = []
    for y_id in range(y_n):
        for x_id in range(x_n):
            y_start, y_end = pad_y + y_id*p_size_y, pad_y + (y_id+1)*p_size_y
            x_start, x_end = pad_x + x_id*p_size_x, pad_x + (x_id+1)*p_size_x
            y_center, x_center = (y_start+y_end)/2., (x_start+x_end)/2.
            x_coords.append(x_center)
            y_coords.append(y_center)
    vf_x = -vector_field[:, :, 0]
    vf_y = -vector_field[:, :, 1]
    # Bilinear spline through the block centers. This is exactly what the former
    # scipy interp2d(x_coords, y_coords, vf) did (interp2d was removed in SciPy 1.14).
    tck_x = bisplrep(x_coords, y_coords, vf_x.ravel(), kx=1, ky=1, s=0.0)
    tck_y = bisplrep(x_coords, y_coords, vf_y.ravel(), kx=1, ky=1, s=0.0)
    coord_continuous_x, coord_continuous_y = np.linspace(0, x_s, x_s, endpoint=True), np.linspace(0, y_s, y_s, endpoint=True)
    displacement_x = linear_spline_on_grid(tck_x, coord_continuous_x, coord_continuous_y)
    displacement_y = linear_spline_on_grid(tck_y, coord_continuous_x, coord_continuous_y)
    map_x = displacement_x + coord_continuous_x.astype(np.float32)[np.newaxis, :]
    map_y = displacement_y + coord_continuous_y.astype(np.float32)[:, np.newaxis]
    if get_remap:
        # import matplotlib.pyplot as plt
        # plt.plot([pad_x, x_s-pad_x, x_s-pad_x,  pad_x, pad_x], [pad_y, pad_y, y_s - pad_y, y_s-pad_y, pad_y], "b-")
        # plt.imshow(displacement_x)
        # plt.plot(x_coords, y_coords, ".r")
        # plt.show()
        return map_x, map_y
    img_w = cv2.remap(img, map_x, map_y, interpolation=cv2.INTER_LINEAR)
    if debug:
        pr.show(
            [
                [(vf_y, "vf y"), (vf_x, "vf x")],
                [(displacement_y, "displacement y"), (displacement_x, "displacement x")],
                [(img, 'original'), (img_w, "local warp")]
            ],
            suptitle="local warp based on {}x{} vectors".format(x_n, y_n)
        )
    return img_w


def warp_discontinuously_from_sparse_vector_field(img, vector_field):
    """DEPRECATED"""
    logging.warning("Deprecated, please use warp_from_sparse_vector_field instead")
    out_img = np.zeros_like(img)
    y_n, x_n = vector_field.shape[:2]
    y_s, x_s, c_s = img.shape
    p_size_x = int(np.floor(x_s / x_n))
    p_size_y = int(np.floor(y_s / y_n))
    for y_id in range(y_n):
        for x_id in range(x_n):
            displacement = -vector_field[y_id, x_id, :]
            displacement_y = int(np.round(displacement[1]))
            displacement_x = int(np.round(displacement[0]))
            y_start, y_end = y_id*p_size_y, (y_id+1)*p_size_y
            x_start, x_end = x_id*p_size_x, (x_id+1)*p_size_x
            y_start_target = min(max(y_start+ displacement_y, 0), y_s-1)
            y_end_target = min(max(y_end+ displacement_y, 0), y_s-1)
            x_start_target = min(max(x_start+ displacement_x, 0), x_s-1)
            x_end_target = min(max(x_end+ displacement_x, 0), x_s-1)
            out_img[
            y_start: y_start+(y_end_target-y_start_target),
            x_start: x_start+(x_end_target-x_start_target),
            :
            ] = img[y_start_target: y_end_target, x_start_target:x_end_target, :]
    return out_img


def warp(im, cal, homog, outsize=None, vector_field=None, padding=None, crop=None):
    """
    Global warp = 3D Rotate (homography) and undistort an image
    Local warp  = Vector field can be composed to compensate local motion on top of the global warp.
    Padding is mandatory to get a correct local warp composition.
    Please note that the padding trick applies only if the global warp is valid on a slightly larger FOV.
    This is usually the case when the reference camera has a narrower field of view than the moving one.

    crop = (x, y, width, height): only this part of the output (of size outsize) is computed and returned,
    with the same values as cropping the whole output (the padded border of a local warp is not warped for nothing).
    """
    mtx, dist = cal["mtx"], cal["dist"]
    if outsize is None:
        outsize = (im.data.shape[1], im.data.shape[0])
    map1x, map1y = cv2.initUndistortRectifyMap(
        mtx,
        dist,
        np.eye(3, 3),
        np.dot(homog, mtx),
        outsize, cv2.CV_32FC1
    )
    if vector_field is not None:
        # pr.show(
        #     [(map1x, "vfx"), (map1y, "vfy")]
        # )
        res_mapx, res_mapy = warp_from_sparse_vector_field(np.empty(outsize[::-1]), vector_field,
                                                           get_remap=True, padding=padding)
        if crop is not None:
            crop_x, crop_y, crop_width, crop_height = crop
            res_mapx = np.ascontiguousarray(res_mapx[crop_y:crop_y+crop_height, crop_x:crop_x+crop_width])
            res_mapy = np.ascontiguousarray(res_mapy[crop_y:crop_y+crop_height, crop_x:crop_x+crop_width])
        map1x_n = cv2.remap(map1x, res_mapx, res_mapy,
                            interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        map1y_n = cv2.remap(map1y, res_mapx, res_mapy,
                            interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        # print(res_mapx.shape, map1x.shape, outsize)
        # pr.show([
        #     [(map1x, "vfx"), (map1y, "vfy")],
        #     [(res_mapx, "resx"), (res_mapy, "resy")],
        #     [(map1x_n, "vfxn"), (map1y_n, "vfxn")]
        #     ])
        map1x = map1x_n
        map1y = map1y_n
    elif crop is not None:
        crop_x, crop_y, crop_width, crop_height = crop
        map1x = np.ascontiguousarray(map1x[crop_y:crop_y+crop_height, crop_x:crop_x+crop_width])
        map1y = np.ascontiguousarray(map1y[crop_y:crop_y+crop_height, crop_x:crop_x+crop_width])
    out = cv2.remap(
        im if not isinstance(im, pr.Image) else im.data,
        map1x, map1y,
        interpolation=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0, 0)
    )
    return out

if __name__ == "__main__":
    import sys
    import os.path as osp
    root = osp.join(osp.dirname(__file__), "..")
    sys.path.append(root)
    import irdrone.process as pr
    data_path = r"registration\iterative_multiscale_multispectral_alignment_MSR_search_laplacian_energies_NTG_[(4, 1, 5), (4, 1, 15), (2, 1, 15)]\local_displacement.npy"
    dico = np.load(
        data_path,
        allow_pickle=True
    ).item()
    img = dico["img"]
    vector_field = dico["vector_field"]
    w_img = warp_from_sparse_vector_field(img, vector_field)
    pr.Image(w_img).save("locally_aligned_by_flow.jpg")
    pr.show(img)
