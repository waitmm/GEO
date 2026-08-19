"""Layer 2 — Source Qualification：Ownership Resolver + Content Quality。

关键纪律：
- Content Quality 与 fetch_status 分层：新增 source_quality 记录，
  绑定 clean_text_hash + extractor_version，绝不改写历史 fetch_status。
- Ownership（source_owner_entity）只是 provenance；
  语义主体判断以 SourceClaim.subject_entity 为准（Layer 4）。
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Competitor, Project, SourceDocument, SourceQuality

OWNERSHIP_VERSION = "ownership.v1"
QUALITY_VERSION = "content_quality.v1_rule_zh"

# ---------------------------------------------------------------------------
# Ownership Resolver（确定性规则）
# ---------------------------------------------------------------------------

_UGC_DOMAINS = {
    "zhihu.com", "zhuanlan.zhihu.com", "baijiahao.baidu.com", "weibo.com",
    "xiaohongshu.com", "bbs.molelink.cn", "tieba.baidu.com",
}
_PLATFORM_NATIVE_DOMAINS = {
    "bilibili.com", "douyin.com", "m.douyin.com", "open.douyin.com",
    "haokan.baidu.com", "quanmin.baidu.com", "so.douyin.com",
    "mp.weixin.qq.com",
}
_EDITORIAL_DOMAINS = {
    "news.sohu.com", "sohu.com", "mbd.baidu.com", "jingyan.baidu.com",
    "baike.baidu.com", "word.baidu.com",
}


def host_of(url: str) -> str:
    host = url.split("://")[-1].split("/")[0].split("?")[0].lower()
    return host[4:] if host.startswith("www.") else host


def resolve_ownership(db: Session, project: Project, url: str, domain: str | None = None) -> dict:
    """返回 {source_role, source_owner_entity, platform}。

    竞品从 Project.competitors 动态读取（不硬编码）。
    """
    d = (domain or host_of(url)).lower()
    brand_domain = host_of(project.website_url or "") if project.website_url else ""
    brand_name = project.brand_name

    # 目标品牌第一方
    if brand_domain and (d == brand_domain or d.endswith("." + brand_domain)):
        return {"source_role": "TARGET_FIRST_PARTY", "source_owner_entity": brand_name, "platform": "OWNED"}

    # 竞品第一方（动态读取 competitors）
    competitors = db.query(Competitor).filter(Competitor.project_id == project.id).all()
    for comp in competitors:
        comp_domain = host_of(comp.website_url or "") if comp.website_url else ""
        if comp_domain and (d == comp_domain or d.endswith("." + comp_domain)):
            return {"source_role": "COMPETITOR_FIRST_PARTY", "source_owner_entity": comp.name, "platform": "COMPETITOR_OWNED"}

    # 其他确定性分类
    if any(d == item or d.endswith("." + item) for item in _UGC_DOMAINS):
        return {"source_role": "UGC_COMMUNITY", "source_owner_entity": "UNKNOWN", "platform": "UGC"}
    if any(d == item or d.endswith("." + item) for item in _PLATFORM_NATIVE_DOMAINS):
        return {"source_role": "PLATFORM_NATIVE", "source_owner_entity": "UNKNOWN", "platform": "PLATFORM"}
    if any(d == item or d.endswith("." + item) for item in _EDITORIAL_DOMAINS):
        return {"source_role": "INDEPENDENT_EDITORIAL", "source_owner_entity": "UNKNOWN", "platform": "EDITORIAL"}

    return {"source_role": "UNKNOWN", "source_owner_entity": "UNKNOWN", "platform": "UNKNOWN"}


# ---------------------------------------------------------------------------
# Content Quality Assessor（规则，不改写 fetch_status）
# ---------------------------------------------------------------------------

_CSS_NOISE = re.compile(r"@(?:keyframes|-webkit-|media)\b", re.IGNORECASE)
_BRACE_DENSITY_THRESHOLD = 0.03  # {} 占字符比
_CHALLENGE_KEYWORDS = ["验证码", "安全验证", "请点击", "访问异常", "登录后查看", "请完成验证", "人机验证"]
_NAV_KEYWORDS = ["首页", "登录", "注册", "导航", "更多好文", "相关阅读", "为你推荐"]


def _content_hash(clean_text: str) -> str:
    import hashlib
    return hashlib.sha256((clean_text or "").encode("utf-8")).hexdigest()


def assess_quality(doc: SourceDocument, extractor_version: str = "") -> SourceQuality:
    """对 SourceDocument 做内容质量分层（新增记录，不改 fetch_status）。"""
    text = doc.clean_text or ""
    length = len(text)
    reason_parts: list[str] = []

    if doc.fetch_status == "FETCH_FAILED":
        status = "FETCH_FAILED"
        reason_parts.append("fetch_status=FETCH_FAILED，无可分析正文")
    elif length == 0:
        status = "EMPTY"
        reason_parts.append("正文为空")
    elif length < 50:
        status = "NOISY"
        reason_parts.append(f"正文过短（{length} 字），疑为骨架/登录墙")
    else:
        brace_ratio = (text.count("{") + text.count("}")) / length
        css_hits = len(_CSS_NOISE.findall(text))
        if css_hits >= 3 or brace_ratio > _BRACE_DENSITY_THRESHOLD:
            status = "NOISY"
            reason_parts.append(f"CSS/JS 残留（css_hits={css_hits}, brace_ratio={brace_ratio:.3f}）")
        elif any(kw in text[:500] for kw in _CHALLENGE_KEYWORDS):
            status = "NOISY"
            reason_parts.append("疑似验证码/登录墙页面")
        elif text.count("\n") < 2 and any(kw in text for kw in _NAV_KEYWORDS) and length < 800:
            # 短文本且带导航特征 → 可能是导航壳
            status = "NOISY"
            reason_parts.append("疑似导航壳（短文本+导航关键词）")
        else:
            status = "CONTENT_VALID"

    return SourceQuality(
        source_document_id=doc.id,
        content_quality_status=status,
        quality_source="RULE",
        quality_reason="；".join(reason_parts) if reason_parts else "正文长度与噪声信号正常",
        clean_text_hash=_content_hash(text),
        extractor_version=extractor_version or QUALITY_VERSION,
        reviewed_at=None,
        reviewed_by="",
    )


def run_source_qualification(db: Session, project: Project, doc_ids: list[int] | None = None) -> dict:
    """对指定（或全部）SourceDocument 执行质量分层 + Ownership 解析。"""
    query = db.query(SourceDocument)
    if doc_ids:
        query = query.filter(SourceDocument.id.in_(doc_ids))
    docs = query.all()

    stats = {"CONTENT_VALID": 0, "NOISY": 0, "EMPTY": 0, "FETCH_FAILED": 0, "total": len(docs)}
    for doc in docs:
        # 幂等：同 hash + 同 extractor 已评估则跳过（保留历史评估）
        existing = (
            db.query(SourceQuality)
            .filter(
                SourceQuality.source_document_id == doc.id,
                SourceQuality.clean_text_hash == _content_hash(doc.clean_text or ""),
                SourceQuality.extractor_version == QUALITY_VERSION,
            )
            .first()
        )
        if existing:
            stats[existing.content_quality_status] = stats.get(existing.content_quality_status, 0) + 1
            continue
        record = assess_quality(doc, QUALITY_VERSION)
        db.add(record)
        stats[record.content_quality_status] = stats.get(record.content_quality_status, 0) + 1
    db.commit()
    return stats
