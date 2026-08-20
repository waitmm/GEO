"""人工审核工作流 — 机器分析 → 人工确认 → 一键继续 → 下一 Gate。

产品化目标：用户只负责"确认"，系统负责"接着往后跑"。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.models import (
    BrowserMonitorRun,
    Competitor,
    EvidenceAlignment,
    Project,
    Prompt,
    RecommendationEvent,
    SourceClaim,
    TargetBrandCapabilityTruth,
)
from app.services.serialization import dumps, loads


# ---------------------------------------------------------------------------
# 竞品候选发现
# ---------------------------------------------------------------------------

def discover_competitor_candidates(db: Session, project: Project, prompt_id: int) -> list[dict]:
    """从 RecommendationEvent 中发现潜在竞品（未在项目竞品库中的实体）。

    发现依据：Grounding 通过的事件实体，排除目标品牌自身。
    """
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()

    known = {project.brand_name, *(c.name for c in db.query(Competitor).filter(Competitor.project_id == project.id).all())}
    # 目标品牌别名也算已知
    known |= set(loads(project.brand_aliases_json, []))

    seen: dict[str, dict] = {}
    for e in events:
        name = (e.entity_text or "").strip()
        if not name or name in known:
            continue
        row = seen.setdefault(name, {"entity": name, "run_ids": set(), "speech_acts": set(), "answer_span": e.answer_span})
        row["run_ids"].add(e.run_id)
        row["speech_acts"].add(e.speech_act)

    return [
        {
            "entity": v["entity"],
            "run_coverage": f"{len(v['run_ids'])}/{len(events)}",
            "speech_acts": sorted(v["speech_acts"]),
            "answer_span": v["answer_span"][:200],
        }
        for v in sorted(seen.values(), key=lambda x: -len(x["run_ids"]))
    ]


def confirm_competitor(db: Session, project: Project, name: str, website_url: str = "") -> dict:
    """确认竞品 → 永久加入 Project Competitors。"""
    existing = db.query(Competitor).filter(
        Competitor.project_id == project.id, Competitor.name == name,
    ).first()
    if existing:
        return {"status": "EXISTS", "id": existing.id}
    comp = Competitor(project_id=project.id, name=name, aliases_json="[]", website_url=website_url)
    db.add(comp)
    db.commit()
    db.refresh(comp)
    return {"status": "CONFIRMED", "id": comp.id}


# ---------------------------------------------------------------------------
# 工作流状态
# ---------------------------------------------------------------------------

def workflow_status(db: Session, project: Project, prompt_id: int) -> dict:
    """返回 Prompt 级工作流状态（9 步）。"""
    run_ids = [
        r.id for r in db.query(BrowserMonitorRun).filter(
            BrowserMonitorRun.project_id == project.id,
            BrowserMonitorRun.prompt_id == prompt_id,
        ).all()
    ]
    total_runs = len(run_ids) or 1

    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
    ).all()
    unique_event_keys = {(e.answer_hash, e.entity_text, e.speech_act) for e in events}
    events_reviewed = sum(1 for e in events if e.review_status in {"HUMAN_CONFIRMED", "HUMAN_REJECTED"})

    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
    ).all()
    supports_reviewed = sum(1 for a in supports if a.review_status in {"HUMAN_CONFIRMED", "HUMAN_REJECTED"})

    truths = db.query(TargetBrandCapabilityTruth).filter(
        TargetBrandCapabilityTruth.project_id == project.id,
    ).all()
    truths_pending = [t for t in truths if t.product_truth_status in {"UNKNOWN", ""}]

    reviews_done = (
        bool(events) and events_reviewed >= len(unique_event_keys)
        and bool(supports) and supports_reviewed >= len(supports)
        and bool(truths) and not truths_pending
    )

    # gap/action 的人工确认状态
    import sqlite3
    conn = sqlite3.connect('geo_v0.db')
    confirmed = {
        r[0] for r in conn.execute(
            "SELECT step_key FROM workflow_confirmations WHERE project_id=? AND prompt_id=? AND decision_status='CONFIRMED'",
            (project.id, prompt_id),
        ).fetchall()
    }
    conn.close()
    gap_confirmed = "gap" in confirmed
    action_confirmed = "action" in confirmed
    steps = [
        {"key": "collection", "label": "数据采集", "done": total_runs >= 1, "detail": f"{total_runs} Runs"},
        {"key": "answer_semantic", "label": "推荐行为分析", "done": len(unique_event_keys) >= 1, "detail": f"{len(unique_event_keys)} 组独特事件"},
        {"key": "event_review", "label": "推荐行为人工确认", "done": bool(events) and events_reviewed >= len(unique_event_keys), "detail": f"{min(events_reviewed, len(unique_event_keys))}/{len(unique_event_keys)} 组已审"},
        {"key": "evidence", "label": "Evidence 分析", "done": bool(supports), "detail": f"{len(supports)} 条对齐"},
        {"key": "evidence_review", "label": "Evidence 人工确认", "done": bool(supports) and supports_reviewed >= len(supports), "detail": f"{supports_reviewed}/{len(supports)} 条已审"},
        {"key": "product_truth", "label": "目标品牌能力确认", "done": bool(truths) and not truths_pending, "detail": f"{len(truths)-len(truths_pending)}/{len(truths)} 条已确认" if truths else "0 条"},
        {"key": "gap", "label": "Gap Diagnosis", "done": gap_confirmed, "detail": "已人工确认" if gap_confirmed else ("可生成（点「继续分析」）" if reviews_done else "待审核完成后生成")},
        {"key": "action", "label": "Action Candidate", "done": action_confirmed, "detail": "已人工确认" if action_confirmed else ("可生成（点「继续分析」）" if reviews_done else "待 Gap 后生成")},
        {"key": "experiment", "label": "实验", "done": False, "detail": "待 Action 确认后进入" if gap_confirmed and action_confirmed else "未开始"},
    ]
    pending = sum(1 for s in steps if not s["done"] and s["key"] not in {"gap", "action", "experiment"})
    return {
        "project_id": project.id,
        "prompt_id": prompt_id,
        "steps": steps,
        "pending_review_steps": pending,
        "all_reviews_done": pending == 0,
    }


# ---------------------------------------------------------------------------
# 审核队列（去重：相同 answer_hash 只审一次）
# ---------------------------------------------------------------------------

def review_queue(db: Session, project: Project, prompt_id: int) -> dict:
    """返回去重后的待审核队列：事件（按 answer_hash 去重）+ 对齐（按 claim 对）。"""
    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "MACHINE_CANDIDATE"]),
    ).all()

    # 按 answer_hash 去重事件
    unique_events: dict[str, dict] = {}
    for e in events:
        key = e.answer_hash or e.answer_span
        row = unique_events.setdefault(key, {
            "answer_hash": e.answer_hash,
            "entity_text": e.entity_text,
            "speech_act": e.speech_act,
            "recommendation_strength": e.recommendation_strength,
            "polarity": e.polarity,
            "answer_span": e.answer_span,
            "reasons": loads(e.reasons_json, []),
            "run_ids": set(),
            "event_ids": [],
        })
        row["run_ids"].add(e.run_id)
        row["event_ids"].append(e.id)

    # 审核队列只包含需要人工判断的对齐：
    # SUPPORTS（可能过度断言）—— RELATED/NONE/COMPETITOR_CONTEXT 为确定性或低价值，不占用人工
    supports = db.query(EvidenceAlignment).filter(
        EvidenceAlignment.project_id == project.id,
        EvidenceAlignment.prompt_id == prompt_id,
        EvidenceAlignment.relation == "SUPPORTS",
        EvidenceAlignment.review_status == "MACHINE_GROUNDED",
    ).all()

    align_items = []
    seen_align = set()
    for a in supports:
        claim = db.get(SourceClaim, a.source_claim_id) if a.source_claim_id else None
        key = (a.source_claim_id, a.recommendation_reason_id)
        if key in seen_align:
            continue
        seen_align.add(key)
        align_items.append({
            "alignment_id": a.id,
            "reason_text": a.recommendation_reason_id.replace("reason:", ""),
            "claim_text": claim.normalized_claim if claim else "",
            "claim_span": claim.source_span if claim else "",
            "relation": a.relation,
            "run_ids": sorted({e.run_id for e in events})[:12],
        })

    if not unique_events and not align_items and not events:
        # 该 Prompt 尚未运行语义分析：明确告知，不要误报"全部审核完成"
        return {"status": "NOT_ANALYZED", "unique_events": [], "alignments": [], "message": "该 Prompt 尚未执行机器分析，请先运行分析。"}

    return {
        "status": "READY",
        "unique_events": [
            {**{k: v for k, v in row.items() if k not in {"run_ids", "event_ids"}},
             "run_ids": sorted(row["run_ids"]), "event_ids": row["event_ids"], "run_count": len(row["run_ids"])}
            for row in unique_events.values()
        ],
        "alignments": align_items,
    }


def batch_confirm_events(db: Session, event_ids: list[int], reviewer: str = "human") -> dict:
    """批量确认事件（answer_hash 相同的全部 Runs 一起确认）。"""
    updated = 0
    for eid in event_ids:
        e = db.get(RecommendationEvent, eid)
        if e:
            e.review_status = "HUMAN_CONFIRMED"
            e.reviewer = reviewer
            updated += 1
    db.commit()
    return {"updated": updated}


def confirm_alignment(db: Session, alignment_id: int, relation: str, reviewer: str = "human") -> dict:
    a = db.get(EvidenceAlignment, alignment_id)
    if not a:
        return {"status": "NOT_FOUND"}
    a.review_status = "HUMAN_CONFIRMED"
    a.relation = relation
    a.reviewer = reviewer
    db.commit()
    return {"status": "CONFIRMED", "relation": relation}
