# RTI Sahayak

Drafts a Right to Information Act, 2005 application from a citizen's plain-language
problem description. Every procedural claim in the letter (filing manner, fee, response
timeline) is grounded in retrieved Act text and cited by section; the department guess is
always labeled as a guess. It declines to draft only when the request itself isn't asking
for a record — not when the topic happens to share no vocabulary with the statute, which
is most legitimate requests.

**Demo video:** [add link here]
**Live deployment:** https://rti-sahayak.onrender.com
**Sample application (no LLM/Chroma required):** https://rti-sahayak.onrender.com/demo

## The problem

Filing an RTI application means citing specific sections of a 20-year-old statute correctly,
and most citizens have never read it. Get the procedure wrong — the wrong fee, a missing
citation, the wrong Public Information Officer — and the application can be rejected or
delayed on a technicality that has nothing to do with the actual grievance.

## Screenshot

A generated draft, with clause-level citation chips (linking each procedural sentence back
to the Act section that justifies it) and the retrieved source passages shown below:

![Draft screen with citation chips and source cards](docs/draft-screen.png)

## Architecture

```
agent/    intake slot-filling (agent/intake.py) and letter drafting/composition
          (agent/drafter.py) - the LLM scope classification and procedural
          clause-provenance logic both live here
rag/      corpus ingestion (rag/ingest.py) and retrieval (rag/retriever.py) -
          the Chroma vector store and its embedding function
llm/      provider-agnostic LLM client (llm/client.py) - Groq primary, Gemini
          fallback, automatic retry on the other provider if one fails
export/   PDF generation (export/pdf_writer.py) - renders the final letter text,
          nothing else
web/      FastAPI app: routes (web/main.py), the /api/draft and /api/act
          endpoints (web/api/), Jinja2 templates, per-IP rate limiting
app.py    Streamlit conversational-intake interface over the same
          agent/llm/rag/export pipeline as web/ - see Known limitations for
          how it differs from the FastAPI app
```

A request flows: **web/api/draft.py** (intake fields) → **CHECK A** (`agent/drafter.py`'s
`gather_grounding()`, via `rag/retriever.py`) → **CHECK B** (`agent/drafter.py`'s
`understand_request()`, via `llm/client.py`) → **agent/drafter.py**'s `compose_letter()`
(procedural clauses assembled in plain Python, department guess and information-sought from
the LLM) → **export/pdf_writer.py** on download.

## The two-check grounding design

This is the most important design decision in the project, and it went through two
iterations - the first one was wrong in a way that's worth explaining, because the failure
mode is easy to reach for.

**The obvious approach, and why it doesn't work.** The natural instinct is to check whether
the Act's text is actually relevant to what the citizen typed - embed their problem
description, retrieve the nearest chunks from the Act, and refuse if nothing scores close
enough. This is what an earlier version of this app did, using the same distance threshold
already tuned for retrieval quality (0.75).

It's the wrong question. The RTI Act, 2005 is a procedural statute: Section 3 grants an
unconditional right to information, Section 6 lets any citizen request any record from any
public authority without stating a reason, and Section 8 lists a short, specific set of
exemptions (national security, cabinet papers, personal privacy) - none of them topic-based.
The Act's own text never mentions ration cards, roads, or pensions by name, because it was
never meant to. Coverage is near-universal by design; there's no "does the Act cover this
topic" question that retrieval distance could sensibly answer, because almost everything is
covered and the statute doesn't say so per-topic.

In practice this produced two failure modes at once, both confirmed empirically:
- **False refusals.** "My ration card renewal is stuck with no update" - an extremely
  common, obviously legitimate RTI request - retrieved nothing under the threshold at all,
  because "ration card" shares no vocabulary with the Act's procedural language.
- **Meaningless false positives.** "My pension payments have stopped without explanation"
  passed the gate not because the Act says anything about pensions, but because it happened
  to score under 0.75 against **Section 16** - the term-of-office rules for State
  Information Commissioners. The letter would have gone out grounded in a coincidence, not
  a reason.

**The fix: separate the two questions actually being asked, and answer each with the tool
suited to it.**

- **CHECK A - procedural grounding (deterministic).** Does the corpus actually contain the
  procedural text that backs the Section 6/7 clauses and the citation chips? This runs
  `gather_grounding()`'s two fixed retrieval queries (filing manner + fee, response
  timeline) - unrelated to the citizen's topic, so it succeeds for every real request against
  a healthy corpus and only fails if Chroma itself is empty or broken (e.g. a deploy that
  skipped ingestion). It's not a relevance filter; it's a corpus-health check, and it's
  cheap enough to run before any LLM call.
- **CHECK B - scope (LLM classification, explicit verdict).** Is this genuinely a request
  for records held by an Indian public authority? Semantic similarity to the Act's own text
  can't answer this, so it isn't inferred from retrieval distance, and it isn't inferred
  from the LLM's `information_sought` list coming back empty either - a truncated
  completion or a provider hiccup would look identical to a genuine "not a records request"
  answer otherwise. The model returns an explicit `{"in_scope": true|false, "reason": "..."}`
  verdict alongside the drafting fields, and the three resulting states are handled
  separately: `true` drafts normally, `false` shows an out-of-scope screen with the model's
  stated reason, and *no verdict obtained* (a parse failure or provider error, distinct from
  an explicit `false`) fails open - the letter is still drafted, with a visible warning that
  scope screening was unavailable, on the reasoning that procedural grounding (CHECK A)
  already held and a mysterious refusal during a live demo is worse than a flagged draft.

The regression suite (`tools/scope_regression_suite.py`) exists specifically to keep this
honest: it includes a deliberately adjacent pair - *"how do I file my income tax
return"* (out of scope: a how-to question) versus *"certified copy of my income tax return
filed for AY 2023-24"* (in scope: a specific record) - that semantic distance to the Act's
text could never have separated, because both sit in the same topic neighborhood. Splitting
the check by *what kind of question it answers*, rather than tuning one threshold harder,
is what made that distinction possible.

## Setup

Verified end-to-end via a clean clone into a fresh directory, fresh venv, and a fresh
`pip install` - most recently, against the exact Render build command:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and fill in GROQ_API_KEY and/or GEMINI_API_KEY
```

`LLM_PROVIDER` in `.env` selects the primary provider (`groq` or `gemini`); the other is
used automatically as a fallback. See `.env.example` for every variable the app reads.

Build the knowledge base (not committed — see Architecture):

```bash
python -m rag.ingest
```

This downloads the embedding model on first run (cached under `data/onnx_model_cache/`,
gitignored) and prints `Ingested 78 chunks from 1 PDF(s) ... (78/78 tagged with a section
number)`. Re-run it any time the corpus PDF changes; it deletes and replaces the existing
Chroma collection.

Run either front end (both read the same `data/chroma/` index, built above):

```bash
streamlit run app.py                                    # conversational intake
uvicorn web.main:app --host 127.0.0.1 --port 8000        # web UI, http://127.0.0.1:8000
```

The FastAPI app (`web/`) is the primary surface; the Streamlit app (`app.py`) is a
reduced fallback - see Known limitations.

Warm-up is fast since the embedding model is ONNX-based and the model artifact is cached at
build/ingest time - measured under 1s on local dev hardware, ~8s on the deployed Render
free-tier instance (0.1 CPU). The FastAPI app warms this up in a background task at
startup, binding its port immediately so it never blocks Render's health check; Streamlit
loads it lazily on first use (`st.cache_resource`) and caches it for the life of the
process.

**Troubleshooting (Windows):** if `git clone` fails with `Filename too long`, it's hitting
the 260-character `MAX_PATH` limit — one self-hosted font file has a long, hash-based name.
Clone to a short path (e.g. `C:\rti-sahayak`) or run
`git config --global core.longpaths true`.

## Deployment

`render.yaml` targets Render's native Python runtime (no Dockerfile): `buildCommand` runs
`pip install -r requirements.txt && python -m rag.ingest`, baking the Chroma index and the
ONNX model cache into the build (the filesystem is otherwise ephemeral across deploys, and
both are gitignored). `GET /healthz` reports the live chunk count, resolved persist path,
and configured LLM provider — built specifically to make a zero-chunk deploy (e.g. a build
that silently skipped ingestion) immediately visible instead of surfacing only as a vague
empty `/browse` page or a wall of refusals. A startup check independently logs a loud
`[startup] ERROR` line to Render's logs if the collection is empty or if any chunk still
carries the pre-fix `"unknown"` front-matter label.

## Scope

| | |
|---|---|
| **Implemented** | Conversational intake (Streamlit) and one-shot web form (FastAPI); two-check grounded letter drafting with clause-level citations (see above); PDF export; Browse the Act (real section list + search over the corpus); a static `/demo` sample application that works with neither Chroma nor the LLM available; system telemetry panel; Groq/Gemini provider fallback; per-IP rate limiting on `/api/draft`; real content pages for the legal disclaimer, privacy policy, terms of service, and support. |
| **Not implemented** | **Ask** (standalone Q&A over the Act), **Track** (filing status and statutory deadline tracking), **Save Draft**, and **Login** are all honestly labeled "Coming in v2" stubs, not built — clicking them does not fake functionality. **Multilingual drafting** (हिंदी / मराठी) shows an inline "in development" note where clicked — no translation happens. |

## Known limitations

- **`likely_authority` is a suggestion, not a verified fact.** The department/PIO named in
  a draft is the LLM's best guess at who is likely to hold the requested records - it is
  never checked against any official directory. Every draft (letter body, and both places
  Streamlit surfaces it separately) carries "(Best guess — please confirm the correct
  Public Information Officer and mailing address before submitting.)" for exactly this
  reason. Confirm the correct office before filing.
- **The Streamlit app (`app.py`) has no CHECK B scope gate.** It shares the same
  `agent/drafter.py` pipeline as the FastAPI app, but its conversational flow calls
  `understand_request()` without acting on the `in_scope` verdict it now returns - so it
  will draft a letter for a plainly out-of-scope input (e.g. "write me a poem about
  cricket") where the FastAPI app would decline. This is a deliberate, documented gap (the
  FastAPI app is the primary surface), not an oversight discovered after the fact.
- `rag/retriever.py` imports `streamlit` and uses `st.cache_resource` to cache the loaded
  collection, a pattern built for the Streamlit app. Called from FastAPI, this still works
  but logs a `missing ScriptRunContext` warning to stderr on every process start — cosmetic,
  not functional.
- `gemini-flash-latest` is a reasoning model that spends part of `max_output_tokens` on
  internal reasoning before producing visible output. A low token budget can be entirely
  consumed by reasoning, returning empty text with no error — observed directly with a
  20-token budget. The app's actual budgets are large enough that this hasn't shown up in
  practice, but it's a real characteristic of the model, not handled defensively in code.
- Gemini's free tier is a hard 20 requests/day on this project's key, observed directly
  during testing (both a 5/minute and a 20/day limit) - Groq is the configured primary for
  exactly this reason, with Gemini as fallback only.
