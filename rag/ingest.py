"""One-shot CLI script: chunk the PDFs in data/corpus/ and embed them into Chroma.

Run this whenever the corpus changes:
    python -m rag.ingest
"""
import bisect
import os
import re

import chromadb
import pymupdf as fitz
from chromadb.utils import embedding_functions

CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "corpus")
CHROMA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "chroma")
# chromadb's ONNXMiniLM_L6_V2 defaults to caching its model under
# Path.home()/.cache, outside the project directory. On Render's native
# Python runtime, buildCommand (which triggers this download during
# ingest) and startCommand aren't documented to guarantee the same $HOME
# persists between them - redirecting into the project directory removes
# that ambiguity: whatever the build writes here is guaranteed to ship
# with the deploy, the same way data/chroma already does. Must match
# rag/retriever.py's override exactly, or a build-time download here
# won't be found by the runtime process.
ONNX_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "onnx_model_cache")
COLLECTION_NAME = "rti_corpus"

# A section becomes a single chunk when its full text is <= CHUNK_MAX_CHARS.
# Longer sections are sub-split into ~CHUNK_TARGET_CHARS pieces (all carrying
# that section's label) with a small overlap so context isn't lost at the seam.
CHUNK_TARGET_CHARS = 1200
CHUNK_MAX_CHARS = 1800
CHUNK_OVERLAP_CHARS = 150

# Matches an operative section heading like:
#   "5. Designation of Public Information Officers.-(I) Every public authority..."
# i.e. a leading section number, a Title Case heading, then a dash. The heading
# text may contain an apostrophe (OCR sometimes corrupts a letter into one,
# e.g. section 18's "'Unctions" for "Functions") and the closing period before
# the dash is optional (OCR sometimes drops it entirely, e.g. section 14's
# "Commissioner-CO" for "Commissioner.-(1)"). Deliberately does NOT require
# anything after the dash (an earlier version required an immediate "(" -
# that excluded single-sentence sections with no subsection marker at all,
# e.g. "31. Repeal.-The Freedom of Information Act ... is hereby repealed.",
# and sections with explanatory prose before their first "(a)"/"(1)", e.g.
# "2. Definitions.-In this Act, unless the context otherwise requires,-(a)...").
# Table-of-contents lines (e.g. "2. Definitions.") and Schedule list items
# (e.g. "16.Special Branch (CID)...") still don't match: TOC/heading lines
# have no dash at all, and Schedule entries have no space after the period.
SECTION_HEADING_RE = re.compile(
    r"(?<!\d)(\d{1,3}[A-Z]?)\.\s+[A-Z][a-zA-Z ,'\-]{3,80}?\.?\s*[-–—]"
)

# This exact phrase is unique to this specific RTI_Act_2005.pdf and marks
# where the Act's actual legal text begins - the long title ("An Act to
# provide for...") immediately followed by the enacting formula and the
# WHEREAS clauses (the Preamble). Everything before this anchor (title
# page, Ministry header, preface, table of contents) carries no legal
# content and is dropped from the corpus entirely rather than ingested as
# unlabeled "unknown" text: a bare table-of-contents chunk repeats every
# section title in the Act, which makes it similar enough to almost any
# RTI query to clear the grounding threshold on its own - a real
# retrieval-quality bug, not a cosmetic one, since it then competes with
# genuine section text in every query.
#
# If this corpus PDF is ever swapped for a different edition, this anchor
# will very likely no longer match - see the RuntimeError in ingest()
# below. That's deliberate: a silent fallback here would silently
# reintroduce the exact bug this constant fixes.
PREAMBLE_ANCHOR = "An Act to provide for"


def extract_pages(pdf_path: str) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for a PDF, 1-indexed pages."""
    doc = fitz.open(pdf_path)
    pages = [(i + 1, page.get_text()) for i, page in enumerate(doc)]
    doc.close()
    return pages


def build_document(pages: list[tuple[int, str]]) -> tuple[str, list[tuple[int, int]]]:
    """Concatenate page texts into one string; return (text, [(char_offset, page_num), ...])."""
    parts = []
    offsets = []
    pos = 0
    for page_num, text in pages:
        offsets.append((pos, page_num))
        parts.append(text)
        pos += len(text)
    return "".join(parts), offsets


def find_section_markers(text: str) -> list[tuple[int, str]]:
    """Return [(char_offset, section_number), ...] for each detected section heading."""
    return [(m.start(1), m.group(1)) for m in SECTION_HEADING_RE.finditer(text)]


def label_for_offset(offset: int, markers: list[tuple[int, int | str]], default) -> str:
    """Return the label of the last marker at or before offset, or default if none."""
    positions = [m[0] for m in markers]
    idx = bisect.bisect_right(positions, offset) - 1
    return markers[idx][1] if idx >= 0 else default


def _split_oversized_segment(segment_text: str, target: int, overlap: int):
    """Yield (start, end) char spans covering an over-long segment in pieces of
    up to ~target chars each, breaking at the nearest following whitespace so
    words aren't cut mid-token, with a small overlap between consecutive spans.
    """
    n = len(segment_text)
    if n <= target:
        yield 0, n
        return
    start = 0
    while start < n:
        end = min(start + target, n)
        if end < n:
            next_space = segment_text.find(" ", end)
            if next_space != -1 and next_space - end < 100:
                end = next_space
        yield start, end
        if end >= n:
            break
        start = max(end - overlap, start + 1)


# Section 7 only (see _split_section_7_at_subsections) - matches a TRUE
# top-level sub-section start like "(6)" or "(4) Where", never the far more
# common inline cross-reference to some other sub-section mid-sentence
# ("sub-section (2) of section 5", "sub-sections (1) and (5) of section 7").
# The bare pattern \(\d{1,2}\) can't tell those apart; empirically, in this
# Act's actual text, a true start is always immediately followed by the
# capitalized first word of a new sentence ("(4) Where access...", or with
# an OCR-dropped space: "(6)Notwithstanding..."), while a cross-reference is
# always followed by a lowercase continuation word or punctuation ("(2) of
# section 5", "(6), pay such fee"). Verified against every one of Section
# 7's 14 numeric-paren occurrences (8 true starts, 6 cross-references) before
# relying on this - see the "targeted Section 7(6) retrieval fix" report.
_SUBSECTION_START_RE = re.compile(r"\(\d{1,2}\)\s*(?=[A-Z])")


def _split_section_7_at_subsections(segment_text: str) -> list[tuple[int, int]]:
    """Section 7 (Disposal of request) ONLY - one chunk per top-level
    sub-section, (1) through (9), instead of the general splitter's blind
    ~1200-char windows.

    Investigation found the general splitter's arbitrary windows put the
    single most citizen-relevant sentence in Section 7 - sub-section (6),
    "the information shall be provided free of charge where a public
    authority fails to comply with the time limits" - inside the same chunk
    as unrelated sub-section (4)/(5) content (disability-access assistance,
    printed/electronic-format fee mechanics). A chunk's embedding is an
    average over everything in it, so (6)'s own topic was diluted by that
    unrelated text: it ranked 46th of 78 chunks for a natural "what happens
    if the PIO misses the deadline" question - unreachable at any sane
    top_k, not merely ranked low. Splitting one-sub-section-per-chunk
    removes that dilution entirely, for every sub-section of Section 7, not
    only (6) - most of them are already well under CHUNK_TARGET_CHARS on
    their own, so this doesn't fragment anything that needed to stay whole.

    Deliberately scoped to Section 7 alone via chunk_document()'s dispatch,
    not a general chunking strategy - _split_oversized_segment (every other
    section) is completely untouched by this function's existence.
    """
    starts = [m.start() for m in _SUBSECTION_START_RE.finditer(segment_text)]
    boundaries = sorted({0, *(s for s in starts if s > 0), len(segment_text)})
    return [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]


def chunk_document(
    text: str,
    page_offsets: list[tuple[int, int]],
    section_markers: list[tuple[int, str]],
    preamble_start: int,
):
    """Yield (chunk_text, page_num, section_number) chunks split on section
    boundaries - each chunk belongs to exactly one section, by construction,
    never inferred from a midpoint. A section's full text becomes a single
    chunk when it's <= CHUNK_MAX_CHARS; a longer section is sub-split into
    ~CHUNK_TARGET_CHARS pieces (see _split_oversized_segment) that all carry
    that same section label.

    preamble_start: char offset of PREAMBLE_ANCHOR in `text` (see that
    constant). Everything before it is title page/Ministry header/preface/
    table of contents with no legal content - text[:preamble_start] is
    simply never visited, so it's dropped rather than yielded as a chunk.
    The span from preamble_start up to the first real section heading is
    yielded as section="Preamble".
    """
    if not text:
        return

    boundaries = [(preamble_start, "Preamble")] + list(section_markers)
    for i, (start, section) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        segment = text[start:end]
        if not segment.strip():
            continue

        if len(segment) <= CHUNK_MAX_CHARS:
            spans = [(0, len(segment))]
        elif section == "7":
            # Targeted fix, not a general chunking-strategy change - see
            # _split_section_7_at_subsections. Every other oversized section
            # still goes through _split_oversized_segment exactly as before.
            spans = _split_section_7_at_subsections(segment)
        else:
            spans = list(_split_oversized_segment(segment, CHUNK_TARGET_CHARS, CHUNK_OVERLAP_CHARS))

        for sub_start, sub_end in spans:
            chunk_text_str = segment[sub_start:sub_end].strip()
            if not chunk_text_str:
                continue
            page_num = label_for_offset(start + sub_start, page_offsets, default=page_offsets[0][1])
            yield chunk_text_str, page_num, section


def ingest() -> int:
    """Chunk and embed every PDF in data/corpus/. Returns the number of chunks written."""
    pdf_files = [f for f in os.listdir(CORPUS_DIR) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"No PDFs found in {CORPUS_DIR}. Add the RTI Act 2005 PDF there first.")
        return 0

    # ONNX runtime, not sentence-transformers/torch - same model
    # (all-MiniLM-L6-v2) and same output vectors, but without pulling in a
    # ~500MB PyTorch runtime just to run inference. Must match
    # rag/retriever.py's embedding function exactly, or query-time vectors
    # won't be comparable to what's stored here.
    embedding_functions.ONNXMiniLM_L6_V2.DOWNLOAD_PATH = ONNX_CACHE_DIR
    embed_fn = embedding_functions.ONNXMiniLM_L6_V2()
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    if COLLECTION_NAME in [c.name for c in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)
    collection = client.create_collection(name=COLLECTION_NAME, embedding_function=embed_fn)

    documents, metadatas, ids = [], [], []
    chunk_id = 0

    for filename in pdf_files:
        path = os.path.join(CORPUS_DIR, filename)
        print(f"Processing {filename}...")
        pages = extract_pages(path)
        full_text, page_offsets = build_document(pages)

        preamble_start = full_text.find(PREAMBLE_ANCHOR)
        if preamble_start == -1:
            raise RuntimeError(
                f"PREAMBLE_ANCHOR {PREAMBLE_ANCHOR!r} not found in {filename}. "
                "This anchor is specific to the current RTI_Act_2005.pdf edition - "
                "if the corpus PDF was swapped for a different edition, update "
                "PREAMBLE_ANCHOR to match its actual long-title wording. Refusing "
                "to guess: ingesting without a verified anchor would silently drop "
                "or mislabel the front matter again."
            )

        section_markers = find_section_markers(full_text)

        for chunk_text_str, page_num, section in chunk_document(full_text, page_offsets, section_markers, preamble_start):
            documents.append(chunk_text_str)
            if section == "Preamble":
                section_label = "Preamble"
            elif section:
                section_label = f"Section {section}"
            else:
                section_label = "unknown"
            metadatas.append(
                {
                    "source": filename,
                    "page": page_num,
                    "section": section_label,
                }
            )
            ids.append(f"{filename}-c{chunk_id}")
            chunk_id += 1

    if documents:
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

    with_section = sum(1 for m in metadatas if m["section"] != "unknown")
    print(
        f"Ingested {len(documents)} chunks from {len(pdf_files)} PDF(s) into {CHROMA_DIR} "
        f"({with_section}/{len(documents)} tagged with a section number)"
    )
    return len(documents)


if __name__ == "__main__":
    ingest()
