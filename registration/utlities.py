import matplotlib.pyplot as plt
from matplotlib import cm
import os.path as osp
import irdrone.process as pr
import numpy as np
from registration.newton import search_minimum_full_patch_discrete, newton_iter, quadric_approximation
from registration.constants import NEWTON, GRADIENT_DESCENT, QUADRATIC_FORM
import logging


def plot_trajectory(x, y, z=None, ax=None):
    n_channels = len(x)
    if z is not None:
        ax.plot(x[-1], y[-1], z[-1], "y+", markersize=5)
        ax.plot(x[0], y[0], z[0], "r+", markersize=5)
        for i in range(len(x)-1):
            ax.plot(x[i:i+2], y[i:i+2], z[i:i+2], color=plt.cm.jet(int(255*i/n_channels)), markersize=5)
    else:
        for i in range(len(x)-1):
            ax.plot(
                x[i:i+2],
                y[i:i+2],
                "-o",
                color = plt.cm.jet(int(255*3*i/n_channels)%255),
                markersize=1
            )
        ax.plot(x[-1], y[-1], "y+", markersize=5)
        ax.plot(x[0], y[0], "r+", markersize=5)


def generate_synthetic_surface(size=5, center=[0.8, 0.9], ch_number=1, grad=[0., 0.]):
    """Synthetic quadric surface, same function for all channels
    """
    single_cost = np.zeros((size, size, ch_number))
    surf_center_y, surf_center_x = single_cost.shape[0]//2, single_cost.shape[1]//2
    for y in range(single_cost.shape[0]):
        for x in range(single_cost.shape[1]):
            coord = np.array([x - (surf_center_x + center[0]), y - (surf_center_y+center[1])])
            sx, sy = 3., 1.
            theta = np.deg2rad(32.)
            Q = np.array([[sx, 0.], [0., sy]])
            Q = np.dot(Q, np.array(
                [
                    [np.cos(theta), np.sin(theta)],
                    [-np.sin(theta), np.cos(theta)]
                ])
            )
            single_cost[y, x, :] = np.dot(coord.T, np.dot(Q, coord))
            single_cost[y, x, :]+= grad[0]*x + grad[1]*y
    return single_cost


def generate_synthetic_surface_multi(size=5, center=[0.8, 0.9], ch_number=2):
    single_cost = np.zeros((size, size, ch_number))
    surf_center_y, surf_center_x = single_cost.shape[0]//2, single_cost.shape[1]//2
    for y in range(single_cost.shape[0]):
        for x in range(single_cost.shape[1]):
            single_cost[y, x, 0] = 3*(x - (surf_center_x + center[0]))**2 + 1.*(y - (surf_center_y+center[1]))**2
            single_cost[y, x, 1] = -1.*(x - (surf_center_x + center[0]))**2 + 0.1*(y - (surf_center_y+center[1]))**2 #+ 0.5*x*y
    return single_cost


def plot_search(cost, val_x, val_y):
    fig = plt.figure(figsize=plt.figaspect(1.))
    n_channels = cost.shape[-1]
    for ch in range(n_channels):
        ax = fig.add_subplot(n_channels, 2, ch*2+1, projection='3d')
        cost_mins = [cost[int(val_y[id])+cost.shape[0]//2, int(val_x[id])+cost.shape[1]//2, ch] for id in range(len(val_x))]
        coord_y = np.arange(-cost.shape[0]//2+1, cost.shape[0]//2+1, 1.)
        coord_x = np.arange(-cost.shape[1]//2+1, cost.shape[1]//2+1, 1.)
        coord_x, coord_y = np.meshgrid(coord_x, coord_y)
        coord_z = cost[:, :, ch]
        _surf = ax.plot_surface(
            coord_x, coord_y, coord_z,
            cmap=cm.coolwarm,
            linewidth=0, antialiased=False, alpha=0.5
        )
        plot_trajectory(val_x, val_y, cost_mins, ax=ax)
        ax.invert_yaxis()
        # ax.view_init(azim=90, elev=90)
        ax.view_init(azim=90, elev=30)
        ax = fig.add_subplot(n_channels, 2, ch*2+2)
        plt.imshow(cost[:, :, ch], extent=[-cost.shape[0]//2 +0.5 , cost.shape[0]//2 +0.5, cost.shape[1]//2 +0.5,  -cost.shape[1]//2+0.5])
        plt.contour(coord_x, coord_y, cost[:, :, ch], 10,  cmap='RdGy', alpha=0.5)
        plot_trajectory(val_x, val_y, ax=ax)
    plt.tight_layout()
    plt.show()


def quadric_surface(coord, hess, grad, constant=None):
    """
    Compute x^TAx + bx + c
    """
    coord_z = np.dot(hess, coord)
    coord_z = 0.5*(coord*coord_z).sum(axis=0)
    coord_z += np.dot(grad, coord)
    if constant is not None:
        coord_z += constant
    return coord_z


def quadratic_approximation_plot(
        cost=None, grad=None, hess=None, constants=None, offset=None, previous_position=None, next_position=None,
        hess_original=None, grad_original=None, constants_original=None
    ):
    fig = plt.figure(figsize=plt.figaspect(1.))
    n_channels = cost.shape[-1]
    for ch in range(n_channels):
        ax = fig.add_subplot(n_channels, 1, ch+1, projection='3d')
        coord_y = np.arange(-cost.shape[0]//2+1, cost.shape[0]//2+1, 1.)
        coord_x = np.arange(-cost.shape[1]//2+1, cost.shape[1]//2+1, 1.)
        coord_x, coord_y = np.meshgrid(coord_x, coord_y)
        _surf = ax.plot_wireframe(
            coord_x, coord_y, cost[:, :, ch],
            cmap=cm.viridis,
            linewidth=1, antialiased=False, alpha=0.5
        )
        coord_y = np.linspace(-2, 2, num=20, endpoint=True)
        coord_x = np.linspace(-2, 2, num=20, endpoint=True)
        coord_x, coord_y = np.meshgrid(coord_x, coord_y)
        coord = np.array([coord_x.flatten(), coord_y.flatten()])
        coord_z = quadric_surface(coord, hess[ch, :, :], grad[ch, :], constant=cost[cost.shape[0]//2, cost.shape[1]//2, ch] if constants is None else constants[ch])
        coord_z = coord_z.reshape(coord_x.shape)
        if offset is not None:
            coord_x += offset[0]
            coord_y += offset[1]
        _surf = ax.plot_surface(
            coord_x, coord_y, coord_z,
            cmap=cm.coolwarm,
            linewidth=5, antialiased=False, alpha=0.5
        )
        if previous_position is not None and next_position is not None:
            ax.plot(
                [previous_position[0], next_position[0]],
                [previous_position[1], next_position[1]],
                [
                    quadric_surface(np.array([previous_position[0] -offset[0], previous_position[1] -offset[1]]), hess[ch, :, :], grad[ch, :], constant=cost[cost.shape[0]//2, cost.shape[1]//2, ch] if constants is None else constants[ch]),
                    quadric_surface(np.array([next_position[0] -offset[0], next_position[1] -offset[1]]), hess[ch, :, :], grad[ch, :], constant=cost[cost.shape[0]//2, cost.shape[1]//2, ch] if constants is None else constants[ch]),
                ],
                "k-o", markersize=1
            )
        if previous_position is not None:
            ax.plot(
                previous_position[0],
                previous_position[1],
                quadric_surface(np.array([previous_position[0]-offset[0], previous_position[1]-offset[1]]).T, hess[ch, :, :], grad[ch, :], constant=cost[cost.shape[0]//2, cost.shape[1]//2, ch] if constants is None else constants[ch]),
                "r+", markersize=5)
        if next_position is not None:
            ax.plot(
                next_position[0],
                next_position[1],
                quadric_surface(np.array([next_position[0]-offset[0], next_position[1]-offset[1]]).T, hess[ch, :, :], grad[ch, :], constant=cost[cost.shape[0]//2, cost.shape[1]//2, ch] if constants is None else constants[ch]),
                "y+", markersize=5)
        if grad_original is not None and hess_original is not None:
            coord_y = np.linspace(-2, 2, num=20, endpoint=True)
            coord_x = np.linspace(-2, 2, num=20, endpoint=True)
            coord_x, coord_y = np.meshgrid(coord_x, coord_y)
            coord = np.array([coord_x.flatten(), coord_y.flatten()])
            coord_z = quadric_surface(coord, hess_original[ch, :, :], grad_original[ch, :], constant=cost[cost.shape[0]//2, cost.shape[1]//2, ch] if constants_original is None else constants_original[ch])
            coord_z = coord_z.reshape(coord_x.shape)
            if offset is not None:
                coord_x += offset[0]
                coord_y += offset[1]
            _surf = ax.plot_surface(
                coord_x, coord_y, coord_z,
                cmap=cm.viridis,
                linewidth=5, antialiased=False, alpha=0.3
            )
            ax.set_title("{}  -vs-  {}\n{}        {}\ngrad={}  -vs-  {}".format(hess_original[ch, 0, :], hess[ch, 0, :], hess_original[ch, 1, :], hess[ch, 1, :], grad_original[ch, :], grad[ch, :]))
        else:
            ax.set_title("{}\n{}\ngrad={}".format(hess[ch, 0, :], hess[ch, 1, :], grad[ch, :]))
        # ax = fig.add_subplot(n_channels, 2, ch*2+2, projection='3d')

    plt.show()


def search_minimum(single_cost, debug=False, mode=QUADRATIC_FORM):
    if mode == QUADRATIC_FORM:
        hessi, gradi, constants = quadric_approximation(single_cost)
        logging.info("GRADIENT QUADRATRIC FORM APPROACH {}".format(gradi))
        logging.info("HESSIAN QUADRATRIC FORM APPROACH {}".format(hessi))
    new_val = newton_iter(
        np.array([0., 0.]).T,
        gradi,
        hess_mat = hessi,
        max_step=None
    )
    if debug:
        quadratic_approximation_plot(single_cost, gradi, hessi)
    if debug:
        fig, ax = plt.subplots(subplot_kw={"projection": "3d"})
        coord_y = np.arange(-single_cost.shape[0]//2+1, single_cost.shape[0]//2+1, 1.)
        coord_x = np.arange(-single_cost.shape[1]//2+1, single_cost.shape[1]//2+1, 1.)
        coord_x, coord_y = np.meshgrid(coord_x, coord_y)
        coord_z = single_cost[:, :, 0].T
        surf = ax.plot_surface(
            coord_x, coord_y, coord_z, cmap=cm.coolwarm,
            linewidth=0, antialiased=False
        )
        ax.plot(new_val[1], new_val[0], "r.")
        plt.show()

    return new_val


def search_full():
    single_cost = generate_synthetic_surface(size=128, center=[15.5, -30.], ch_number=1)
    start_point = [-40, -50]
    #CONVERGE IN A SINGLE STEP!
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=1., init_val=start_point, mode=NEWTON, max_step=None)
    plot_search(*res)
    #CONVERGE IN A FEW STEPS DUE TO STEP CLIPPING
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=1., init_val=start_point, mode=NEWTON, max_step=10.)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.1, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.25, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)


def search_multi_channel():
    single_cost = generate_synthetic_surface_multi(size=128, center=[15.5, -8.2])
    start_point = [-40, -50]
    res = search_minimum_full_patch_discrete(single_cost, iter=100, alpha=1., init_val=start_point, mode=NEWTON, max_step=10)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.1, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.25, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)


def real_search(cost_file=osp.join(osp.dirname(__file__), "..", "samples" , "cost.npy")):
    costs = np.load(cost_file)
    center_y, center_x = costs.shape[2]//2, costs.shape[3]//2
    extraction_area = 5
    for i in range(costs.shape[0]):
        for j in range(costs.shape[1]):
            logging.info("patch {} {}".format(i, j))
            single_cost = costs[
                          i, j,
                          center_y-extraction_area:center_y+extraction_area+1,
                          center_x-extraction_area:center_x+extraction_area+1,
                          :
                          ]
            res = search_minimum_full_patch_discrete(
                single_cost,
                init_val = [0., 0.],
                # init_val = [1., 2.],
                # init_val = [2.25, -2.4], # CLOSE TO THE EDGE!
                alpha=1.,
                iter=10,
                mode=NEWTON
            )
            plot_search(*res)


def test_search(debug=False):
    center=[0.8, -0.9]
    single_cost = generate_synthetic_surface(size=5, center=center, grad=[0., 0.] if not debug else [0.1, 0.5])
    estimated_center = search_minimum(single_cost, debug=debug)
    if not debug:
        assert (np.fabs(center - estimated_center)< 1E-8).all(), "{} vs {}".format(center, estimated_center)
    else:
        logging.info("Single parabola minimum search OK")


if __name__ == "__main__":
    log = logging.getLogger()
    log.setLevel(logging.INFO)
    test_search(debug=False)
    test_search(debug=True)
    search_full()
    real_search()
    search_multi_channel()

