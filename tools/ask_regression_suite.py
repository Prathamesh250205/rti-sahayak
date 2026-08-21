"""Regression suite for standalone Q&A (Gate 11).

Runs a small fixture of questions through the real POST /api/ask endpoint -
not answer_question() in isolation - and checks both that the endpoint
reaches the expected status (ok vs insufficient_grounding) and, for "ok"
cases, that the answer actually carries a citation into the expected
section. An "ok" answer with zero citations is a fail here even if the
prose itself looks right - see agent/qa.py's module docstring for why every
claim is required to carry a citation.

Usage:
    python -m tools.ask_regression_suite [base_url] [delay_seconds]

base_url defaults to http://127.0.0.1:8000 (a locally running server).
Pass a deployed URL to run the same suite against production, e.g.:
    python -m tools.ask_regression_suite https://rti-sahayak.onrender.com

delay_seconds (default 6.0) is a pause before each case after the first -
see tools/scope_regression_suite.py's docstring for why (Gate 12e: a
per-minute provider throttle, not a code defect).
"""
import json
import sys
import time
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DELAY_SECONDS = 6.0

FIXTURE = [
    {
        "label": "PIO response deadline",
        "question": "how many days does a PIO have to respond",
        "expected_status": "ok",
        "expected_sections": ["Section 7"],
    },
    {
        "label": "RTI filing fee",
        "question": "what is the fee for filing an RTI",
        "expected_status": "ok",
        "expected_sections": ["Section 6", "Section 7"],
    },
    {
        "label": "Cabinet papers exemption",
        "question": "can I ask for cabinet papers",
        "expected_status": "ok",
        "expected_sections": ["Section 8"],
    },
    {
        "label": "Unrelated general-knowledge question - must refuse",
        "question": "who won the cricket world cup",
        "expected_status": "insufficient_grounding",
        "expected_sections": [],
    },
]


def run_case(base_url: str, case: dict) -> dict:
    payload = {"question": case["question"]}
    req = urllib.request.Request(
        f"{base_url}/api/ask",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}
    return data


def evaluate(case: dict, data: dict) -> tuple[bool, str]:
    actual_status = data.get("status", "<missing>")
    if actual_status != case["expected_status"]:
        return False, f"expected status={case['expected_status']!r}, got {actual_status!r}"

    if case["expected_status"] == "insufficient_grounding":
        if data.get("citations"):
            return False, "insufficient_grounding response unexpectedly carried citations"
        return True, "refused with no answer, as expected"

    citations = data.get("citations") or []
    if not citations:
        return False, "status=ok but citations list is empty - every claim must carry a citation"

    cited_sections = {c.get("section", "") for c in citations}
    if not any(
        any(expected in section for section in cited_sections)
        for expected in case["expected_sections"]
    ):
        return False, (
            f"expected a citation into one of {case['expected_sections']}, "
            f"got sections {sorted(cited_sections)}"
        )

    return True, f"{len(citations)} citation(s) into {sorted(cited_sections)}"


def run_suite(base_url: str, delay_seconds: float) -> list[dict]:
    rows = []
    for i, case in enumerate(FIXTURE):
        if i > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)

        data = run_case(base_url, case)
        if "error" in data:
            rows.append({"label": case["label"], "passed": False, "provider": None, "detail": data["error"]})
            continue
        passed, detail = evaluate(case, data)
        provider = (data.get("meta") or {}).get("provider")
        rows.append({"label": case["label"], "passed": passed, "provider": provider, "detail": detail})
    return rows


def print_report(rows: list[dict]) -> int:
    print(f"{'PASS/FAIL':<9} LABEL / DETAIL")
    print("-" * 100)
    n_passed = 0
    for row in rows:
        mark = "PASS" if row["passed"] else "FAIL"
        n_passed += row["passed"]
        print(f"{mark:<9} {row['label']}")
        print(f"{'':<9} -> {row['detail']}")

    print()
    print(f"{n_passed}/{len(rows)} passed")
    return n_passed


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    delay_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DELAY_SECONDS
    print(f"Running ask regression suite against {base_url} (delay={delay_seconds}s)\n")

    rows = run_suite(base_url, delay_seconds)
    n_passed = print_report(rows)

    if n_passed != len(rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
