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
    python -m tools.ask_regression_suite https://<your-deployment>.vercel.app

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
    # The next two were added after a real user hit "After how many days
    # PIO have to respond?" on the deployed site and got an honest refusal
    # instead of the answer - the retrieved Section 7(1) chunk existed but
    # ranked outside ANSWER_TOP_K=5 (now 10). "PIO response deadline" above
    # already covers that exact regression; these two extend the fixture to
    # the other two questions raised alongside it.
    {
        "label": "First appeal deadline",
        "question": "how long do I have to file a first appeal",
        "expected_status": "ok",
        "expected_sections": ["Section 19"],
    },
    {
        # KNOWN FAILING - not dropped, recorded honestly. Section 7(6) (fee
        # waiver when a PIO misses the deadline) was found mislabeled in the
        # index: the general chunker put it in the same chunk as unrelated
        # sub-section (4)/(5) content (disability-access assistance,
        # printed/electronic-format fees), diluting its embedding. A
        # targeted fix (rag/ingest.py's _split_section_7_at_subsections,
        # Section 7 only) improved it from rank 46/78 (distance 0.877) to
        # rank 21/83 (distance 0.786) - real progress, but still outside
        # ANSWER_TOP_K=10 and the 0.75 grounding threshold for this exact
        # phrasing. Raising the threshold to catch it was deliberately not
        # done - see the "30 days RTI" note in README's Known limitations -
        # and corpus-wide re-chunking was ruled out for its blast radius on
        # Sections 2/4/16/19. This case is expected to fail until a further
        # fix lands; if it ever starts passing, that's worth investigating
        # (see KNOWN_FAILING handling in evaluate()/print_report() below).
        "label": "Fee waiver on missed deadline (Section 7(6))",
        "question": "what happens if the PIO misses the deadline",
        "expected_status": "ok",
        "expected_sections": ["Section 7"],
        "expected_chunk_text_contains": "free of charge",
        "known_failing": (
            "Section 7(6)'s fee-waiver chunk ranks ~21st of 83 chunks for this "
            "phrasing (distance ~0.79) - inside neither ANSWER_TOP_K=10 nor the "
            "0.75 grounding threshold, even after the targeted Section 7 chunking "
            "fix. See this case's comment in FIXTURE above for the full history."
        ),
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
        with urllib.request.urlopen(req, timeout=120) as resp:
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

    # A bare section-name match isn't precise enough for a fixture that
    # cares about ONE specific sub-section's content, not just any chunk
    # from that section (e.g. Section 7 has 9 sub-sections after the
    # targeted chunking fix - "cited Section 7" alone doesn't tell you
    # WHICH one). Checked against the retrieved chunks' own text, not just
    # what the model happened to cite - a stricter, more mechanical signal
    # of whether the right content was even reachable at all.
    needle = case.get("expected_chunk_text_contains")
    if needle:
        chunk_texts = [c.get("text", "") for c in (data.get("chunks") or [])]
        if not any(needle.lower() in t.lower() for t in chunk_texts):
            return False, (
                f"cited {sorted(cited_sections)}, but no retrieved chunk contained "
                f"{needle!r} - the specific content this question needs wasn't reachable"
            )

    return True, f"{len(citations)} citation(s) into {sorted(cited_sections)}"


def run_suite(base_url: str, delay_seconds: float) -> list[dict]:
    rows = []
    for i, case in enumerate(FIXTURE):
        if i > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)

        known_failing = case.get("known_failing")
        data = run_case(base_url, case)
        if "error" in data:
            rows.append({"label": case["label"], "passed": False, "known_failing": known_failing, "provider": None, "latency_ms": None, "detail": data["error"]})
            continue
        passed, detail = evaluate(case, data)
        provider = (data.get("meta") or {}).get("provider")
        latency_ms = (data.get("meta") or {}).get("latency_ms")
        rows.append({
            "label": case["label"], "passed": passed, "known_failing": known_failing,
            "provider": provider, "latency_ms": latency_ms,
            "detail": detail + f" (provider={provider} latency_ms={latency_ms})",
        })
    return rows


def print_report(rows: list[dict]) -> int:
    # Known-failing rows (see FIXTURE) are reported honestly, never quietly
    # dropped or folded into the core pass rate - a case documented as
    # "expected to fail until a further fix lands" corrupting the headline
    # N/M number would make every future run look like a regression that
    # isn't one. XFAIL = failing exactly as documented; XPASS = it started
    # passing anyway, which is itself worth noticing (the documented reason
    # may be stale - the fix may have landed some other way).
    core_rows = [r for r in rows if not r.get("known_failing")]
    known_rows = [r for r in rows if r.get("known_failing")]

    print(f"{'PASS/FAIL':<9} LABEL / DETAIL")
    print("-" * 100)
    n_passed = 0
    for row in core_rows:
        mark = "PASS" if row["passed"] else "FAIL"
        n_passed += row["passed"]
        print(f"{mark:<9} {row['label']}")
        print(f"{'':<9} -> {row['detail']}")

    if known_rows:
        print()
        print("Known-failing (excluded from the pass rate above, tracked separately):")
        for row in known_rows:
            mark = "XPASS - now passing, investigate why" if row["passed"] else "XFAIL - failing as documented"
            print(f"{mark:<40} {row['label']}")
            print(f"{'':<9} -> {row['detail']}")
            print(f"{'':<9} -> reason: {row['known_failing']}")

    print()
    print(f"{n_passed}/{len(core_rows)} passed" + (f", {len(known_rows)} known-failing case(s) tracked separately" if known_rows else ""))
    return n_passed, len(core_rows)


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    delay_seconds = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DELAY_SECONDS
    print(f"Running ask regression suite against {base_url} (delay={delay_seconds}s)\n")

    rows = run_suite(base_url, delay_seconds)
    n_passed, n_core = print_report(rows)

    if n_passed != n_core:
        sys.exit(1)


if __name__ == "__main__":
    main()
