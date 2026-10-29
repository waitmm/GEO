from __future__ import annotations

import json

import pytest

from app.modules.agent_experiment.evidence_pack import (
    DEFAULT_TEXT_BUDGET,
    EvidencePackCapacityError,
    build_evidence_pack,
)
from app.modules.agent_experiment.evidence_pack_capacity import (
    audit_citation_content_versions,
    audit_source_dispositions,
    model_input_characters,
    plan_evidence_pack_batches,
    shadow_omitted_citation_catalog_entries,
)
from app.modules.single_prompt_v2.delivery_text import digest


SCALES = (22, 50, 100, 300, 1_000)
DISTRIBUTIONS = ("HIGH_REPEAT", "HIGH_UNIQUE", "LONG_SOURCE")


def synthetic_scope(run_count: int, distribution: str) -> dict:
    if distribution == "HIGH_REPEAT":
        unique_count, passage_size = 5, 240
    elif distribution == "HIGH_UNIQUE":
        unique_count, passage_size = run_count * 2, 240
    elif distribution == "LONG_SOURCE":
        unique_count, passage_size = max(1, (run_count + 9) // 10), 5_000
    else:  # pragma: no cover - fixture author error
        raise AssertionError(distribution)

    urls = [f"https://evidence.example/source/{index}" for index in range(unique_count)]
    runs = []
    for index in range(run_count):
        references = []
        for reference_index in range(2):
            if distribution == "HIGH_REPEAT":
                url_index = (index + reference_index) % unique_count
            elif distribution == "HIGH_UNIQUE":
                url_index = index * 2 + reference_index
            else:
                url_index = min(index // 10, unique_count - 1)
            references.append({
                "reference_id": reference_index + 1,
                "index": reference_index + 1,
                "canonical_url": urls[url_index],
                "url": urls[url_index],
                "title": f"来源 {url_index}",
            })
        answer = f"第 {index + 1} 次回答。" + ("回答观察内容" * 35)
        runs.append({
            "run_id": index + 1,
            "status": "success",
            "answer_text": answer,
            "references": references,
            "brand_mentioned": index % 3 == 0,
            "competitors": [],
        })

    snapshots = []
    for index, url in enumerate(urls):
        text = (f"来源 {index} 的冻结正文。" + "证据正文") * max(1, passage_size // 5)
        snapshots.append({
            "snapshot_id": f"snapshot-{index}",
            "source_key": f"source-{index}",
            "canonical_url": url,
            "title": f"来源 {index}",
            "content_hash": digest(text),
            "passages": [{
                "passage_id": "passage-1",
                "content_hash": digest(text),
                "text": text,
            }],
        })
    return {
        "identity": {"project_id": 1, "prompt_id": 1},
        "prompt": {"prompt_id": 1, "prompt_text": "推荐一个合适的工具"},
        "project_configuration": {
            "brand": {"brand_name": "目标品牌", "brand_aliases": [], "website_url": ""},
        },
        "project_entities": {"competitors": []},
        "runs": runs,
        "citation_manifest": None,
        "source_snapshots": snapshots,
        "source_dispositions": [{
            "source_key": f"source-{index}", "status": "AVAILABLE",
        } for index in range(unique_count)],
        "product_truth": {"set_hash": digest([]), "facts": []},
        "brand_context": {"mode": "EMPTY"},
        "monitor_metrics": {"valid_answer_count": run_count},
        "qualification": {"delivery_level": "L3"},
    }


def direct_capacity(scope: dict) -> tuple[str, int | None]:
    try:
        pack = build_evidence_pack(scope)
    except EvidencePackCapacityError:
        return "CORE_EXCEEDS", None
    return "FIT" if model_input_characters(pack) <= DEFAULT_TEXT_BUDGET else "JSON_EXCEEDS", model_input_characters(pack)


def test_v3_22_run_high_repeat_baseline_fits_without_omission():
    pack = build_evidence_pack(synthetic_scope(22, "HIGH_REPEAT"))
    assert pack["coverage"]["run_ids"] == [str(value) for value in range(1, 23)]
    assert pack["coverage"]["citation_occurrence_count"] == 44
    assert pack["coverage"]["citation_evidence_total"] == 5
    assert pack["coverage"]["citation_evidence_omitted"] == 0
    assert pack["coverage"]["source_passage_omitted"] == 0
    assert model_input_characters(pack) <= DEFAULT_TEXT_BUDGET


@pytest.mark.parametrize("run_count", SCALES)
@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_shadow_capacity_plan_covers_every_identity(run_count: int, distribution: str):
    scope = synthetic_scope(run_count, distribution)
    plan = plan_evidence_pack_batches(scope)
    assert plan["partition_status"] == "READY", (
        distribution, run_count, plan["blocked_runs"][:1]
    )
    assert plan["mode"] == "SHADOW_ONLY_NO_MODEL_EXECUTION_NO_RESULT_MERGE"
    assert plan["coverage"]["run_planned"] == run_count
    assert plan["coverage"]["citation_occurrence_covered"] == run_count * 2
    assert plan["coverage"]["source_snapshot_covered"] == len(scope["source_snapshots"])
    assert not plan["coverage"]["missing_run_ids"]
    assert not plan["coverage"]["missing_citation_occurrence_ids"]
    assert not plan["coverage"]["missing_source_snapshot_ids"]
    assert not plan["coverage"]["missing_source_disposition_ids"]
    assert not plan["coverage"]["unassigned_source_snapshot_ids"]
    assert all(row["actual_model_input_characters"] <= DEFAULT_TEXT_BUDGET
               for row in plan["batches"])
    assert all(row["total_token_reservation"] <= plan["task_token_cap"]
               for row in plan["batches"])
    assert plan["aggregate_total_token_reservation"] == (
        plan["aggregate_input_token_upper_bound"]
        + plan["aggregate_output_token_reservation"]
    )
    if plan["status"] == "READY":
        assert plan["aggregate_budget_status"] == "WITHIN_TASK_CAP"
    else:
        assert plan["aggregate_budget_status"] == (
            "AGGREGATE_TASK_TOKEN_RESERVATION_EXCEEDS_CAP"
        )
    assert all(row["run_ids"] == sorted(row["run_ids"], key=int)
               for row in plan["batches"])
    assert plan["cutover_blocker"].startswith("SEMANTIC_CONTRACT_REVIEW_REQUIRED")


def test_shadow_plan_is_deterministic_and_does_not_mutate_scope():
    scope = synthetic_scope(100, "HIGH_UNIQUE")
    before = json.loads(json.dumps(scope))
    first = plan_evidence_pack_batches(scope)
    second = plan_evidence_pack_batches(scope)
    assert first == second
    assert scope == before


def test_same_url_content_versions_are_not_claimed_as_identical():
    scope = synthetic_scope(22, "HIGH_REPEAT")
    original = scope["source_snapshots"][0]
    changed = json.loads(json.dumps(original))
    changed["snapshot_id"] = "snapshot-0-v2"
    changed["content_hash"] = "b" * 64
    changed["passages"][0]["content_hash"] = "b" * 64
    scope["source_snapshots"].append(changed)
    audit = audit_citation_content_versions(scope)
    row = next(item for item in audit
               if item["canonical_url"] == original["canonical_url"])
    assert row["content_identity_status"] == "MULTIPLE_KNOWN_VERSIONS"
    assert {item["content_hash"] for item in row["source_content_versions"]} == {
        original["content_hash"], "b" * 64,
    }
    assert row["projection_semantics"] == (
        "SAME_URL_OCCURRENCES_NOT_CONTENT_EQUIVALENCE"
    )

    changed["content_hash"] = None
    audit = audit_citation_content_versions(scope)
    row = next(item for item in audit
               if item["canonical_url"] == original["canonical_url"])
    assert row["content_identity_status"] == "UNKNOWN"


def test_url_less_citation_has_stable_identity_with_occurrence_lineage():
    scope = synthetic_scope(2, "HIGH_REPEAT")
    for run in scope["runs"]:
        for reference in run["references"]:
            reference["canonical_url"] = ""
            reference["url"] = ""
            reference["domain"] = "unknown.example"
            reference["title"] = "无链接来源"
    audit = audit_citation_content_versions(scope)
    assert len(audit) == 1
    row = audit[0]
    assert row["catalog_identity"]["canonical_url"] is None
    assert row["catalog_identity"]["fallback_domain"] == "unknown.example"
    assert row["catalog_identity"]["fallback_title"] == "无链接来源"
    assert len(row["citation_occurrence_ids"]) == 4
    assert row["catalog_identity_hash"] == digest(row["catalog_identity"])
    assert audit == audit_citation_content_versions(scope)


def test_snapshotless_failed_unknown_waived_dispositions_are_globally_preserved():
    scope = synthetic_scope(50, "HIGH_REPEAT")
    scope["source_dispositions"].extend([
        {"source_key": "missing-failed", "state": "FAILED", "reason": "FETCH_FAILED"},
        {"source_key": "missing-unknown", "state": "UNKNOWN", "reason": "NOT_EVALUATED"},
        {"source_key": "missing-waived", "state": "WAIVED", "reason": "OWNER_WAIVER"},
    ])
    audit = audit_source_dispositions(scope)
    assert {row["status"] for row in audit if not row["snapshot_present"]} == {
        "FAILED", "UNKNOWN", "WAIVED",
    }
    plan = plan_evidence_pack_batches(scope)
    assert plan["partition_status"] == "READY"
    assert plan["coverage"]["source_disposition_covered"] == (
        plan["coverage"]["source_disposition_total"]
    )
    assert not plan["coverage"]["missing_source_disposition_ids"]
    assert plan["source_disposition_audit"]["snapshot_missing_count"] == 3
    assert plan["source_disposition_audit"]["unknown_semantics"] == (
        "PRESERVED_NOT_UPGRADED"
    )
    missing_ids = {
        row["disposition_identity"] for row in audit if not row["snapshot_present"]
    }
    assert all(missing_ids.issubset(set(batch["source_disposition_ids"]))
               for batch in plan["batches"])


def test_output_reservation_mirrors_provider_minimum():
    scope = synthetic_scope(22, "HIGH_REPEAT")
    plan = plan_evidence_pack_batches(scope, max_output_tokens=1)
    assert plan["max_output_tokens_per_batch"] == 2_048
    assert all(batch["max_output_tokens"] == 2_048 for batch in plan["batches"])


def test_unplannable_single_run_is_explicit_and_never_silently_dropped():
    scope = synthetic_scope(1, "HIGH_REPEAT")
    scope["runs"][0]["answer_text"] = "过长回答" * 30_000
    plan = plan_evidence_pack_batches(scope)
    assert plan["status"] == "REVIEW_REQUIRED"
    assert plan["batch_count"] == 0
    assert plan["blocked_runs"][0]["run_id"] == "1"
    assert "CORE_EXCEEDS_BUDGET" in plan["blocked_runs"][0]["reason"]
    assert plan["coverage"]["run_planned"] == 0


def test_omitted_citation_identity_is_reported_when_direct_pack_is_constrained():
    scope = synthetic_scope(22, "HIGH_UNIQUE")
    pack = build_evidence_pack(scope, text_budget=12_000)
    assert pack["coverage"]["citation_evidence_omitted"] > 0
    omissions = shadow_omitted_citation_catalog_entries(scope, pack)
    assert len(omissions) == pack["coverage"]["citation_evidence_omitted"]
    assert all(row["canonical_url"] and row["run_ids"] for row in omissions)


def test_direct_v3_capacity_classification_is_not_used_as_batch_success():
    status, _characters = direct_capacity(synthetic_scope(1_000, "HIGH_UNIQUE"))
    assert status in {"CORE_EXCEEDS", "JSON_EXCEEDS"}
    plan = plan_evidence_pack_batches(synthetic_scope(1_000, "HIGH_UNIQUE"))
    assert plan["partition_status"] == "READY"
    assert plan["batch_count"] > 1
