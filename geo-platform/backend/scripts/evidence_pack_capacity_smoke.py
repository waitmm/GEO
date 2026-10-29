#!/usr/bin/env python3
"""Print the synthetic Evidence Pack v3 capacity acceptance matrix.

No database, network, provider, or paid model is used.  The fixture generator
is intentionally shared from the focused test module so the reported matrix is
the exact matrix protected by pytest.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.agent_experiment.evidence_pack import (
    DEFAULT_TEXT_BUDGET,
    EvidencePackCapacityError,
    build_evidence_pack,
)
from app.modules.agent_experiment.evidence_pack_capacity import (
    model_input_characters,
    plan_evidence_pack_batches,
)
from tests.test_evidence_pack_capacity_scaling import DISTRIBUTIONS, SCALES, synthetic_scope


def main() -> None:
    rows = []
    for distribution in DISTRIBUTIONS:
        for run_count in SCALES:
            scope = synthetic_scope(run_count, distribution)
            try:
                pack = build_evidence_pack(scope)
                direct_status = (
                    "FIT" if model_input_characters(pack) <= DEFAULT_TEXT_BUDGET
                    else "SERIALIZED_JSON_EXCEEDS"
                )
                direct_characters = model_input_characters(pack)
                logical_characters = pack["coverage"]["estimated_text_characters"]
            except EvidencePackCapacityError as exc:
                direct_status = str(exc).split(":", 1)[0]
                direct_characters = None
                logical_characters = None
            plan = plan_evidence_pack_batches(scope)
            rows.append({
                "distribution": distribution,
                "run_count": run_count,
                "unique_url_count": len(scope["source_snapshots"]),
                "direct_status": direct_status,
                "direct_logical_characters": logical_characters,
                "direct_serialized_characters": direct_characters,
                "shadow_plan_status": plan["status"],
                "partition_status": plan["partition_status"],
                "aggregate_budget_status": plan["aggregate_budget_status"],
                "batch_count": plan["batch_count"],
                "largest_batch_run_count": max(
                    (len(row["run_ids"]) for row in plan["batches"]), default=0,
                ),
                "max_batch_serialized_characters": max(
                    (row["actual_model_input_characters"] for row in plan["batches"]), default=0,
                ),
                "max_batch_total_token_reservation": max(
                    (row["total_token_reservation"] for row in plan["batches"]), default=0,
                ),
                "aggregate_total_token_reservation": plan[
                    "aggregate_total_token_reservation"
                ],
                "run_coverage": (
                    f"{plan['coverage']['run_planned']}/{plan['coverage']['run_total']}"
                ),
                "citation_coverage": (
                    f"{plan['coverage']['citation_occurrence_covered']}/"
                    f"{plan['coverage']['citation_occurrence_total']}"
                ),
                "source_snapshot_coverage": (
                    f"{plan['coverage']['source_snapshot_covered']}/"
                    f"{plan['coverage']['source_snapshot_total']}"
                ),
            })
    print(json.dumps({
        "contract_version": "geo.evidence-pack.capacity-acceptance.synthetic.v1",
        "text_budget": DEFAULT_TEXT_BUDGET,
        "external_calls": 0,
        "synthetic_not_business_quality_evidence": True,
        "rows": rows,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
