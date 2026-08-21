"""FastAPI entry point for the web/ UI layer."""
import asyncio
import json
import sys
import time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

import llm.client as llm_client
from rag.retriever import CHROMA_DIR, COLLECTION_NAME, RetrieverError, _get_collection
from rag.retriever import warm_up as warm_up_retriever
from web import state as web_state
from web.api.act import router as act_router
from web.api.draft import router as draft_router
from web.api.system import router as system_router

BASE_DIR = Path(__file__).parent


def _check_corpus_health() -> None:
    """Log loud, unmissable ERROR lines if the just-loaded Chroma collection
    is empty or still carries the pre-Gate-3 "unknown" front-matter label.

    Both are silent-degradation failure modes otherwise: a zero-chunk
    collection (e.g. a Render deploy whose build step skipped ingestion)
    doesn't crash anything - every draft just quietly refuses via CHECK A,
    which looks identical to a real corpus-health problem from the outside.
    An "unknown" chunk reappearing would mean the PREAMBLE_ANCHOR split in
    rag/ingest.py regressed (see that module) - the retrieval-quality bug
    Gate 2/3 fixed. Neither condition should ever be true in a healthy
    deploy; this makes it obvious in Render logs the moment it isn't,
    rather than only showing up as vague empty-/browse or refusal
    complaints days later. Never raises - a broken health check must not
    be mistaken for a warm-up failure in the caller's logs.
    """
    try:
        collection = _get_collection()
        result = collection.get(include=["metadatas"])
        metadatas = result["metadatas"]
    except Exception as e:
        print(f"[startup] ERROR: corpus health check itself failed: {type(e).__name__}: {e}", file=sys.stderr)
        return

    if not metadatas:
        print(
            "[startup] ERROR: Chroma collection has 0 chunks. The corpus was not ingested "
            "(check the build command actually ran `python -m rag.ingest`) - every draft "
            "will refuse via CHECK A until this is fixed.",
            file=sys.stderr,
        )
        return

    unknown_count = sum(1 for m in metadatas if m.get("section") == "unknown")
    if unknown_count:
        print(
            f"[startup] ERROR: {unknown_count} chunk(s) carry section='unknown' - the "
            "PREAMBLE_ANCHOR front-matter split in rag/ingest.py has regressed. See that "
            "module's PREAMBLE_ANCHOR constant.",
            file=sys.stderr,
        )


async def _warm_up_in_background() -> None:
    # Runs as a fire-and-forget task from lifespan below, off the event
    # loop thread (warm_up_retriever is blocking, synchronous work) so the
    # port is already accepting connections while the embedding model
    # loads. Render's free tier (0.1 CPU) kills services that don't bind
    # their port fast - blocking startup on this ~20s+ load risked exactly
    # that. Never blocks startup on failure - retrieval just surfaces its
    # own error normally on first real use if this doesn't work.
    t0 = time.perf_counter()
    try:
        await asyncio.to_thread(warm_up_retriever)
        web_state.warm_up_seconds = time.perf_counter() - t0
        print(f"[startup] RTI Act knowledge base warm-up completed in {web_state.warm_up_seconds:.2f}s", file=sys.stderr)
        await asyncio.to_thread(_check_corpus_health)
    except Exception as e:
        print(f"[startup] Knowledge base warm-up failed after {time.perf_counter() - t0:.2f}s: {e}", file=sys.stderr)
    finally:
        # Set even on failure - a wedged "still warming up" response
        # forever would be worse than letting retrieve() surface its own
        # real error on first genuine use.
        web_state.ready = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(_warm_up_in_background())
    yield


app = FastAPI(title="RTI Sahayak", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
# Computed once at process start, not re-read from disk per request - the
# footer's "© {year}" only needs to be right for whatever year this
# process happens to be running in, which a redeploy refreshes anyway.
templates.env.globals["current_year"] = date.today().year
app.include_router(draft_router)
app.include_router(act_router)
app.include_router(system_router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # /api/* routes must keep returning JSON (browse.html's and draft.html's
    # own JS parse `.detail` out of error responses) - only page routes get
    # the HTML error screen.
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return templates.TemplateResponse(request, "404.html", status_code=404)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    print(f"[error] Unhandled exception on {request.method} {request.url.path}: {type(exc).__name__}: {exc}", file=sys.stderr)
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
    return templates.TemplateResponse(request, "500.html", status_code=500)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/healthz")
def healthz():
    """Deployment diagnostics for the Chroma corpus - built to make a
    zero-chunk deploy (e.g. a build step that silently failed to run
    ingestion) immediately visible instead of surfacing only as a vague
    empty /browse page or a universal insufficient_grounding refusal.

    chroma_persist_path is resolved with Path.resolve() specifically so
    this reports the real absolute filesystem location the process is
    actually reading, not the unresolved "rag/../data/chroma" string the
    code constructs it from - the two can look identical relative to the
    repo but only the resolved form proves what's genuinely on disk.
    """
    from chromadb.utils import embedding_functions

    resolved_path = Path(CHROMA_DIR).resolve()
    path_exists = resolved_path.exists()

    chunk_count = None
    collection_error = None
    if path_exists:
        try:
            chunk_count = _get_collection().count()
        except RetrieverError as e:
            collection_error = str(e)
        except Exception as e:
            collection_error = f"{type(e).__name__}: {e}"
    else:
        collection_error = "Persist path does not exist on disk."

    return {
        "chroma_collection_name": COLLECTION_NAME,
        "chroma_chunk_count": chunk_count,
        "chroma_persist_path": str(resolved_path),
        "chroma_persist_path_exists": path_exists,
        "collection_error": collection_error,
        "llm_provider": llm_client.PROVIDER,
        "embedding_model": embedding_functions.ONNXMiniLM_L6_V2.MODEL_NAME,
    }


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse(request, "home.html")


@app.get("/_smoke")
def smoke(request: Request):
    return templates.TemplateResponse(request, "_smoke.html")


@app.get("/draft")
def draft(request: Request):
    return templates.TemplateResponse(request, "draft.html")


@app.get("/browse")
def browse(request: Request):
    return templates.TemplateResponse(request, "browse.html")


# A real POST /api/draft response, captured once from an actual run of this
# app's own pipeline (see web/fixtures/demo_draft.json) - not hand-written,
# not connected to Chroma or the LLM at request time. This is what /demo
# renders, so it stays up if either of those is down during judging. Loaded
# once at import time since the file never changes at runtime.
with open(BASE_DIR / "fixtures" / "demo_draft.json", encoding="utf-8") as _f:
    DEMO_DRAFT = json.load(_f)


@app.get("/demo")
def demo(request: Request):
    return templates.TemplateResponse(request, "demo.html", {"demo_data": DEMO_DRAFT})


# Every dead "#" link found while auditing home.html/draft.html/browse.html
# and their partials leads here instead of doing nothing - each entry states
# plainly what the feature will do, with no functionality faked. Title/copy
# are server-defined (not query-param input) so nothing here can be used to
# inject arbitrary page content.
COMING_SOON_FEATURES = {
    "ask": ("Ask", "Standalone Q&A over the Act is not yet implemented."),
    "track": ("Track", "Filing status and statutory deadline tracking is not yet implemented."),
    "login": ("Account Login", "Signing in to save and manage your RTI applications is not yet implemented."),
    "save-draft": ("Save Draft", "Saving a draft to return to later is not yet implemented."),
}

# Real content pages, not stubs - each rendered through content_page.html.
# All server-authored, never user input, so Jinja's default autoescaping is
# the only escaping this needs.
CONTENT_PAGES = {
    "legal": (
        "Legal Disclaimer",
        [
            {"paragraphs": [
                "RTI Sahayak is an educational tool that helps you draft a Right to Information "
                "Act, 2005 application. It is not legal advice, and nothing on this site should be "
                "treated as legal advice or as the practice of law.",
            ]},
            {"heading": "Verify before filing", "paragraphs": [
                "Every draft is produced with the help of an AI model. AI-generated content can be "
                "wrong. Before submitting any application, verify the full text - including the "
                "cited sections - against the official Right to Information Act, 2005 and the rules "
                "applicable in your state.",
            ]},
            {"heading": "The suggested public authority is a guess", "paragraphs": [
                "The department or public authority named in a draft is the AI's best guess at who "
                "is likely to hold the information you're asking for. It is not checked against any "
                "official directory and may be wrong, outdated, or incomplete. Confirm the correct "
                "Public Information Officer and mailing address with the relevant government office "
                "before filing.",
            ]},
            {"heading": "No professional relationship", "paragraphs": [
                "Using this tool does not create a lawyer-client relationship or any other "
                "professional relationship between you and the creators of RTI Sahayak. If you need "
                "legal advice about a specific matter, consult a qualified professional.",
            ]},
        ],
    ),
    "privacy": (
        "Privacy Policy",
        [
            {"heading": "What this app stores", "paragraphs": [
                "RTI Sahayak has no user accounts and no session store or database of past requests. "
                "Each draft request is processed statelessly: the form data you submit is used to "
                "generate a response and is not saved anywhere by this application once that "
                "response is returned.",
            ]},
            {"heading": "What happens to your request", "paragraphs": [
                "The problem description and other details you enter are sent to the LLM provider "
                "configured for this deployment (Groq or Google Gemini, depending on configuration) "
                "to help draft the letter, and are used to search the RTI Act text stored locally in "
                "this application's own database. Beyond that, RTI Sahayak's own code does not "
                "deliberately log, store, or share the content of your request.",
            ]},
            {"heading": "Operational logs", "paragraphs": [
                "Like most web services, the hosting platform (Render) may keep short-lived "
                "infrastructure-level logs, such as request timing or error traces, as part of "
                "running the service.",
            ]},
            {"heading": "Third-party terms", "paragraphs": [
                "Requests are also subject to the privacy practices of the configured LLM provider. "
                "If you have concerns about how they handle data sent to their API, review their own "
                "privacy policy directly.",
            ]},
        ],
    ),
    "terms": (
        "Terms of Service",
        [
            {"paragraphs": [
                "RTI Sahayak is provided as-is, for educational use, without warranty of any kind, "
                "express or implied.",
                "Drafts generated by this tool may contain errors, and you are solely responsible "
                "for reviewing, correcting, and verifying anything you choose to file with a public "
                "authority.",
                "Use of this tool does not guarantee your RTI application will be accepted or will "
                "receive a response.",
            ]},
        ],
    ),
    "support": (
        "Support",
        [
            {"paragraphs": [
                "RTI Sahayak is a hackathon submission, not a maintained product, and there's no "
                "dedicated support channel. If you've found a bug or want to see how it works, the "
                "source code is public:",
            ], "link": {"href": "https://github.com/Prathamesh250205/rti-sahayak", "text": "github.com/Prathamesh250205/rti-sahayak"}},
        ],
    ),
}


def _content_page(request: Request, page_key: str):
    page_title, sections = CONTENT_PAGES[page_key]
    return templates.TemplateResponse(request, "content_page.html", {"page_title": page_title, "sections": sections})


def _coming_soon(request: Request, feature_key: str):
    title, description = COMING_SOON_FEATURES[feature_key]
    return templates.TemplateResponse(
        request, "coming_soon.html", {"feature_title": title, "feature_description": description}
    )


@app.get("/ask")
def ask(request: Request):
    return _coming_soon(request, "ask")


@app.get("/track")
def track(request: Request):
    return _coming_soon(request, "track")


@app.get("/legal")
def legal(request: Request):
    return _content_page(request, "legal")


@app.get("/privacy")
def privacy(request: Request):
    return _content_page(request, "privacy")


@app.get("/terms")
def terms(request: Request):
    return _content_page(request, "terms")


@app.get("/support")
def support(request: Request):
    return _content_page(request, "support")


@app.get("/contact")
def contact():
    # /contact and /support were two separate stub routes for the same
    # concept - /support is the one every page's footer actually links to
    # (see web/templates/*.html), so it's the one that survives; this
    # redirect exists only for anyone who already had /contact bookmarked
    # or linked, rather than serving them a raw 404.
    return RedirectResponse(url="/support", status_code=301)


@app.get("/login")
def login(request: Request):
    return _coming_soon(request, "login")


@app.get("/save-draft")
def save_draft(request: Request):
    return _coming_soon(request, "save-draft")
