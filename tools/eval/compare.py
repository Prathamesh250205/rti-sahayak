"""Gate E3: side-by-side comparison of the new two-check design against the
reconstructed old distance gate, on the identical 113-case dataset.

Uses run_eval.py's cache for the new-design results (should be a 100% cache
hit if Gate E2 has already run) and old_gate_eval's pure-retrieval path for
the old gate (no API cost either way, so this comparison itself is free
once E2's cache is warm).

Usage:
    python -m tools.eval.compare [base_url] [delay_seconds]
"""
import sys

from tools.eval.run_eval import CASE_TYPES, compute_metrics, is_correct, load_dataset
from tools.eval.run_eval import DEFAULT_BASE_URL, DEFAULT_DELAY_SECONDS
from tools.eval.run_eval import run as run_new_gate
from tools.eval.run_old_gate_eval import run as run_old_gate


def fmt(x: float) -> str:
    return "nan" if x != x else f"{x:.3f}"


def print_comparison(new_results: list[dict], old_results: list[dict]):
    print("\n" + "=" * 100)
    print("GATE E3 - two_check_v1 (new) vs old_distance_gate_v1 (reconstructed), same 113 cases")
    print("=" * 100)

    new_m = compute_metrics(new_results, "two_check_v1")
    old_m = compute_metrics(old_results, "old_distance_gate_v1")

    print(f"\n{'metric':<28} {'NEW (two_check)':<20} {'OLD (distance gate)':<20} {'winner'}")
    print("-" * 90)
    rows = [
        ("n", new_m["n"], old_m["n"], ""),
        ("Precision", new_m["precision"], old_m["precision"], "NEW" if new_m["precision"] > old_m["precision"] else ("OLD" if old_m["precision"] > new_m["precision"] else "tie")),
        ("Recall", new_m["recall"], old_m["recall"], "NEW" if new_m["recall"] > old_m["recall"] else ("OLD" if old_m["recall"] > new_m["recall"] else "tie")),
        ("F1", new_m["f1"], old_m["f1"], "NEW" if new_m["f1"] > old_m["f1"] else ("OLD" if old_m["f1"] > new_m["f1"] else "tie")),
        ("False refusal rate", new_m["false_refusal_rate"], old_m["false_refusal_rate"],
         "NEW" if new_m["false_refusal_rate"] < old_m["false_refusal_rate"] else ("OLD" if old_m["false_refusal_rate"] < new_m["false_refusal_rate"] else "tie")),
        ("Predicted in_scope rate", new_m["predicted_in_scope_rate"], old_m["predicted_in_scope_rate"], ""),
    ]
    for name, nv, ov, winner in rows:
        nv_s = fmt(nv) if isinstance(nv, float) else str(nv)
        ov_s = fmt(ov) if isinstance(ov, float) else str(ov)
        print(f"{name:<28} {nv_s:<20} {ov_s:<20} {winner}")
    print(f"\nActual base rate (both gates, same data): {fmt(new_m['base_rate'])}")
    print(f"Confusion - NEW: TP={new_m['tp']} FP={new_m['fp']} TN={new_m['tn']} FN={new_m['fn']}")
    print(f"Confusion - OLD: TP={old_m['tp']} FP={old_m['fp']} TN={old_m['tn']} FN={old_m['fn']}")

    print("\n" + "-" * 100)
    print("PER-CASE_TYPE BREAKDOWN - BOTH GATES (the grievance row, n=40, is the headline)")
    print("-" * 100)
    print(f"{'case_type':<20} {'n':<5} {'NEW correct':<14} {'NEW %':<8} {'OLD correct':<14} {'OLD %':<8} winner")
    for ct in CASE_TYPES:
        new_rows = [r for r in new_results if r["case_type"] == ct]
        old_rows = [r for r in old_results if r["case_type"] == ct]
        if not new_rows:
            continue
        new_correct = sum(1 for r in new_rows if is_correct(r))
        old_correct = sum(1 for r in old_rows if is_correct(r))
        new_pct = 100 * new_correct / len(new_rows)
        old_pct = 100 * old_correct / len(old_rows)
        winner = "NEW" if new_pct > old_pct else ("OLD" if old_pct > new_pct else "tie")
        flag = "  [UNDERPOWERED n<20]" if len(new_rows) < 20 else ""
        print(f"{ct:<20} {len(new_rows):<5} {new_correct:<14} {new_pct:<8.1f} {old_correct:<14} {old_pct:<8.1f} {winner}{flag}")

    print("\n" + "-" * 100)
    print("PER-LANGUAGE BREAKDOWN - BOTH GATES")
    print("-" * 100)
    print(f"{'language':<12} {'n':<5} {'NEW FRR':<10} {'OLD FRR':<10} {'NEW precision':<15} {'OLD precision':<15}")
    for lang in ["en", "hi", "mr"]:
        nr = [r for r in new_results if r["language"] == lang]
        orow = [r for r in old_results if r["language"] == lang]
        if not nr:
            continue
        nm = compute_metrics(nr, lang)
        om = compute_metrics(orow, lang)
        flag = "  [UNDERPOWERED n<20]" if len(nr) < 20 else ""
        print(f"{lang:<12} {len(nr):<5} {fmt(nm['false_refusal_rate']):<10} {fmt(om['false_refusal_rate']):<10} "
              f"{fmt(nm['precision']):<15} {fmt(om['precision']):<15}{flag}")

    print("\n" + "-" * 100)
    print("ADVERSARIAL-PAIR ACCURACY - BOTH GATES")
    print("-" * 100)
    new_adv = [r for r in new_results if r["category"] == "adversarial"]
    old_adv = [r for r in old_results if r["category"] == "adversarial"]
    new_adv_correct = sum(1 for r in new_adv if is_correct(r))
    old_adv_correct = sum(1 for r in old_adv if is_correct(r))
    print(f"NEW: {new_adv_correct}/{len(new_adv)} ({100*new_adv_correct/len(new_adv):.1f}%)")
    print(f"OLD: {old_adv_correct}/{len(old_adv)} ({100*old_adv_correct/len(old_adv):.1f}%)")

    print("\n" + "-" * 100)
    print("WHERE THE OLD GATE WINS (explicit callout - a comparison with only one side winning is not evidence)")
    print("-" * 100)
    old_wins = []
    if old_m["precision"] > new_m["precision"]:
        old_wins.append(f"Precision: OLD {fmt(old_m['precision'])} > NEW {fmt(new_m['precision'])}")
    for ct in CASE_TYPES:
        new_rows = [r for r in new_results if r["case_type"] == ct]
        old_rows = [r for r in old_results if r["case_type"] == ct]
        if not new_rows:
            continue
        new_pct = 100 * sum(1 for r in new_rows if is_correct(r)) / len(new_rows)
        old_pct = 100 * sum(1 for r in old_rows if is_correct(r)) / len(old_rows)
        if old_pct > new_pct:
            old_wins.append(f"case_type={ct}: OLD {old_pct:.1f}% > NEW {new_pct:.1f}% (n={len(new_rows)})")
    if old_wins:
        for w in old_wins:
            print(f"  - {w}")
    else:
        print("  (none found on any reported slice)")

    print("\n" + "-" * 100)
    print("EVERY CASE WHERE THE TWO GATES DISAGREE")
    print("-" * 100)
    n_disagree = 0
    for nr, orow in zip(new_results, old_results):
        if nr["predicted"] != orow["predicted"]:
            n_disagree += 1
            print(f"[{nr['id']}] ({nr['language']}, {nr['case_type']}) gold={nr['label']}  "
                  f"NEW={nr['predicted']}  OLD={orow['predicted']}")
            print(f"       {nr['query']}")
            print(f"       OLD reason: {orow['reason']}")
    print(f"\nTotal disagreements: {n_disagree}/{len(new_results)}")


def main():
    base_url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else DEFAULT_BASE_URL
    delay = float(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DELAY_SECONDS

    print("Loading NEW gate results (cache should already be warm from Gate E2)...")
    new_results = run_new_gate(base_url, delay)

    print("\nComputing OLD gate results (pure retrieval, no API cost)...")
    old_results = run_old_gate()

    print_comparison(new_results, old_results)


if __name__ == "__main__":
    main()
