# -*- coding: utf-8 -*-
from pathlib import Path
import cv2
import numpy as np
import re
import csv
import matplotlib.pyplot as plt
from scipy.signal import savgol_filter
from typing import Optional

# --- Chargement des images ---
def load_grayscale_image(
    path: Path,
    check_images: bool = True,
    channel: Optional[str] = None
) -> np.ndarray:
    """
    Charge une image en niveau de gris ou extrait un canal spécifique.

    Parameters
    ----------
    path : Path
        Chemin vers l'image
    check_images : bool
        Sauvegarde de l'image chargée pour vérification
    channel : str | None
        'R', 'G', 'B' pour extraire un canal, None pour convertir en gris

    Returns
    -------
    np.ndarray
        Image 2D (grayscale ou canal)
    """
    data = path.read_bytes()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)

    if img is None:
        raise ValueError(f"Image illisible : {path}")

    # Conversion en gris si channel non précisé
    if channel is None:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        # OpenCV charge BGR par défaut
        channel_idx = {'B': 0, 'G': 1, 'R': 2}.get(channel.upper(), None)
        if channel_idx is None:
            raise ValueError(f"Canal inconnu : {channel}")
        img = img[:, :, channel_idx]

    if check_images:
        debug_dir = path.parent / "check_cv2"
        debug_dir.mkdir(exist_ok=True)
        suffix = channel.upper() if channel else "GRAY"
        cv2.imwrite(str(debug_dir / f"{path.stem}_{suffix}.png"), img)

    return img


# --- extraction de la position de l'objectif (position angulaire) ---

def extract_position(filename: str) -> int:
    """
    Extrait le nombre final d'un nom de fichier de type 'XXXX123.tiff'.
    """
    name = Path(filename).stem
    match = re.search(r'(\d+)$', name)

    if not match:
        raise ValueError(f"Aucun nombre final trouvé dans '{filename}'")

    return int(match.group(1))

# --- Fonction pour mesurer la netteté ---

def focus_laplacian(img: np.ndarray) -> float:
    return cv2.Laplacian(img, cv2.CV_64F).var()

def focus_tenengrad(img: np.ndarray) -> float:
    gx = cv2.Sobel(img, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_64F, 0, 1, ksize=3)
    return np.mean(gx**2 + gy**2)

def focus_brenner(img: np.ndarray) -> float:
    diff = img[:, 2:] - img[:, :-2]
    return np.mean(diff**2)

def focus_gradient_variance(img: np.ndarray) -> float:
    gx = cv2.Sobel(img, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(img, cv2.CV_64F, 0, 1, ksize=3)
    g = np.sqrt(gx**2 + gy**2)
    return g.var()


# --- Dessin des graphes de netteté ---
def plot_focus(positions, sharpness, metric_name, suffixes, folder: Path, show=False, save=False) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(positions, sharpness, "o-", markersize=8, linewidth=2)
    ax.set_xlabel("Position")
    ax.set_ylabel("Métrique de netteté")
    ax.set_title(
        f"Netteté ({metric_name}) — images {', '.join(sorted(suffixes))}"
    )
    ax.grid(True)

    if save:
        save_focus(fig, folder, metric_name, suffixes)
    if show: plt.show()
    plt.close(fig)

def save_focus(fig, folder: Path, metric_name, suffixes) -> None:
    suffix_str = "_".join(sorted(suffixes))
    output_file = folder / f"focus_curve_{metric_name}_{suffix_str}.png"
    fig.savefig(output_file, dpi=150, bbox_inches="tight")
    print(f"Courbe sauvegardée : {output_file}")

def normalize_curve(values: np.ndarray) -> np.ndarray:
    vmin = values.min()
    vmax = values.max()
    if vmax == vmin:
        return np.zeros_like(values)
    return (values - vmin) / (vmax - vmin)

def smooth_curve(
    y: np.ndarray,
    window: int = 7,
    polyorder: int = 3
) -> np.ndarray:
    """
    Lissage Savitzky–Golay d'une courbe 1D.

    Parameters
    ----------
    y : ndarray
        Courbe à lisser
    window : int
        Taille de la fenêtre (impair, < len(y))
    polyorder : int
        Ordre du polynôme

    Returns
    -------
    ndarray
        Courbe lissée
    """
    if window >= len(y):
        window = len(y) - 1 if len(y) % 2 == 0 else len(y)
    if window % 2 == 0:
        window += 1

    return savgol_filter(y, window_length=window, polyorder=polyorder)


def detect_focus_peak(
    positions: np.ndarray,
    sharpness: np.ndarray,
    smooth_window: int = 11,
    smooth_polyorder: int = 3,
    n_interp: int = 200
):
    sharp_norm = normalize_curve(sharpness)

    # 1) Lissage uniquement pour localiser la zone
    sharp_smooth = smooth_curve(
        sharp_norm,
        window=smooth_window,
        polyorder=smooth_polyorder
    )

    idx_smooth = np.argmax(sharp_smooth)

    # 2) Voisinage
    i0 = max(idx_smooth - 1, 0)
    i1 = min(idx_smooth + 2, len(positions))

    # 3) Maximum brut dans ce voisinage
    idx_local = i0 + np.argmax(sharp_norm[i0:i1])

    # Sécurité
    if idx_local == 0 or idx_local == len(positions) - 1:
        return {
            "pos_raw": positions[idx_local],
            "pos_refined": positions[idx_local],
            "x_local": np.array([]),
            "y_local": np.array([]),
            "x_interp": np.array([]),
            "y_interp": np.array([]),
        }

    # 4) Parabole sur (i-1, i, i+1)
    x_local = positions[idx_local - 1: idx_local + 2]
    y_local = sharp_norm[idx_local - 1: idx_local + 2]

    a, b, c = np.polyfit(x_local, y_local, 2)

    # Position raffinée
    pos_refined = -b / (2 * a) if a < 0 else positions[idx_local]

    # 5) Courbe interpolée (raffinée)
    x_interp = np.linspace(x_local[0], x_local[-1], n_interp)
    y_interp = a * x_interp**2 + b * x_interp + c

    return {
        "pos_raw": positions[idx_local],
        "pos_refined": pos_refined,
        "idx_raw": idx_local,
        "idx_smooth": idx_smooth,
        "x_local": x_local,
        "y_local": y_local,
        "x_interp": x_interp,
        "y_interp": y_interp,
    }


def plot_focus_overlay(
    positions: np.ndarray,
    results: dict,
    suffixes,
    folder: Path,
    save: bool = False,
    show: bool = False,
    smooth: bool = False,
    smooth_window: int = 7,  # toujours impair
    smooth_polyorder: int = 3,
    plot_raw: bool = True
) -> None:

    """
    Trace les courbes de netteté normalisées sur un même graphe.

    Parameters
    ----------
    positions : ndarray
        Positions de mise au point (triées)
    results : dict[str, ndarray]
        Dictionnaire {nom_métrique: valeurs_de_netteté}
    suffixes : iterable[str]
        Extensions des images analysées
    folder : Path
        Dossier de sortie
    save : bool
        Sauvegarde de la figure si True
    """
    fig, ax = plt.subplots(figsize=(9, 6))

    markers = ["o", "s", "^", "D", "v", "x"]
    linestyles = ["-", "--", "-.", ":"]

    for i, (name, sharpness) in enumerate(results.items()):
        sharp_norm = normalize_curve(sharpness)
        ax.plot(
            positions,
            sharp_norm,
            linestyle=linestyles[i % len(linestyles)],
            marker=markers[i % len(markers)],
            markersize=5,
            linewidth=1.8,
            label=name
        )

        peak = detect_focus_peak(positions, sharpness)

        # parabole locale
        ax.plot(
            peak["x_interp"],
            peak["y_interp"],
            linewidth=2.5,
            alpha=0.9
        )

        # points utilisés pour l'interpolation
        ax.plot(
            peak["x_local"],
            peak["y_local"],
            "o",
            markersize=8,
            markerfacecolor="none",
            markeredgewidth=2
        )

        # position raffinée
        ax.axvline(
            peak["pos_refined"],
            linestyle=":",
            linewidth=1.8,
            label=f"{name} ≈ {peak['pos_refined']:.2f}"
        )

    ax.set_xlabel("Position")
    ax.set_ylabel("Netteté normalisée")
    ax.set_title(
        f"Comparaison des métriques de netteté — images {', '.join(sorted(suffixes))}"
    )
    ax.grid(True)
    ax.legend()
    ax.set_ylim(-0.05, 1.05)

    if save:
        suffix_str = "_".join(sorted(suffixes))
        out = folder / f"focus_comparison_normalized_{suffix_str}.png"
        fig.savefig(out, dpi=150, bbox_inches="tight")
        print(f"Comparaison sauvegardée : {out}")

    if show: plt.show()

def save_csv(positions, sharpness, folder: Path) -> None:
    csv_file = folder / "focus_results.csv"

    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Position", "Sharpness"])
        writer.writerows(zip(positions, sharpness))

    print(f"\nRésultats sauvegardés dans {csv_file}")


# --- Répertoire des images ---
folder = Path(r"G:\MOP SJCam Optics Concept\Photo\MOP_serie2")
suffixes = {"tiff"}

image_files = sorted(
    p for p in folder.iterdir()
    if p.is_file() and p.suffix[1:].lower() in suffixes
)

if not image_files:
    raise RuntimeError("Aucune image trouvée dans le dossier spécifié.")

# --- Positions ---
positions = np.array([extract_position(p.name) for p in image_files])

# --- Métriques ---
# metrics = {"laplacian": focus_laplacian,"tenengrad": focus_tenengrad,"brenner": focus_brenner,"gradvar": focus_gradient_variance,}

metrics = {"tenengrad": focus_tenengrad,}

# --- Calcul + tracé ---
results = {}

for name, metric in metrics.items():
    sharpness = []

    for f in image_files:
        img = load_grayscale_image(f, channel='G')  # channel= 'R', 'G', 'B' , None
        sharpness.append(metric(img))
        print(f'{f.name}   metric : {name}      sharpness = {metric(img):.2f}')

    sharpness = np.array(sharpness)

    # Tri selon la position
    idx = np.argsort(positions)
    pos_sorted = positions[idx]
    sharp_sorted = sharpness[idx]

    # Stockage pour l’overlay
    results[name] = sharp_sorted

    # Information utile
    best = pos_sorted[np.argmax(sharp_sorted)]
    print(f"{name:10s} → position la plus nette = {best}")

    plot_focus(
        pos_sorted,
        sharp_sorted,
        metric_name=name,
        suffixes=suffixes,
        folder=folder,
        show=False,
        save=False
    )


plot_focus_overlay(
    positions=pos_sorted,
    results=results,
    suffixes=suffixes,
    folder=folder,
    show=True,
    save=True,
    smooth=False
)

