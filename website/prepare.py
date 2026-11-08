"""Assemble the MkDocs sources of the GitHub Pages site from the repository docs.

Nothing is duplicated: the readme and docs stay the single source, this script copies
them (and the illustrations they use) into website/build/src and fixes their links:
- links between included Markdown files point to the matching site page,
- images are copied next to the pages,
- links to any other repository file point to it on GitHub.

Usage: python website/prepare.py   then   mkdocs build -f website/mkdocs.yml
"""
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "website" / "build" / "src"
GITHUB = "https://github.com/wisescootering/infrareddrone"

# Repository file -> site page. Keep in sync with the nav of mkdocs.yml.
PAGES = {
    "readme.md": "index.md",
    "calibration/readme.md": "calibration.md",
    "docs/ODM_MAPPING_PREPARATION.md": "odm-mapping.md",
    "docs/IGN_IMAGE_REGISTRATION.md": "ign-registration.md",
}
MATHJAX_CONFIG = """window.MathJax = {
  tex: {inlineMath: [["\\\\(", "\\\\)"]], displayMath: [["\\\\[", "\\\\]"]],
        processEscapes: true, processEnvironments: true, tags: "ams"},
  options: {ignoreHtmlClass: ".*|", processHtmlClass: "arithmatex"}
};
document$.subscribe(() => { MathJax.typesetPromise && MathJax.typesetPromise(); });
"""
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}

# Markdown links/images ](target) and HTML src="target" / href="target".
LINK = re.compile(r'(\]\(\s*<?|(?:src|href)=")([^)"\s>]+)')


def _repo_path(target, source):
    """Repository-relative path of a local link target, or None if it is not a repo file."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
        return None  # URL, mailto:, in-page anchor
    if target.startswith("/"):
        candidates = [ROOT / target.lstrip("/")]
    else:
        # Some links are written relative to the repository root instead of the file.
        candidates = [(ROOT / source).parent / target, ROOT / target]
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate.exists() and ROOT in candidate.parents:
            return candidate.relative_to(ROOT).as_posix()
    return None


def _rewrite(match, source):
    prefix, target = match.groups()
    path, _, anchor = target.partition("#")
    anchor = "#" + anchor if anchor else ""
    if not path:
        return match.group(0)
    repo_path = _repo_path(path, source)
    if repo_path is None:
        return match.group(0)
    if repo_path in PAGES:
        return prefix + PAGES[repo_path] + anchor
    if Path(repo_path).suffix.lower() in IMAGE_SUFFIXES:
        destination = OUT / "assets" / repo_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / repo_path, destination)
        return prefix + "assets/" + repo_path
    kind = "tree" if (ROOT / repo_path).is_dir() else "blob"
    return f"{prefix}{GITHUB}/{kind}/master/{repo_path}{anchor}"


def main():
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    for source, page in PAGES.items():
        text = (ROOT / source).read_text(encoding="utf-8")
        text = LINK.sub(lambda m: _rewrite(m, source), text)
        (OUT / page).write_text(text, encoding="utf-8")
    # the user manual, converted from the LaTeX source (English version)
    import manual
    manual.build(OUT)
    js = OUT / "javascripts"
    js.mkdir(exist_ok=True)
    (js / "mathjax.js").write_text(MATHJAX_CONFIG, encoding="utf-8")
    print(f"Site sources written to {OUT}")


if __name__ == "__main__":
    main()
