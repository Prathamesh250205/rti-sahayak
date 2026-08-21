"""Minimal per-IP rate limiter for /api/draft.

In-memory, single-process, fixed-window - appropriate for this deployment
(one Render free-tier instance, no shared state across workers) and not a
general abuse-prevention system. Exists specifically to protect the
Groq/Gemini quota from being burned during judging, per the project's
explicit ask.
"""
import time

WINDOW_SECONDS = 300
# 10 was too tight for the actual demo environment: judges are often behind
# shared NAT (several people testing from one venue IP), and even this
# project's own 10-case regression suite fires that many drafts in under
# two minutes from a single IP. 30 still stops runaway quota burn while
# surviving a handful of people sharing an egress IP.
MAX_REQUESTS_PER_WINDOW = 30

_request_log: dict[str, list[float]] = {}


def is_rate_limited(client_ip: str) -> bool:
    """Record this request and return whether client_ip is over the limit.

    Called once per request, so it both checks and records in the same
    pass - a caller must not call this speculatively without following
    through on the request, or it will undercount.
    """
    now = time.time()
    timestamps = _request_log.setdefault(client_ip, [])

    cutoff = now - WINDOW_SECONDS
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)

    if len(timestamps) >= MAX_REQUESTS_PER_WINDOW:
        return True

    timestamps.append(now)
    return False
