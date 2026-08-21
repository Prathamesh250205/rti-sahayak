"""Regression suite for the CHECK B scope classification (Gate 5).

Runs a small fixture of labelled citizen requests through the real
POST /api/draft endpoint - not retrieve() or understand_request() in
isolation - and reports pass/fail against each case's expected status.

Usage:
    python -m tools.scope_regression_suite [base_url]

base_url defaults to http://127.0.0.1:8000 (a locally running server).
Pass a deployed URL to run the same suite against production, e.g.:
    python -m tools.scope_regression_suite https://rti-sahayak.onrender.com
"""
import json
import sys
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8000"

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


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    print(f"Running scope regression suite against {base_url}\n")

    rows = []
    for case in FIXTURE:
        data = run_case(base_url, case)
        if "error" in data:
            rows.append(
                {
                    "label": case["label"],
                    "expected": case["expected_status"],
                    "actual": "REQUEST_ERROR",
                    "passed": False,
                    "detail": data["error"],
                }
            )
            continue

        actual_status = data.get("status", "<missing>")
        passed = actual_status == case["expected_status"]

        if actual_status == "out_of_scope":
            detail = (data.get("meta") or {}).get("scope_reason", "<no reason returned>")
        elif actual_status == "ok":
            detail = (
                f"chunks_used={data.get('meta', {}).get('chunks_used')} "
                f"department_guess={data.get('department_guess', '')[:60]!r}"
            )
        else:
            detail = json.dumps(data)[:200]

        rows.append(
            {
                "label": case["label"],
                "expected": case["expected_status"],
                "actual": actual_status,
                "passed": passed,
                "detail": detail,
            }
        )

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

    if n_passed != len(rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
