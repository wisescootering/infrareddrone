"""1D curve interactive fit using control points and cubics
"""

import numpy as np
from scipy.interpolate import interp1d
from matplotlib.backend_bases import MouseButton
import matplotlib.pyplot as plt


def interpolate(x, y):
    i = np.arange(len(x))
    interp_i = np.linspace(0, i.max(), 100 * i.max())
    xi = interp1d(i, x, kind='linear')(interp_i)
    yi = interp1d(i, y, kind='cubic')(interp_i)
    return xi, yi


def dist(x, y):
    """
    Return the distance between two points.
    """
    d = x - y
    return np.sqrt(np.dot(d, d))


def dist_point_to_segment(p, s0, s1):
    """
    Get the distance of a point to a segment.
      *p*, *s0*, *s1* are *xy* sequences
    This algorithm from
    http://geomalgorithms.com/a02-_lines.html
    """
    v = s1 - s0
    w = p - s0
    c1 = np.dot(w, v)
    if c1 <= 0:
        return dist(p, s0)
    c2 = np.dot(v, v)
    if c2 <= c1:
        return dist(p, s1)
    b = c1 / c2
    pb = s0 + b * v
    return dist(p, pb)



class PathInteractor:
    """
    An path editor.

    Press 't' to toggle vertex markers on and off.  When vertex markers are on,
    they can be dragged with the mouse.
    """

    showverts = True
    epsilon = 5  # max pixel distance to count as a vertex hit

    def __init__(self, spline, verts):
        self.ax = spline.axes###pathpatch.axes
        canvas = self.ax.figure.canvas
        self.verts = verts
        self.spline = spline
        self.spline.set_animated(True)

        x, y = zip(*self.verts)

        self.line, = ax.plot(x, y, marker='o', ls = '--',
                             markerfacecolor='r', animated=True)

        self._ind = None  # the active vertex

        canvas.mpl_connect('draw_event', self.on_draw)
        canvas.mpl_connect('button_press_event', self.on_button_press)
        canvas.mpl_connect('key_press_event', self.on_key_press)
        canvas.mpl_connect('button_release_event', self.on_button_release)
        canvas.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.canvas = canvas

    def get_ind_under_point(self, event):
        """
        Return the index of the point closest to the event position or *None*
        if no point is within ``self.epsilon`` to the event position.
        """
        # display coords
        xyt = self.spline.get_transform().transform(self.verts)
        xt, yt = xyt[:, 0], xyt[:, 1]
        d = np.sqrt((xt - event.x)**2 + (yt - event.y)**2)
        ind = d.argmin()

        if d[ind] >= self.epsilon:
            ind = None

        return ind

    def on_draw(self, event):
        """Callback for draws."""
        self.background = self.canvas.copy_from_bbox(self.ax.bbox)
        self.ax.draw_artist(self.spline)
        self.ax.draw_artist(self.line)
        self.canvas.blit(self.ax.bbox)

    def on_button_press(self, event):
        """Callback for mouse button presses."""
        if (event.inaxes is None
                or event.button != MouseButton.LEFT
                or not self.showverts):
            return
        self._ind = self.get_ind_under_point(event)

    def on_button_release(self, event):
        """Callback for mouse button releases."""
        if (event.button != MouseButton.LEFT
                or not self.showverts):
            return
        self._ind = None

    def on_key_press(self, event):
        """Callback for key presses."""
        if not event.inaxes:
            return
        if event.key == 't':
            self.showverts = not self.showverts
            self.line.set_visible(self.showverts)
            if not self.showverts:
                self._ind = None
        elif event.key == 'j':
            xys = self.spline.get_transform().transform(self.verts)
            p = event.x, event.y
            for i in range(len(xys) - 1):
                s0 = xys[i]
                s1 = xys[i + 1]
                d = dist_point_to_segment(p, s0, s1)
                if d <= self.epsilon:
                    self.verts.insert(i+1, (event.xdata, event.ydata))
                    self.line.set_data(zip(*self.verts))
                    x, y = interpolate(*zip(*self.verts))
                    self.spline.set_data(x, y)
        elif event.key == 'i':
            print(self.verts)

        self.canvas.draw()

    def on_mouse_move(self, event):
        """Callback for mouse movements."""
        if (self._ind is None
                or event.inaxes is None
                or event.button != MouseButton.LEFT
                or not self.showverts):
            return

        #vertices = verts

        self.verts[self._ind] = event.xdata, event.ydata
        self.line.set_data(zip(*self.verts))
        x, y = interpolate(*zip(*self.verts))
        self.spline.set_data(x, y)

        self.canvas.restore_region(self.background)
        self.ax.draw_artist(self.spline)
        self.ax.draw_artist(self.line)
        self.canvas.blit(self.ax.bbox)


fig, ax = plt.subplots()

if __name__ == "__main__":
    verts = [
        (921, 1181),
        (951, 1230),
        (993, 1243),
        (1035, 1230),
        (1065, 1181),
        (1045, 1130),
        (993, 1130),
        (945, 1130),
        (921, 1181)
    ]

    x, y = interpolate(*zip(*verts))
    from matplotlib.lines import Line2D
    spline = Line2D(x,y)
    ax.add_line(spline)

    interactor = PathInteractor(spline, verts)
    ax.set_title('drag vertices to update path')
    ax.set_xlim(800, 1300)
    ax.set_ylim(1000, 1300)

    plt.show()
