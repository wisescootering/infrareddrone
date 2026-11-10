"""The user manual (help/irdrone_help.tex) as a page of the GitHub Pages site.

The LaTeX manual stays the single source. This script:
1. expands the manual's own macros (\\figureIRD, \\figurePaireIRD, \\bouton, \\og/\\fg, ...)
   into plain LaTeX that pandoc understands,
2. converts the document body to Markdown with pandoc,
3. adapts pandoc's Markdown to MkDocs (Python-Markdown): every \\label becomes an
   anchor of the page (``manual/#btn:step4_stop``: the software's contextual help
   links there), cross-references show the title of the section they point to,
   figures are numbered as in the PDF,
4. copies the images (PDF figures rendered to PNG, photos reduced for the web).

Needs pandoc (apt install pandoc) and PyMuPDF (PDF figures).
Usage: called by website/prepare.py, or  python website/manual.py OUT_DIR
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEX = ROOT / "help" / "irdrone_help_en.tex"   # the web manual is in English
IMAGES = ROOT / "help" / "images"
PAGE = "manual/index.md"   # served at /manual/, its images next to it (raw HTML <img> paths are not rewritten)
IMAGE_DIR = "manual-images"
PDF_URL = "https://github.com/wisescootering/infrareddrone/releases/download/help-latest/irdrone_help_en.pdf"
PDF_URL_FR = "https://github.com/wisescootering/infrareddrone/releases/download/help-latest/irdrone_help.pdf"
MAX_SIDE = 1600          # photos reduced for the web
PDF_DPI = 150            # vector figures rendered at this resolution

PANDOC_TO = ("markdown-grid_tables-multiline_tables-simple_tables-fenced_divs-native_divs"
             "-bracketed_spans-native_spans-raw_attribute-link_attributes-inline_code_attributes"
             "-fenced_code_attributes-smart")


# ----------------------------------------------------------------------------- LaTeX side
def braced(text, i):
    """Content of the {...} group starting at text[i] == '{' and the index after it."""
    assert text[i] == "{", text[i:i + 30]
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "\\":
            continue
        if c == "{" and text[j - 1] != "\\":
            depth += 1
        elif c == "}" and text[j - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
    raise ValueError("unbalanced braces at " + text[i:i + 60])


def args(text, i, n, optional=False):
    """[optional] then n {arguments} starting at text[i]."""
    opt = None
    while text[i].isspace():
        i += 1
    if optional and text[i] == "[":
        j = text.index("]", i)
        opt, i = text[i + 1:j], j + 1
    out = []
    for _ in range(n):
        while text[i].isspace():
            i += 1
        value, i = braced(text, i)
        out.append(value)
    return opt, out, i


def expand(text, name, n, optional, make):
    """Replace every \\name[opt]{a1}..{an} by make(opt, [a1..an])."""
    pattern = re.compile(r"\\" + name + r"(?![A-Za-z])")
    while True:
        m = pattern.search(text)
        if m is None:
            return text
        opt, values, end = args(text, m.end(), n, optional)
        text = text[:m.start()] + make(opt, values) + text[end:]


class Images:
    """Finds the manual's images (same rules as \\figureIRD) and copies them for the web."""

    def __init__(self, out_dir: Path):
        self.out = out_dir / IMAGE_DIR
        self.out.mkdir(parents=True, exist_ok=True)

    def find(self, name):
        for candidate in (name, name + ".png", name + ".jpg", name + ".jpeg", name + ".pdf"):
            if (IMAGES / candidate).is_file():
                return IMAGES / candidate
        return None

    def web(self, name):
        """Site path of the image, or None if it is missing."""
        src = self.find(name)
        if src is None:
            return None
        if src.suffix.lower() == ".pdf":
            dst = self.out / (src.stem + ".png")
            import pymupdf
            with pymupdf.open(src) as doc:
                doc[0].get_pixmap(dpi=PDF_DPI).save(dst)
        else:
            dst = self.out / src.name
            try:
                from PIL import Image
                with Image.open(src) as img:
                    if max(img.size) > MAX_SIDE:
                        img.thumbnail((MAX_SIDE, MAX_SIDE))
                        img.save(dst)
                    else:
                        shutil.copy2(src, dst)
            except ImportError:
                shutil.copy2(src, dst)
        return f"{IMAGE_DIR}/{dst.name}"


def latex_body(images: Images) -> str:
    text = TEX.read_text(encoding="utf-8")
    body = text[text.index(r"\begin{document}") + len(r"\begin{document}"):text.index(r"\end{document}")]
    body = re.sub(r"(?<!\\)%.*", "", body)                                  # comments
    body = re.sub(r"\\begin\{titlepage\}.*?\\end\{titlepage\}", "", body, flags=re.S)
    body = re.sub(r"\\legacybegin\{([^}]*)\}", r"\n\nLEGACYBEGIN \1\n\n", body)   # collapsible legacy sections
    body = body.replace(r"\legacyend", "\n\nLEGACYEND\n\n")
    body = body.replace(r"\tableofcontents", "").replace(r"\appendix", "")

    def picture(name, width="0.8"):
        path = images.web(name)
        if path is None:
            return r"\emph{(missing image: " + name.replace("_", r"\_") + ")}"
        return r"\includegraphics{" + path + "}"

    def figure(opt, a):
        name, caption, width = a
        label = r"\label{" + opt + "}" if opt else ""
        return (r"\begin{figure}" + picture(name, width) + r"\caption{" + caption + "}" + label
                + r"\end{figure}")

    def pair(_opt, a):
        label, left, cap_left, right, cap_right, caption = a
        # one web figure per image, the pair caption on the second one; (a)/(b) as in the PDF
        return (r"\begin{figure}" + picture(left) + r"\caption{(a) " + cap_left + "}" + r"\label{" + label
                + r"_avant}\end{figure}" + r"\begin{figure}" + picture(right) + r"\caption{(b) " + cap_right
                + " --- " + caption + "}" + r"\label{" + label + r"}\end{figure}"
                + r"\hypertarget{" + label + r"_apres}{}")

    body = expand(body, "figureIRD", 3, True, figure)
    body = expand(body, "figurePaireIRD", 6, False, pair)
    body = expand(body, "bouton", 1, False, lambda _o, a: r"\texttt{" + a[0] + "}")
    body = expand(body, "todo", 1, False, lambda _o, a: "")
    body = expand(body, "subref", 1, False,
                  lambda _o, a: "(a)" if a[0].endswith("_avant") else "(b)" if a[0].endswith("_apres") else "")
    # footnote reused by number in the PDF (\textsuperscript{\ref{fn:...}}): not on the web
    body = re.sub(r"\\textsuperscript\{\\ref\{fn:[^}]*\}\}", "", body)
    body = re.sub(r"\\og(\{\s*\})?\s*", "« ", body)
    body = re.sub(r"\s*\\fg(\{\s*\})?", " »", body)
    body = body.replace(r"\oe ", "œ").replace(r"\oe{}", "œ").replace(r"\oe", "œ")
    body = re.sub(r"\\textdegree(\{\})?", "°", body)     # pandoc drops it
    return "\\documentclass{report}\n\\usepackage{amsmath,amssymb}\n\\begin{document}\n" + body + "\n\\end{document}\n"


# ----------------------------------------------------------------------------- Markdown side
HEADING = re.compile(r"^(#{1,6}) (.*?)\s*\{#([^\s}]+)[^}]*\}\s*$", re.M)
REF = re.compile(r'(§\s*)?<a href="#([^"]+)" data-reference-type="ref" data-reference="[^"]*">([^<]*)</a>')
FIGURE = re.compile(r"!\[(.*?)\]\(([^)\s]+)\)\{#([^\s}]+)[^}]*\}", re.S)


def plain(title):
    """Heading text without Markdown markup (for link texts)."""
    title = re.sub(r"`([^`]*)`", r"\1", title)
    title = re.sub(r"[*_]{1,2}([^*_]+)[*_]{1,2}", r"\1", title)
    return re.sub(r"\s+", " ", title).strip().rstrip(".")


def to_mkdocs(md: str) -> str:
    titles = {anchor: plain(title) for _h, title, anchor in HEADING.findall(md)}
    figures = {}
    for m in REF.finditer(md):                      # pandoc numbers figures as LaTeX does (chapter.n)
        if m.group(2).startswith("fig:") or m.group(2) not in titles:
            figures.setdefault(m.group(2), m.group(3))

    def ref(m):
        section, anchor, number = m.group(1), m.group(2), m.group(3)
        if anchor in titles:
            return f"[{titles[anchor]}](#{anchor})"
        return f"{section or ''}[{number}](#{anchor})"

    md = REF.sub(ref, md)
    # legacy sections: collapsed (md_in_html), opened by website/javascripts/legacy.js when a link points inside
    md = re.sub(r"^LEGACYBEGIN (.*)$", r'<details class="legacy" markdown="1">\n<summary>\1</summary>', md, flags=re.M)
    md = md.replace("LEGACYEND", "</details>")

    def fig(m):
        caption, src, anchor = m.group(1), m.group(2), m.group(3)
        number = figures.get(anchor)
        caption_text = re.sub(r"\s+", " ", caption).strip()
        lead = f"**Figure {number}.** " if number else ""
        return (f'<figure id="{anchor}" markdown>\n![{plain(caption_text)}]({src})\n'
                f"<figcaption markdown>{lead}{caption_text}</figcaption>\n</figure>")

    md = FIGURE.sub(fig, md)
    # pandoc writes figures as HTML: number the ones the text refers to, as in the PDF
    md = re.sub(r'(<figure id="([^"]+)">.*?<figcaption>)',
                lambda m: m.group(1) + (f"<strong>Figure {figures[m.group(2)]}.</strong> "
                                        if m.group(2) in figures else ""), md, flags=re.S)
    # equation references: MathJax numbers the equations and resolves \eqref
    md = re.sub(r'<a href="#([^"]+)" data-reference-type="eqref"[^>]*>[^<]*</a>', r"$\\eqref{\1}$", md)
    # headings: {#id .class} -> {#id} (attr_list), pandoc spans -> html anchors
    md = HEADING.sub(lambda m: f"{m.group(1)} {m.group(2)} {{#{m.group(3)}}}", md)
    md = re.sub(r"\[\]\{#([^\s}]+)[^}]*\}", r'<span id="\1"></span>', md)
    md = re.sub(r"<span id=\"([^\"]+)\"></span>", r'<span id="\1"></span>', md)
    md = hard_breaks(md)
    # display equations: a block of their own (pandoc leaves them inside the paragraph)
    def display(m):
        body = m.group(1).strip()
        if r"\label{" in body:     # numbered as in the PDF, so that \eqref resolves
            return "\n\n\\begin{equation}\n" + body + "\n\\end{equation}\n\n"
        return "\n\n$$\n" + body + "\n$$\n\n"

    md = re.sub(r"[ \t]*\$\$(.+?)\$\$[ \t]*", display, md, flags=re.S)
    md = re.sub(r"\n{3,}", "\n\n", md)
    header = (f"# User manual\n\n"
              f"!!! info \"PDF version\"\n    The same manual as a PDF, rebuilt on every change: "
              f"[irdrone_help_en.pdf]({PDF_URL}) (in French: [irdrone_help.pdf]({PDF_URL_FR})). "
              f"In the software, press F1 over a button to open this page at the section of that button.\n\n")
    return header + md


def hard_breaks(md: str) -> str:
    """pandoc ends a line with a single backslash for a line break: <br> outside the maths
    (where \\\\ is a LaTeX line end); after a display equation, a new paragraph."""
    lines, in_math = [], False
    for line in md.split("\n"):
        toggles = line.count("$$")
        ends_math = in_math and toggles % 2 == 1
        if line.endswith("\\") and not line.endswith("\\\\"):
            if ends_math or (not in_math and line.rstrip("\\").endswith("$$")):
                line = line[:-1] + "\n"                 # equation closed: new paragraph
            elif not in_math:
                line = line[:-1] + "<br>"
        if toggles % 2 == 1:
            in_math = not in_math
        lines.append(line)
    return "\n".join(lines)


def build(out_dir: Path) -> Path:
    """Write out_dir/manual/index.md (and its images); returns its path."""
    out_dir = out_dir / Path(PAGE).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    images = Images(out_dir)
    tex = out_dir / "_manual.tex"
    tex.write_text(latex_body(images), encoding="utf-8")
    md = subprocess.run(["pandoc", "-f", "latex", "-t", PANDOC_TO, "--wrap=none", "--shift-heading-level-by=1",
                         str(tex)], check=True, capture_output=True, text=True, encoding="utf-8").stdout
    tex.unlink()
    page = out_dir / Path(PAGE).name
    page.write_text(to_mkdocs(md), encoding="utf-8")
    missing = sorted(set(labels_used_by_the_software()) - set(anchors(page.read_text(encoding="utf-8"))))
    if missing:
        raise SystemExit(f"Help labels used by the software but missing from the web manual: {missing}")
    return page


def anchors(md: str):
    return set(re.findall(r"\{#([^\s}]+)\}", md)) | set(re.findall(r'id="([^"]+)"', md))


def labels_used_by_the_software():
    used = set()
    for path in (ROOT / "irdrone_wizard").glob("*.py"):
        used |= set(re.findall(r"[\"']((?:btn|ch|sec):[A-Za-z0-9_]+)[\"']", path.read_text(encoding="utf-8")))
    return used


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "website" / "build" / "src"))
