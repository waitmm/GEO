from __future__ import annotations

import argparse
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import SessionLocal, init_db
from app.models import Project
from app.modules.optimization.readiness_report import build_v1_1_final_acceptance_report


def _fmt_ms(value) -> str:
    if value is None:
        return "not_run"
    return f"{int(value)} ms"


def _prompt_section(item: dict) -> str:
    source_claim = item["source_claims"]
    alignment = item["evidence_alignment"]
    run_scope = item["run_scope"]
    downstream = item["downstream"]
    workflow = item["workflow"]
    return f"""## Prompt #{item["prompt_id"]}

- Runs: {run_scope.get("run_count")} from {run_scope.get("source")} (Evidence Package #{run_scope.get("evidence_package_id")} v{run_scope.get("evidence_package_version")})
- Candidate keys: {alignment.get("candidate_keys")}
- Planner vs Production candidate diff: {alignment.get("planner_vs_production_diff")}
- SourceClaim required/hits/external calls: {source_claim.get("required")} / {source_claim.get("materialization_hit")} ledger hit + {source_claim.get("legacy_reusable")} legacy / {source_claim.get("external_llm_required")}
- SourceClaim recovery: {source_claim.get("llm_call_cache_hit")} LLMCallCache hits, {source_claim.get("failed_retryable")} retryable, {source_claim.get("failed_final")} final failed
- Alignment naive/candidates/hits/external calls: {alignment.get("naive_pairs")} / {alignment.get("candidate_keys")} / {alignment.get("materialization_hit")} ledger hit + {alignment.get("legacy_reusable")} legacy / {alignment.get("external_llm_required")}
- Recall: {alignment.get("recall_layer_counts")}
- Benchmark: {downstream.get("benchmark")}
- Gap: {downstream.get("gap")}
- Strategy: {downstream.get("strategy")}
- Workflow: Step 7={workflow.get("strategy_step_status")}, Step 8={workflow.get("execution_step_status")}
- Durations: planner={_fmt_ms(item["durations_ms"].get("planner_duration"))}, production dry-run={_fmt_ms(item["durations_ms"].get("production_candidate_dry_run_duration"))}, total={_fmt_ms(item["durations_ms"].get("total_readiness_report_duration"))}
"""


def render_markdown(report: dict) -> str:
    prompts = "\n".join(_prompt_section(item) for item in report["prompts"])
    duplicate = "\n".join(
        f"- {row['runs']} Runs: SourceClaim unique jobs={row['source_claim_unique_jobs']}, "
        f"Alignment unique jobs={row['alignment_unique_jobs']}, expensive semantic work delta={row['expensive_semantic_work_delta']}"
        for row in report["duplicate_run_stress"]
    )
    citation = "\n".join(
        f"- {row['citations']} citations: naive pairs={row['naive_pairs']}, final candidates={row['final_candidates']}, "
        f"LLM amplification ratio={row['llm_amplification_ratio']}"
        for row in report["citation_stress"]
    )
    gate = report["final_gate"]
    immediate = report["immediate_rerun"]
    return f"""# GEO V1.1 Final Acceptance

Generated at: {report["generated_at"]}

Architecture: {report["architecture"]}

{prompts}
## Immediate Rerun

- SourceClaim external calls: {immediate["source_claim_external_calls"]}
- Alignment external calls: {immediate["alignment_external_calls"]}
- Status: {immediate["status"]}
- Duration: {immediate["duration_ms"] or "not_run"}

## Duplicate Run Stress

{duplicate}

## Citation Stress

{citation}

## Reliability

- Single-flight: {report["reliability"]["single_flight"]}
- Lease: {report["reliability"]["lease"]}
- Retry: {report["reliability"]["retry"]}
- Resume: {report["reliability"]["resume"]}
- Failed-final: {report["reliability"]["failed_final"]}

## UX

- Progress visible: {report["ux"]["progress_visible"]}
- Failure visible: {report["ux"]["failure_visible"]}
- Remaining work visible: {report["ux"]["remaining_work_visible"]}
- Resume available: {report["ux"]["resume_available"]}
- Resume semantics: {report["ux"]["resume_semantics"]}

## External Smoke

- SourceClaim: {report["external_smoke"]["source_claim"]}
- Alignment: {report["external_smoke"]["alignment"]}
- Single-flight: {report["external_smoke"]["single_flight"]}
- Concurrency: {report["external_smoke"]["concurrency"]}
- Retry: {report["external_smoke"]["retry"]}

## Final Gate

- INTERNAL_PRODUCT_READY: {gate["INTERNAL_PRODUCT_READY"]}
- EXTERNAL_PRODUCTION_VERIFIED: {gate["EXTERNAL_PRODUCTION_VERIFIED"]}
- Remaining blockers: {gate["remaining_blockers"]}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate GEO V1.1 final acceptance report.")
    parser.add_argument("--project-id", type=int, default=3)
    parser.add_argument("--prompt-id", type=int, action="append", dest="prompt_ids")
    parser.add_argument("--output", default="../docs/v1_1_final_acceptance.md")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        project = db.get(Project, args.project_id)
        if not project:
            raise SystemExit(f"Project #{args.project_id} not found")
        report = build_v1_1_final_acceptance_report(
            db,
            project,
            prompt_ids=args.prompt_ids or [19, 40],
        )
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_markdown(report), encoding="utf-8")
        print(render_markdown(report))
    finally:
        db.close()


if __name__ == "__main__":
    main()
