from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import (
    AnswerClaim,
    AnswerDecisionBinding,
    AnswerEvidenceShadowRun,
    AnswerUnit,
    Base,
    BrowserMonitorRun,
    BrowserMonitorTask,
    EvidenceAlignment,
    LLMCallCache,
    OptimizationEvidencePackage,
    Organization,
    Project,
    Prompt,
    RecommendationEvent,
    ReferenceSource,
    SourceClaim,
    SourceDocument,
)
from app.modules.optimization.incremental_materialization import build_incremental_materialization_plan
from app.modules.optimization.evidence_alignment import (
    ALIGNMENT_PROMPT_VERSION,
    ALIGNMENT_SCHEMA_VERSION,
    run_evidence_alignment,
)
from app.modules.optimization.passage_retrieval import SHADOW_INPUT_PIPELINE_VERSION
from app.modules.optimization.source_claim import (
    SOURCE_CLAIM_PROMPT_VERSION,
    SOURCE_CLAIM_SCHEMA_VERSION,
    source_claim_llm_input_hash,
)
from app.services.serialization import dumps


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _base_project(db):
    org = Organization(id=1, name="测试组织")
    project = Project(id=1, organization_id=1, name="GEO", brand_name="爱短链")
    prompt = Prompt(id=1, project_id=1, prompt_text="抖音跳转微信怎么做", title="抖音跳转微信怎么做")
    task = BrowserMonitorTask(id=1, project_id=1, status="success")
    db.add_all([org, project, prompt, task])
    db.commit()
    return project


def test_planner_is_read_only_and_scopes_to_current_cited_documents():
    db = _session()
    try:
        project = _base_project(db)
        run = BrowserMonitorRun(
            id=101,
            task_id=1,
            project_id=1,
            prompt_id=1,
            status="success",
            answer_text="爱短链支持点击统计。",
        )
        event = RecommendationEvent(
            id=201,
            project_id=1,
            prompt_id=1,
            run_id=101,
            answer_hash="a",
            entity_text="爱短链",
            speech_act="RECOMMEND",
            review_status="HUMAN_CONFIRMED",
            reasons_json=dumps([{"normalized_reason": "支持点击统计", "reason_scope": "ENTITY_SPECIFIC"}]),
        )
        cited_doc = SourceDocument(
            id=301,
            url="https://aifabu.com/card",
            canonical_url="https://aifabu.com/card",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text="爱短链支持点击统计，可以查看短链访问数据。",
            content_blocks_json=dumps([{"block_index": 1, "text": "爱短链支持点击统计，可以查看短链访问数据。"}]),
        )
        historical_doc = SourceDocument(
            id=302,
            url="https://history.example/doc",
            canonical_url="https://history.example/doc",
            domain="history.example",
            fetch_status="SUCCESS",
            clean_text="历史文档也支持点击统计，但不在当前引用范围。",
            content_blocks_json=dumps([{"block_index": 1, "text": "历史文档也支持点击统计，但不在当前引用范围。"}]),
        )
        ref = ReferenceSource(
            id=401,
            run_id=101,
            reference_index=1,
            url="https://aifabu.com/card",
            canonical_url="https://aifabu.com/card",
            domain="aifabu.com",
        )
        current_claim = SourceClaim(
            id=501,
            project_id=1,
            source_document_id=301,
            passage_id="doc301:b1",
            source_owner_entity="爱短链",
            subject_entity="爱短链",
            normalized_claim="爱短链支持点击统计",
            claim_type="CAPABILITY",
            polarity="POSITIVE",
            source_span="爱短链支持点击统计",
            prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
            review_status="MACHINE_GROUNDED",
        )
        historical_claim = SourceClaim(
            id=502,
            project_id=1,
            source_document_id=302,
            passage_id="doc302:b1",
            source_owner_entity="历史",
            subject_entity="历史",
            normalized_claim="历史文档支持点击统计",
            claim_type="CAPABILITY",
            polarity="POSITIVE",
            source_span="历史文档支持点击统计",
            prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
            review_status="MACHINE_GROUNDED",
        )
        package = OptimizationEvidencePackage(
            id=601,
            project_id=1,
            prompt_id=1,
            version=1,
            status="active",
            package_hash="pkg",
            source_run_ids_json=dumps([101]),
        )
        db.add_all([run, event, cited_doc, historical_doc, ref, package])
        db.commit()
        db.add_all([current_claim, historical_claim])
        db.commit()
        before_counts = {
            "claims": db.query(SourceClaim).count(),
            "alignments": db.query(EvidenceAlignment).count(),
            "llm_cache": db.query(LLMCallCache).count(),
        }

        plan = build_incremental_materialization_plan(db, project, 1)

        after_counts = {
            "claims": db.query(SourceClaim).count(),
            "alignments": db.query(EvidenceAlignment).count(),
            "llm_cache": db.query(LLMCallCache).count(),
        }
        assert plan["read_only"] is True
        assert before_counts == after_counts
        assert plan["run_scope"]["source"] == "ACTIVE_EVIDENCE_PACKAGE"
        assert plan["source_documents"]["required_documents"] == 1
        assert plan["source_claims"]["valid_source_claim_rows"] == 1
        assert plan["source_claims"]["missing_unique_llm_inputs"] == 0
        assert plan["source_claims"]["lookup_first_llm_required"] == 0
        assert plan["evidence_alignment"]["source_claim_candidates"] == 1
        assert plan["evidence_alignment"]["naive_pairs"] == 1
        assert plan["evidence_alignment"]["recall_top_k"] == 5
        assert plan["amplification"]["primary_bottleneck"] in {"SOURCE_CLAIM", "EVIDENCE_ALIGNMENT"}
    finally:
        db.close()


def test_planner_keeps_duplicate_runs_as_observations_not_semantic_objects():
    db = _session()
    try:
        project = _base_project(db)
        runs = [
            BrowserMonitorRun(
                id=run_id,
                task_id=1,
                project_id=1,
                prompt_id=1,
                status="success",
                answer_text="爱短链支持点击统计。",
            )
            for run_id in (101, 102)
        ]
        doc = SourceDocument(
            id=301,
            url="https://aifabu.com/card",
            canonical_url="https://aifabu.com/card",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text="爱短链支持点击统计，可以查看短链访问数据。",
            content_blocks_json=dumps([{"block_index": 1, "text": "爱短链支持点击统计，可以查看短链访问数据。"}]),
        )
        package = OptimizationEvidencePackage(
            id=601,
            project_id=1,
            prompt_id=1,
            version=1,
            status="active",
            package_hash="pkg",
            source_run_ids_json=dumps([101, 102]),
        )
        shadow = AnswerEvidenceShadowRun(
            id=701,
            project_id=1,
            prompt_id=1,
            evidence_package_id=601,
            source_run_ids_json=dumps([101, 102]),
            pipeline_version=SHADOW_INPUT_PIPELINE_VERSION,
            status="completed",
            formal_output_impact="NONE",
        )
        db.add_all([*runs, doc, package, shadow])
        db.commit()
        for idx, run_id in enumerate((101, 102), start=1):
            event = RecommendationEvent(
                id=200 + idx,
                project_id=1,
                prompt_id=1,
                run_id=run_id,
                answer_hash=f"a{idx}",
                entity_text="爱短链",
                speech_act="RECOMMEND",
                review_status="HUMAN_CONFIRMED",
                reasons_json=dumps([{"normalized_reason": "支持点击统计", "reason_scope": "ENTITY_SPECIFIC"}]),
            )
            claim = AnswerClaim(id=300 + idx, run_id=run_id, raw_text="爱短链支持点击统计。")
            unit = AnswerUnit(
                id=400 + idx,
                shadow_run_id=701,
                project_id=1,
                prompt_id=1,
                run_id=run_id,
                answer_claim_id=300 + idx,
                unit_text_normalized="爱短链支持点击统计",
                semantic_type="FEATURE",
                entity_hint="爱短链",
                review_status="MACHINE_GROUNDED",
            )
            binding = AnswerDecisionBinding(
                id=500 + idx,
                shadow_run_id=701,
                project_id=1,
                prompt_id=1,
                run_id=run_id,
                recommendation_event_id=200 + idx,
                answer_unit_id=400 + idx,
                decision_role="DIRECT_REASON",
                binding_strength="HIGH",
                pipeline_version=SHADOW_INPUT_PIPELINE_VERSION,
                review_status="MACHINE_GROUNDED",
            )
            ref = ReferenceSource(
                id=800 + idx,
                run_id=run_id,
                reference_index=1,
                url="https://aifabu.com/card",
                canonical_url="https://aifabu.com/card",
                domain="aifabu.com",
            )
            db.add_all([event, claim, unit, binding, ref])
        source_claim = SourceClaim(
            id=901,
            project_id=1,
            source_document_id=301,
            passage_id="doc301:b1",
            source_owner_entity="爱短链",
            subject_entity="爱短链",
            normalized_claim="爱短链支持点击统计",
            claim_type="CAPABILITY",
            polarity="POSITIVE",
            source_span="爱短链支持点击统计",
            prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
            review_status="MACHINE_GROUNDED",
        )
        db.add(source_claim)
        db.commit()

        plan = build_incremental_materialization_plan(db, project, 1, top_k=3)

        assert plan["run_scope"]["run_count"] == 2
        assert plan["answer_units"]["raw_observations"] == 2
        assert plan["answer_units"]["semantic_objects"] == 1
        assert plan["source_claims"]["lookup_first_llm_required"] == 0
        assert plan["evidence_alignment"]["reason_observations"] >= 2
        assert plan["evidence_alignment"]["semantic_reasons"] == 2
        assert plan["evidence_alignment"]["naive_pairs"] == 2
        assert plan["evidence_alignment"]["recall_top_k"] == 3
        assert plan["amplification"]["answer_unit_semantic_reuse_factor"] == 2.0
    finally:
        db.close()


def test_planner_explains_missing_llm_cache_delta_with_conservation():
    db = _session()
    try:
        project = _base_project(db)
        passage_text = "爱短链支持点击统计，可以查看短链访问数据。"
        run = BrowserMonitorRun(
            id=101,
            task_id=1,
            project_id=1,
            prompt_id=1,
            status="success",
            answer_text="爱短链支持点击统计。",
        )
        event = RecommendationEvent(
            id=201,
            project_id=1,
            prompt_id=1,
            run_id=101,
            answer_hash="a",
            entity_text="爱短链",
            speech_act="RECOMMEND",
            review_status="HUMAN_CONFIRMED",
            reasons_json=dumps([{"normalized_reason": "支持点击统计", "reason_scope": "ENTITY_SPECIFIC"}]),
        )
        doc = SourceDocument(
            id=301,
            url="https://aifabu.com/card",
            canonical_url="https://aifabu.com/card",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text=passage_text,
            content_blocks_json=dumps([{"block_index": 1, "text": passage_text}]),
        )
        ref = ReferenceSource(
            id=401,
            run_id=101,
            reference_index=1,
            url="https://aifabu.com/card",
            canonical_url="https://aifabu.com/card",
            domain="aifabu.com",
        )
        package = OptimizationEvidencePackage(
            id=601,
            project_id=1,
            prompt_id=1,
            version=1,
            status="active",
            package_hash="pkg",
            source_run_ids_json=dumps([101]),
        )
        cache = LLMCallCache(
            provider="deepseek",
            model="deepseek-v4-flash",
            prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
            input_hash=source_claim_llm_input_hash(passage_text),
            parsed_payload_json=dumps({"claims": []}),
        )
        db.add_all([run, event, doc, ref, package, cache])
        db.commit()

        plan = build_incremental_materialization_plan(db, project, 1)
        source_claims = plan["source_claims"]

        assert source_claims["missing_count"] == 1
        assert source_claims["missing_unique_llm_inputs"] == 1
        assert source_claims["lookup_first_llm_required"] == 0
        assert source_claims["missing_llm_call_cache_hit"] == 1
        assert source_claims["missing_no_external_llm_breakdown"] == {
            "llm_call_cache_hit": 1,
            "invalid_input": 0,
            "empty_content": 0,
            "deduped_elsewhere": 0,
        }
        assert source_claims["missing_conservation"]["is_balanced"] is True
        assert source_claims["object_conservation"]["is_balanced"] is True
    finally:
        db.close()


def test_alignment_candidate_builder_shadow_audits_old_only_supports():
    db = _session()
    try:
        project = _base_project(db)
        runs = [
            BrowserMonitorRun(
                id=run_id,
                task_id=1,
                project_id=1,
                prompt_id=1,
                status="success",
                answer_text=answer_text,
            )
            for run_id, answer_text in (
                (101, "爱短链因为支持点击统计被推荐。"),
                (102, "爱短链因为有二维码背景图模板被推荐。"),
            )
        ]
        event_1 = RecommendationEvent(
            id=201,
            project_id=1,
            prompt_id=1,
            run_id=101,
            answer_hash="a1",
            entity_text="爱短链",
            speech_act="RECOMMEND",
            review_status="HUMAN_CONFIRMED",
            reasons_json=dumps([{"normalized_reason": "支持点击统计", "reason_scope": "ENTITY_SPECIFIC"}]),
        )
        event_2 = RecommendationEvent(
            id=202,
            project_id=1,
            prompt_id=1,
            run_id=102,
            answer_hash="a2",
            entity_text="爱短链",
            speech_act="RECOMMEND",
            review_status="HUMAN_CONFIRMED",
            reasons_json=dumps([{"normalized_reason": "二维码背景图模板", "reason_scope": "ENTITY_SPECIFIC"}]),
        )
        doc_1 = SourceDocument(
            id=301,
            url="https://aifabu.com/stat",
            canonical_url="https://aifabu.com/stat",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text="爱短链支持点击统计，可以查看短链访问数据。",
            content_blocks_json=dumps([{"block_index": 1, "text": "爱短链支持点击统计，可以查看短链访问数据。"}]),
        )
        doc_2 = SourceDocument(
            id=302,
            url="https://aifabu.com/template",
            canonical_url="https://aifabu.com/template",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text="爱短链提供二维码背景图模板，适合活动海报、门店物料和品牌传播场景。",
            content_blocks_json=dumps([{
                "block_index": 1,
                "text": "爱短链提供二维码背景图模板，适合活动海报、门店物料和品牌传播场景。",
            }]),
        )
        refs = [
            ReferenceSource(
                id=401,
                run_id=101,
                reference_index=1,
                url="https://aifabu.com/stat",
                canonical_url="https://aifabu.com/stat",
                domain="aifabu.com",
            ),
            ReferenceSource(
                id=402,
                run_id=102,
                reference_index=1,
                url="https://aifabu.com/template",
                canonical_url="https://aifabu.com/template",
                domain="aifabu.com",
            ),
        ]
        package = OptimizationEvidencePackage(
            id=601,
            project_id=1,
            prompt_id=1,
            version=1,
            status="active",
            package_hash="pkg",
            source_run_ids_json=dumps([101, 102]),
        )
        claim_1 = SourceClaim(
            id=501,
            project_id=1,
            source_document_id=301,
            passage_id="doc301:b1",
            source_owner_entity="爱短链",
            subject_entity="爱短链",
            normalized_claim="爱短链支持点击统计",
            claim_type="CAPABILITY",
            polarity="POSITIVE",
            source_span="爱短链支持点击统计",
            prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
            review_status="MACHINE_GROUNDED",
        )
        claim_2 = SourceClaim(
            id=502,
            project_id=1,
            source_document_id=302,
            passage_id="doc302:b1",
            source_owner_entity="爱短链",
            subject_entity="爱短链",
            normalized_claim="爱短链提供二维码背景图模板",
            claim_type="CAPABILITY",
            polarity="POSITIVE",
            source_span="爱短链提供二维码背景图模板",
            prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
            schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
            review_status="MACHINE_GROUNDED",
        )
        old_only_support = EvidenceAlignment(
            id=701,
            project_id=1,
            prompt_id=1,
            run_id=101,
            recommendation_event_id=201,
            recommendation_reason_id="reason:支持点击统计",
            source_document_id=302,
            source_claim_id=502,
            relation="SUPPORTS",
            scope_relation="PASS",
            prompt_version=ALIGNMENT_PROMPT_VERSION,
            schema_version=ALIGNMENT_SCHEMA_VERSION,
            review_status="HUMAN_CONFIRMED",
            machine_payload_json=dumps({"semantic_reason_key": "支持点击统计|ENTITY_SPECIFIC|爱短链"}),
        )
        db.add_all([*runs, event_1, event_2, doc_1, doc_2, *refs, package, claim_1, claim_2, old_only_support])
        db.commit()

        plan = build_incremental_materialization_plan(db, project, 1, top_k=1)
        shadow = plan["evidence_alignment"]["candidate_builder_shadow"]

        dry_run = run_evidence_alignment(
            db,
            project,
            prompt_id=1,
            run_ids=[101, 102],
            include_answer_binding_reasons=True,
            doc_id_filter=[301, 302],
            candidate_dry_run=True,
        )

        assert shadow["mode"] == "PRODUCTION_CUTOVER"
        assert shadow["cutover_enabled"] is True
        assert shadow["legacy_candidate_builder_rollback_available"] is True
        assert shadow["current_candidate_keys"] == 4
        assert shadow["proposed_candidate_keys"] == 2
        assert dry_run["production_candidate_keys"] == shadow["proposed_candidate_keys"]
        assert dry_run["candidate_key_hash"] == shadow["proposed_candidate_key_hash"]
        assert shadow["old_only_candidate_keys"] == 2
        assert shadow["new_only_candidate_keys"] == 0
        assert shadow["old_only_existing_verdict_counts"] == {"SUPPORTS": 1}
        assert shadow["old_only_supports_contradicts_row_count"] == 1
        assert shadow["old_only_supports_contradicts_count"] == 1
        assert shadow["old_only_requires_review_before_cutover"] is True
        assert shadow["critical_classification_counts"] == {"TRUE_POSITIVE_RECALL_LOSS": 1}
        assert shadow["critical_exclusion_reason_counts"] == {"RUN_SCOPE_MISS": 1}
        assert shadow["recall_layer_comparison"]["L0_EXPLICIT"]["candidates"] == 0
        assert shadow["recall_layer_comparison"]["L1_ANSWER_CONTEXT"]["candidates"] == 0
        assert shadow["recall_layer_comparison"]["L2_RUN_SCOPE"]["candidates"] == 2
        assert shadow["recall_layer_comparison"]["L3_PROMPT_SCOPE"]["candidates"] == 0
        assert shadow["l1_status"] == "L1_UNAVAILABLE_BY_SCHEMA"
        assert shadow["l2_status"] == "L2_IMPLEMENTED_MATCH"
        assert shadow["topk_application"]["L0_EXPLICIT_topk_applied"] is False
        assert shadow["topk_application"]["L2_RUN_SCOPE_topk_applied"] is True
        assert shadow["old_only_supports_contradicts"][0]["sample_alignment_id"] == 701
        assert shadow["old_only_supports_contradicts"][0]["alignment_ids"] == [701]
        assert shadow["old_only_supports_contradicts"][0]["source_claim_id"] == 502
        trace = shadow["old_only_supports_contradicts"][0]["recall_trace"]
        assert trace["final_exclusion_reason"] == "RUN_SCOPE_MISS"
        assert trace["highest_recall_level_used"] == "L2_RUN_SCOPE"
        assert trace["BM25_score"] == "unavailable"
        assert trace["semantic_score"] == "unavailable"
    finally:
        db.close()


def test_alignment_shadow_policy_d_keeps_boundary_ties():
    db = _session()
    try:
        project = _base_project(db)
        runs = [
            BrowserMonitorRun(
                id=run_id,
                task_id=1,
                project_id=1,
                prompt_id=1,
                status="success",
                answer_text=answer_text,
            )
            for run_id, answer_text in (
                (101, "爱短链因为可以自动生成加密短链被推荐。"),
                (102, "补充引用样本。"),
            )
        ]
        event = RecommendationEvent(
            id=201,
            project_id=1,
            prompt_id=1,
            run_id=101,
            answer_hash="a1",
            entity_text="爱短链",
            speech_act="RECOMMEND",
            review_status="HUMAN_CONFIRMED",
            reasons_json=dumps([{"normalized_reason": "可以自动生成加密短链", "reason_scope": "ENTITY_SPECIFIC"}]),
        )
        low_doc = SourceDocument(
            id=301,
            url="https://aifabu.com/low",
            canonical_url="https://aifabu.com/low",
            domain="aifabu.com",
            fetch_status="SUCCESS",
            clean_text="爱短链提供访问统计。",
            content_blocks_json=dumps([{"block_index": 1, "text": "爱短链提供访问统计。"}]),
        )
        refs = [
            ReferenceSource(
                id=401,
                run_id=101,
                reference_index=1,
                url="https://aifabu.com/low",
                canonical_url="https://aifabu.com/low",
                domain="aifabu.com",
            )
        ]
        docs = [low_doc]
        claims = [
            SourceClaim(
                id=501,
                project_id=1,
                source_document_id=301,
                passage_id="doc301:b1",
                source_owner_entity="爱短链",
                subject_entity="爱短链",
                normalized_claim="爱短链提供访问统计",
                claim_type="CAPABILITY",
                polarity="POSITIVE",
                source_span="爱短链提供访问统计",
                prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
                schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
                review_status="MACHINE_GROUNDED",
            )
        ]
        for offset in range(6):
            doc_id = 302 + offset
            claim_id = 502 + offset
            url = f"https://aifabu.com/tie-{offset}"
            text = f"爱短链系统自动生成加密短链，适合跳转场景 {offset}"
            docs.append(SourceDocument(
                id=doc_id,
                url=url,
                canonical_url=url,
                domain="aifabu.com",
                fetch_status="SUCCESS",
                clean_text=text,
                content_blocks_json=dumps([{"block_index": 1, "text": text}]),
            ))
            refs.append(ReferenceSource(
                id=402 + offset,
                run_id=102,
                reference_index=offset + 1,
                url=url,
                canonical_url=url,
                domain="aifabu.com",
            ))
            claims.append(SourceClaim(
                id=claim_id,
                project_id=1,
                source_document_id=doc_id,
                passage_id=f"doc{doc_id}:b1",
                source_owner_entity="爱短链",
                subject_entity="爱短链",
                normalized_claim="爱短链系统自动生成加密短链",
                claim_type="CAPABILITY",
                polarity="POSITIVE",
                source_span=text,
                prompt_version=SOURCE_CLAIM_PROMPT_VERSION,
                schema_version=SOURCE_CLAIM_SCHEMA_VERSION,
                review_status="MACHINE_GROUNDED",
            ))
        package = OptimizationEvidencePackage(
            id=601,
            project_id=1,
            prompt_id=1,
            version=1,
            status="active",
            package_hash="pkg",
            source_run_ids_json=dumps([101, 102]),
        )
        old_support = EvidenceAlignment(
            id=701,
            project_id=1,
            prompt_id=1,
            run_id=101,
            recommendation_event_id=201,
            recommendation_reason_id="reason:可以自动生成加密短链",
            source_document_id=307,
            source_claim_id=507,
            relation="SUPPORTS",
            scope_relation="PASS",
            prompt_version=ALIGNMENT_PROMPT_VERSION,
            schema_version=ALIGNMENT_SCHEMA_VERSION,
            review_status="HUMAN_CONFIRMED",
            machine_payload_json=dumps({"semantic_reason_key": "可以自动生成加密短链|ENTITY_SPECIFIC|爱短链"}),
        )
        db.add_all([*runs, event, *docs, *refs, package, *claims, old_support])
        db.commit()

        plan = build_incremental_materialization_plan(db, project, 1, top_k=5)
        shadow = plan["evidence_alignment"]["candidate_builder_shadow"]

        assert shadow["selected_shadow_policy"] == "Policy D"
        assert shadow["policy_simulations"]["Policy A"]["TRUE_POSITIVE_RECALL_LOSS"] == 1
        assert shadow["policy_simulations"]["Policy D"]["TRUE_POSITIVE_RECALL_LOSS"] == 0
        assert shadow["base_hard_topk_true_positive_recall_loss_count"] == 1
        assert shadow["true_positive_recall_loss_count"] == 0
        assert shadow["proposed_candidate_keys"] == 6
        assert shadow["boundary_tie_stats"]["reasons_with_boundary_ties"] == 1
        assert shadow["boundary_tie_stats"]["max_boundary_tie_bucket_size"] == 6
        assert shadow["critical_boundary_tie_details"][0]["source_claim_id"] == 507
        assert shadow["critical_boundary_tie_details"][0]["rank"] == 6
        assert shadow["critical_boundary_tie_details"][0]["tie_bucket_size"] == 6
        assert shadow["c2b_cutover_gate"]["boundary_tie_policy_verified"] is True
        assert shadow["l0_status"] == "L0_IMPLEMENTED_NO_MATCH"
        assert shadow["l0_semantics_change_explanation"]["reason_for_L0_change"] == "SHADOW_LOGIC_CHANGED_AS_DESIGNED"
    finally:
        db.close()
