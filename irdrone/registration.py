import cv2
import matplotlib.pyplot as plt
import numpy as np
import logging
from itertools import product
from skimage.registration import phase_cross_correlation


def estimateFeaturePoints(img1o, img2o, debug=False):
def fit_affinity(input_pts, output_pts, weights=None, debug=False):
    """Fit affinity from coordinates (supports Gaussian elimination)

    Parameters
    ----------
    input_pts : np.array
        input coordinates [N, 2]
    output_pts : np.array
        output coordinates [N, 2]
    weights : np.array, optional
        weights applied to each coordinate during fitting [N], by default None
    Returns
    -------
    affinity (np.array)
        affinity [2,3] contained in an [3,3] homography

        (Ax-b)tWtW(Ax-b) = (uv)t=vt ut   (W(Ax-b))t

    Details
    -------
    Affinity H is defined by 6 coefficients
    ```
              | a b c | | u |   |u'|
    y = H x = | d e f | | v | = |v'|
                        | 1 |
    ```

    Rewriting h_x = | a b c |^t and h_y = | d e f |^t
    we can write 2 independant systems of linear equations

    [u v 1].h_x = |u'|

    [u v 1].h_y = |v'|

    A.h=B can be solved as h = (AtA)^-1 At. B
    """
    weights = None
    one_vec = np.ones_like(input_pts[:, :1])
    mat_a = np.concatenate((input_pts, one_vec), axis=1)
    vec_output = output_pts[:, :2]
    for id_iter in range(3):
        if weights is not None:
            mat_a = np.dot(np.diag(weights), mat_a)
            vec_output = np.dot(np.diag(weights), vec_output)
        mat_ata = np.dot(mat_a.T, mat_a)
        mat_ata_inv = np.linalg.inv(mat_ata)
        solution = np.dot(mat_ata_inv, np.dot(mat_a.T, vec_output))
        last_vec = np.zeros((1, 3))
        last_vec[0, -1] = 1
        affinity = np.concatenate((solution.T, last_vec), axis=0)
        residue = np.dot(affinity[:2, :], mat_a.T).T - vec_output
        errors = np.sqrt(np.sum(residue**2, axis=1))
        rms = np.average(errors)
        std_dev = np.std(errors)
        previous_weights = (np.ones(vec_output.shape[0]) if weights is None else weights).copy()
        weights = previous_weights * (errors < rms + std_dev)
        if debug > 1:
            fig, axs = plt.subplots(nrows=3, figsize=(10, 10))
            axs[0].plot(vec_output[:, 0], "r.")
            axs[0].plot(np.dot(affinity[:2, :], mat_a.T).T[:, 0], "r--")
            axs[1].plot(vec_output[:, 1], "b.")
            axs[1].plot(np.dot(affinity[:2, :], mat_a.T).T[:, 1], "b--")

            axs[2].plot(1 - weights, "r-")
            axs[2].plot(np.ma.masked_array(errors, mask=(weights == 1)), "b.")
            axs[2].plot(np.ma.masked_array(errors, mask=(weights == 1)), "mo")
            axs[2].plot(np.ma.masked_array(errors, mask=(previous_weights == 0)), "g.")
            axs[2].set_title("ITER %d PROJECTION RMS %.2f STD %.2f" % (id_iter, rms, std_dev))
            plt.show()
        if rms <= 1.:  # stop at 1 pixel residue
            break
    return affinity




def geometric_rigid_transform_estimation(vpos, vector_field, img=None, debug=False, affinity=False, ax=None):
    """Fit homography on a vector field

    Parameters
    ----------
    vpos : numpy array (nx, ny, 2)
        coordinates of patch centers where motion has been estimated, [x,y]
    vector_field : numpy array (nx, ny, 2)
        vector field [vx, vy]
    debug : bool, optional
        plot vector field quiver, by default False

    Returns
    -------
    homography : numpy array
        (3,3) array
    """
    nx, ny = vpos.shape[0], vpos.shape[1]
    input_pts = [[vpos[idx, idy][0], vpos[idx, idy][1]] for idx, idy in product(range(nx), range(ny))]
    output_pts = [[vpos[idx, idy][0] + vector_field[idx, idy, 0], vpos[idx, idy][1] + +vector_field[idx, idy, 1]]
                  for (idx, idy) in product(range(nx), range(ny))]
    input_pts, output_pts = np.array(input_pts).astype(np.float32), np.array(output_pts).astype(np.float32)
    if affinity:
        homog_estim = fit_affinity(input_pts, output_pts, debug=debug)
    else:
        homog_estim, _ret = cv2.findHomography(input_pts, output_pts, ransacReprojThreshold=3., method=cv2.RANSAC)
    input_pts_ = np.concatenate((input_pts, np.ones((input_pts.shape[0], 1))), axis=1)

    wrp = np.dot(homog_estim, input_pts_.T).T
    wrp[:, 0] /= wrp[:, -1]
    wrp[:, 1] /= wrp[:, -1]
    mv = wrp[:, :-1] - input_pts
    mv = mv.reshape(vector_field.shape)

    if debug or ax is not None:
        if ax is None:
            show_flag = True
            _fig, ax = plt.subplots(ncols=1, nrows=1)
        else:
            show_flag = False
        if img is not None:
            # ax.imshow(img.clip(0., 1.), origin='lower')
            ax.imshow(img, origin='lower')
        kwargs = dict(
            angles="xy",
            scale_units="xy",
            # scale=1.,
            # headwidth=2.,
            # headlength=4.,
            # headaxislength=2.5,
            #   headwidth=0.,
            #   headlength=0.,
            #   headaxislength=0.,
            # width=0.001
        )
        ax.quiver(vpos[:, :, 1], vpos[:, :, 0], -vector_field[:, :, 0], -vector_field[:, :, 1], color="b", label="ESTIMATED", **kwargs)
        ax.quiver(vpos[:, :, 1], vpos[:, :, 0], -mv[:, :, 0], -mv[:, :, 1], color="r", label="FIT", **kwargs)
        ax.set_aspect("equal")
        ax.invert_yaxis()
        # ax.axis('off')
        if show_flag:
            plt.show()
    return homog_estim


    """
    SIFT + Flann knn matching based image registration with homography fitting

    :param img1o: image 1 ir image to displace (register onto image1)
    :param img2o: image 2 visible image to be matched (template = reference)
    :param debug: used to show feature matching
    :return: aligned image, homography
    """
    img1 = cv2.cvtColor(img1o, cv2.COLOR_BGRA2GRAY)
    img2 = cv2.cvtColor(img2o, cv2.COLOR_BGRA2GRAY)
    # Initiate SIFT detector
    sift = cv2.xfeatures2d.SIFT_create(5000)
    # find the keypoints and descriptors with SIFT
    kp1, des1 = sift.detectAndCompute(img1,None)
    kp2, des2 = sift.detectAndCompute(img2,None)

    # FLANN parameters
    FLANN_INDEX_KDTREE = 0
    index_params = dict(algorithm = FLANN_INDEX_KDTREE, trees = 5) #5
    search_params = dict(checks=50)   # or pass empty dictionary

    flann = cv2.FlannBasedMatcher(index_params,search_params)
    matches = flann.knnMatch(des1,des2, k=2)

    # Need to draw only good matches, so create a mask
    matchesMask = [[0,0] for i in range(len(matches))]

    # ratio test as per Lowe's paper
    for i,(m,n) in enumerate(matches):
        if m.distance < 0.7*n.distance: #0.7 is nice
            matchesMask[i]=[1,0]

    draw_params = dict(matchColor = (0,255,0),
                       singlePointColor = (255,0,0),
                       matchesMask = matchesMask,
                       flags = 0)
    if debug:
        img3 = cv2.drawMatchesKnn(img1,kp1,img2,kp2,matches,None,**draw_params)
        plt.imshow(img3,)
        plt.show()

    ptsA, ptsB = [] ,[]
    # loop over the top matches
    for (i, (m,n)) in enumerate(matches):
        if matchesMask[i][0] == 1:
            ptsA.append(kp1[m.queryIdx].pt)
            ptsB.append(kp2[m.trainIdx].pt)
    print("%d matches"%len(ptsA))
    ptsA = np.array(ptsA, dtype="float")
    ptsB = np.array(ptsB, dtype="float")

    # plt.plot(ptsA[:,0], ptsA[:,1], ".r")
    # plt.plot(ptsB[:,0], ptsB[:,1], ".b")
    # plt.show()

    (H, mask) = cv2.findHomography(ptsA, ptsB, method=cv2.RANSAC, ransacReprojThreshold=5.0)
    (h, w) = img2.shape[:2]
    aligned = None if not debug else cv2.warpPerspective(img1o, H, (w, h))
    return aligned, H