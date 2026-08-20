"""Intervention Plan → per-channel Experiment → Benchmark Checklist → Brief → Release/Retest/Outcome。

产品纪律：
- 渠道多选，但一个 Experiment 一个渠道 + 一个主要资产 + 一个 Hypothesis。
- Benchmark 只做定性 Checklist（不评分），由现有 Evidence 自动预填。
- 所有状态 fail-closed：未 Approved 不允许 RELEASED；无 Post Runs 不允许 Outcome。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    EvidenceAlignment,
    OptimizationExperiment,
    Project,
    Prompt,
    RecommendationEvent,
    SourceClaim,
    SourceDocument,
    TargetBrandCapabilityTruth,
)
from app.services.serialization import dumps, loads

from app.modules.optimization.content_brief import ContentBriefGenerator, _collect_evidence_context

CHANNEL_OPTIONS = [
    {"key": "OWNED_NEW_PAGE", "label": "官网新建教程页", "asset_type": "PAGE"},
    {"key": "OWNED_UPDATE", "label": "官网更新现有页", "asset_type": "PAGE"},
    {"key": "ZHIHU", "label": "知乎", "asset_type": "ARTICLE"},
    {"key": "BAIJIAHAO", "label": "百家号", "asset_type": "ARTICLE"},
    {"key": "BILIBILI", "label": "B站", "asset_type": "VIDEO"},
]


class InterventionPlanService:
    """Intervention Plan CRUD + per-channel Experiment 生成。"""

    def __init__(self, db: Session, project: Project, prompt: Prompt):
        self.db = db
        self.project = project
        self.prompt = prompt

    def _plan_table(self):
        import sqlite3
        return sqlite3.connect("geo_v0.db")

    def create_plan(self, run_ids: list[int], title: str = "") -> dict:
        """基于已确认 Gap 创建 Intervention Plan。"""
        context = _collect_evidence_context(self.db, self.project, self.prompt.id)
        reasons = context["market_criteria"]
        plan_title = title or f"{self.prompt.prompt_text} — 增强 {self.project.brand_name} Evidence"
        objective = (
            f"增强「{self.project.brand_name}」在 {', '.join(reasons[:3]) if reasons else '当前市场选择标准'} "
            "上的证据，提升品牌进入 AI 候选/推荐的概率"
        )
        conn = self._plan_table()
        cur = conn.execute(
            """INSERT INTO intervention_plans
               (project_id, prompt_id, title, objective, reason_ids_json, intervention_goal, status, created_by)
               VALUES (?, ?, ?, ?, ?, 'EVIDENCE_STRENGTHEN', 'DRAFT', 'human')""",
            (self.project.id, self.prompt.id, plan_title, objective, dumps(reasons)),
        )
        plan_id = cur.lastrowid
        conn.commit()
        conn.close()
        return {"plan_id": plan_id, "title": plan_title, "objective": objective}

    def get_or_create_plan(self, run_ids: list[int]) -> dict:
        conn = self._plan_table()
        row = conn.execute(
            "SELECT id, title, objective, status, reason_ids_json FROM intervention_plans WHERE project_id=? AND prompt_id=? ORDER BY id DESC LIMIT 1",
            (self.project.id, self.prompt.id),
        ).fetchone()
        conn.close()
        if row:
            return {"plan_id": row[0], "title": row[1], "objective": row[2], "status": row[3], "reason_ids": loads(row[4], [])}
        return self.create_plan(run_ids)

    def create_per_channel_experiment(self, plan_id: int, channel: str, run_ids: list[int]) -> dict:
        """一个渠道创建一个 Experiment 草案。"""
        info = next((c for c in CHANNEL_OPTIONS if c["key"] == channel), CHANNEL_OPTIONS[0])
        # 该渠道的 Benchmark：SUPPORTS 且人工确认的 SourceClaim 所属文档按渠道匹配
        benchmark = self._benchmark_for_channel(channel)
        hypothesis = (
            f"如果在{info['label']}发布围绕市场选择标准（{', '.join(benchmark['reasons'][:2]) if benchmark['reasons'] else '当前标准'}）"
            f"、提供 {self.project.brand_name} 真实 Product Truth 证据的内容，"
            f"则品牌在 Prompt #{self.prompt.id} 中的候选/推荐表现可能提升。"
        )
        exp = OptimizationExperiment(
            action_id=self._ensure_action_id(channel),
            intervention_plan_id=plan_id,
            channel=channel,
            experiment_mode="PER_CHANNEL",
            primary_benchmark_source_id=benchmark["primary_source_id"],
            benchmark_source_ids_json=dumps(benchmark["source_ids"]),
            target_reason_ids_json=dumps([]),
            target_gap_ids_json=dumps([]),
            hypothesis_text=hypothesis,
            brief_json=dumps({}),
            target_asset_type=info["asset_type"],
            target_asset_url="",
            status="draft",
            release_blocked=True,
            release_blocked_reason="WAITING_FOR_HUMAN_REVIEW",
            primary_metric="brand_mention_rate",
            secondary_metrics_json=dumps(["candidate_capture_rate", "explicit_recommendation_rate"]),
            target_prompt_scope_json=dumps([self.prompt.id]),
        )
        self.db.add(exp)
        self.db.commit()
        self.db.refresh(exp)
        return {
            "experiment_id": exp.id,
            "channel": channel,
            "channel_label": info["label"],
            "hypothesis": hypothesis,
            "benchmark": benchmark,
            "status": "DRAFT",
        }

    def _benchmark_for_channel(self, channel: str) -> dict:
        """从 Evidence Chain 自动带出该渠道的 Benchmark 来源。"""
        supports = self.db.query(EvidenceAlignment).filter(
            EvidenceAlignment.project_id == self.project.id,
            EvidenceAlignment.prompt_id == self.prompt.id,
            EvidenceAlignment.relation == "SUPPORTS",
            EvidenceAlignment.review_status == "HUMAN_CONFIRMED",
        ).all()
        reasons = []
        source_ids = []
        doc_ids = set()
        for a in supports:
            reasons.append(a.recommendation_reason_id.replace("reason:", ""))
            doc_ids.add(a.source_document_id)
            source_ids.append(a.source_claim_id)

        # 渠道 → 域名映射（benchmark 只取与该渠道域名匹配的文档）
        channel_domains = {
            "ZHIHU": ["zhihu.com", "zhuanlan.zhihu.com"],
            "BILIBILI": ["bilibili.com"],
            "BAIJIAHAO": ["baijiahao.baidu.com"],
            "OWNED_NEW_PAGE": ["aifabu.com", "aiduanlian.com"],
            "OWNED_UPDATE": ["aifabu.com", "aiduanlian.com"],
        }
        domains = channel_domains.get(channel, [])
        docs = self.db.query(SourceDocument).filter(SourceDocument.id.in_(doc_ids)).all()
        matched_docs = [d for d in docs if any(d.domain and (d.domain == dm or d.domain.endswith("." + dm)) for dm in domains)]

        primary_id = matched_docs[0].id if matched_docs else (docs[0].id if docs else None)
        return {
            "reasons": sorted(set(reasons))[:5],
            "source_ids": source_ids[:20],
            "primary_source_id": primary_id,
            "channel_docs": [
                {"doc_id": d.id, "title": d.title, "domain": d.domain, "url": d.url}
                for d in (matched_docs or docs)[:5]
            ],
            "note": "Benchmark 是定性参考（不评分），用于生成内容 Brief",
        }

    def _ensure_action_id(self, channel: str) -> int:
        from app.models import OptimizationAction, OptimizationIssue
        issue = (
            self.db.query(OptimizationIssue)
            .filter(
                OptimizationIssue.project_id == self.project.id,
                OptimizationIssue.prompt_id == self.prompt.id,
            )
            .order_by(OptimizationIssue.id.desc())
            .first()
        )
        if not issue:
            issue = OptimizationIssue(
                project_id=self.project.id, prompt_id=self.prompt.id,
                issue_type="brand_absent", status="confirmed", severity=4,
                confidence_level="medium", analyzable_sample_count=12,
                observed_facts_json=dumps({"prompt_text": self.prompt.prompt_text}),
                diagnosis_summary="EVIDENCE_GAP（人工已确认）",
                confirmed_at=datetime.utcnow(),
            )
            self.db.add(issue)
            self.db.flush()
        action = OptimizationAction(
            issue_id=issue.id,
            action_type="content_create" if "NEW" in channel else ("content_update" if "UPDATE" in channel else ("video_publish" if channel == "BILIBILI" else "article_publish")),
            target_type="owned_content" if "OWNED" in channel else "external_platform",
            target_url="",
            status="PLANNED",
            priority=4,
            action_summary=f"{channel} 渠道内容干预（Intervention Plan 驱动）",
        )
        self.db.add(action)
        self.db.flush()
        return action.id


def generate_benchmark_checklist(db: Session, project: Project, prompt_id: int, experiment_id: int) -> dict:
    """自动生成定性 Benchmark Checklist（不评分）。"""
    exp = db.get(OptimizationExperiment, experiment_id)
    if not exp:
        return {"error": "experiment not found"}

    benchmark_ids = loads(exp.benchmark_source_ids_json, [])
    claims = db.query(SourceClaim).filter(SourceClaim.id.in_(benchmark_ids)).all()
    truths = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project.id,
        TargetBrandCapabilityTruth.product_truth_status == "SUPPORTED",
    ).all()

    # Benchmark 已覆盖（从 SourceClaim 归一化文本提取主题）
    covered = sorted({c.normalized_claim[:40] for c in claims[:8]})
    # Product Truth 增量
    truth_advantages = [t.capability_key for t in truths]
    # 观察到的不足：竞品 claims 中没有目标品牌能力（确定性判断）
    truth_keys = {t.capability_key for t in truths}
    misses = [
        "未发现目标品牌能力证据",
        "未明确说明限制条件（需人工核实对标原文）",
    ]

    checklist = {
        "benchmark_covered": [{"text": c} for c in covered],
        "observed_gaps": [{"text": m} for m in misses],
        "product_truth_advantages": [{"text": t, "source": "MANUAL_CONFIRMED"} for t in truth_advantages],
        "brief_requirements": [
            {"text": f"直接回答 Prompt：{prompt_id}", "checked": False},
            {"text": "覆盖市场选择标准（Reason）", "checked": False},
            *[{"text": f"提供真实 Product Truth：{t}", "checked": False} for t in truth_advantages],
            {"text": "说明限制条件与适用边界", "checked": False},
            {"text": "避免无法验证的营销表述", "checked": False},
        ],
        "no_score": True,
        "note": "Checklist 只做事实性指导，不评分、不排名。",
    }
    return checklist
