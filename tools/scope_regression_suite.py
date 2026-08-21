"""Regression suite for the CHECK B scope classification (Gate 5).

Runs a small fixture of labelled citizen requests through the real
POST /api/draft endpoint - not retrieve() or understand_request() in
isolation - and reports pass/fail against each case's expected status.

Usage:
    python -m tools.scope_regression_suite [base_url] [delay_seconds]

base_url defaults to http://127.0.0.1:8000 (a locally running server).
Pass a deployed URL to run the same suite against production, e.g.:
    python -m tools.scope_regression_suite https://rti-sahayak.onrender.com

delay_seconds (default 6.0) is a pause before each case after the first -
Gate 12e's diagnosis was that this suite's failures were a per-minute
provider throttle, not a code defect: 10 cases (each 1-2 LLM calls) fired in
under two minutes was enough to trip it. Slowing the suite down is the fix,
not retrying faster.
"""
import json
import sys
import time
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DELAY_SECONDS = 6.0

# Each case's expected_status is what /api/draft should return for a
# well-formed request. "ok" means CHECK B judged it in-scope and a letter
# should be produced; "out_of_scope" means CHECK B should explicitly refuse
# it. The income-tax pair is deliberately adjacent in vocabulary - that's
# the whole point (see Gate 4/5 discussion): semantic distance to the Act's
# text could never separate a genuine record request from a how-to question
# about the same general subject.
FIXTURE = [
    {
        "label": "Homepage example 1: road repair",
        "problem_description": "My road repair complaint has been ignored for months",
        "expected_status": "ok",
    },
    {
        "label": "Homepage example 2: ration card",
        "problem_description": "My ration card renewal is stuck with no update",
        "expected_status": "ok",
    },
    {
        "label": "Homepage example 3: pension",
        "problem_description": "My pension payments have stopped without explanation",
        "expected_status": "ok",
    },
    {
        "label": "Homepage example 4: municipal complaint",
        "problem_description": "My complaint to the municipal office was never addressed",
        "expected_status": "ok",
    },
    {
        "label": "How-to advice question, not a records request",
        "problem_description": "how do I file my income tax return",
        "expected_status": "out_of_scope",
    },
    {
        "label": "Specific record request, income-tax-adjacent wording",
        "problem_description": "certified copy of my income tax return filed for AY 2023-24",
        "expected_status": "ok",
    },
    {
        "label": "Unrelated creative-writing request",
        "problem_description": "write me a poem about cricket",
        "expected_status": "out_of_scope",
    },
    {
        "label": "PMAY housing scheme selection criteria",
        "problem_description": (
            "I want to know the criteria used to select beneficiaries for the "
            "PMAY housing scheme in my ward"
        ),
        "expected_status": "ok",
    },
    {
        "label": "General financial advice, not a records request",
        "problem_description": "What is the best way to invest my savings for retirement?",
        "expected_status": "out_of_scope",
    },
    {
        "label": "Food safety complaint inspection report",
        "problem_description": (
            "I need the inspection report for the food safety complaint I filed "
            "against a local restaurant"
        ),
        "expected_status": "ok",
    },
]


def run_case(base_url: str, case: dict) -> dict:
    payload = {
        "full_name": "Ramesh Kulkarni",
        "address": "12, Shivaji Nagar",
        "locality": "Pune",
        "phone": "9876543210",
        "timeframe": "the last 6 months",
        "problem_description": case["problem_description"],
        "public_authority": "",
        "pio": "",
    }
    req = urllib.request.Request(
        f"{base_url}/api/draft",
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


def run_suite(base_url: str, delay_seconds: float) -> list[dict]:
    """Run FIXTURE against base_url and return the raw row list - split out
    from main() so other scripts (e.g. a combined verification report) can
    call this directly and get structured data back, not just printed text.
    """
    rows = []
    for i, case in enumerate(FIXTURE):
        if i > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)

        data = run_case(base_url, case)
        if "error" in data:
            rows.append(
                {
                    "label": case["label"],
                    "expected": case["expected_status"],
                    "actual": "REQUEST_ERROR",
                    "passed": False,
                    "scope_check_failed": None,
                    "authority": None,
                    "info_sought_count": None,
                    "detail": data["error"],
                }
            )
            continue

        actual_status = data.get("status", "<missing>")
        passed = actual_status == case["expected_status"]
        scope_check_failed = None
        authority = None
        info_sought_count = None

        if actual_status == "out_of_scope":
            detail = (data.get("meta") or {}).get("scope_reason", "<no reason returned>")
        elif actual_status == "ok":
            # scope_check_failed distinguishes a genuine in_scope=True verdict
            # from CHECK B's classification call having failed outright (see
            # web/api/draft.py: in_scope is None -> fail-open -> "ok" anyway,
            # with this exact warning attached). Without this, an "ok" row
            # looks identical whether the model actually judged it in-scope
            # or the classifier never got an answer at all - the distinction
            # this fixture exists to catch. info_sought_count is a second,
            # independent tell: the None/fail-open path always returns an
            # empty information_sought list, since UnderstandResult.__new__
            # for that branch has nothing else to work with.
            warnings_list = data.get("warnings") or []
            scope_check_failed = any("scope screening was unavailable" in w for w in warnings_list)
            authority = data.get("department_guess", "")
            info_sought_count = len(data.get("information_sought") or [])
            detail = (
                f"chunks_used={data.get('meta', {}).get('chunks_used')} "
                f"department_guess={authority[:60]!r} "
                f"info_sought_count={info_sought_count} "
                f"scope_check_failed={scope_check_failed}"
            )
        else:
            detail = json.dumps(data)[:200]

        rows.append(
            {
                "label": case["label"],
                "expected": case["expected_status"],
                "actual": actual_status,
                "passed": passed,
                "scope_check_failed": scope_check_failed,
                "authority": authority,
                "info_sought_count": info_sought_count,
                "detail": detail,
            }
        )
    return rows


def print_report(rows: list[dict]) -> int:
    print(f"{'PASS/FAIL':<9} {'EXPECTED':<13} {'ACTUAL':<17} LABEL / DETAIL")
    print("-" * 100)
    n_passed = 0
    for row in rows:
        mark = "PASS" if row["passed"] else "FAIL"
        n_passed += row["passed"]
        print(f"{mark:<9} {row['expected']:<13} {row['actual']:<17} {row['label']}")
        print(f"{'':<9} {'':<13} {'':<17} -> {row['detail']}")

    print()
    print(f"{n_passed}/{len(rows)} passed")
    return n_passed


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    delay_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DELAY_SECONDS
    print(f"Running scope regression suite against {base_url} (delay={delay_seconds}s)\n")

    rows = run_suite(base_url, delay_seconds)
    n_passed = print_report(rows)

    if n_passed != len(rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
