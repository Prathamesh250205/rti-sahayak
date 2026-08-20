"""Self-host the Google Fonts used by web/templates/base.html, for offline rendering.

Reads the fonts.googleapis.com stylesheet URLs currently in base.html, fetches
each one with a desktop-browser User-Agent (Google serves woff2 only to
recognized modern browsers - anything else gets older/heavier formats),
downloads every referenced .woff2 into web/static/vendor/fonts/, rewrites each
url() to the local relative path, and writes the combined CSS to
web/static/vendor/fonts.css.

Run: python tools/fetch_fonts.py
"""
import re
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).parent.parent
BASE_HTML = BASE_DIR / "web" / "templates" / "base.html"
FONTS_DIR = BASE_DIR / "web" / "static" / "vendor" / "fonts"
OUTPUT_CSS = BASE_DIR / "web" / "static" / "vendor" / "fonts.css"

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

FONT_URL_RE = re.compile(r'url\(\s*[\'"]?(https://fonts\.gstatic\.com/[^\'")]+)[\'"]?\s*\)')


def fetch(url: str) -> bytes:
    req = Request(url, headers={"User-Agent": DESKTOP_UA})
    with urlopen(req, timeout=30) as resp:
        return resp.read()


def extract_stylesheet_urls(html: str) -> list[str]:
    hrefs = re.findall(r'href="(https://fonts\.googleapis\.com/css2\?[^"]+)"', html)
    return [h.replace("&amp;", "&") for h in hrefs]


def main():
    if not BASE_HTML.exists():
        print(f"Could not find {BASE_HTML}", file=sys.stderr)
        sys.exit(1)

    urls = extract_stylesheet_urls(BASE_HTML.read_text(encoding="utf-8"))
    if not urls:
        print("No fonts.googleapis.com stylesheet links found in base.html", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(urls)} Google Fonts stylesheet URL(s) in base.html")

    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    seen_filenames: set[str] = set()
    combined_css_parts = []

    for url in urls:
        print(f"Fetching CSS: {url}")
        css_text = fetch(url).decode("utf-8")

        def replace_url(match: re.Match) -> str:
            font_url = match.group(1)
            filename = Path(urlparse(font_url).path).name
            if filename not in seen_filenames:
                seen_filenames.add(filename)
                print(f"  Downloading {filename}")
                (FONTS_DIR / filename).write_bytes(fetch(font_url))
            return f'url("./fonts/{filename}")'

        combined_css_parts.append(FONT_URL_RE.sub(replace_url, css_text))

    OUTPUT_CSS.write_text("\n".join(combined_css_parts), encoding="utf-8")

    woff2_count = len(list(FONTS_DIR.glob("*.woff2")))
    print(f"\nSaved {woff2_count} .woff2 files to {FONTS_DIR}")
    print(f"Wrote combined CSS to {OUTPUT_CSS}")


if __name__ == "__main__":
    main()
