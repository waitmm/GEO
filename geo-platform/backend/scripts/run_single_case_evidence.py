"""Single Case Evidence Runner — Prompt #19 / Runs 173-184。

用法（backend 目录）：
    python3 scripts/run_single_case_evidence.py --project-id 3 --prompt-id 19 \
        --run-ids 173,174,175,176,177,178,179,180,181,182,183,184 \
        --provider deepseek [--dry-run] [--stage 1|2|3|4|5|all]

- 默认不覆盖历史结果（各层幂等：同 hash 复用 cache）。
- --dry-run 只打印计划不执行。
- Artifact 输出到 artifacts/single_case_evidence/prompt_19/。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, engine
from app.models import Project, Prompt
from app.modules.optimization.answer_semantic import run_answer_semantic
from app.modules.optimization.source_qualification import run_source_qualification
from app.modules.optimization.passage_retrieval import run_reason_driven_retrieval
from app.modules.optimization.source_claim import run_source_claim_extraction
from app.modules.optimization.evidence_alignment import run_evidence_alignment
from app.modules.optimization.gap_action import derive_gap, build_action_candidate
from app.services.serialization import dumps


def _dump_artifact(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--prompt-id", type=int, required=True)
    parser.add_argument("--run-ids", type=str, required=True)
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--stage", default="all", choices=["1", "2", "3", "4", "5", "gap", "all"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run_ids = [int(x.strip()) for x in args.run_ids.split(",") if x.strip()]
    engine.dispose()
    db = SessionLocal()
    project = db.get(Project, args.project_id)
    prompt = db.get(Prompt, args.prompt_id)
    if not project or not prompt:
        print("project/prompt not found")
        return 1

    out_dir = Path("artifacts/single_case_evidence") / f"prompt_{args.prompt_id}"
    plan = {
        "project_id": args.project_id,
        "prompt_id": args.prompt_id,
        "run_ids": run_ids,
        "provider": args.provider,
        "dry_run": args.dry_run,
        "stage": args.stage,
        "generated_at": datetime.utcnow().isoformat(),
    }
    print(f"Plan: {plan}")
    if args.dry_run:
        return 0

    results: dict = {"plan": plan}
    stage = args.stage

    if stage in {"1", "all"}:
        r = run_answer_semantic(db, project, prompt, run_ids)
        results["layer1_answer_semantic"] = r
        print(f"Layer1: {r}")
        _dump_artifact(out_dir / "recommendation_events.json", r)

    if stage in {"2", "all"}:
        r = run_source_qualification(db, project)
        results["layer2_source_quality"] = r
        print(f"Layer2: {r}")
        _dump_artifact(out_dir / "source_quality.json", r)

    if stage in {"3", "all"}:
        r = run_reason_driven_retrieval(db, project, args.prompt_id, run_ids)
        results["layer3_retrieval"] = {
            "status": r["status"], "unique_reasons": r["unique_reasons"],
            "passages_retrieved": r["passages_retrieved"],
        }
        print(f"Layer3: {results['layer3_retrieval']}")
        _dump_artifact(out_dir / "source_selection.json", r)

    if stage in {"4", "all"}:
        r = run_source_claim_extraction(db, project, args.prompt_id, run_ids)
        results["layer4_source_claims"] = r
        print(f"Layer4: {r}")
        _dump_artifact(out_dir / "source_claims.json", r)

    if stage in {"5", "all"}:
        r = run_evidence_alignment(db, project, args.prompt_id, run_ids)
        results["layer5_alignments"] = r
        print(f"Layer5: {r}")
        _dump_artifact(out_dir / "evidence_alignments.json", r)

    if stage in {"gap", "all"}:
        gap = derive_gap(db, project, args.prompt_id, run_ids)
        action = build_action_candidate(db, project, args.prompt_id, run_ids, gap)
        results["gap_diagnosis"] = gap
        results["action_candidate"] = action
        print(f"Gap: {gap}")
        print(f"Action: {action}")
        _dump_artifact(out_dir / "gap_diagnosis.json", gap)
        _dump_artifact(out_dir / "action_candidate.json", action)

    _dump_artifact(out_dir / "baseline_manifest.json", results)
    print(f"\nArtifacts written to {out_dir}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
