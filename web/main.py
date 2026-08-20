"""FastAPI entry point for the web/ UI layer."""
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from rag.retriever import warm_up as warm_up_retriever
from web import state as web_state
from web.api.act import router as act_router
from web.api.draft import router as draft_router
from web.api.system import router as system_router

BASE_DIR = Path(__file__).parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Force the embedding-model cold-load (~20s) to happen now, at startup,
    # rather than during whichever request happens to hit gather_grounding()
    # first. Never blocks startup on failure - retrieval just surfaces its
    # own error normally on first real use if this doesn't work.
    t0 = time.perf_counter()
    try:
        warm_up_retriever()
        web_state.warm_up_seconds = time.perf_counter() - t0
        print(f"[startup] RTI Act knowledge base warm-up completed in {web_state.warm_up_seconds:.2f}s", file=sys.stderr)
    except Exception as e:
        print(f"[startup] Knowledge base warm-up failed after {time.perf_counter() - t0:.2f}s: {e}", file=sys.stderr)
    yield


app = FastAPI(title="RTI Sahayak", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")
app.include_router(draft_router)
app.include_router(act_router)
app.include_router(system_router)


@app.get("/health")
def health():
    return {"status": "ok"}


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


# Every dead "#" link found while auditing home.html/draft.html/browse.html
# and their partials leads here instead of doing nothing - each entry states
# plainly what the feature will do, with no functionality faked. Title/copy
# are server-defined (not query-param input) so nothing here can be used to
# inject arbitrary page content.
COMING_SOON_FEATURES = {
    "ask": ("Ask", "Standalone Q&A over the Act is not yet implemented."),
    "track": ("Track", "Filing status and statutory deadline tracking is not yet implemented."),
    "legal": ("Legal Disclaimer", "A dedicated legal disclaimer page is not yet implemented."),
    "privacy": ("Privacy Policy", "A dedicated privacy policy page is not yet implemented."),
    "terms": ("Terms of Service", "A dedicated terms of service page is not yet implemented."),
    "support": ("Support", "A dedicated support and help center is not yet implemented."),
    "contact": ("Contact Us", "A contact form is not yet implemented."),
    "login": ("Account Login", "Signing in to save and manage your RTI applications is not yet implemented."),
    "save-draft": ("Save Draft", "Saving a draft to return to later is not yet implemented."),
}


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
    return _coming_soon(request, "legal")


@app.get("/privacy")
def privacy(request: Request):
    return _coming_soon(request, "privacy")


@app.get("/terms")
def terms(request: Request):
    return _coming_soon(request, "terms")


@app.get("/support")
def support(request: Request):
    return _coming_soon(request, "support")


@app.get("/contact")
def contact(request: Request):
    return _coming_soon(request, "contact")


@app.get("/login")
def login(request: Request):
    return _coming_soon(request, "login")


@app.get("/save-draft")
def save_draft(request: Request):
    return _coming_soon(request, "save-draft")
