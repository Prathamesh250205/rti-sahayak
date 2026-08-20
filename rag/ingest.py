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


def chunk_document(text: str, page_offsets: list[tuple[int, int]], section_markers: list[tuple[int, str]]):
    """Yield (chunk_text, page_num, section_number) chunks split on section
    boundaries - each chunk belongs to exactly one section (or section=None
    for the front matter before the first detected heading), by construction,
    never inferred from a midpoint. A section's full text becomes a single
    chunk when it's <= CHUNK_MAX_CHARS; a longer section is sub-split into
    ~CHUNK_TARGET_CHARS pieces (see _split_oversized_segment) that all carry
    that same section label.
    """
    if not text:
        return

    boundaries = [(0, None)] + list(section_markers)
    for i, (start, section) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        segment = text[start:end]
        if not segment.strip():
            continue

        if len(segment) <= CHUNK_MAX_CHARS:
            spans = [(0, len(segment))]
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

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
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
        section_markers = find_section_markers(full_text)

        for chunk_text_str, page_num, section in chunk_document(full_text, page_offsets, section_markers):
            documents.append(chunk_text_str)
            metadatas.append(
                {
                    "source": filename,
                    "page": page_num,
                    "section": f"Section {section}" if section else "unknown",
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
