"""Vercel entrypoint: Vercel looks for an ASGI `app` in index.py at the repo
root. The real app lives in web/main.py; run it locally with
`uvicorn web.main:app` as before."""
from web.main import app  # noqa: F401
