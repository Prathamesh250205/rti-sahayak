"""Query interface over the RTI corpus index.

Every result carries its section/page metadata so callers can cite sources
and can tell when nothing relevant was found, instead of improvising.

The corpus is 83 chunks, so search is a brute-force numpy scan over their
stored vectors (data/index/, written by rag/ingest.py and committed). This
replaced chromadb, which pulled ~200 MB of dependencies (kubernetes, grpc,
...) into a serverless function for an index this small - enough to overflow
Vercel's runtime install space. Vectors, distance metric and results are
unchanged: _Embedder is a port of chromadb's ONNXMiniLM_L6_V2, and the stored
vectors were exported from the old Chroma collection (parity verified).
"""
import functools
import hashlib
import json
import os
import tarfile
import threading
import urllib.request
from dataclasses import dataclass

import numpy as np

INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "index")
ONNX_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "onnx_model_cache")
MODEL_DIR = os.path.join(ONNX_CACHE_DIR, "onnx")
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
# The same archive chromadb downloaded, pinned by its published sha256.
MODEL_URL = "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
MODEL_SHA256 = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"
MODEL_FILES = ("config.json", "model.onnx", "special_tokens_map.json",
               "tokenizer.json", "tokenizer_config.json", "vocab.txt")

# Distance is chromadb's "l2" value over normalized MiniLM embeddings - half
# the squared Euclidean distance, i.e. 1 - cosine similarity (see
# _Index.query); kept identical when chromadb was replaced so this cutoff holds.
# Re-measured after switching rag/ingest.py from 500-word sliding-window
# chunks to section-boundary chunks (~975 chars mean, vs ~3128 before):
# smaller, more topically focused chunks pull genuine RTI-procedure queries
# in closer (best matches ~0.21-0.73) but also pull the *best* off-topic
# match in closer too (~0.78+, down from ~0.95+ under the old chunking) - a
# stray sentence in a small chunk has a better chance of superficially
# resembling an unrelated query than the same sentence buried in a 3000-char
# chunk did. The old 0.8 cutoff sat above the new off-topic floor (0.78),
# so it would wrongly admit clearly off-topic queries; 0.75 sits back in the
# gap between the two clusters. Chunks above this cutoff are not relevant.
MAX_RELEVANT_DISTANCE = 0.75

class RetrieverError(RuntimeError):
    """Raised when the corpus index or the embedding model is missing."""


@dataclass
class RetrievedChunk:
    text: str
    section: str
    page: int
    source: str
    distance: float


def ensure_model() -> None:
    """Download and unpack the ONNX model into MODEL_DIR if it isn't there.

    Run at build time (tools/vercel_build.py) and by rag/ingest.py - never on
    a live request, where the function's disk is read-only.
    """
    if all(os.path.exists(os.path.join(MODEL_DIR, f)) for f in MODEL_FILES):
        return
    os.makedirs(ONNX_CACHE_DIR, exist_ok=True)
    archive = os.path.join(ONNX_CACHE_DIR, "onnx.tar.gz")
    urllib.request.urlretrieve(MODEL_URL, archive)
    with open(archive, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != MODEL_SHA256:
            raise RetrieverError(f"Embedding model download failed its sha256 check: {MODEL_URL}")
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(ONNX_CACHE_DIR, filter="data")
    os.remove(archive)


class _Embedder:
    """all-MiniLM-L6-v2 on onnxruntime - a line-for-line port of chromadb's
    ONNXMiniLM_L6_V2._forward (256-token padding, attention-masked mean
    pooling, L2 normalisation), so query vectors match the stored ones."""

    def __init__(self):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if not all(os.path.exists(os.path.join(MODEL_DIR, f)) for f in MODEL_FILES):
            raise RetrieverError(f"Embedding model not found in {MODEL_DIR}. Run `python -m rag.ingest` first.")
        self.tokenizer = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=256)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(os.path.join(MODEL_DIR, "model.onnx"),
                                            providers=ort.get_available_providers(), sess_options=options)

    def __call__(self, texts: list[str], batch_size: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(texts), batch_size):
            encoded = [self.tokenizer.encode(t) for t in texts[i:i + batch_size]]
            ids = np.array([e.ids for e in encoded], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
            hidden = self.session.run(None, {"input_ids": ids, "attention_mask": mask,
                                             "token_type_ids": np.zeros_like(ids)})[0]
            weights = np.broadcast_to(np.expand_dims(mask, -1), hidden.shape)
            pooled = np.sum(hidden * weights, 1) / np.clip(weights.sum(1), a_min=1e-9, a_max=None)
            norm = np.linalg.norm(pooled, axis=1)
            norm[norm == 0] = 1e-12
            out.append((pooled / norm[:, np.newaxis]).astype(np.float32))
        return np.concatenate(out)


class _Index:
    """The corpus chunks and their vectors, with the same get/query/count
    shape as the chromadb collection it replaced, so callers didn't change."""

    def __init__(self, ids, documents, metadatas, embeddings, embed):
        self.ids, self.documents, self.metadatas = ids, documents, metadatas
        self.embeddings, self.embed = embeddings, embed

    def count(self) -> int:
        return len(self.ids)

    def get(self, where: dict | None = None, include=None) -> dict:
        rows = [i for i, m in enumerate(self.metadatas)
                if not where or all(m.get(k) == v for k, v in where.items())]
        return {"ids": [self.ids[i] for i in rows],
                "documents": [self.documents[i] for i in rows],
                "metadatas": [self.metadatas[i] for i in rows]}

    def query(self, query_texts: list[str], n_results: int = 10) -> dict:
        q = self.embed(query_texts)
        # Half the squared L2 distance - exactly the number chromadb reported
        # (= 1 - cosine similarity for these unit vectors), so the tuned
        # MAX_RELEVANT_DISTANCE keeps its meaning. 83 rows: no ANN index needed.
        dist = ((self.embeddings[np.newaxis, :, :] - q[:, np.newaxis, :]) ** 2).sum(-1) / 2
        order = np.argsort(dist, axis=1, kind="stable")[:, :n_results]
        return {key: [[vals[i] for i in row] for row in order] for key, vals in
                (("ids", self.ids), ("documents", self.documents), ("metadatas", self.metadatas))} | \
               {"distances": [[float(dist[r, i]) for i in row] for r, row in enumerate(order)]}


def save_index(ids, documents, metadatas, embeddings) -> None:
    """Write the index rag/ingest.py builds (and the repo commits)."""
    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(os.path.join(INDEX_DIR, "chunks.json"), "w", encoding="utf-8") as f:
        json.dump({"ids": ids, "documents": documents, "metadatas": metadatas}, f, ensure_ascii=False)
    np.save(os.path.join(INDEX_DIR, "embeddings.npy"), np.asarray(embeddings, dtype=np.float32))


_load_lock = threading.Lock()


def _get_collection():
    # The startup warm-up thread and the first request can arrive together;
    # functools.cache alone would let both load the model.
    with _load_lock:
        return _load_collection()


@functools.cache
def _load_collection():
    """Load the embedding model + corpus index once per server process.

    Loading the ONNX model is the biggest latency cost in the app -
    functools.cache means every request after the first gets it for free.
    ONNX runtime, not sentence-transformers/torch - same model and vectors
    without a ~500MB PyTorch runtime.
    """
    try:
        with open(os.path.join(INDEX_DIR, "chunks.json"), encoding="utf-8") as f:
            chunks = json.load(f)
        embeddings = np.load(os.path.join(INDEX_DIR, "embeddings.npy"))
    except FileNotFoundError:
        raise RetrieverError("RTI corpus is not ingested yet. Run `python -m rag.ingest` first.")
    return _Index(chunks["ids"], chunks["documents"], chunks["metadatas"], embeddings, _Embedder())


def warm_up() -> None:
    """Force the embedding model to actually load now rather than on first use.

    Call this once at app startup so the one-time model-load cost (~20s,
    or longer on a cold cache - see rag/ingest.py) happens behind a startup
    spinner instead of interrupting a live conversation the first time a
    user reaches the drafting step.

    A throwaway query also runs the ONNX session once, so its first-run
    graph setup is paid here rather than on the first real request.
    """
    collection = _get_collection()
    collection.query(query_texts=["warm up"], n_results=1)


def retrieve(query: str, top_k: int = 4) -> list[RetrievedChunk]:
    """Return up to top_k relevant chunks for query, most relevant first.

    Returns an empty list if nothing in the corpus is relevant enough —
    callers must treat that as "no grounding available", not fall back to
    the model's own knowledge.
    """
    collection = _get_collection()
    result = collection.query(query_texts=[query], n_results=top_k)

    chunks = []
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    for text, meta, distance in zip(documents, metadatas, distances):
        if distance > MAX_RELEVANT_DISTANCE:
            continue
        chunks.append(
            RetrievedChunk(
                text=text,
                section=meta["section"],
                page=meta["page"],
                source=meta["source"],
                distance=distance,
            )
        )
    return chunks


def format_context(chunks: list[RetrievedChunk]) -> str:
    """Render retrieved chunks as a citation-labeled block for an LLM prompt."""
    if not chunks:
        return ""
    parts = []
    for chunk in chunks:
        label = chunk.section if chunk.section != "unknown" else f"{chunk.source} p.{chunk.page}"
        parts.append(f"[{label}]\n{chunk.text}")
    return "\n\n".join(parts)
