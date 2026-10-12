"""Render a drafted RTI application as a submission-ready PDF."""
from pathlib import Path

from fpdf import FPDF

DISCLAIMER = (
    "Drafted with AI assistance from retrieved RTI Act, 2005 text. This is an informational "
    "drafting aid, not legal advice - verify the public authority, current fees, and all facts "
    "before submitting."
)

# Same typeface as the website. Inter covers English (curly quotes, dashes and
# all); it has no Devanagari, so Hindi/Marathi text - and the rupee sign -
# fall back to Noto Sans Devanagari. Both are SIL OFL, licenses alongside.
FONT_DIR = Path(__file__).parent / "fonts"
BODY_PT = 11.5
LINE_MM = 6.2          # ~1.5 line spacing at 11.5pt
PARAGRAPH_GAP_MM = 3.5
# Hyphen variants the LLM sometimes emits that neither font has a glyph for -
# fpdf would silently drop them ("road‑repair" -> "roadrepair").
_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "­": ""})


def build_pdf(application_text: str) -> bytes:
    """Render the application text as a PDF and return its bytes."""
    pdf = FPDF(format="A4")
    pdf.add_font("Inter", "", FONT_DIR / "Inter-Regular.ttf")
    pdf.add_font("Inter", "B", FONT_DIR / "Inter-Bold.ttf")
    pdf.add_font("NotoDeva", "", FONT_DIR / "NotoSansDevanagari-Regular.ttf")
    pdf.add_font("NotoDeva", "B", FONT_DIR / "NotoSansDevanagari-Bold.ttf")
    pdf.set_fallback_fonts(["NotoDeva"])
    # Devanagari needs shaping (conjuncts, vowel signs placed correctly).
    pdf.set_text_shaping(True)

    pdf.set_auto_page_break(auto=True, margin=24)
    pdf.set_margins(left=22, top=20, right=22)
    pdf.add_page()

    pdf.set_font("Inter", style="B", size=14)
    pdf.multi_cell(0, 7.5, "APPLICATION UNDER THE RIGHT TO INFORMATION ACT, 2005", align="C")
    pdf.ln(6)

    # Left-aligned, not fpdf's default justification - justified text in a
    # letter stretches word gaps unevenly.
    pdf.set_font("Inter", size=BODY_PT)
    for paragraph in application_text.translate(_HYPHENS).split("\n\n"):
        pdf.multi_cell(0, LINE_MM, paragraph.strip(), align="L")
        pdf.ln(PARAGRAPH_GAP_MM)

    # Disable auto page break for the footer draw itself - otherwise fpdf treats
    # positioning this close to the bottom margin as needing a fresh page.
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(-20)
    pdf.set_font("Inter", size=8.5)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 4.2, DISCLAIMER, align="C")

    return bytes(pdf.output())
