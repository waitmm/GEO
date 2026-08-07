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
        "title": "Signal Scope",
        "status": "ACKNOWLEDGED",
        "description": (
            "Current active evidence signals mainly reflect citation frequency "
            "and citation rank strength. Predictive value for real GEO uplift "
            "has not yet been validated through controlled experiments."
        ),
        "evidence_scope": "Package #7, 1 prompt, 1 model, 12 runs",
        "impact": "V0 ranking represents relative citation signal strength, not GEO effectiveness.",
    },
    {
        "code": "PLATFORM_AGGREGATION_LIMITATION",
        "title": "Platform Aggregation",
        "status": "ACKNOWLEDGED",
        "description": (
            "Inferred platforms are derived from source domains via DOMAIN_PLATFORM_MAP. "
            "Domains mapped to the same inferred platform may not represent the same "
            "content ecosystem, publishing mechanism, or execution channel."
        ),
        "evidence_scope": "Domain-to-platform mapping is heuristic (INFERRED_FROM_DOMAIN).",
        "impact": "Platform scores aggregate heterogeneous sources. Always drill down to domain level.",
    },
    {
        "code": "CITATION_SOURCE_CONCENTRATION_LIMITATION",
        "title": "Citation Source Concentration",
        "status": "ACKNOWLEDGED",
        "description": (
            "Package #7 shows high citation-source concentration: 372 occurrences "
            "from only 31 unique canonical URLs; 10/17 domains have 100% top1 URL share. "
            "Whether this concentration implies persistence over time or difficulty "
            "for new content to enter the cited-source set remains unverified."
        ),
        "evidence_scope": "Package #7, single time window.",
        "impact": "High-ranking domains may be driven by a small number of URLs. "
                 "Do not interpret as a fixed citation pool.",
    },
    {
        "code": "COMPLETENESS_VALIDATION_LIMITATION",
        "title": "Completeness Validation",
        "status": "ACKNOWLEDGED",
        "description": (
            "All ranked domains in Package #7 have 100% evidence completeness. "
            "The three completeness models (RAW_NO_PENALTY, LINEAR_PENALTY, "
            "MINIMUM_COMPLETENESS_GATE) produce identical rankings under uniform "
            "completeness. This validates that the models do not incorrectly perturb "
            "rankings given complete data, but does not validate their behavior "
            "under real missing-data conditions."
        ),
        "evidence_scope": "Package #7, uniform completeness.",
        "impact": "Completeness model behavior under real data gaps remains untested.",
    },
]

USAGE_WARNINGS = [
    "Evidence Score is a relative signal ranking within the current Evidence Package — not a probability (0–100%) and not cross-Package comparable.",
    "Confidence (LOW/MEDIUM/HIGH) reflects data support for the ranking judgment — not experiment success probability.",
    "Platform Rank is derived from domain aggregation — not a recommendation for the single best publishing platform.",
    "Rankings are WITHIN_PACKAGE_RELATIVE. Scores from different Packages should not be directly compared without calibration.",
    "V0 is frozen. Any formula-level change (weights, thresholds, models, rules) requires scoring.v1.",
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
