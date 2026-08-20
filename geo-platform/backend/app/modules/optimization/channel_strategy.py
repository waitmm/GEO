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
    "BILIBILI": ["视频教程"],
}

PLATFORM_LABELS = {
    "DOUYIN": "抖音",
    "BAIJIAHAO": "百家号",
    "ZHIHU": "知乎",
    "BILIBILI": "B站",
}

# 平台关键词（事件/理由文本匹配）
PLATFORM_KEYWORDS = {
    "DOUYIN": ("抖音", "douyin"),
    "BAIJIAHAO": ("百家号", "百度百家号"),
    "ZHIHU": ("知乎",),
    "BILIBILI": ("bilibili", "b站", "哔哩哔哩"),
}

# 平台引用域名
PLATFORM_DOMAINS = {
    "DOUYIN": {"douyin.com"},
    "BAIJIAHAO": {"baijiahao.baidu.com", "mbd.baidu.com", "quanmin.baidu.com"},
    "ZHIHU": {"zhihu.com", "zhuanlan.zhihu.com"},
    "BILIBILI": {"bilibili.com", "b23.tv"},
}

# 建议执行组合（按平台拼接，V3 固定文案）
PLATFORM_COMBINATION_TEXT = {
    "DOUYIN": "在抖音发布视频教程、操作教程，重点展示卡片效果、配置步骤、适用场景和跳转限制",
    "BAIJIAHAO": "在百家号发布操作教程、问答内容，重点沉淀可索引的步骤说明、FAQ、平台规则和排障清单",
    "ZHIHU": "在知乎发布问答内容、操作教程，重点回答怎么做、工具选择、限制条件、常见失败原因和安全合规问题",
    "BILIBILI": "在B站发布视频教程，重点演示操作步骤、卡片效果、适用场景和常见失败原因",
}

TIER_LABELS = {
    1: "答案明确推荐上下文",
    2: "选择理由上下文",
    3: "普通引用分布",
}

SORTING_RULE = "答案明确推荐上下文优先，其次选择理由上下文，再其次普通引用分布。"

# 引用计分权重：答案中明确推荐了品牌（含自身品牌与竞品）的答案，其引用计分更高
RECOMMENDED_ANSWER_CITATION_WEIGHT = 2

# 备选罗列阈值：引用次数超过该值（严格大于 2 次，即 ≥3）的域名都罗列为备选
MIN_CITATION_THRESHOLD = 3

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

    # 明确推荐了品牌（含自身品牌与竞品）的答案 Run：其引用计分更高
    recommended_answer_run_ids = {
        e.run_id for e in events if e.speech_act == "INCLUDE_AS_OPTION"
    }

    # 普通引用分布（按域名归平台）
    references = (
        db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
        if run_ids
        else []
    )
    citation_count: dict[str, int] = {}
    citation_runs: dict[str, set[int]] = {}
    recommended_answer_citation_count: dict[str, int] = {}
    # 未映射到四平台的域名单独统计（备选罗列用）
    domain_count: dict[str, int] = {}
    domain_runs: dict[str, set[int]] = {}
    domain_recommended_count: dict[str, int] = {}
    for ref in references:
        domain = (ref.domain or "").strip().lower()
        if not domain:
            continue
        matched = False
        for key, domains in PLATFORM_DOMAINS.items():
            if domain in domains:
                citation_count[key] = citation_count.get(key, 0) + 1
                citation_runs.setdefault(key, set()).add(ref.run_id)
                if ref.run_id in recommended_answer_run_ids:
                    recommended_answer_citation_count[key] = recommended_answer_citation_count.get(key, 0) + 1
                matched = True
                break
        if not matched:
            domain_count[domain] = domain_count.get(domain, 0) + 1
            domain_runs.setdefault(domain, set()).add(ref.run_id)
            if ref.run_id in recommended_answer_run_ids:
                domain_recommended_count[domain] = domain_recommended_count.get(domain, 0) + 1

    platforms = []
    for key in PLATFORM_LABELS:
        tier = 1 if tier1.get(key) else 2 if tier2.get(key) else 3
        total = citation_count.get(key, 0)
        rec = recommended_answer_citation_count.get(key, 0)
        # 引用计分：答案中明确推荐了品牌（含自身与竞品）的引用加权
        citation_score = rec * RECOMMENDED_ANSWER_CITATION_WEIGHT + (total - rec)
        platforms.append(
            {
                "key": key,
                "label": PLATFORM_LABELS[key],
                "tier": tier,
                "tier_label": TIER_LABELS[tier],
                "tier1_signals": tier1.get(key, []),
                "tier2_signals": tier2.get(key, []),
                "citation_count": total,
                "citation_run_count": len(citation_runs.get(key, set())),
                "recommended_answer_citation_count": rec,
                "citation_score": citation_score,
                "content_types": PLATFORM_CONTENT_TYPES[key],
            }
        )
    # 引用超过阈值的其他域名罗列为备选（无内容类型映射，只罗列数据）
    for domain, total in sorted(domain_count.items(), key=lambda item: -item[1]):
        if total < MIN_CITATION_THRESHOLD:
            continue
        rec = domain_recommended_count.get(domain, 0)
        platforms.append(
            {
                "key": f"DOMAIN:{domain}",
                "label": domain,
                "tier": 3,
                "tier_label": TIER_LABELS[3],
                "tier1_signals": [],
                "tier2_signals": [],
                "citation_count": total,
                "citation_run_count": len(domain_runs.get(domain, set())),
                "recommended_answer_citation_count": rec,
                "citation_score": rec * RECOMMENDED_ANSWER_CITATION_WEIGHT + (total - rec),
                "content_types": [],
            }
        )
    # 排序：分层优先（V3 规则）；同层内按引用计分降序，平分按引用量，再按名称
    platforms.sort(
        key=lambda p: (p["tier"], -p["citation_score"], -p["citation_count"], p["label"])
    )

    combination = "；".join(
        PLATFORM_COMBINATION_TEXT[p["key"]]
        for p in platforms
        if p["key"] in PLATFORM_COMBINATION_TEXT
    ) + "。"

    from app.models import Prompt

    prompt_row = db.get(Prompt, prompt_id)
    topic_text = (prompt_row.prompt_text or "").strip().split("\n")[0][:40] if prompt_row else str(prompt_id)

    return {
        "prompt_id": prompt_id,
        "content_direction": CONTENT_DIRECTION_TEMPLATE.format(topic=topic_text),
        "platforms": platforms,
        "combination": combination,
        "sorting_rule": SORTING_RULE,
        "citation_scoring_rule": (
            f"普通引用分布内按引用计分排序：答案中明确推荐了品牌（含自身品牌与竞品）"
            f"的引用计分更高（权重 {RECOMMENDED_ANSWER_CITATION_WEIGHT}），其余引用计 1。"
        ),
        "recommended_answer_run_count": len(recommended_answer_run_ids),
        "notes": NOTES,
    }
