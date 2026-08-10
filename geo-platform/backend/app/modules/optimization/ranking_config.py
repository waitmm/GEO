"""Citation Evidence Ranking V0 — Scoring Configuration.

All scoring parameters are centralized here for configurability and versioning.
Future experiment results should drive tuning of these parameters.

V0 is FROZEN as of 2026-08-07.
Any formula-level change (weights, thresholds, models, rules) requires scoring.v1.
"""

from __future__ import annotations

import hashlib
import json

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
SCORING_SPEC_VERSION = "scoring.v0"
CONFIDENCE_SPEC_VERSION = "confidence.v0"
RANKING_SCOPE = "WITHIN_PACKAGE_RELATIVE"


def compute_spec_fingerprint() -> str:
    """Deterministic hash of canonical scoring parameters.

    Same config → same fingerprint. Any V0 parameter change → fingerprint change.
    """
    canonical = {
        "version": SCORING_SPEC_VERSION,
        "confidence_version": CONFIDENCE_SPEC_VERSION,
        "factor_weights": dict(sorted(FACTOR_WEIGHTS.items())),
        "dimension_weights": dict(sorted(DIMENSION_WEIGHTS.items())),
        "correlation_threshold": CORRELATION_THRESHOLD,
        "correlation_min_pairs": CORRELATION_MIN_PAIRS,
        "sample_adequacy": dict(sorted(SAMPLE_ADEQUACY_CONFIG.items())),
        "minimum_observed_sample": dict(sorted(MINIMUM_OBSERVED_SAMPLE.items())),
        "minimum_completeness_gate": MINIMUM_COMPLETENESS_GATE,
        "completeness_linear_penalty_rate": COMPLETENESS_LINEAR_PENALTY_RATE,
        "rank_log_base": RANK_LOG_BASE,
        "rank_buckets": dict(sorted((k, dict(sorted(v.items()))) for k, v in RANK_BUCKETS.items())),
        "confidence_thresholds": dict(sorted((k, dict(sorted(v.items()))) for k, v in CONFIDENCE_THRESHOLDS.items())),
    }
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Known Limitations (frozen V0)
# ---------------------------------------------------------------------------
KNOWN_LIMITATIONS = [
    {
        "code": "SIGNAL_SCOPE_LIMITATION",
        "title": "信号范围局限",
        "status": "ACKNOWLEDGED",
        "description": (
            "当前活跃的证据信号主要反映引用频率和引用排名强度。"
            "对真实 GEO 提升效果的预测能力尚未通过受控实验验证。"
        ),
        "evidence_scope": "证据包 #7，1 个 Prompt，1 个模型，12 次采样",
        "impact": "V0 排名代表相对引用信号强度，不代表 GEO 有效性。",
    },
    {
        "code": "PLATFORM_AGGREGATION_LIMITATION",
        "title": "平台聚合局限",
        "status": "ACKNOWLEDGED",
        "description": (
            "推断平台是通过域名映射表从来源域名推导得出的。"
            "映射到同一推断平台的域名可能并不代表相同的内容生态、"
            "发布机制或执行渠道。"
        ),
        "evidence_scope": "域名到平台的映射基于启发式规则（基于域名推断）。",
        "impact": "平台分数聚合了异质来源。请务必下钻到域名级别查看详情。",
    },
    {
        "code": "CITATION_SOURCE_CONCENTRATION_LIMITATION",
        "title": "引用来源集中度",
        "status": "ACKNOWLEDGED",
        "description": (
            "证据包 #7 显示较高的引用来源集中度：372 次引用仅来自 31 个独立规范 URL；"
            "10/17 个域名的最高频 URL 占比达到 100%。"
            "这种集中度是否意味着引用来源的长期固化，或新内容进入引用集合存在困难，目前尚未验证。"
        ),
        "evidence_scope": "证据包 #7，单个时间窗口。",
        "impact": "排名靠前的域名可能仅由少量 URL 驱动。请勿将其解读为固定的引用池。",
    },
    {
        "code": "COMPLETENESS_VALIDATION_LIMITATION",
        "title": "完整度验证局限",
        "status": "ACKNOWLEDGED",
        "description": (
            "证据包 #7 中所有排名域名的证据完整度均为 100%。"
            "三种完整度模型在数据完整度一致的条件下产生相同的排名，"
            "这验证了模型不会在数据完整时错误扰动排名，"
            "但无法验证在真实缺失数据条件下的行为。"
        ),
        "evidence_scope": "证据包 #7，完整度均一。",
        "impact": "完整度模型在真实数据缺失场景下的行为尚未经过检验。",
    },
]

USAGE_WARNINGS = [
    "证据分数是当前证据包内的相对信号排名 —— 不是概率（0-100%），不可跨证据包直接比较。",
    "置信度（高/中/低）反映排名判断的数据支持程度 —— 不代表实验成功概率。",
    "平台排名来自域名聚合 —— 不是对单一最佳发布平台的推荐。",
    "排名范围为「证据包内相对比较」。不同证据包的分数不应在未经校准的情况下直接对比。",
    "V0 已冻结。任何公式级别修改（权重、阈值、模型、规则）需升级至 scoring.v1。",
]
# ---------------------------------------------------------------------------
SCORING_SPEC_VERSION = "scoring.v0"
CONFIDENCE_SPEC_VERSION = "confidence.v0"

# ---------------------------------------------------------------------------
# Rank Model Configuration
# ---------------------------------------------------------------------------
RANK_MODEL_LOG = "rank_model_v0_log"
RANK_MODEL_BUCKET = "rank_model_v0_bucket"

# Log model: score = 1 / log2(rank + 1)
RANK_LOG_BASE = 2.0

# Bucket model: discrete score buckets
RANK_BUCKETS = {
    "top_1_3": {"min_rank": 1, "max_rank": 3, "score": 3.0},
    "top_4_10": {"min_rank": 4, "max_rank": 10, "score": 2.0},
    "top_11_20": {"min_rank": 11, "max_rank": 20, "score": 1.0},
    "top_21_plus": {"min_rank": 21, "max_rank": float("inf"), "score": 0.5},
}

# ---------------------------------------------------------------------------
# Evidence Dimension Weights (V0 — configurable, not scientifically proven)
# ---------------------------------------------------------------------------
DIMENSION_WEIGHTS = {
    # Citation Volume
    "citation_occurrence_count": 0.15,
    "citation_run_coverage": 0.20,
    "citation_volume_share": 0.10,
    # Citation Rank (if available)
    "mean_citation_rank": 0.15,
    "top3_occurrence_share": 0.10,
    # Source Diversity
    "unique_citation_urls": 0.10,
    "source_diversity_ratio": 0.10,
    # Cross-Run Presence
    "citation_run_count": 0.10,
}

# Factor-level weights (aggregated from dimensions)
FACTOR_WEIGHTS = {
    "citation_strength": 0.35,
    "rank_strength": 0.25,
    "source_diversity": 0.20,
    "cross_run_presence": 0.20,
}

# ---------------------------------------------------------------------------
# Correlation / Redundancy
# ---------------------------------------------------------------------------
CORRELATION_THRESHOLD = 0.85  # |r| >= threshold → HIGHLY_CORRELATED
CORRELATION_MIN_PAIRS = 5     # minimum data points for correlation calculation

# ---------------------------------------------------------------------------
# Sample Adequacy Thresholds
# ---------------------------------------------------------------------------
SAMPLE_ADEQUACY_CONFIG = {
    "citation_run_count_low": 4,    # < this → LOW
    "citation_run_count_high": 8,   # >= this → HIGH
    "occurrence_count_low": 10,     # < this → LOW
    "occurrence_count_high": 30,    # >= this → HIGH
}

# ---------------------------------------------------------------------------
# Minimum Observed Sample
# ---------------------------------------------------------------------------
MINIMUM_OBSERVED_SAMPLE = {
    "citation_run_count": 2,
    "citation_occurrence_count": 3,
}

# ---------------------------------------------------------------------------
# Completeness Model
# ---------------------------------------------------------------------------
COMPLETENESS_MODEL_A = "RAW_NO_PENALTY"
COMPLETENESS_MODEL_B = "LINEAR_PENALTY"
COMPLETENESS_MODEL_C = "MINIMUM_COMPLETENESS_GATE"

MINIMUM_COMPLETENESS_GATE = 0.40  # below this → excluded from top-N auto-recommendation

# Linear penalty config: adjusted_score = raw_score * (1 - penalty_rate * (1 - completeness))
COMPLETENESS_LINEAR_PENALTY_RATE = 0.30

# ---------------------------------------------------------------------------
# Confidence V0 Components
# ---------------------------------------------------------------------------
CONFIDENCE_LEVELS = {"LOW", "MEDIUM", "HIGH"}

CONFIDENCE_THRESHOLDS = {
    "sample_adequacy": {"LOW": 0.3, "HIGH": 0.7},
    "evidence_completeness": {"LOW": 0.4, "HIGH": 0.8},
    "signal_consistency": {"LOW": 0.3, "HIGH": 0.7},
    "cross_scope_validation": {"LOW": 1, "HIGH": 3},  # min prompts/models for HIGH
}

# ---------------------------------------------------------------------------
# URL Canonicalization
# ---------------------------------------------------------------------------
# Parameters to strip for canonicalization
URL_STRIP_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "spm", "from", "source", "ref", "referrer",
    "tracking_id", "click_id", "session_id",
    "_ga", "_gl", "fbclid", "gclid", "gclsrc",
}
