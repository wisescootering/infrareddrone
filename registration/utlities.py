import matplotlib.pyplot as plt
from matplotlib import cm
import os.path as osp
import irdrone.utils as ut
import irdrone.process as pr
import numpy as np
from registration.newton import search_minimum_full_patch_discrete, derivatives, newton_iter
from registration.constants import NEWTON, GRADIENT_DESCENT


def plot_trajectory(x, y, z=None, ax=None):
    n_channels = len(x)
    if z is not None:
        ax.plot(x[0], y[0], z[0], "r+", markersize=5)
        ax.plot(x[-1], y[-1], z[-1], "y+", markersize=5)
        for i in range(len(x)-1):
            ax.plot(x[i:i+2], y[i:i+2], z[i:i+2], color=plt.cm.jet(int(255*i/n_channels)), markersize=5)
    else:
        for i in range(len(x)-1):
            ax.plot(
                x[i:i+2],
                y[i:i+2],
                "-o",
                color = plt.cm.jet(int(255*3*i/N)%255),
                markersize=1
            )
        ax.plot(x[0], y[0], "r+", markersize=5)
        ax.plot(x[-1], y[-1], "y+", markersize=5)


def generate_synthetic_surface(size=5, center=[0.8, 0.9], ch_number=1):
    """Synthetic quadric surface, same function for all channels
    """
    single_cost = np.zeros((size, size, ch_number))
    surf_center_y, surf_center_x = single_cost.shape[0]//2, single_cost.shape[1]//2
    for y in range(single_cost.shape[0]):
        for x in range(single_cost.shape[1]):
            single_cost[y, x, :] = 3*(x - (surf_center_x + center[0]))**2 + 1.*(y - (surf_center_y+center[1]))**2
            # single_cost[y, x, 1] = 100.*np.sin(x *0.25)
            # single_cost[y, x, :] += 0.1*x + 0.3*y + 0.1*x*y
            # single_cost[y, x, :] += 100.*np.sin(x *0.25)
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
        plt.imshow(cost[:, :, ch], extent=[-cost.shape[0]//2 , cost.shape[0]//2, cost.shape[1]//2,  -cost.shape[1]//2])
        plt.contour(coord_x, coord_y, cost[:, :, ch], 10,  cmap='RdGy', alpha=0.5)
        plot_trajectory(val_x, val_y, ax=ax)
    plt.tight_layout()
    plt.show()


def search_minimum(single_cost, debug=False):
    gradients, hess = derivatives(single_cost)
    new_val = newton_iter(
        np.array([0., 0.]).T,
        gradients[1, 1, :, :],
        hess_mat = hess[0, 0, :, :, :]
    )
    if debug:
        fig, ax = plt.subplots(subplot_kw={"projection": "3d"})
        coord_y = np.arange(-single_cost.shape[0]//2+1, single_cost.shape[0]//2+1, 1.)
        coord_x = np.arange(-single_cost.shape[1]//2+1, single_cost.shape[1]//2+1, 1.)
        coord_x, coord_y = np.meshgrid(coord_x, coord_y)
        coord_z = single_cost[:, :, 0].T
        surf = ax.plot_surface(coord_x, coord_y, coord_z, cmap=cm.coolwarm,
                               linewidth=0, antialiased=False)
        ax.plot(new_val[1], new_val[0], "r.")
        ch = 0
        pr.show(
            [
                [single_cost[:, :, ch]],
                [(gradients[:, :, ch, 0], "grad X"), (gradients[:, :, ch,  1], "grad Y")],
                [(hess[:, :, ch, 0, 0], "xx"), (hess[:, :, ch, 0, 1], "xy")],
                [(hess[:, :, ch, 1, 0], "yx"), (hess[:, :, ch, 1, 1], "yy")]
            ]
        )
    return new_val


def search_full():
    single_cost = generate_synthetic_surface(size=128, center=[15.5, -30.], ch_number=1)
    start_point = [-40, -50]
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.4, init_val=start_point, mode=NEWTON)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.1, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.25, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)


def search_multi_channel():
    single_cost = generate_synthetic_surface_multi(size=128, center=[15.5, -8.2])
    start_point = [-40, -50]
    res = search_minimum_full_patch_discrete(single_cost, iter=100, alpha=0.2, init_val=start_point, mode=NEWTON)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.1, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)
    res = search_minimum_full_patch_discrete(single_cost, iter=25, alpha=0.25, init_val=start_point, mode=GRADIENT_DESCENT)
    plot_search(*res)


def real_search(cost_file=osp.join(osp.dirname(__file__), ".." , "samples" , "cost.npy")):
    costs = np.load(cost_file)
    center_y, center_x = costs.shape[2]//2, costs.shape[3]//2
    extraction_area = 5
    for i in range(costs.shape[0]):
        for j in range(costs.shape[1]):
            print("patch {} {}".format(i, j))
            single_cost = costs[
                          i, j,
                          center_y-extraction_area:center_y+extraction_area+1,
                          center_x-extraction_area:center_x+extraction_area+1,
                          :
                          ]
            res = search_minimum_full_patch_discrete(single_cost, init_val = [0., 0.], alpha=0.8, iter=20, mode=NEWTON)
            plot_search(*res)


def test_search(debug=False):
    center=[0.8, -0.9]
    single_cost = generate_synthetic_surface(size=5, center=center)
    estimated_center = search_minimum(single_cost, debug=debug)
    assert (np.fabs(center - estimated_center)< 1E-8).all(), "{} vs {}".format(center, estimated_center)


if __name__ == "__main__":
    test_search(debug=True)
    real_search()
    search_full()
    search_multi_channel()