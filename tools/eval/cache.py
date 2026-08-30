"""Disk-backed response cache for tools/eval scripts - keyed by (system_id,
language, query), so re-running an eval against unchanged cases costs
nothing. system_id distinguishes which scope-gate implementation produced a
cached response (e.g. the live two-check design vs. Gate E3's
evaluation-only reconstruction of the old distance gate), so their entries
never collide even though they share this one cache file.
"""
import hashlib
import json
import os

CACHE_PATH = os.path.join(os.path.dirname(__file__), ".cache", "responses.json")


def cache_key(system_id: str, language: str, query: str) -> str:
    raw = f"{system_id}::{language}::{query}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_cache() -> dict:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
