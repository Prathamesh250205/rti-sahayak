"""One-shot combined verification, run in the order specified: (1) the full
mocked llm.client provider-fallback/chain test suite - zero API cost, (2)
scope regression suite, (3) ask regression suite, (4) the 4-example x
3-language matrix. Steps 2-4 are paced (default 6s between calls - see
tools/scope_regression_suite.py's docstring for why) and hit the real
server/API exactly once each, in this single run.

Gate 13 context: with Anthropic in the provider chain as a last resort,
quota exhaustion should no longer be able to produce scope_check_failed=True
or an unresolved authority - if either still shows up, it's a real code
problem, not something attributable to provider quota.

Usage:
    python -m tools.gate12_verification [base_url] [delay_seconds]
"""
import json
import sys
import time
import urllib.request

import tools.ask_regression_suite as ask_suite
import tools.scope_regression_suite as scope_suite
import tools.test_llm_provider_fallback as fallback_test
from agent.drafter import UNKNOWN_AUTHORITY

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DELAY_SECONDS = 6.0

LANGUAGE_MATRIX_EXAMPLES = [
    ("Homepage example 1: road repair", "My road repair complaint has been ignored for months"),
    ("Homepage example 2: ration card", "My ration card renewal is stuck with no update"),
    ("Homepage example 3: pension", "My pension payments have stopped without explanation"),
    ("Homepage example 4: municipal complaint", "My complaint to the municipal office was never addressed"),
]
LANGUAGES = ["en", "hi", "mr"]

# Every function in tools.test_llm_provider_fallback whose name starts with
# "test_" - run all of them, not a hand-picked subset, so this step tracks
# that file as it grows instead of silently going stale.
_FALLBACK_TESTS = [
    getattr(fallback_test, name)
    for name in dir(fallback_test)
    if name.startswith("test_") and callable(getattr(fallback_test, name))
]


def run_language_matrix(base_url: str, delay_seconds: float) -> list[dict]:
    rows = []
    first = True
    for label, problem in LANGUAGE_MATRIX_EXAMPLES:
        for lang in LANGUAGES:
            if not first and delay_seconds > 0:
                time.sleep(delay_seconds)
            first = False

            payload = {
                "full_name": "Ramesh Kulkarni",
                "address": "12, Shivaji Nagar",
                "locality": "Pune",
                "phone": "9876543210",
                "timeframe": "the last 6 months",
                "problem_description": problem,
                "public_authority": "",
                "pio": "",
                "language": lang,
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
                rows.append(
                    {
                        "label": f"{label} [{lang}]", "expected": "ok", "actual": "REQUEST_ERROR",
                        "passed": False, "scope_check_failed": None, "authority": None,
                        "provider": None, "detail": str(e),
                    }
                )
                continue

            actual_status = data.get("status", "<missing>")
            passed = actual_status == "ok"
            warnings_list = data.get("warnings") or []
            scope_check_failed = any("scope screening was unavailable" in w for w in warnings_list)
            authority_unresolved = any("public authority could not be automatically determined" in w for w in warnings_list)
            authority = data.get("department_guess", "")
            provider = (data.get("meta") or {}).get("provider")
            rows.append(
                {
                    "label": f"{label} [{lang}]",
                    "expected": "ok",
                    "actual": actual_status,
                    "passed": passed,
                    "scope_check_failed": scope_check_failed,
                    "authority": authority,
                    "provider": provider,
                    "detail": (
                        f"chunks_used={data.get('meta', {}).get('chunks_used')} "
                        f"authority={authority[:50]!r} scope_check_failed={scope_check_failed} "
                        f"authority_unresolved_warning={authority_unresolved} provider={provider}"
                    ),
                }
            )
    return rows


def print_combined_table(scope_rows, ask_rows, matrix_rows):
    print("\n" + "=" * 125)
    print("COMBINED VERIFICATION TABLE")
    print("=" * 125)
    header = (
        f"{'SUITE':<12} {'PASS/FAIL':<9} {'EXPECTED':<15} {'ACTUAL':<17} {'SCOPE_FAIL':<11} "
        f"{'PROVIDER':<10} {'AUTHORITY':<40} LABEL"
    )
    print(header)
    print("-" * 125)

    def emit(suite_name, row):
        mark = "PASS" if row["passed"] else "FAIL"
        scope_fail = row.get("scope_check_failed")
        scope_fail_str = "-" if scope_fail is None else str(scope_fail)
        authority = row.get("authority") or "-"
        provider = row.get("provider") or "-"
        print(
            f"{suite_name:<12} {mark:<9} {str(row.get('expected', '-')):<15} "
            f"{str(row.get('actual', '-')):<17} {scope_fail_str:<11} {provider:<10} {authority[:38]:<40} {row['label']}"
        )

    for row in scope_rows:
        emit("scope", row)
    for row in ask_rows:
        # ask suite rows don't carry expected/actual/scope_check_failed/authority -
        # only label/passed/provider/detail (it's a grounding check, not a
        # scope check) - but provider is now real, not a placeholder.
        mark = "PASS" if row["passed"] else "FAIL"
        provider = row.get("provider") or "-"
        print(f"{'ask':<12} {mark:<9} {'-':<15} {'-':<17} {'-':<11} {provider:<10} {'-':<40} {row['label']}")
    for row in matrix_rows:
        emit("lang_matrix", row)

    print("-" * 125)
    total = len(scope_rows) + len(ask_rows) + len(matrix_rows)
    total_passed = sum(r["passed"] for r in scope_rows) + sum(r["passed"] for r in ask_rows) + sum(r["passed"] for r in matrix_rows)
    print(f"{total_passed}/{total} passed overall")

    scope_checked_rows = [r for r in (scope_rows + matrix_rows) if r.get("scope_check_failed") is not None]
    n_scope_failed = sum(1 for r in scope_checked_rows if r["scope_check_failed"])
    print(f"scope_check_failed: {n_scope_failed}/{len(scope_checked_rows)} rows had it True (want 0)")

    unresolved_authority_rows = [r for r in (scope_rows + matrix_rows) if r.get("authority") == UNKNOWN_AUTHORITY]
    print(f"authority resolved to the Unknown sentinel: {len(unresolved_authority_rows)} row(s) (want 0)")

    providers_seen = sorted({r["provider"] for r in (scope_rows + ask_rows + matrix_rows) if r.get("provider")})
    print(f"providers that served at least one request: {providers_seen}")


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    delay_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DELAY_SECONDS

    print("=" * 125)
    print(f"STEP 1/4: mocked provider-fallback/chain unit tests ({len(_FALLBACK_TESTS)} tests, no API cost)")
    print("=" * 125)
    for test_fn in _FALLBACK_TESTS:
        test_fn()

    print(f"\n{'=' * 125}")
    print(f"STEP 2/4: scope regression suite against {base_url} (delay={delay_seconds}s)")
    print("=" * 125)
    scope_rows = scope_suite.run_suite(base_url, delay_seconds)
    scope_suite.print_report(scope_rows)

    print(f"\n{'=' * 125}")
    print(f"STEP 3/4: ask regression suite against {base_url} (delay={delay_seconds}s)")
    print("=" * 125)
    time.sleep(delay_seconds)
    ask_rows = ask_suite.run_suite(base_url, delay_seconds)
    ask_suite.print_report(ask_rows)

    print(f"\n{'=' * 125}")
    print(f"STEP 4/4: 4-example x 3-language matrix against {base_url} (delay={delay_seconds}s)")
    print("=" * 125)
    time.sleep(delay_seconds)
    matrix_rows = run_language_matrix(base_url, delay_seconds)
    for row in matrix_rows:
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"{mark:<9} {row['label']}")
        print(f"{'':<9} -> {row['detail']}")

    print_combined_table(scope_rows, ask_rows, matrix_rows)


if __name__ == "__main__":
    main()
