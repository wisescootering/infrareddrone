# -*- coding: utf-8 -*-
"""Cree help/images_light a partir de help/images (images reduites pour la version legere).

- PNG / JPEG : reduits a MAX_SIDE pixels sur le plus grand cote (jamais agrandis),
  meme nom et meme extension que l'original (le .tex n'a donc pas a changer).
- PDF : copies telles quelles.
- Autres fichiers (.dng, .pptx, .txt, ...) : ignores.
- Incremental : une image n'est reconvertie que si l'original est plus recent.
- Les originaux ne sont jamais modifies.

Usage : python make_images_light.py [--max-side 1600] [--force]
"""
import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
SRC = HERE / "images"
DST = HERE / "images_light"
JPEG_QUALITY = 85

Image.MAX_IMAGE_PIXELS = None  # les grandes orthophotos depassent la limite par defaut


def convert(src: Path, dst: Path, max_side: int) -> None:
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        if src.suffix.lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(dst, "JPEG", quality=JPEG_QUALITY, optimize=True)
        else:
            img.save(dst, "PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-side", type=int, default=1600, help="plus grand cote en pixels")
    parser.add_argument("--force", action="store_true", help="reconvertit tout")
    args = parser.parse_args()

    if not SRC.is_dir():
        raise SystemExit(f"Dossier introuvable : {SRC}")
    DST.mkdir(exist_ok=True)

    done = skipped = 0
    for src in sorted(SRC.iterdir()):
        ext = src.suffix.lower()
        if not src.is_file() or ext not in (".png", ".jpg", ".jpeg", ".pdf"):
            continue
        dst = DST / src.name
        if not args.force and dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            skipped += 1
            continue
        try:
            if ext == ".pdf":
                shutil.copy2(src, dst)
            else:
                convert(src, dst, args.max_side)
                shutil.copystat(src, dst)  # garde la date de l'original pour l'incremental
        except Exception as error:
            print(f"  ECHEC {src.name} : {error}")
            continue
        print(f"  {src.name} : {src.stat().st_size / 1e6:.1f} Mo -> {dst.stat().st_size / 1e6:.1f} Mo")
        done += 1

    # Supprime les images light dont l'original a disparu
    for dst in DST.iterdir():
        if dst.is_file() and not (SRC / dst.name).exists():
            dst.unlink()
            print(f"  supprime (original absent) : {dst.name}")

    total = sum(f.stat().st_size for f in DST.iterdir() if f.is_file()) / 1e6
    print(f"{done} converties, {skipped} a jour. Taille de images_light : {total:.1f} Mo")


if __name__ == "__main__":
    main()
