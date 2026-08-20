# RTI Sahayak

An AI-assisted drafting tool for Right to Information Act, 2005 applications. Every
procedural claim in a drafted letter (filing manner, fee, response timeline) is grounded
in retrieved RTI Act text and cited by section — nothing is asserted without a matching
passage from the corpus, and requests that fall outside the Act's text are refused rather
than guessed at.

Two front ends share the same drafting pipeline:
- **Streamlit** (`app.py`) — conversational, turn-by-turn intake.
- **FastAPI + Jinja2** (`web/`) — a one-shot web UI (home, draft, browse-the-Act, system
  telemetry).

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and fill in GROQ_API_KEY and/or GEMINI_API_KEY
```

`LLM_PROVIDER` selects the primary provider (`groq` or `gemini`); the other is used
automatically as a fallback if the primary fails. See `.env.example` for every variable
the app reads.

## Build the knowledge base

The Chroma vector index (`data/chroma/`) is not committed — it's fully rebuildable from
the source PDF already checked in at `data/corpus/RTI_Act_2005.pdf`:

```bash
python -m rag.ingest
```

Re-run this any time the corpus PDF changes. It chunks the Act on section boundaries,
embeds the chunks (`all-MiniLM-L6-v2`, downloaded on first run), and writes a fresh
Chroma collection — deleting and replacing any existing one.

## Run

**Streamlit** (conversational intake):
```bash
streamlit run app.py
```

**FastAPI web UI** (http://127.0.0.1:8000):
```bash
uvicorn web.main:app --host 127.0.0.1 --port 8000
```

Both read from the same `data/chroma/` index, so run the ingestion step first. First
request/startup after ingestion is slower (~20-30s) while the embedding model loads;
the FastAPI app warms this up at startup, Streamlit caches it on first use.

## Project layout

- `agent/` — intake slot-filling and letter drafting/composition logic
- `llm/` — provider-agnostic LLM client (Gemini + Groq, automatic fallback)
- `rag/` — corpus ingestion (`ingest.py`) and retrieval (`retriever.py`)
- `export/` — PDF generation
- `web/` — FastAPI app, routes, and Jinja2 templates
- `data/corpus/` — source PDF (committed)
- `data/chroma/` — vector index (gitignored, rebuilt via `python -m rag.ingest`)
- `design/` — Stitch-exported HTML/Tailwind screen designs the `web/` templates were
  ported from
