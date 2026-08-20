"""Small in-process state shared across the web/ API layer.

Populated by web/main.py's startup lifespan (warm_up_seconds) and
web/api/draft.py's request handler (last_request), read by
web/api/system.py. Deliberately not persisted - it exists only to answer
"what actually just happened in this running process," so it resets to
None on every restart, which is the honest behavior for a live telemetry
readout (no stale numbers surviving past a redeploy).
"""

warm_up_seconds: float | None = None
last_request: dict | None = None
