from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.modules.runtime_projection import run_projection_spike


def _summary(report: dict) -> dict:
    cases = {}
    for case_id, result in report["cases"].items():
        cases[case_id] = {
            "virtual_context_id": result["virtual_context_id"],
            "root_completeness": result["root_projection"]["completeness"],
            "stage_completeness": result["stage_completeness_counts"],
            "strategy_lineage": result["strategy_lineage"],
            "current_projection": result["current_projection"]["status"],
            "review_risks": result["review_binding_risks"],
            "blocking_reasons": result["blocking_reasons"],
            "stage_expectation_diff": result["stage_expectation_diff_count"],
        }
    return {
        "result_classification": report["result_classification"],
        "frozen_contract": report["frozen_contract"],
        "normative_vectors": report["normative_vectors"],
        "cases": cases,
        "determinism": report["determinism"],
        "safety": report["safety"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen #19/#40 read-only Runtime projection Spike.")
    parser.add_argument("--db", type=Path, default=None, help="Exact fixed SQLite database path.")
    parser.add_argument("--output", type=Path, help="Optional path for the full JSON projection artifact.")
    args = parser.parse_args()
    report = run_projection_spike(args.db) if args.db else run_projection_spike()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(_summary(report), ensure_ascii=False, indent=2))
    return 0 if report["result_classification"] == "SPIKE_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
