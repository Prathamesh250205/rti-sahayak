"""Gate E2: measure the live two-check scope gate (CHECK A + CHECK B, see
README's "The two-check grounding design") against tools/eval/dataset.jsonl,
through the real POST /api/draft path - not understand_request() in
isolation, so this measures exactly what a citizen actually experiences.

Responses are cached (tools/eval/cache.py) keyed by (system_id, language,
query) - a second run against unchanged cases costs zero API calls. Delete
tools/eval/.cache/responses.json to force a clean re-run.

Usage:
    python -m tools.eval.run_eval [base_url] [delay_seconds]
"""
import json
import os
import sys
import time
import urllib.request
from collections import Counter, defaultdict

from tools.eval.cache import cache_key, load_cache, save_cache

SYSTEM_ID = "two_check_v1"  # the live app's current CHECK A + CHECK B design
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_DELAY_SECONDS = 2.5
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset.jsonl")

CASE_TYPES = ["explicit_request", "grievance", "advice_seeking", "opinion_prediction", "service_request"]


def load_dataset() -> list[dict]:
    with open(DATASET_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def call_draft_api(base_url: str, case: dict) -> dict:
    payload = {
        "full_name": "Eval Citizen",
        "address": "1, Eval Lane",
        "phone": "9999999999",
        "problem_description": case["query"],
        "language": case["language"],
    }
    req = urllib.request.Request(
        f"{base_url}/api/draft",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_response(base_url: str, case: dict, cache: dict, delay: float) -> tuple[dict, bool]:
    key = cache_key(SYSTEM_ID, case["language"], case["query"])
    if key in cache:
        return cache[key], True
    if delay > 0:
        time.sleep(delay)
    try:
        data = call_draft_api(base_url, case)
    except Exception as e:
        # Deliberately NOT cached: a 429 (this app's own per-IP rate limiter,
        # web/rate_limit.py - 30 req/300s) or a connection/timeout failure is
        # a transient artifact of how fast THIS run happened to fire
        # requests, not a scope-classification answer. Caching it would
        # permanently freeze a pacing mistake into every future "free"
        # re-run. Only genuine application-level responses (whatever status
        # the app itself decided on) are cache-worthy.
        return {"status": "error", "error": str(e)}, False
    cache[key] = data
    save_cache(cache)  # incremental - a crash mid-run doesn't lose progress
    return data, False


def extract_verdict(data: dict) -> tuple[bool | None, str]:
    """Returns (predicted_in_scope, reason). predicted_in_scope is None for
    a request the system never rendered a scope verdict for at all
    (insufficient_grounding / error) - that's a service failure, not a
    scope-classification answer, and must never be silently folded into
    either True or False.
    """
    status = data.get("status")
    if status == "ok":
        return True, "(drafted - CHECK B judged in_scope; no refusal reason to report)"
    if status == "out_of_scope":
        return False, (data.get("meta") or {}).get("scope_reason", "(no reason recorded)")
    if status == "insufficient_grounding":
        return None, "insufficient_grounding - CHECK A found no procedural grounding at all (service/index issue)"
    return None, data.get("error") or f"unexpected status={status!r}"


def run(base_url: str, delay: float) -> list[dict]:
    dataset = load_dataset()
    cache = load_cache()
    results = []
    n_cache_hits = 0
    for i, case in enumerate(dataset):
        data, was_cached = get_response(base_url, case, cache, delay)
        n_cache_hits += was_cached
        predicted, reason = extract_verdict(data)
        results.append({**case, "predicted": predicted, "reason": reason, "raw_status": data.get("status")})
        mark = "CACHED" if was_cached else "LIVE  "
        print(f"[{i+1:>3}/{len(dataset)}] {mark} gold={case['label']:<12} pred={str(predicted):<5} :: {case['query'][:70]}")
    print(f"\nCache hits: {n_cache_hits}/{len(dataset)} ({len(dataset) - n_cache_hits} live calls made)")
    return results


def is_correct(r: dict) -> bool:
    """True only if the system rendered an actual verdict AND it matched
    gold. predicted=None (no_verdict) must never read as "correct" -
    `(None is True) == (label == "in_scope")` evaluates to True for every
    out-of-scope no-verdict case (False == False), which silently hid 37
    genuinely-unresolved cases as passes in the first draft of this script.
    Caught before reporting any number built on it.
    """
    return r["predicted"] is not None and r["predicted"] == (r["label"] == "in_scope")


def _prf1(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if (tp + fp) else float("nan")
    recall = tp / (tp + fn) if (tp + fn) else float("nan")
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) and precision == precision and recall == recall else float("nan")
    return precision, recall, f1


def compute_metrics(rows: list[dict], label: str = "") -> dict:
    """Confusion matrix + precision/recall/F1 + false-refusal rate over one
    slice of rows. no_verdict rows (insufficient_grounding/error) are
    reported but excluded from precision/recall/F1's denominators - they
    are a different failure mode (the system never reached a verdict at
    all), not a wrong verdict. A second, fully-inclusive miss rate is also
    reported so nothing is hidden by that exclusion either.
    """
    tp = sum(1 for r in rows if r["label"] == "in_scope" and r["predicted"] is True)
    fp = sum(1 for r in rows if r["label"] == "out_of_scope" and r["predicted"] is True)
    tn = sum(1 for r in rows if r["label"] == "out_of_scope" and r["predicted"] is False)
    fn = sum(1 for r in rows if r["label"] == "in_scope" and r["predicted"] is False)
    no_verdict_in = sum(1 for r in rows if r["label"] == "in_scope" and r["predicted"] is None)
    no_verdict_out = sum(1 for r in rows if r["label"] == "out_of_scope" and r["predicted"] is None)

    precision, recall, f1 = _prf1(tp, fp, fn)
    total_in_scope = tp + fn  # verdict-bearing in-scope cases only
    false_refusal_rate = fn / total_in_scope if total_in_scope else float("nan")
    total_in_scope_incl = tp + fn + no_verdict_in
    false_refusal_rate_inclusive = (fn + no_verdict_in) / total_in_scope_incl if total_in_scope_incl else float("nan")

    # Leniency check: does the gate predict in_scope more often than the
    # slice's own actual base rate? A gate that says "yes" whenever unsure
    # would show a perfect false-refusal rate for a boring reason - that
    # would be bias toward yes, not precision, and must be visible here,
    # not just inferable from precision alone.
    n_base = sum(1 for r in rows if r["label"] == "in_scope")
    base_rate = n_base / len(rows) if rows else float("nan")
    predicted_in_scope_rate = (tp + fp) / len(rows) if rows else float("nan")

    return {
        "label": label, "n": len(rows), "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "no_verdict_in_scope": no_verdict_in, "no_verdict_out_of_scope": no_verdict_out,
        "precision": precision, "recall": recall, "f1": f1,
        "false_refusal_rate": false_refusal_rate,
        "false_refusal_rate_inclusive": false_refusal_rate_inclusive,
        "base_rate": base_rate, "predicted_in_scope_rate": predicted_in_scope_rate,
        "underpowered": len(rows) < 20,
    }


def print_metrics_block(m: dict):
    flag = "  [UNDERPOWERED: n<20 - cannot distinguish e.g. 1.00 from 0.90 at this sample size]" if m["underpowered"] else ""
    print(f"\n--- {m['label']} (n={m['n']}){flag} ---")
    print(f"Confusion matrix: TP={m['tp']}  FP={m['fp']}  TN={m['tn']}  FN={m['fn']}"
          f"  | no-verdict: in_scope={m['no_verdict_in_scope']} out_of_scope={m['no_verdict_out_of_scope']}")
    print(f"Precision={m['precision']:.3f}  Recall={m['recall']:.3f}  F1={m['f1']:.3f}")
    print(f"FALSE REFUSAL RATE = {m['false_refusal_rate']:.3f}  "
          f"({m['fn']}/{m['tp']+m['fn']} verdict-bearing in-scope cases wrongly refused)")
    if m["no_verdict_in_scope"]:
        print(f"  (inclusive false-refusal-or-no-verdict rate, counting service failures too: "
              f"{m['false_refusal_rate_inclusive']:.3f})")
    gap = m["predicted_in_scope_rate"] - m["base_rate"]
    print(f"Predicted in_scope rate={m['predicted_in_scope_rate']:.3f}  vs. actual base rate={m['base_rate']:.3f}"
          f"  (gap={gap:+.3f}){'  <- predicts in_scope more often than the base rate: leniency, not pure precision' if gap > 0.03 else ''}")


def print_report(results: list[dict]):
    print("\n" + "=" * 100)
    print("GATE E2 RESULTS - two_check_v1 (live system) vs tools/eval/dataset.jsonl")
    print("=" * 100)

    overall = compute_metrics(results, "OVERALL")
    print_metrics_block(overall)

    print("\n" + "-" * 100)
    print("PER-LANGUAGE BREAKDOWN")
    print("-" * 100)
    for lang in ["en", "hi", "mr"]:
        rows = [r for r in results if r["language"] == lang]
        if rows:
            print_metrics_block(compute_metrics(rows, f"language={lang}"))

    print("\n" + "-" * 100)
    print("ADVERSARIAL-PAIR ACCURACY (reported separately, not folded into the overall figure)")
    print("-" * 100)
    adv_rows = [r for r in results if r["category"] == "adversarial"]
    adv_correct = sum(1 for r in adv_rows if is_correct(r))
    adv_no_verdict = sum(1 for r in adv_rows if r["predicted"] is None)
    print(f"{adv_correct}/{len(adv_rows)} adversarial cases correct "
          f"({100*adv_correct/len(adv_rows):.1f}%), across {len(adv_rows)//2} pairs"
          + (f"  [{adv_no_verdict} no_verdict]" if adv_no_verdict else "")
          + ("  [UNDERPOWERED: n<20]" if len(adv_rows) < 20 else ""))
    adv_in = [r for r in adv_rows if r["label"] == "in_scope"]
    adv_out = [r for r in adv_rows if r["label"] == "out_of_scope"]
    adv_in_correct = sum(1 for r in adv_in if r["predicted"] is True)
    adv_out_correct = sum(1 for r in adv_out if r["predicted"] is False)
    print(f"  in-scope half:     {adv_in_correct}/{len(adv_in)} correct"
          f"  [{sum(1 for r in adv_in if r['predicted'] is None)} no_verdict]")
    print(f"  out-of-scope half: {adv_out_correct}/{len(adv_out)} correct"
          f"  [{sum(1 for r in adv_out if r['predicted'] is None)} no_verdict]")

    print("\n" + "-" * 100)
    print("PER-CASE_TYPE BREAKDOWN")
    print("-" * 100)
    for ct in CASE_TYPES:
        rows = [r for r in results if r["case_type"] == ct]
        if not rows:
            continue
        correct = sum(1 for r in rows if is_correct(r))
        no_verdict = sum(1 for r in rows if r["predicted"] is None)
        incorrect = len(rows) - correct - no_verdict
        flag = "  [UNDERPOWERED: n<20]" if len(rows) < 20 else ""
        print(f"{ct:<20} n={len(rows):<4} correct={correct:<4} ({100*correct/len(rows):.1f}%)  "
              f"incorrect={incorrect}  no_verdict={no_verdict}{flag}")
        if ct == "grievance":
            print("  ^ THE key slice: pure grievances, no document named - where the old distance gate")
            print("    produced false refusals. See Gate E3 for the side-by-side comparison.")

    print("\n" + "-" * 100)
    print(f"CONTESTED / AMBIGUOUS CASES (n={sum(1 for r in results if r.get('contested'))}, reported on their own, "
          f"not folded into headline numbers)")
    print("-" * 100)
    for r in results:
        if r.get("contested"):
            correct = is_correct(r)
            alt = r.get("sensitivity_alt_label")
            print(f"[{r['id']}] primary_gold={r['label']:<12} alt_gold={str(alt):<12} pred={str(r['predicted']):<5} "
                  f"{'(matches primary)' if correct else '(DIFFERS from primary)'}")
            print(f"       {r['query']}")
            print(f"       system's stated reason: {r['reason']}")

    print("\n" + "-" * 100)
    print("SENSITIVITY ANALYSIS: score all 20 contested cases on their alternative reading instead")
    print("-" * 100)
    print("Per instruction: relabelling only the cases the system got wrong would be cherry-picking.")
    print("This flips ALL 20 contested cases (see tools/eval/README.md) to their documented")
    print("alternative gold label and rescores OVERALL - most of them the system already answered")
    print("correctly under the PRIMARY label, so flipping turns those into misses under the")
    print("alternative view. Both numbers are real; neither is hidden.")
    sensitivity_rows = []
    for r in results:
        alt = r.get("sensitivity_alt_label")
        if r.get("contested") and alt:
            sensitivity_rows.append({**r, "label": alt})
        else:
            sensitivity_rows.append(r)
    print_metrics_block(compute_metrics(results, "PRIMARY (as labelled)"))
    print_metrics_block(compute_metrics(sensitivity_rows, "SENSITIVITY (20 contested cases on alt reading)"))
    n_flipped_to_correct = sum(1 for r, s in zip(results, sensitivity_rows) if not is_correct(r) and is_correct(s))
    n_flipped_to_incorrect = sum(1 for r, s in zip(results, sensitivity_rows) if is_correct(r) and not is_correct(s))
    print(f"\nUnder the alternative reading: {n_flipped_to_correct} case(s) flip from incorrect to correct, "
          f"{n_flipped_to_incorrect} case(s) flip from correct to incorrect.")

    print("\n" + "-" * 100)
    print("EVERY MISCLASSIFIED CASE (predicted != gold, including no-verdict)")
    print("-" * 100)
    n_misclassified = 0
    for r in results:
        if not is_correct(r):
            n_misclassified += 1
            print(f"[{r['id']}] ({r['language']}, {r['case_type']}) gold={r['label']} pred={r['predicted']} status={r['raw_status']}")
            print(f"       query: {r['query']}")
            print(f"       system's stated reason: {r['reason']}")
    if n_misclassified == 0:
        print("(none)")
    print(f"\nTotal misclassified: {n_misclassified}/{len(results)}")


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DELAY_SECONDS
    print(f"Running Gate E2 eval against {base_url} (delay={delay}s, system_id={SYSTEM_ID})\n")
    results = run(base_url, delay)
    print_report(results)


if __name__ == "__main__":
    main()
