"""V3 平台×内容方向分析 — 基于当前答案信号分层，纯数据推导，不含人工偏好。

分层排序规则（由高到低）：
  1. 答案明确推荐上下文（INCLUDE_AS_OPTION 事件中出现的平台信号）
  2. 选择理由上下文（事件理由中出现的平台信号）
  3. 普通引用分布（引用来源域名）

平台 → 内容类型（固定映射）：
  抖音: 视频教程、操作教程
  百家号: 操作教程、问答内容
  知乎: 问答内容、操作教程

前置条件：三方平台账号可新注册，不以历史内容或账号存量作为前置条件；
最终平台、账号和 target_url 仍需人工审核确认。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import BrowserMonitorRun, Project, RecommendationEvent, ReferenceSource
from app.services.serialization import loads

# 平台 → 内容类型（V3 固定映射）
PLATFORM_CONTENT_TYPES = {
    "DOUYIN": ["视频教程", "操作教程"],
    "BAIJIAHAO": ["操作教程", "问答内容"],
    "ZHIHU": ["问答内容", "操作教程"],
}

PLATFORM_LABELS = {
    "DOUYIN": "抖音",
    "BAIJIAHAO": "百家号",
    "ZHIHU": "知乎",
}

# 平台关键词（事件/理由文本匹配）
PLATFORM_KEYWORDS = {
    "DOUYIN": ("抖音", "douyin"),
    "BAIJIAHAO": ("百家号", "百度百家号"),
    "ZHIHU": ("知乎",),
}

# 平台引用域名
PLATFORM_DOMAINS = {
    "DOUYIN": {"douyin.com"},
    "BAIJIAHAO": {"baijiahao.baidu.com", "mbd.baidu.com", "quanmin.baidu.com"},
    "ZHIHU": {"zhihu.com", "zhuanlan.zhihu.com"},
}

# 建议执行组合（按平台拼接，V3 固定文案）
PLATFORM_COMBINATION_TEXT = {
    "DOUYIN": "在抖音发布视频教程、操作教程，重点展示卡片效果、配置步骤、适用场景和跳转限制",
    "BAIJIAHAO": "在百家号发布操作教程、问答内容，重点沉淀可索引的步骤说明、FAQ、平台规则和排障清单",
    "ZHIHU": "在知乎发布问答内容、操作教程，重点回答怎么做、工具选择、限制条件、常见失败原因和安全合规问题",
}

TIER_LABELS = {
    1: "答案明确推荐上下文",
    2: "选择理由上下文",
    3: "普通引用分布",
}

SORTING_RULE = "答案明确推荐上下文优先，其次选择理由上下文，再其次普通引用分布。"

CONTENT_DIRECTION_TEMPLATE = (
    "围绕「{topic}」制作操作教程、问答内容、视频教程、工具说明页，"
    "重点回答定义、适用场景、操作步骤、风险限制和常见失败原因。"
)

NOTES = [
    "三方平台账号可新注册，不以历史内容或账号存量作为前置条件。",
    "最终平台、账号和 target_url 仍需人工审核确认。",
]


def _platform_hits(text: str) -> set[str]:
    """文本中命中的平台 key 集合。"""
    folded = (text or "").casefold()
    return {
        key
        for key, keywords in PLATFORM_KEYWORDS.items()
        if any(kw.casefold() in folded for kw in keywords)
    }


def channel_strategy(db: Session, project: Project, prompt_id: int) -> dict:
    """计算平台×内容方向建议。"""
    run_ids = [
        r.id
        for r in db.query(BrowserMonitorRun).filter(
            BrowserMonitorRun.project_id == project.id,
            BrowserMonitorRun.prompt_id == prompt_id,
        ).all()
    ]

    events = db.query(RecommendationEvent).filter(
        RecommendationEvent.project_id == project.id,
        RecommendationEvent.prompt_id == prompt_id,
        RecommendationEvent.review_status.in_(["MACHINE_GROUNDED", "HUMAN_CONFIRMED"]),
    ).all()

    # 分层信号
    tier1: dict[str, list[str]] = {}  # 答案明确推荐上下文
    tier2: dict[str, list[str]] = {}  # 选择理由上下文
    for e in events:
        context_text = " ".join(filter(None, [e.entity_text, e.answer_span]))
        if e.speech_act == "INCLUDE_AS_OPTION":
            for key in _platform_hits(context_text):
                tier1.setdefault(key, []).append(e.entity_text or "")
        for reason in loads(e.reasons_json, []):
            for key in _platform_hits(reason.get("normalized_reason", "")):
                tier2.setdefault(key, []).append(reason.get("normalized_reason", ""))

    # 普通引用分布（按域名归平台）
    references = (
        db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
        if run_ids
        else []
    )
    citation_count: dict[str, int] = {}
    citation_runs: dict[str, set[int]] = {}
    for ref in references:
        domain = (ref.domain or "").strip().lower()
        for key, domains in PLATFORM_DOMAINS.items():
            if domain in domains:
                citation_count[key] = citation_count.get(key, 0) + 1
                citation_runs.setdefault(key, set()).add(ref.run_id)
                break

    platforms = []
    for key in PLATFORM_LABELS:
        tier = 1 if tier1.get(key) else 2 if tier2.get(key) else 3
        platforms.append(
            {
                "key": key,
                "label": PLATFORM_LABELS[key],
                "tier": tier,
                "tier_label": TIER_LABELS[tier],
                "tier1_signals": tier1.get(key, []),
                "tier2_signals": tier2.get(key, []),
                "citation_count": citation_count.get(key, 0),
                "citation_run_count": len(citation_runs.get(key, set())),
                "content_types": PLATFORM_CONTENT_TYPES[key],
            }
        )
    # 排序规则：层内保持固定平台顺序（抖音→百家号→知乎），不引入其他排序偏好
    platforms.sort(key=lambda p: (p["tier"], list(PLATFORM_LABELS).index(p["key"])))

    combination = "；".join(PLATFORM_COMBINATION_TEXT[p["key"]] for p in platforms) + "。"

    from app.models import Prompt

    prompt_row = db.get(Prompt, prompt_id)
    topic_text = (prompt_row.prompt_text or "").strip().split("\n")[0][:40] if prompt_row else str(prompt_id)

    return {
        "prompt_id": prompt_id,
        "content_direction": CONTENT_DIRECTION_TEMPLATE.format(topic=topic_text),
        "platforms": platforms,
        "combination": combination,
        "sorting_rule": SORTING_RULE,
        "notes": NOTES,
    }
