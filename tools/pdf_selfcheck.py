"""Self-check for export/pdf_writer.py (no network, no LLM).

Fails if the embedded fonts go missing, characters get dropped or replaced,
Devanagari stops using its font, or long letters stop paginating cleanly.
Needs pymupdf (requirements-dev.txt). Run: python -m tools.pdf_selfcheck
"""
import json

import pymupdf

from export.pdf_writer import DISCLAIMER, build_pdf


def main():
    english = json.load(open("web/fixtures/demo_draft.json", encoding="utf-8"))["application_text"]
    english += "\n\nA road‑repair record — “quoted” …"
    doc = pymupdf.open(stream=build_pdf(english), filetype="pdf")
    text = "".join(p.get_text() for p in doc)
    fonts = {f[3].split("+")[-1] for p in doc for f in p.get_fonts()}
    assert {"Inter", "InterBold"} <= fonts, fonts
    assert "road-repair" in text and "—" in text and "“quoted”" in text, "punctuation dropped"
    assert "?" not in text.replace("?", "", english.count("?")), "characters replaced with '?'"

    hindi = build_pdf("सूचना का अधिकार अधिनियम, 2005 की धारा 6(1) के अंतर्गत आवेदन। शुल्क ₹10 संलग्न है।")
    hdoc = pymupdf.open(stream=hindi, filetype="pdf")
    assert any("NotoSansDevanagari" in f[3] for f in hdoc[0].get_fonts()), "Devanagari font not used"
    assert "₹10" in hdoc[0].get_text()

    long = pymupdf.open(stream=build_pdf((english + "\n\n") * 4), filetype="pdf")
    assert long.page_count > 1
    assert DISCLAIMER.split(" - ")[0][:40] in long[-1].get_text().replace("\n", " ")
    for page in long:  # nothing drawn into the side margins
        for x0, _, x1, *_ in page.get_text("blocks"):
            assert x0 >= 20 and x1 <= page.rect.width - 20, (x0, x1)
    print(f"pdf self-check: all passed ({long.page_count}-page long letter)")


if __name__ == "__main__":
    main()
