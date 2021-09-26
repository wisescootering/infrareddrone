"""
- x, y = coordinates
- U = displacement (depend on position x,y ... and geometric model affinity A paramaterized by p ) -> U = a.x , Y = X.p
- S[i](U) = cost function at a given location [i] = (x_i, y_i) for a displacement U
- S[i](U(x,y,P))
- Gradient of S regarding vector p
    dS/dp = dS/dU . dU/dp = X^T . dS/dU

- Hessian of S regarding vector p
    H_p(S) = X^T H_u(S) . X

Cost aggregation over the whole image
M(p) = Sum over i  ( S[i](U) )


_________________________________________________
U = X.p <-> U = A.x
_________________________________________________
Starting from the direct writing of the affinity.

U = A.x

u = p11 x + p12 y + p13
v = p21 x + p22 y + p23

[u] =   [p11, p12, p13] . [x]
[v]     [p21, p22, p23]   [y]
                          [1]
________________________________________________
Rewriting with a pseudo vector

(2, 6)
X = [x y 1 0 0 0]
    [0 0 0 x y 1]

(2, 1) =  (2, 6)   . (6, 1)

                      [p11]
                      [p12]
[u]   [x y 1 0 0 0]   [p13]
[v] = [0 0 0 x y 1] . [p21]
                      [p22]
                      [p23]


IMPORTANT REMARK : because of discrete sampling, gradient computation is sort of assymetric and not well defined...
- To overcome this difficulty, we may use a quadric surface fit
xT A x + B x + C
So it could be easier to retrieve Hessian A and gradient Ax+B
"""
import numpy as np
import logging
from registration.constants import NEWTON, GRADIENT_DESCENT, QUADRATIC_FORM, SOBEL_DERIVATIVES
from scipy.ndimage import convolve

def classic_gradient(cost, sobel_flag=False):
    """
    2N+1, 2M+1, C -> 2N-1 , 2M-1, C, 2
    Single gradient needs a 3x3 neighborhood.
    """
    grads = np.empty((cost.shape[0]-2, cost.shape[1]-2, cost.shape[2], 2))
    sobel_ = cost[:, 2:, :] - cost[:, :-2, :]
    grad_y = sobel_[1:-1]
    if sobel_flag:  # REMOVE FOR NUMBA?
        grad_y = (sobel_[:-2] + sobel_[2:] + 2*sobel_[1:-1])/4.
    sobel_ = cost[2:, :, :] - cost[:-2, :, :]
    grad_x = sobel_[:, 1:-1, :]
    if sobel_flag:  # REMOVE FOR NUMBA?
        grad_x = (sobel_[:, :-2] + sobel_[:, 2:] + 2*sobel_[:, 1:-1])/4.
    grads[:, :, :, 0] = grad_y / 2.
    grads[:, :, :, 1] = grad_x / 2.
    return grads


def hessian(grad_x_y, sobel_flag=False):
    """
    Hessian is the matrix of gradients of gradients
    2N+1, 2M+1, C -> 2N-1 , 2M-1, C, 2, 2
    |g_xx , g_xy|
    |g_yx , g_yy|
    :param grad_x_y:
    :param sobel_flag:
    :return:
    """
    hes = np.empty((grad_x_y.shape[0]-2, grad_x_y.shape[1]-2, grad_x_y.shape[2], 2, 2))
    hes[:, :, :, 0, :] = classic_gradient(grad_x_y[:, :, :, 0], sobel_flag=sobel_flag)
    hes[:, :, :, 1, :] = classic_gradient(grad_x_y[:, :, :, 1], sobel_flag=sobel_flag)
    return hes


def derivatives(cost, sobel_flag=False):
    """
    Naive gradient computation using the Sobel filter ... and the hessian as the matrix of Sobel of Sobel.
    2N+1, 2M+1, C 
    -> gradient (2N-1 , 2M-1, C, 2)
    -> hessian  (2N-3 , 2M-3, C, 2, 2)
    
    :param cost: 
    :param sobel_flag: 
    :return: 
    """
    grads = classic_gradient(cost, sobel_flag=sobel_flag)
    hessi = hessian(grads, sobel_flag=sobel_flag)
    constant = cost
    return hessi, grads, constant


def quadric_approximation(full_cost):
    """
    -> gradient (2N-1 , 2M-1, C, 2)
    -> hessian  (2N-1 , 2M-1, C, 2, 2)
    Based on the HDR+ paper (supplemental material)
    http://www.hdrplusdata.org/hdrplus_supp.pdf   section 4
    Requires a 3x3 neighborhood

    z = 1/2 . u^T . A. u + B u + C
    B = [b1, b2]
    A = [a11 a12]
        [a21 a22]

    z is a quadric form to approximate cost function y.

    b1 & b2 are the gradients.. and are exactly Sobel filters
         [ -1   0   1 ]
    b1 = [ -2   0   2 ] /8 * y
         [ -1   0   1 ]

         [ -1  -2  -1 ]
    b2 = [  0   0   0 ] /4 * y
         [  1   2   1 ]


          [1   -2   1]
    a11 = [2   -4   2] /4  * y
          [1   -2   1]

          [ 1   2   1]
    a22 = [-2  -4  -2] /4  * y
          [ 1   2   1]

                [ 1  0 -1 ]
    a12 = a21 = [ 0  0  0 ] /4 * y
                [-1  0  1 ]

        [-1  2  -1]
    C = [2  12   2] /16 * y
        [-1  2  -1]
    """
    if full_cost.shape[0] !=3 or full_cost.shape[1]!=3:
        full_cost = full_cost[
            full_cost.shape[0]//2 - 1:full_cost.shape[0]//2 + 2,
            full_cost.shape[1]//2 - 1:full_cost.shape[1]//2 + 2,
            :
        ]
    grad_x_conv = np.array([
        [-1., 0., 1.],
        [-2., 0., 2.],
        [-1., 0., 1.],
    ])/8. # b1
    grad_y_conv = grad_x_conv.T  # b2
    hess_xx_conv = np.array([
        [1., -2., 1.],
        [2., -4., 2.],
        [1., -2., 1.],
    ])/4.
    hess_yy_conv = hess_xx_conv.T
    hess_xy_conv = np.array([
        [ 1, 0, -1 ],
        [ 0, 0,  0 ],
        [-1, 0,  1 ]
    ])/4.
    constant_conv = np.array([
        [-1,  2, -1 ],
        [ 2, 12,  2 ],
        [-1,  2, -1 ]
    ])/16.
    n_channels = full_cost.shape[-1]
    hessi = np.empty((n_channels, 2, 2))
    grads = np.empty((n_channels, 2))
    constants = np.empty((n_channels))
    for ch in range(n_channels):
        cost = full_cost[:, :, ch]
        hess_xx = np.sum(cost * hess_xx_conv)
        hess_yy = np.sum(cost * hess_yy_conv)
        hess_xy = np.sum(cost * hess_xy_conv)
        grad_x = np.sum(cost * grad_x_conv)
        grad_y = np.sum(cost * grad_y_conv)
        constants[ch] = np.sum(cost * constant_conv)
        hessi[ch, :, :] = np.array([
            [hess_xx, hess_xy],
            [hess_xy, hess_yy]
        ])
        grads[ch, :] = np.array([grad_x, grad_y])
    return hessi, grads, constants


def newton_iter(previous_val, grad_vec, hess_mat=None, alpha=1., max_step=1.):
    step = np.zeros_like(previous_val)
    n_ch = grad_vec.shape[0]
    for ch in range(n_ch):
        new_val = previous_val
        if hess_mat is None:
            step += - alpha*grad_vec[ch, :]
        else:
            try:
                hess_inv = np.linalg.inv(hess_mat[ch, :, :])
                current_step = alpha*np.dot(hess_inv, grad_vec[ch, :])
                current_step_norm = np.sqrt(np.sum(current_step**2))
                if max_step is not None and current_step_norm > max_step:
                    logging.info("TRUNCATE DISPLACEMENT TO MAXIMUM {} pixel".format(max_step))
                    current_step = current_step/(current_step_norm/max_step)
                logging.info("Channel {}\tcurrent step {}".format(ch, current_step))

                step += - alpha*current_step
            except:
                current_step = grad_vec[ch, :]/np.sqrt(np.sum(grad_vec[ch, :]**2))
                logging.warning("CANNOT INVERT HESSIAN MATRIX! FALLBACK TO GRADIENT DESCENT!\nChannel {}\tcurrent step {}".format(ch, current_step))
                step += - current_step #MOVE BY ONE PIXEL ALONG THE SLOPE!
                # print("STEP: {} - grad {}".format(step, grad_vec[ch, :]))

    new_val += step/n_ch
    return new_val


def plane_approximation(cost_full):
    n_channels = cost_full.shape[0]
    hessians = None
    # hessians = np.empty((n_channels, 2, 2))
    grads = np.empty((n_channels, 2))
    constants = np.empty((n_channels, 1))
    for ch in range(n_channels):
        cost = cost_full[ch, :, :]
        size_y, size_x = cost.shape[0], cost.shape[1]
        a_matrix = np.empty((size_x*size_y, 3))
        center_y, center_x = cost.shape[0]//2, cost.shape[1]//2
        for id_y in range(size_y):
            for id_x in range(size_x):
                a_matrix[id_y*size_x+id_x, :] = np.array([id_x-center_x, id_y-center_y, 1.])
        plane = np.linalg.lstsq(a_matrix, cost.flatten(), rcond=None)[0]
        logging.info("PLANE APPROXIMATION {} - {} {}".format(plane, size_y, size_x))
        grads[ch, :] = np.array([plane[0], plane[1]])
        constants[ch, 0] = plane[2]
    return hessians, grads, constants


def get_derivatives_at_position(cost, x_pos, y_pos, mode=QUADRATIC_FORM):
    debug_dict = None
    center_y, center_x = cost.shape[0]//2, cost.shape[1]//2
    id_y_f = y_pos + center_y
    id_x_f = x_pos + center_x
    id_x = int(np.round(id_x_f))
    id_y = int(np.round(id_y_f))
    x_pos_discrete, y_pos_discrete = id_x - center_x, id_y - center_y
    subpix_x = id_x_f - id_x
    subpix_y = id_y_f - id_y
    logging.info("Position - x {} y {}  [quantified x {} y {}]".format(x_pos, y_pos, id_x, id_y))
    if id_x < 3 or id_x > cost.shape[1]-3 or id_y < 3 or id_y > cost.shape[0]-3:
        logging.warning("WENT TOO FAR!")
        return False, None, None, None, x_pos_discrete, y_pos_discrete, debug_dict

    neighborhood_size = 2 # 5x5
    extracted_patch = cost[
        id_y-neighborhood_size:id_y+neighborhood_size+1,
        id_x-neighborhood_size:id_x+neighborhood_size+1,
        :
    ]
    if mode == SOBEL_DERIVATIVES:
        hess, gradients, constants = derivatives(extracted_patch, sobel_flag=True)
        hess_mat = hess[0, 0, :, :, :]
        grads = gradients[1, 1, :, :]
        constants = extracted_patch[2, 2, :]
    elif mode == QUADRATIC_FORM:
        hess_mat, grads, constants = quadric_approximation(extracted_patch)
    hess_mat[:, 0, 0] = hess_mat[:, 0, 0].clip(0, None)
    hess_mat[:, 1, 1] = hess_mat[:, 1, 1].clip(0, None)
    dets = hess_mat[:, 0, 0]  * hess_mat[:, 1, 1] - hess_mat[:, 0, 1]**2
    hess_mat_original = hess_mat.copy()
    grads_original = grads.copy()
    constants_original = constants.copy()
    plan_approx = False
    for ch in range(hess_mat.shape[0]):
        if dets[ch] <0:
            logging.warning("NON SEMI-POSITIVE MATRIX! \n {} , determinant = {}".format(hess_mat[ch, :,: ], dets[ch]))
            hess_mat[ch, 1, 0] = 0.
            hess_mat[ch, 0, 1] = 0.
        if hess_mat[ch, 0, 0] == 0. or hess_mat[ch, 1, 1] == 0.:
            plan_approx = True
            logging.warning("NON INVERTIBLE HESSIAN! {}".format(hess_mat[ch, :, :]))
            neighborhood_size = 1 # 3x3
            extracted_patch_small = cost[
                  id_y-neighborhood_size:id_y+neighborhood_size+1,
                  id_x-neighborhood_size:id_x+neighborhood_size+1,
                  :
              ]
            _, grads_plane, _constant = plane_approximation(np.array([extracted_patch_small[:, :, ch]]))
            logging.info("GRADS {} VS PLANE FITITNG {}".format(grads[ch, :], grads_plane))
            grads[ch, :] = grads_plane
            constants[ch] = _constant
            hess_mat[ch, :, :] = 0.
    shifted_grad = np.dot(hess_mat, np.array([subpix_x, subpix_y]).T)
    debug_dict = dict(
        cost=cost,
        grad=grads,
        hess=hess_mat,
        constants=constants,
        offset=[x_pos_discrete, y_pos_discrete]
    )
    if plan_approx:
        debug_dict["hess_original"] = hess_mat_original
        debug_dict["grad_original"] = grads_original
        debug_dict["constants_original"] = constants_original
    grads_final = grads+shifted_grad
    return True, extracted_patch, grads_final, hess_mat, x_pos_discrete, y_pos_discrete, debug_dict


def search_minimum_full_patch_discrete(cost, init_val=None, iter=20, alpha=0.5, mode=[NEWTON, GRADIENT_DESCENT][0], max_step=1.):
    if init_val is None:
        new_val = np.array([0., 0.]).T
    else:
        new_val = np.array(init_val).T
    new_val_x_list = []
    new_val_y_list = []
    for i in range(iter):
        ret, _selected_patch, grads, hess_mat,  x_pos_discrete, y_pos_discrete, dbg_dict = get_derivatives_at_position(
            cost,
            new_val[0],
            new_val[1]
        )
        if not ret:
            logging.warning("EARLY STOP iteration {} - getting out of bounds".format(i))
            new_val_x_list.append(new_val[0])
            new_val_y_list.append(new_val[1])

            break

        new_val_x_list.append(new_val[0])
        new_val_y_list.append(new_val[1])
        previous_val = new_val.copy()
        new_val = newton_iter(
            np.array([new_val[0], new_val[1]]).T.astype(np.float32),
            grads,
            hess_mat = hess_mat if mode == NEWTON else None,
            alpha=alpha,
            max_step=max_step
        )
        step_norm = np.sqrt((new_val-previous_val)**2).sum()
        # FOLLOWING CODE IS FOR DEBUGGING THE CASES OF QUADRATIC FORM NOT BEING CORRECT APPROXIMATIONS OF THE SURFACE
        # WORKAROUND IS TO SWITCH TO PLANAR FITTING, SET HESSIAN TO ZERO AND STICK TO A STEP OF GRADIENT DESCENT
        # if (hess_mat[:, 0 , 0] == 0.).any() or (hess_mat[:, 1, 1] == 0.).any():
        #     from registration.utlities import quadratic_approximation_plot
        #     quadratic_approximation_plot(**dbg_dict, previous_position=previous_val, next_position=new_val)
        # if np.fabs(new_val[0])>cost.shape[0]//2-2 or  np.fabs(new_val[1])>cost.shape[1]//2-2: #GETTING OUT OF BOUNDS!
        #     from registration.utlities import quadratic_approximation_plot
        #     quadratic_approximation_plot(**dbg_dict, previous_position=previous_val, next_position=new_val)
        if step_norm<0.1:
            logging.info("Finished converging! {}".format(step_norm))
            break

    new_val_x_list = np.array(new_val_x_list)
    new_val_y_list = np.array(new_val_y_list)
    return cost, new_val_x_list, new_val_y_list
