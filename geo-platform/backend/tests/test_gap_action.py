from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Organization,
    Project,
    Prompt,
    RecommendationEvent,
    TargetBrandCapabilityTruth,
)
from app.modules.optimization.gap_action import build_action_candidate, derive_gap


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed_project(db):
    org = Organization(id=1, name="测试组织")
    project = Project(id=3, organization_id=1, name="爱短链品牌监测", brand_name="爱短链")
    prompt = Prompt(id=43, project_id=3, prompt_text="长链接怎么缩短", title="长链接怎么缩短")
    db.add_all([org, project, prompt])
    db.commit()
    return project, prompt


def test_competitor_recommendation_without_supports_is_evidence_gap_not_unresolved():
    db = _session()
    try:
        project, prompt = _seed_project(db)
        db.add(TargetBrandCapabilityTruth(
            project_id=project.id,
            capability_key="短链生成",
            capability_label="短链生成",
            product_truth_status="SUPPORTED",
        ))
        db.add_all([
            RecommendationEvent(
                project_id=project.id,
                prompt_id=prompt.id,
                run_id=245,
                entity_text="虾果",
                speech_act="INCLUDE_AS_OPTION",
                recommendation_strength="MODERATE",
                polarity="POSITIVE",
                answer_span="登录虾果、摩尔企服等短链接工具的后台",
                review_status="HUMAN_CONFIRMED",
            ),
            RecommendationEvent(
                project_id=project.id,
                prompt_id=prompt.id,
                run_id=246,
                entity_text="摩尔企服",
                speech_act="INCLUDE_AS_OPTION",
                recommendation_strength="MODERATE",
                polarity="POSITIVE",
                answer_span="登录虾果、摩尔企服等短链接工具的后台",
                review_status="HUMAN_CONFIRMED",
            ),
        ])
        db.commit()

        gap = derive_gap(db, project, prompt.id, [245, 246])
        action = build_action_candidate(db, project, prompt.id, [245, 246], gap)

        assert gap["gap_type"] == "EVIDENCE_GAP"
        assert gap["total_runs"] == 2
        assert gap["event_run_count"] == 2
        assert gap["competitor_events"] == 2
        assert gap["supports_count"] == 0
        assert "答案已出现 2 个竞品/候选推荐事件" in gap["basis"]
        assert "引用原文尚未形成 SUPPORTS 对齐" in gap["basis"]
        assert action["intervention_goal"] == "EVIDENCE_STRENGTHEN"
        assert action["target_platform"] == "UNRESOLVED"
    finally:
        db.close()


def test_competitor_recommendation_still_blocks_when_product_truth_unknown():
    db = _session()
    try:
        project, prompt = _seed_project(db)
        db.add(RecommendationEvent(
            project_id=project.id,
            prompt_id=prompt.id,
            run_id=245,
            entity_text="虾果",
            speech_act="INCLUDE_AS_OPTION",
            recommendation_strength="MODERATE",
            polarity="POSITIVE",
            answer_span="登录虾果等短链接工具的后台",
            review_status="HUMAN_CONFIRMED",
        ))
        db.commit()

        gap = derive_gap(db, project, prompt.id, [245])

        assert gap["gap_type"] == "UNRESOLVED"
        assert gap["product_truth_status"] == "PRODUCT_TRUTH_UNRESOLVED"
        assert "PRODUCT_TRUTH_UNRESOLVED" in gap["basis"]
    finally:
        db.close()
