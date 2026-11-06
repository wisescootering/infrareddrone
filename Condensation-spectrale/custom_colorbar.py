import matplotlib.pyplot as plt
import numpy as np

import matplotlib as mpl
from matplotlib.colors import LinearSegmentedColormap

# Make some illustrative fake data:

x = np.arange(0, np.pi, 0.01)
y = np.arange(0, 2 * np.pi, 0.01)
X, Y = np.meshgrid(x, y)
Z = np.cos(X) * np.sin(Y)

# ----------------------------------------------------------------------------------------------
#  Pour chaque couleur RGB on décrit les variations par un tuple (a[i], b[i], c[i])
#   a[i]  défini la fin de l'intervalles d'interpolation entre les ligne i-1 et i  ( valeur comprise entre 0 et 1)
#   b[i] est le % de la couleur en fin d'intervalles [i, i+1]
#   c[i] est le % de la couleur en début d'intervalles [i+1, i+2]
#
#   Remarques:
#   >  a[0] = 0  a[n] = 1
#   > a priori le deuxième élément est égal au troisième pour une variation continue mais  ... ce n'est pas obligatoire !
#   > b[0] et c[n] ne sont pas utilisés
#
#
int = [0, 0.5*(-0.75+1), 0.5*(-0.25+1), 0.5*(-0.1+1), 0.5*(0.1+1), 0.5*(0.25+1), 0.5*(0.75+1), 1]
color_band_zero = (0.7 + 0.75)/2
color_dic = {
    'red': (
        (int[0], 0.00, 0.45 * 80 / 256),
        (int[1], 0.7 * 78 / 256, 0.7 * 78 / 256),
        (int[2], 0.60, 0.60),
        (int[3], 0.70, 0.70),
        (int[4], 0.70, 0.70),
        (int[5], 0.60, 0.60),
        (int[6], 75 / 256, 75 / 256),
        (int[7], 0.5 * 75 / 256, 0),
    ),
    'green': (
        (int[0], 0, 0),
        (int[1], 0, 0),
        (int[2], 0.60, 0.60),
        (int[3], 0.70, 0.70),
        (int[4], 0.70, 0.70),
        (int[5], 0.60, 0.60),
        (int[6], 0.7 * 34 / 257, 0.7 * 34 / 256),
        (int[7], 0.7 * 34 / 256, 0.00),
    ),
    'blue': (
        (int[0], 0.00, 0.5 * 160 / 256),
        (int[1], 140 / 256, 140 / 256),
        (int[2], 0.60, 0.60),
        (int[3], 0.70, 0.70),
        (int[4], 0.70, 0.70),
        (int[5], 0.60, 0.60),
        (int[6], 0.7 * 34 / 256, 0.7 * 34 / 256),
        (int[7],0.7 * 34 / 256, 0.00),
    )
}
mpl.colormaps.register(LinearSegmentedColormap('Slepian', color_dic))


fig, ax = plt.subplots(figsize=(6, 9))
im1 = ax.imshow(Z, cmap='Slepian')
fig.colorbar(im1)
fig.suptitle('Slepian', fontsize=16)
plt.show()

n_lines = 21
cmap = mpl.colormaps['Slepian']

# Take colors at regular intervals spanning the colormap.
colors = cmap(np.linspace(0, 1, n_lines))
fig, ax = plt.subplots(layout='constrained')
for i, color in enumerate(colors):
    ax.plot([0, i], color=color)
plt.show()

exit()
# ______________________________________________________________________________________________
colors = [(0.25, 0, 0), (0.5, 0.5, 0.5), (1, 1, 1), (0.6, 0.5, 0.4), (1, 140/255, 0)]  # Red -> grey  -> white -> grey -> 0range
n_bins = [3, 6, 10, 100]  # Discretizes the interpolation into bins
cmap_name = 'my_list'
fig, axs = plt.subplots(2, 2, figsize=(6, 9))
fig.subplots_adjust(left=0.02, bottom=0.06, right=0.95, top=0.94, wspace=0.05)
for n_bin, ax in zip(n_bins, axs.flat):
    # Create the colormap
    cmap = LinearSegmentedColormap.from_list(cmap_name, colors, N=n_bin)
    # Fewer bins will result in "coarser" colomap interpolation
    im = ax.imshow(Z, origin='lower', cmap=cmap)
    ax.set_title("N bins: %s" % n_bin)
    fig.colorbar(im, ax=ax)
plt.show()