"""GUI-safe angle analysis plots (no pyplot, files only) for the interactive pipeline.

Adapted from utils_IRdrone_Plot.py / angles_analyzis.py: theoretical NIR-to-VIS angles
on the whole mission timeline, compared with the coarse angles actually applied.
"""
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

ANGLES = ("yaw", "pitch", "roll")
COLORS = {
    "yaw": ("deepskyblue", "navy"),
    "pitch": ("yellowgreen", "darkgreen"),
    "roll": ("orange", "darkorange"),
}
MIN_SPECTRUM_POINTS = 16
MAX_PERIOD_S = 30.0


def _new_figure(width, height):
    figure = Figure(figsize=(width, height))
    FigureCanvasAgg(figure)
    return figure


def _save(figure, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(str(path), dpi=150, facecolor="w", bbox_inches="tight")
    return path


def _mean_text(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return "n/a" if values.size == 0 else f"{values.mean():.2f}"


def plot_angles_timeline(times, theoretical, coarse_times, coarse, title, path):
    """Theoretical angles (all shoot points) and coarse angles (processed ones) vs time."""
    figure = _new_figure(11, 9)
    axes = figure.subplots(3, 1, sharex=True)
    for axis, name in zip(axes, ANGLES):
        light, dark = COLORS[name]
        axis.plot(
            times, theoretical[name], color=light, linewidth=0.9, marker="o",
            markersize=2, zorder=0,
            label=f"{name.capitalize()} theoretical, average = {_mean_text(theoretical[name])}°",
        )
        if len(coarse_times):
            axis.plot(
                coarse_times, coarse[name], color=dark, linestyle="--", linewidth=0.8,
                marker="o", markersize=4, zorder=1,
                label=f"{name.capitalize()} coarse process, average = {_mean_text(coarse[name])}°",
            )
        axis.set_ylabel(f"{name.capitalize()} [°]")
        axis.grid(color="gray", linewidth=0.5)
        axis.legend(loc="best", fontsize=7)
    axes[-1].set_xlabel("VIS timeline [s]")
    figure.suptitle(title, fontsize=9)
    return _save(figure, path)


def plot_angles_dispersion(theoretical, coarse, title, path):
    """Pitch as a function of yaw: theoretical alignment versus coarse alignment."""
    has_coarse = len(coarse["yaw"]) > 0
    figure = _new_figure(11 if has_coarse else 6, 5.5)
    axes = np.atleast_1d(figure.subplots(1, 2 if has_coarse else 1))
    curves = [("Theoretical alignment", theoretical, "darkorange")]
    if has_coarse:
        curves.append(("Coarse alignment", coarse, "darkgoldenrod"))
    values = np.concatenate([np.asarray(c[1][a], float) for c in curves for a in ("yaw", "pitch")])
    values = values[np.isfinite(values)]
    low, high = values.min() - 2.0, values.max() + 2.0
    for axis, (label, data, color) in zip(axes, curves):
        yaw = np.asarray(data["yaw"], float)
        pitch = np.asarray(data["pitch"], float)
        axis.plot(yaw, pitch, marker="o", markersize=6, alpha=0.4, mec=color, mfc=color, linestyle="")
        axis.plot(0.0, 0.0, "k+")
        axis.plot(yaw.mean(), pitch.mean(), "r+", markersize=12)
        axis.set_xlim(low, high)
        axis.set_ylim(low, high)
        axis.set_title(
            f"{label}\nAverage yaw {yaw.mean():.2f}° +/- {yaw.std():.2f}°  |  "
            f"pitch {pitch.mean():.2f}° +/- {pitch.std():.2f}°",
            fontsize=8,
        )
        axis.set_xlabel("YAW [°]", fontsize=8)
        axis.set_ylabel("PITCH [°]", fontsize=8)
        axis.grid(color="gray", linewidth=0.5)
    figure.suptitle(title, fontsize=9)
    return _save(figure, path)


def angle_spectrum(values, sampling_period):
    """Return (periods [s], normalized amplitudes, dominant period) of a regular series."""
    signal = np.asarray(values, dtype=float)
    signal = signal - signal.mean()
    spectrum = np.abs(np.fft.rfft(signal))
    frequencies = np.fft.rfftfreq(signal.size, d=sampling_period)
    # Skip the DC term and the slowest components (fewer than ~3 periods observed).
    # Slow drifts (> MAX_PERIOD_S) are not periodicity and would hide the shot rhythm.
    keep = (frequencies >= 3.0 / (signal.size * sampling_period)) & (frequencies >= 1.0 / MAX_PERIOD_S)
    frequencies, spectrum = frequencies[keep], spectrum[keep]
    if spectrum.size == 0 or spectrum.max() == 0:
        return np.array([]), np.array([]), None
    spectrum = spectrum / spectrum.max()
    periods = 1.0 / frequencies
    return periods, spectrum, float(periods[np.argmax(spectrum)])


def plot_angles_spectrum(theoretical, mask, sampling_period, title, path, mask_label):
    """Fourier spectrum (versus period) of the theoretical angles, to reveal periodicity."""
    mask = np.asarray(mask, dtype=bool)
    note = "" if mask.all() else f" ({mask_label}, {int(mask.sum())} points)"

    figure = _new_figure(10, 5)
    axis = figure.subplots()
    # Pitch is the most significant angle given the flight conditions prescribed to the pilot.
    for name in ("pitch",):
        series = np.asarray(theoretical[name], float)[mask]
        if series.size < MIN_SPECTRUM_POINTS:
            continue
        periods, amplitude, dominant = angle_spectrum(series, sampling_period)
        if dominant is None:
            continue
        color = COLORS[name][1]
        axis.plot(periods, amplitude, color=color, linewidth=0.9,
                  label=f"{name.capitalize()}: main period {dominant:.2f} s")
        axis.plot(dominant, 1.0, "o", color=color, alpha=0.6)
    axis.set_xscale("log")
    axis.set_xlabel("Period [s]")
    axis.set_ylabel("Normalized amplitude")
    axis.set_ylim(0.0, 1.1)
    axis.grid(color="gray", linewidth=0.5, which="both")
    axis.legend(fontsize=8)
    figure.suptitle(f"{title}\nSpectrum of the theoretical pitch{note}", fontsize=9)
    return _save(figure, path)


def save_angle_analysis(times, theoretical, analysis_mask, coarse_times, coarse, sampling_period,
                        title, folder, mask_label="fly phase"):
    """Save the three analysis figures in `folder` and return their paths.

    `analysis_mask` flags the shoot points (the fly phase) used by the dispersion and the
    spectrum; the timeline always shows the whole mission.
    """
    folder = Path(folder)
    mask = np.asarray(analysis_mask, dtype=bool)
    times = np.asarray(times, dtype=float)
    coarse_times = np.asarray(coarse_times, dtype=float)
    in_span = np.ones(len(coarse_times), dtype=bool)
    if mask.any():
        in_span = (coarse_times >= times[mask].min()) & (coarse_times <= times[mask].max())
    fly_theoretical = {k: np.asarray(v, float)[mask] for k, v in theoretical.items()}
    fly_coarse = {k: np.asarray(v, float)[in_span] for k, v in coarse.items()}
    title = f"{title} - {mask_label}"
    return [
        plot_angles_timeline(times[mask], fly_theoretical, coarse_times[in_span], fly_coarse,
                             title, folder / "Angles analysis.png"),
        plot_angles_dispersion(fly_theoretical, fly_coarse, title,
                               folder / "Angles analysis dispersion.png"),
        plot_angles_spectrum(theoretical, mask, sampling_period, title,
                             folder / "Angles analysis spectrum.png", mask_label),
    ]
