from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Project,
    Prompt,
    SinglePromptCitationContributionResult,
    SinglePromptPreparedSourceSnapshot,
)
from app.modules.single_prompt_v2.execution import _compile_machine_delivery


def test_machine_delivery_resolves_content_without_inventing_asset_or_brand_fact(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'delivery.db').as_posix()}")
    db = sessionmaker(bind=engine)()
    Base.metadata.create_all(engine)
    try:
        db.add(Project(
            id=1,
            organization_id=1,
            name="爱短链",
            brand_name="爱短链",
            website_url="https://www.aifabu.com/",
        ))
        db.add(Prompt(id=1, project_id=1, title="抖音跳转链接", prompt_text="抖音跳转链接"))
        db.add(SinglePromptPreparedSourceSnapshot(
            snapshot_id="brand-snapshot",
            preparation_id="prep-1",
            context_id="context-1",
            citation_manifest_id="manifest-1",
            source_key="a" * 64,
            canonical_url="https://aifabu.com/details/42615",
            title="抖音视频怎么跳转链接-爱短链",
            original_urls_json="[]",
            reference_observations_json="[]",
            occurrence_count=1,
            content_hash="b" * 64,
            clean_text=(
                "短链接生成器\n"
                "稳定合规 · 安全跳转 · 防封防劫持 | 日均处理千万级访问\n"
                "抖音私信跳转卡片\n"
                "支持多渠道参数追踪与深度访问分析"
            ),
            artifact_path="artifact.txt",
            artifact_hash="c" * 64,
            passages_json="[]",
            passages_hash="d" * 64,
            parser_version="fixture",
            acquisition_method="AUTO_FETCH",
            coverage_scope="FULL_PAGE",
            submitted_by="fixture",
        ))
        contribution = {
            "bindings": [
                {
                    "binding_id": "binding-private",
                    "citation_id": "citation-11",
                    "answer_unit_id": "answer-private",
                    "source_span": "可以将跳转卡片与私信自动回复功能相结合",
                    "evidence_relation": "SUPPORTS_PARTIAL",
                    "answer_anchor": "UNPROVEN",
                    "generation_influence": "UNAVAILABLE",
                },
                {
                    "binding_id": "binding-live",
                    "citation_id": "citation-15",
                    "answer_unit_id": "answer-live",
                    "source_span": "在抖音直播间通过小风车组件跳转至微信小程序商城",
                    "evidence_relation": "SUPPORTS_PARTIAL",
                    "answer_anchor": "UNPROVEN",
                    "generation_influence": "UNAVAILABLE",
                },
            ],
            "citations": [
                {
                    "citation_id": "citation-4",
                    "snapshot_id": "failed-snapshot",
                    "canonical_url": "https://example.com/failed",
                    "processing_status": "FAILED",
                    "failure_code": "FAILED_NEGATIVE_SPAN",
                    "failure_detail": "invalid negative span",
                }
            ],
        }
        db.add(SinglePromptCitationContributionResult(
            result_version="contribution-v1:fixture",
            contribution_id="contribution-1",
            version_number=1,
            output_json=json.dumps(contribution, ensure_ascii=False),
            output_hash="e" * 64,
            reviewable_set_hash="f" * 64,
        ))
        db.commit()
        snapshot = {
            "identity": {
                "project_id": 1,
                "prompt_id": 1,
                "context_id": "context-1",
                "input_authority_type": "MACHINE_QUALIFICATION",
            },
            "direction": {
                "direction_id": "direction-1",
                "direction_type": "DISCOVERY",
                "channel_key": None,
                "channel_label": None,
                "channel_role": None,
                "dependencies": [{"object_type": "CITATION_CONTRIBUTION_SCOPE", "object_id": "contribution-v1:fixture"}],
            },
            "automatic_draft": {
                "content_blocks": [
                    {
                        "block_id": "private",
                        "draft_text": "私信卡片跳转：在私信自动回复中设置消息卡片，跳转至指定页面。",
                        "binding_id": "binding-private",
                        "citation_id": "citation-11",
                        "answer_unit_id": "answer-private",
                    },
                    {
                        "block_id": "live",
                        "draft_text": "直播间小风车：点击后跳转至企微、小程序等全部目标。",
                        "binding_id": "binding-live",
                        "citation_id": "citation-15",
                        "answer_unit_id": "answer-live",
                    },
                ],
            },
            "baseline": {"baseline_run_ids": [1], "run_manifest": {"valid_run_ids": [1]}},
            "limitations": [],
            "advisories": [],
            "boundary": {},
        }

        output = _compile_machine_delivery(db, "proposal-1", snapshot)

        assert output["asset_operation"] == "CONDITIONAL"
        assert output["asset_resolution"]["inventory_state"] == "UNKNOWN"
        assert output["asset_resolution"]["recommended_asset_type"] == "HELP_DOC"
        assert output["asset_resolution"]["existing_asset_checks"][0]["can_authorize_update"] is False
        assert output["channel_resolution"]["publication_channel_key"] == "OWNED_SITE"
        assert output["strategy_channel"]["channel_role"] is None
        assert output["publication_draft"]["body_markdown"].count("抖音跳转链接") >= 2
        assert "爱短链如何承接这个问题" in output["publication_draft"]["body_markdown"]
        assert "日均处理千万级访问" not in output["publication_draft"]["body_markdown"]
        assert "防封防劫持" not in output["publication_draft"]["body_markdown"]
        assert "跳转至企微、小程序等全部目标" not in output["publication_draft"]["body_markdown"]
        assert "不应扩大为可直接跳转企微" in output["publication_draft"]["body_markdown"]
        assert output["automatic_qa"]["status"] == "READY"
        assert output["automatic_qa"]["checks"]["unsupported_effect_claims_removed"] == "PASS"
        assert output["validation"]["content_delivery_status"] == "READY"
        assert output["validation"]["status"] == "READY_FOR_BUSINESS_INPUT"
        failure = output["evidence_processing_audit"]["historical_failures"][0]
        assert failure["disposition"] == "NOT_EVALUATED_CURRENT_CONTRACT"
        assert failure["used_in_deliverable"] is False
    finally:
        db.close()
        engine.dispose()
