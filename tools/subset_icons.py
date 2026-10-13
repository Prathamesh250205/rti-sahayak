"""Cut the Material Symbols icon font down to the icons the site uses.

The full variable font is 1.1 MB and was downloaded on every page; the
subset (regular weight, unfilled - nothing uses the other styles) is a few
KB. Any word in the templates/JS that matches an icon name is kept, so a
new icon in the markup just needs a re-run:

    pip install -r requirements-dev.txt
    python -m tools.subset_icons

It rewrites web/static/vendor/fonts/material-symbols-<hash>.woff2 and points
web/static/vendor/fonts.css at it (new name = safe to cache forever).
"""
import glob
import hashlib
import io
import os
import re

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FULL = os.path.join(os.path.dirname(__file__), "fonts", "material-symbols-outlined-full.woff2")
FONTS_DIR = "web/static/vendor/fonts"
FONTS_CSS = "web/static/vendor/fonts.css"


def ligatures(font) -> dict:
    """icon name -> glyph name, read from the font's GSUB ligatures."""
    rev = {glyph: chr(code) for code, glyph in font.getBestCmap().items()}
    out = {}
    for lookup in font["GSUB"].table.LookupList.Lookup:
        for st in lookup.SubTable:
            st = getattr(st, "ExtSubTable", st)
            for first, ligs in getattr(st, "ligatures", {}).items():
                for lig in ligs:
                    name = rev.get(first, "") + "".join(rev.get(c, "") for c in lig.Component)
                    out[name] = lig.LigGlyph
    return out


def main():
    font = TTFont(FULL)
    names = ligatures(font)
    words = set()
    for path in glob.glob("web/templates/**/*.html", recursive=True) + glob.glob("web/static/js/*.js"):
        words |= set(re.findall(r"[a-z][a-z0-9_]+", open(path, encoding="utf-8").read()))
    used = sorted(names.keys() & words)

    font = instancer.instantiateVariableFont(font, {"FILL": 0, "wght": 400})
    opts = subset.Options(flavor="woff2", layout_features=["*"], layout_closure=False)
    sub = subset.Subsetter(opts)
    # The letters are the ligature input; without layout closure only the
    # listed icon glyphs survive, and ligatures to anything else are dropped.
    sub.populate(glyphs=[names[n] for n in used], text="abcdefghijklmnopqrstuvwxyz0123456789_")
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    data = buf.getvalue()

    name = f"material-symbols-{hashlib.sha256(data).hexdigest()[:10]}.woff2"
    for old in glob.glob(os.path.join(FONTS_DIR, "material-symbols-*.woff2")):
        os.remove(old)
    with open(os.path.join(FONTS_DIR, name), "wb") as f:
        f.write(data)
    css = open(FONTS_CSS, encoding="utf-8").read()
    css = re.sub(r'url\("\./fonts/(material-symbols-[0-9a-f]+|kJEPBv[^"]+)\.woff2"\)', f'url("./fonts/{name[:-6]}.woff2")', css)
    open(FONTS_CSS, "w", encoding="utf-8").write(css)
    print(f"{len(used)} icons -> {name} ({len(data) // 1024} KB)")


if __name__ == "__main__":
    main()
