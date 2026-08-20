"""Render a drafted RTI application as a submission-ready PDF."""
from fpdf import FPDF

DISCLAIMER = (
    "Drafted with AI assistance from retrieved RTI Act, 2005 text. This is an informational "
    "drafting aid, not legal advice - verify the public authority, current fees, and all facts "
    "before submitting."
)

# Core PDF fonts (Helvetica) only support Latin-1. LLM output sometimes contains
# "smart" typography (em dashes, curly quotes, narrow no-break spaces) outside that
# range - normalize those to plain ASCII equivalents rather than crashing or
# bundling a Unicode font just for this.
_CHAR_REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "‑": "-",
    " ": " ", " ": " ", "…": "...",
}


def _sanitize(text: str) -> str:
    for bad, good in _CHAR_REPLACEMENTS.items():
        text = text.replace(bad, good)
    # Anything else outside Latin-1 (core font's range) would raise on render -
    # drop it rather than crash the export.
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build_pdf(application_text: str) -> bytes:
    """Render the application text as a PDF and return its bytes."""
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(left=20, top=18, right=20)
    pdf.add_page()

    pdf.set_font("Helvetica", style="B", size=13)
    pdf.multi_cell(0, 8, "APPLICATION UNDER THE RIGHT TO INFORMATION ACT, 2005", align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", size=11)
    for paragraph in _sanitize(application_text).split("\n\n"):
        pdf.multi_cell(0, 6.5, paragraph.strip())
        pdf.ln(4)

    # Disable auto page break for the footer draw itself - otherwise fpdf treats
    # positioning this close to the bottom margin as needing a fresh page.
    pdf.set_auto_page_break(auto=False)
    pdf.set_y(-22)
    pdf.set_font("Helvetica", style="I", size=8)
    pdf.set_text_color(110, 110, 110)
    pdf.multi_cell(0, 4, _sanitize(DISCLAIMER), align="C")

    return bytes(pdf.output())
