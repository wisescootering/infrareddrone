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
from registration.constants import NEWTON, GRADIENT_DESCENT


def classic_gradient(cost, sobel_flag=False):
    """
    2N+1, 2M+1, C -> 2N-1 , 2M-1, C, 2
    Single gradient needs a 3x3 neighborhood.
    """
    grads = np.empty((cost.shape[0]-2, cost.shape[1]-2, cost.shape[2], 2))
    sobel_ = cost[:, 2:, :] - cost[:, :-2, :]
    grad_y = sobel_[1:-1]
    if sobel_flag:  # REMOVE FOR NUMBA?
        grad_y = sobel_[:-2] + sobel_[2:] + 2*sobel_[1:-1]
    sobel_ = cost[2:, :, :] - cost[:-2, :, :]
    grad_x = sobel_[:, 1:-1, :]
    if sobel_flag:  # REMOVE FOR NUMBA?
        grad_x = sobel_[:, :-2] + sobel_[:, 2:] + 2*sobel_[:, 1:-1]
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
    2N+1, 2M+1, C 
    -> gradient (2N-1 , 2M-1, C, 2)
    -> hessian  (2N-3 , 2M-3, C, 2, 2)
    
    :param cost: 
    :param sobel_flag: 
    :return: 
    """
    grads = classic_gradient(cost, sobel_flag=sobel_flag)
    hessi = hessian(grads, sobel_flag=sobel_flag)
    return grads, hessi


def newton_iter(previous_val, grad_vec, hess_mat=None, alpha=1.):
    step = np.zeros_like(previous_val) # (ch, 2)  ch, [x, y]
    n_ch = grad_vec.shape[0]
    for ch in range(n_ch):
        new_val = previous_val
        if hess_mat is None:
            step += - alpha*grad_vec[ch, :]
        else:
            step += - alpha*np.dot(np.linalg.inv(hess_mat[ch, :, :]), grad_vec[ch, :])
    new_val += step/n_ch
    return new_val


def get_derivatives_at_position(cost, x_pos, y_pos):
    center_y, center_x = cost.shape[0]//2, cost.shape[1]//2
    id_y_f = y_pos + center_y
    id_x_f = x_pos + center_x
    id_x = int(np.round(id_x_f))
    id_y = int(np.round(id_y_f))
    print("x ", x_pos, "y ", y_pos, " -- quantified position", id_x, id_y)
    if id_x < 3 or id_x > cost.shape[1]-3 or id_y < 3 or id_y > cost.shape[0]-3:
        logging.warning("WENT TOO FAR!")
        return False, None, None, None, x_pos, y_pos

    neighborhood_size = 2 # 5x5
    extracted_patch = cost[
        id_y-neighborhood_size:id_y+neighborhood_size+1,
        id_x-neighborhood_size:id_x+neighborhood_size+1,
        :
    ]
    gradients, hess = derivatives(extracted_patch)
    grads = gradients[1, 1, :, :]
    hess_mat = hess[0, 0, :, :, :]
    x_pos_discrete, y_pos_discrete = id_x - center_x, id_y - center_y
    return True, extracted_patch, grads, hess_mat, x_pos_discrete, y_pos_discrete


def search_minimum_full_patch_discrete(cost, init_val=None, iter=20, alpha=0.5, mode=[NEWTON, GRADIENT_DESCENT][0]):
    if init_val is None:
        new_val = np.array([0., 0.]).T
    else:
        new_val = np.array(init_val).T
    new_val_x_list = []
    new_val_y_list = []
    for i in range(iter):
        ret, _selected_patch, grads, hess_mat,  x_pos_discrete, y_pos_discrete = get_derivatives_at_position(
            cost,
            new_val[0],
            new_val[1]
        )
        if not ret:
            print("EARLY STOP iteration {}".format(i))
            break
        new_val_x_list.append(new_val[0])
        new_val_y_list.append(new_val[1])
        new_val = newton_iter(
            np.array([x_pos_discrete, y_pos_discrete]).T.astype(np.float32),
            grads,
            hess_mat = hess_mat if mode == NEWTON else None,
            alpha=alpha
        )
    new_val_x_list = np.array(new_val_x_list)
    new_val_y_list = np.array(new_val_y_list)
    return cost, new_val_x_list, new_val_y_list
