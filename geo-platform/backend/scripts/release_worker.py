"""Single-concurrency business worker for the GEO 1.0 release control plane."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.release_database import ReleaseSessionLocal, release_engine
from app.models import SinglePromptAnalysis, SinglePromptDiagnosisExecution
from app.modules.single_prompt_v2.diagnosis import execute_diagnosis, execute_queued_evidence
from app.modules.single_prompt_v2.service import execute_analysis
from app.release_schema import validate_release_database


def run_once() -> str | None:
    db = ReleaseSessionLocal()
    try:
        analysis = (
            db.query(SinglePromptAnalysis)
            .filter(SinglePromptAnalysis.status == "QUEUED")
            .order_by(SinglePromptAnalysis.id.asc())
            .first()
        )
        if analysis:
            identity = analysis.analysis_id
            work_type = "analysis"
        else:
            diagnosis = (
                db.query(SinglePromptDiagnosisExecution)
                .filter(SinglePromptDiagnosisExecution.status.in_(["QUEUED", "EVIDENCE_QUEUED"]))
                .order_by(SinglePromptDiagnosisExecution.id.asc())
                .first()
            )
            if not diagnosis:
                return None
            identity = diagnosis.diagnosis_id
            work_type = "evidence" if diagnosis.status == "EVIDENCE_QUEUED" else "answer"
    finally:
        db.close()

    if work_type == "analysis":
        execute_analysis(identity, session_factory=ReleaseSessionLocal)
        return f"analysis:{identity}"
    if work_type == "evidence":
        execute_queued_evidence(identity, session_factory=ReleaseSessionLocal)
        return f"evidence:{identity}"
    execute_diagnosis(identity, session_factory=ReleaseSessionLocal)
    return f"answer:{identity}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the single-concurrency GEO 1.0 release worker.")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--max-idle-passes", type=int, default=0)
    args = parser.parse_args()
    print({"release_database": validate_release_database(release_engine), "worker_concurrency": 1})
    idle_passes = 0
    while True:
        completed = run_once()
        print({"completed": completed or "IDLE"})
        if args.once:
            return
        idle_passes = 0 if completed else idle_passes + 1
        if args.max_idle_passes and idle_passes >= args.max_idle_passes:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
