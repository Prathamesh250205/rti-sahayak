"""Gate E3: run tools/eval/dataset.jsonl through the reconstructed old
distance-gate (tools/eval/old_gate.py) - evaluation-only, no HTTP, no LLM
call, pure retrieval. Produces the same report shape as run_eval.py so the
two are directly comparable; see tools/eval/compare.py for the side-by-side.

Usage:
    python -m tools.eval.run_old_gate_eval
"""
from tools.eval.old_gate import old_gate_predict
from tools.eval.run_eval import load_dataset, print_report

SYSTEM_ID = "old_distance_gate_v1"


def run() -> list[dict]:
    dataset = load_dataset()
    results = []
    for i, case in enumerate(dataset):
        predicted, reason = old_gate_predict(case["query"])
        results.append({**case, "predicted": predicted, "reason": reason, "raw_status": "n/a (no HTTP call)"})
        print(f"[{i+1:>3}/{len(dataset)}] gold={case['label']:<12} pred={str(predicted):<5} :: {case['query'][:70]}")
    return results


def main():
    print(f"Running Gate E3 old-gate eval (system_id={SYSTEM_ID}) - pure retrieval, no API cost\n")
    results = run()
    print_report(results)
    return results


if __name__ == "__main__":
    main()
