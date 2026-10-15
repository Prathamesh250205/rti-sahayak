"""Small in-process state shared across the web/ API layer.

Populated by web/main.py's startup lifespan (warm_up_seconds, ready) and
web/api/draft.py's request handler (last_request), read by
web/api/system.py. Deliberately not persisted - it exists only to answer
"what actually just happened in this running process," so it resets to
None on every restart, which is the honest behavior for a live telemetry
readout (no stale numbers surviving past a redeploy).
"""

import threading

warm_up_seconds: float | None = None
last_request: dict | None = None

# Set when the background warm-up task in web/main.py's lifespan finishes
# (success or failure). Pages come from the CDN, so a visitor's first
# Generate/Ask is often the request that starts a cold instance: /api/draft
# and /api/ask wait on this (~1s) rather than refuse while it loads.
ready = threading.Event()
READY_TIMEOUT_SECONDS = 45
