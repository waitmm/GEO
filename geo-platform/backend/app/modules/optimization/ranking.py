"""Citation Evidence Ranking V0.

Evidence-First scoring system for comparing citation sources across domains,
platforms, and channel×content combinations.

Architecture:
  Raw Evidence Dimensions
  → Data Quality Diagnostics
  → Correlation / Redundancy Analysis
  → Evidence Factors
  → Ranking (with completeness & confidence sensitivity)
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from math import log2, sqrt
from typing import Any, Callable
from urllib.parse import parse_qsl, urlparse, urlunparse

from sqlalchemy.orm import Session

from app.models import (
    BrowserMonitorRun,
    OptimizationEvidencePackage,
    Project,
    ReferenceSource,
    RetrievalCandidate,
)
from app.services.serialization import loads

from app.modules.optimization.ranking_config import (
    SCORING_SPEC_VERSION,
    CONFIDENCE_SPEC_VERSION,
    RANKING_SCOPE,
    RANK_LOG_BASE,
    RANK_BUCKETS,
    DIMENSION_WEIGHTS,
    FACTOR_WEIGHTS,
    CORRELATION_THRESHOLD,
    CORRELATION_MIN_PAIRS,
    SAMPLE_ADEQUACY_CONFIG,
    MINIMUM_OBSERVED_SAMPLE,
    COMPLETENESS_MODEL_A,
    COMPLETENESS_MODEL_B,
    COMPLETENESS_MODEL_C,
    MINIMUM_COMPLETENESS_GATE,
    COMPLETENESS_LINEAR_PENALTY_RATE,
    CONFIDENCE_THRESHOLDS,
    URL_STRIP_PARAMS,
    compute_spec_fingerprint,
    KNOWN_LIMITATIONS,
    USAGE_WARNINGS,
)
from app.modules.optimization.service import (
    DOMAIN_PLATFORM_MAP,
    _infer_platform_from_domain,
    _classify_content_type,
)

# ---------------------------------------------------------------------------
# Chinese Label Map — all user-facing output must use Chinese labels
# ---------------------------------------------------------------------------
_ZH = {
    # Factor names
    "citation_strength": "引用强度",
    "rank_strength": "排名强度",
    "source_diversity": "来源多样性",
    "cross_run_presence": "跨采样稳定性",
    # Factor status
    "ACTIVE": "活跃",
    "DIAGNOSTIC_ONLY": "仅诊断",
    "NON_DISCRIMINATIVE": "无区分力",
    "UNAVAILABLE": "不可用",
    "REDUNDANT_AUXILIARY": "冗余（辅助）",
    "PRIMARY": "主要",
    # Dimension names
    "citation_occurrence_count": "引用出现次数",
    "citation_run_count": "引用涉及采样数",
    "citation_run_coverage": "引用采样覆盖率",
    "citation_volume_share": "引用占比",
    "mean_citation_rank": "平均引用排名",
    "median_citation_rank": "中位引用排名",
    "top3_occurrence_share": "前三引用占比",
    "top5_occurrence_share": "前五引用占比",
    "top10_occurrence_share": "前十引用占比",
    "unique_citation_urls": "独立引用URL",
    "source_diversity_ratio": "来源多样性比率",
    "source_concentration": "来源集中度",
    "top1_url_share": "最高频URL占比",
    "top3_url_share": "前三URL占比",
    "min_rank": "最小排名",
    "max_rank": "最大排名",
    # Confidence
    "HIGH": "高",
    "MEDIUM": "中",
    "LOW": "低",
    "sample_adequacy": "样本充分性",
    "evidence_completeness": "证据完整度",
    "signal_consistency": "信号一致性",
    "cross_scope_validation": "跨范围验证",
    # Platform semantics
    "INFERRED_FROM_DOMAIN": "基于域名推断",
    "NO_DOMAIN": "无域名",
    "NO_MAPPING": "无法映射",
    # Completeness models
    "RAW_NO_PENALTY": "原始不惩罚",
    "LINEAR_PENALTY": "线性惩罚",
    "MINIMUM_COMPLETENESS_GATE": "最低完整度门槛",
    # Stability
    "STABLE": "稳定",
    "SENSITIVE": "敏感",
    "MODERATELY_SENSITIVE": "中等敏感",
    # Domain mapping method
    "DOMAIN_MAPPING": "域名精确映射",
    "DOMAIN_SUFFIX_MAPPING": "域名后缀映射",
    # Other
    "total_score": "总分",
    "sources": "来源",
    "reason": "原因",
}

def _zh(key: str) -> str:
    """Return Chinese label for a key, falling back to the key itself."""
    return _ZH.get(key, key)


# ---------------------------------------------------------------------------\n# URL Canonicalization\n# ---------------------------------------------------------------------------

def canonicalize_citation_url(url: str) -> str:
    """Canonicalize citation URL for deduplication (relation.v1 compatible).

    Strips tracking params, fragments, normalizes scheme/path.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        # Normalize scheme
        scheme = parsed.scheme or "https"
        # Normalize netloc
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        # Strip tracking params
        query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
                       if k.lower() not in URL_STRIP_PARAMS]
        query = "&".join(f"{k}={v}" for k, v in sorted(query_pairs))
        # Normalize path (trailing slash)
        path = parsed.path.rstrip("/") or "/"
        return urlunparse((scheme, netloc, path, parsed.params, query, ""))
    except Exception:
        return url.lower().strip().rstrip("/")


def canonicalize_citation_urls(urls: list[str]) -> dict[str, list[str]]:
    """Group raw URLs by their canonical form.

    Returns: {canonical_url: [raw_url, ...]}
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        canonical = canonicalize_citation_url(url)
        groups[canonical].append(url)
    return dict(groups)


# ---------------------------------------------------------------------------
# Citation Source Extraction
# ---------------------------------------------------------------------------

def extract_citation_sources(
    references: list[ReferenceSource],
    run_ids: list[int],
) -> dict:
    """Extract citation sources at domain and platform level.

    Returns dict with:
    - domain_sources: per-domain evidence
    - platform_sources: per-inferred-platform evidence
    - url_groups: canonical URL → raw URL groups
    - source_counts: occurrence vs unique counts by domain
    - rank_available: whether reference_index is valid
    """
    run_id_set = set(run_ids)
    domain_data: dict[str, dict] = defaultdict(lambda: _empty_source_entry())
    platform_data: dict[str, dict] = defaultdict(lambda: _empty_source_entry())
    all_urls: list[str] = []

    # Rank availability check
    valid_rank_count = 0
    total_count = 0

    for ref in references:
        if ref.run_id not in run_id_set:
            continue
        total_count += 1
        domain = (ref.domain or "").lower().strip()
        if not domain:
            domain = "unknown"
        url = ref.canonical_url or ref.url or ""
        all_urls.append(url)

        inferred = _infer_platform_from_domain(domain)
        platform = inferred["inferred_platform"]

        # Domain level
        dd = domain_data[domain]
        dd["occurrence_count"] += 1
        dd["run_ids"].add(ref.run_id)
        dd["urls"].append(url)
        dd["reference_ids"].append(ref.id)

        # Rank data
        if ref.reference_index is not None and ref.reference_index > 0:
            dd["ranks"].append(ref.reference_index)
            valid_rank_count += 1

        # Platform level
        pd_key = platform
        pd = platform_data[pd_key]
        pd["occurrence_count"] += 1
        pd["run_ids"].add(ref.run_id)
        pd["urls"].append(url)
        pd["reference_ids"].append(ref.id)
        pd["domains"].add(domain)
        if ref.reference_index is not None and ref.reference_index > 0:
            pd["ranks"].append(ref.reference_index)

    # Canonicalize URLs for deduplication
    url_groups = canonicalize_citation_urls(all_urls)
    url_to_canonical = {}
    for canonical, raw_list in url_groups.items():
        for raw in raw_list:
            url_to_canonical[raw] = canonical

    # Enrich domain entries with unique URL info
    for domain, dd in domain_data.items():
        dd["unique_urls"] = set()
        for u in dd["urls"]:
            dd["unique_urls"].add(url_to_canonical.get(u, canonicalize_citation_url(u)))
        dd["unique_url_count"] = len(dd["unique_urls"])
        dd["run_count"] = len(dd["run_ids"])

        # Concentration
        if dd["urls"]:
            url_counter = Counter(dd["urls"])
            top1_count = url_counter.most_common(1)[0][1] if url_counter else 0
            top3_count = sum(c for _, c in url_counter.most_common(3))
            dd["top1_url_share"] = top1_count / len(dd["urls"]) if dd["urls"] else 0
            dd["top3_url_share"] = top3_count / len(dd["urls"]) if dd["urls"] else 0
            dd["source_concentration"] = _compute_concentration(url_counter.values())

    # Enrich platform entries
    for platform, pd in platform_data.items():
        all_urls_pd = pd["urls"]
        pd["unique_urls"] = set()
        for u in all_urls_pd:
            pd["unique_urls"].add(url_to_canonical.get(u, canonicalize_citation_url(u)))
        pd["unique_url_count"] = len(pd["unique_urls"])
        pd["run_count"] = len(pd["run_ids"])
        pd["domain_count"] = len(pd["domains"])

        if all_urls_pd:
            url_counter = Counter(all_urls_pd)
            top1_count = url_counter.most_common(1)[0][1] if url_counter else 0
            top3_count = sum(c for _, c in url_counter.most_common(3))
            pd["top1_url_share"] = top1_count / len(all_urls_pd) if all_urls_pd else 0
            pd["top3_url_share"] = top3_count / len(all_urls_pd) if all_urls_pd else 0
            pd["source_concentration"] = _compute_concentration(url_counter.values())

    rank_available = total_count > 0 and valid_rank_count == total_count

    return {
        "domain_sources": dict(domain_data),
        "platform_sources": dict(platform_data),
        "url_groups": url_groups,
        "rank_available": rank_available,
        "total_references": total_count,
        "valid_rank_count": valid_rank_count,
    }


def _empty_source_entry() -> dict:
    return {
        "occurrence_count": 0,
        "run_ids": set(),
        "urls": [],
        "reference_ids": [],
        "ranks": [],
        "domains": set(),
    }


def _compute_concentration(counts) -> float:
    """Compute source concentration (0=perfect diversity, 1=single source).

    Uses a simplified Herfindahl-like index normalized to [0,1].
    """
    total = sum(counts)
    if total <= 1:
        return 0.0
    raw = sum((c / total) ** 2 for c in counts)
    n = len(list(counts))
    if n <= 1:
        return 1.0
    # Normalize: (raw - 1/n) / (1 - 1/n) → [0, 1]
    normalized = (raw - 1.0 / n) / (1.0 - 1.0 / n)
    return max(0.0, min(1.0, normalized))


# ---------------------------------------------------------------------------
# Raw Evidence Dimensions
# ---------------------------------------------------------------------------

def compute_raw_dimensions(
    sources: dict,
    total_runs: int,
    total_references: int,
    rank_available: bool,
) -> list[dict]:
    """Compute raw evidence dimensions for all domain-level sources.

    Returns list of dicts with per-domain raw dimensions.
    """
    rows = []
    domain_sources = sources.get("domain_sources", {})

    for domain, ds in domain_sources.items():
        occ = ds["occurrence_count"]
        runs = ds["run_count"]
        unique_urls = ds["unique_url_count"]
        ranks = ds.get("ranks", [])

        dims = {
            "source_domain": domain,
            "inferred_platform": _infer_platform_from_domain(domain)["inferred_platform"],
            "raw_platform": "wenxin",
            "platform_inference_method": _infer_platform_from_domain(domain)["method"],
            "platform_confidence": _infer_platform_from_domain(domain)["confidence"],

            # Volume dimensions
            "citation_occurrence_count": occ,
            "citation_run_count": runs,
            "citation_run_coverage": runs / total_runs if total_runs else 0.0,
            "citation_volume_share": occ / total_references if total_references else 0.0,

            # Diversity dimensions
            "unique_citation_urls": unique_urls,
            "source_diversity_ratio": unique_urls / occ if occ else 0.0,
            "top1_url_share": ds.get("top1_url_share", 0.0),
            "top3_url_share": ds.get("top3_url_share", 0.0),
            "source_concentration": ds.get("source_concentration", 0.0),

            # Rank dimensions
            "citation_rank_available": rank_available,
        }

        if rank_available and ranks:
            sorted_ranks = sorted(ranks)
            n_ranks = len(sorted_ranks)
            dims.update({
                "mean_citation_rank": sum(sorted_ranks) / n_ranks,
                "median_citation_rank": sorted_ranks[n_ranks // 2],
                "top3_occurrence_share": sum(1 for r in ranks if r <= 3) / len(ranks),
                "top5_occurrence_share": sum(1 for r in ranks if r <= 5) / len(ranks),
                "top10_occurrence_share": sum(1 for r in ranks if r <= 10) / len(ranks),
                "min_rank": sorted_ranks[0],
                "max_rank": sorted_ranks[-1],
            })
        else:
            dims.update({
                "mean_citation_rank": None,
                "median_citation_rank": None,
                "top3_occurrence_share": None,
                "top5_occurrence_share": None,
                "top10_occurrence_share": None,
            })

        # Sample
        dims["sample_size"] = total_runs

        # Metadata
        dims["reference_ids"] = ds.get("reference_ids", [])[:20]
        dims["representative_urls"] = list(ds.get("unique_urls", set()))[:5]

        rows.append(dims)

    return rows


# ---------------------------------------------------------------------------
# Correlation Matrix
# ---------------------------------------------------------------------------

def compute_correlation_matrix(
    dimensions: list[dict],
    min_pairs: int = CORRELATION_MIN_PAIRS,
    threshold: float = CORRELATION_THRESHOLD,
) -> dict:
    """Compute Pearson correlation between numeric evidence dimensions.

    Only dimensions with >= min_pairs data points are included.
    """
    numeric_dims: dict[str, list[float]] = {}
    for row in dimensions:
        for key, val in row.items():
            if isinstance(val, (int, float)) and val is not None and key not in ("sample_size",):
                numeric_dims.setdefault(key, []).append(float(val))

    # Filter to dimensions with enough data
    valid_dims = {k: v for k, v in numeric_dims.items() if len(v) >= min_pairs}
    dim_names = sorted(valid_dims.keys())
    n = len(dim_names)
    if n < 2:
        return {"correlation_available": False, "reason": "INSUFFICIENT_DIMENSIONS",
                "dim_count": n, "matrix": [], "highly_correlated_pairs": []}

    matrix: list[dict] = []
    highly_correlated: list[dict] = []

    for i, dim_a in enumerate(dim_names):
        for j, dim_b in enumerate(dim_names):
            if j <= i:
                continue
            vals_a = valid_dims[dim_a]
            vals_b = valid_dims[dim_b]
            # Trim to matching lengths
            min_len = min(len(vals_a), len(vals_b))
            corr = _pearson_correlation(vals_a[:min_len], vals_b[:min_len])
            entry = {
                "dimension_a": dim_a,
                "dimension_b": dim_b,
                "correlation": corr,
                "pair_count": min_len,
            }
            matrix.append(entry)
            if corr is not None and abs(corr) >= threshold:
                entry["flag"] = "HIGHLY_CORRELATED"
                highly_correlated.append(entry)

    return {
        "correlation_available": True,
        "dimension_count": n,
        "pair_count": len(matrix),
        "matrix": matrix,
        "highly_correlated_pairs": highly_correlated,
        "threshold": threshold,
    }


def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation coefficient. Returns None if variance is zero."""
    n = len(x)
    if n < 3:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    if var_x == 0 or var_y == 0:
        return None
    return cov / sqrt(var_x * var_y)


# ---------------------------------------------------------------------------
# Citation Rank Scoring
# ---------------------------------------------------------------------------

def compute_rank_log_score(rank: int, base: float = RANK_LOG_BASE) -> float:
    """Rank model v0 log: 1 / log_base(rank + 1)."""
    if rank < 1:
        return 0.0
    return 1.0 / (log2(rank + 1) / log2(base))


def compute_rank_bucket_score(rank: int) -> float:
    """Rank model v0 bucket: discrete score based on rank range."""
    for bucket in RANK_BUCKETS.values():
        if bucket["min_rank"] <= rank <= bucket["max_rank"]:
            return bucket["score"]
    return 0.0


def compute_rank_scores_for_source(
    ranks: list[int],
) -> dict:
    """Compute rank scores using both models for a source's citation ranks.

    Returns:
    {
        rank_log_score: mean log score
        rank_bucket_score: mean bucket score
        per_citation: individual scores (for sensitivity)
    }
    """
    if not ranks:
        return {
            "rank_log_score": None,
            "rank_bucket_score": None,
            "rank_data_available": False,
        }
    log_scores = [compute_rank_log_score(r) for r in ranks]
    bucket_scores = [compute_rank_bucket_score(r) for r in ranks]
    return {
        "rank_log_score": sum(log_scores) / len(log_scores),
        "rank_bucket_score": sum(bucket_scores) / len(bucket_scores),
        "rank_data_available": True,
        "per_citation": [
            {"rank": r, "log_score": ls, "bucket_score": bs}
            for r, ls, bs in zip(ranks, log_scores, bucket_scores)
        ],
    }


# ---------------------------------------------------------------------------
# Evidence Factors
# ---------------------------------------------------------------------------

def _detect_zero_variance_dims(dimensions: list[dict]) -> dict[str, dict]:
    """Detect dimensions with zero or near-zero variance across all candidates.

    Returns: {dim_name: {variance, status, active_weight}}
    """
    numeric_vals: dict[str, list[float]] = defaultdict(list)
    for row in dimensions:
        for key, val in row.items():
            if isinstance(val, (int, float)) and val is not None:
                numeric_vals[key].append(float(val))

    result: dict[str, dict] = {}
    for dim_name, vals in numeric_vals.items():
        if len(vals) < 2:
            result[dim_name] = {"variance": 0.0, "status": "NON_DISCRIMINATIVE",
                                "reason": "insufficient data points"}
            continue
        mean_val = sum(vals) / len(vals)
        variance = sum((v - mean_val) ** 2 for v in vals) / len(vals)
        if variance == 0.0:
            result[dim_name] = {"variance": 0.0, "status": "NON_DISCRIMINATIVE",
                                "reason": "zero variance — all candidates have identical value"}
        elif variance < 1e-9:
            result[dim_name] = {"variance": variance, "status": "NON_DISCRIMINATIVE",
                                "reason": "effectively zero variance"}
        else:
            result[dim_name] = {"variance": variance, "status": "DISCRIMINATIVE"}
    return result


def _build_global_redundancy_groups(
    correlation_result: dict,
    dim_to_factor: dict,
) -> tuple[dict[str, str], dict[str, set[str]]]:
    """Build global redundancy groups that span across factors.

    A redundancy group contains dimensions with |r| >= threshold.
    Only one dimension per group can be PRIMARY across all factors.

    Returns:
        dim_role: {dim_name: "PRIMARY" | "REDUNDANT_AUXILIARY"}
        redundancy_groups: {group_key: {dim_names}}
    """
    highly_correlated = correlation_result.get("highly_correlated_pairs", [])

    # Union-find to build global redundancy groups
    parent: dict[str, str] = {}
    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pair in highly_correlated:
        if pair.get("flag") == "HIGHLY_CORRELATED":
            union(pair["dimension_a"], pair["dimension_b"])

    # Group by root
    groups: dict[str, set[str]] = defaultdict(set)
    all_dims = set()
    for pair in highly_correlated:
        all_dims.add(pair["dimension_a"])
        all_dims.add(pair["dimension_b"])
    for dim in all_dims:
        groups[find(dim)].add(dim)

    # Assign roles: in each group, pick one PRIMARY (highest configured weight)
    dim_role: dict[str, str] = {}
    redundancy_groups: dict[str, set[str]] = {}

    group_idx = 0
    for root, dims in groups.items():
        if len(dims) <= 1:
            for d in dims:
                dim_role[d] = "PRIMARY"
            continue
        group_idx += 1
        group_key = f"REDUNDANCY_GROUP_{group_idx}"
        redundancy_groups[group_key] = dims

        # Pick PRIMARY: dimension with highest configured weight
        sorted_dims = sorted(dims, key=lambda d: DIMENSION_WEIGHTS.get(d, 0.05), reverse=True)
        primary = sorted_dims[0]
        for d in dims:
            if d == primary:
                dim_role[d] = "PRIMARY"
            else:
                dim_role[d] = "REDUNDANT_AUXILIARY"

    # Dimensions not in any group are PRIMARY by default
    for dim_name in dim_to_factor:
        if dim_name not in dim_role:
            dim_role[dim_name] = "PRIMARY"

    return dim_role, redundancy_groups


def build_evidence_factors(
    dimensions: list[dict],
    correlation_result: dict,
    rank_available: bool,
) -> tuple[list[dict], dict, dict]:
    """Build evidence factors with global redundancy handling and zero-variance detection.

    Returns:
        dimensions: enriched with _factor_scores, _decomposition
        zero_variance_report: {dim: status}
        redundancy_report: {group: dims}
    """
    # 1. Zero-variance detection
    zero_variance_report = _detect_zero_variance_dims(dimensions)

    # 2. Dimension-to-factor mapping
    dim_to_factor = {
        "citation_occurrence_count": "citation_strength",
        "citation_volume_share": "citation_strength",
        "citation_run_coverage": "cross_run_presence",
        "citation_run_count": "cross_run_presence",
        "mean_citation_rank": "rank_strength",
        "top3_occurrence_share": "rank_strength",
        "unique_citation_urls": "source_diversity",
        "source_diversity_ratio": "source_diversity",
        "source_concentration": "source_diversity",
        "top1_url_share": "source_diversity",
        "top3_url_share": "source_diversity",
        "top5_occurrence_share": "rank_strength",
        "top10_occurrence_share": "rank_strength",
        "median_citation_rank": "rank_strength",
    }

    # 3. Global redundancy analysis (cross-factor)
    dim_role, redundancy_groups = _build_global_redundancy_groups(correlation_result, dim_to_factor)

    # 4. Build factor scores for each dimension row
    for row in dimensions:
        factor_scores: dict[str, list[dict]] = defaultdict(list)
        for dim_name, factor_name in dim_to_factor.items():
            val = row.get(dim_name)
            if val is None or not isinstance(val, (int, float)):
                continue

            # Determine status
            zv_info = zero_variance_report.get(dim_name, {})
            is_zero_var = zv_info.get("status") == "NON_DISCRIMINATIVE"
            redundancy_role = dim_role.get(dim_name, "PRIMARY")

            if is_zero_var:
                status = "NON_DISCRIMINATIVE"
                active_weight = 0.0
                reason = zv_info.get("reason", "zero variance")
            elif redundancy_role == "REDUNDANT_AUXILIARY":
                status = "REDUNDANT_AUXILIARY"
                active_weight = DIMENSION_WEIGHTS.get(dim_name, 0.05) * 0.25  # 75% penalty
                # Find which dimension it's correlated with
                correlated_with = []
                for pair in correlation_result.get("highly_correlated_pairs", []):
                    if pair.get("dimension_a") == dim_name:
                        correlated_with.append(pair["dimension_b"])
                    elif pair.get("dimension_b") == dim_name:
                        correlated_with.append(pair["dimension_a"])
                reason = f"correlated with {', '.join(correlated_with[:3])}"
            else:
                status = "PRIMARY"
                active_weight = DIMENSION_WEIGHTS.get(dim_name, 0.05)
                reason = ""

            configured_weight = DIMENSION_WEIGHTS.get(dim_name, 0.05)

            factor_scores[factor_name].append({
                "dimension": dim_name,
                "value": float(val),
                "configured_weight": configured_weight,
                "active_weight": active_weight,
                "status": status,
                "reason": reason,
            })

        # Compute factor-level decomposition
        row["_factor_scores"] = dict(factor_scores)
        row["_decomposition"] = _compute_factor_decomposition(
            factor_scores, FACTOR_WEIGHTS)

    return dimensions, zero_variance_report, redundancy_groups


def _compute_factor_decomposition(
    factor_scores: dict[str, list[dict]],
    factor_weights: dict[str, float],
) -> dict:
    """Compute full factor decomposition for a single source.

    Factor activation rules:
    - ACTIVE: has at least one DISCRIMINATIVE + NON_REDUNDANT + PRIMARY dimension
    - DIAGNOSTIC_ONLY: has dimensions but none are PRIMARY (all AUXILIARY/NON_DISCRIMINATIVE)
    - NON_DISCRIMINATIVE: all dimensions have zero variance

    Active factors renormalized proportionally to configured weights.
    """
    decomposition: dict[str, dict] = {}

    # --- Pass 1: classify each factor ---
    factor_statuses: dict[str, str] = {}
    for factor_name, dims in factor_scores.items():
        configured_w = factor_weights.get(factor_name, 0.1)
        primary_dims = [d for d in dims if d["status"] == "PRIMARY"]
        has_any_active = any(d["active_weight"] > 0 for d in dims)
        has_any_dim = len(dims) > 0

        if not has_any_dim:
            factor_statuses[factor_name] = "UNAVAILABLE"
        elif not has_any_active:
            factor_statuses[factor_name] = "NON_DISCRIMINATIVE"
            for d in dims:
                # If all dims are REDUNDANT_AUXILIARY with no PRIMARY, it's DIAGNOSTIC_ONLY
                pass
        elif not primary_dims:
            # Has active dims but none are PRIMARY → DIAGNOSTIC_ONLY
            factor_statuses[factor_name] = "DIAGNOSTIC_ONLY"
        else:
            factor_statuses[factor_name] = "ACTIVE"

    # --- Pass 2: compute raw scores and determine active set ---
    active_factors = {fn for fn, st in factor_statuses.items() if st == "ACTIVE"}
    total_configured_active = sum(
        factor_weights.get(fn, 0.1) for fn in active_factors
    )

    for factor_name, dims in factor_scores.items():
        configured_w = factor_weights.get(factor_name, 0.1)
        status = factor_statuses[factor_name]
        primary_dims = [d for d in dims if d["status"] == "PRIMARY"]
        aux_dims = [d for d in dims if d["status"] == "REDUNDANT_AUXILIARY"]
        excl_dims = [d for d in dims if d["status"] == "NON_DISCRIMINATIVE"]

        # Determine reason string
        reasons = []
        if status == "DIAGNOSTIC_ONLY":
            reasons.append("无独立主要维度 —— 所有可用维度均与另一因子的主要维度高度相关")
        elif status == "NON_DISCRIMINATIVE":
            reasons.append("所有维度在当前候选间无差异（零方差）")
        elif status == "UNAVAILABLE":
            reasons.append("无可用维度数据")

        if active_factors and status == "ACTIVE" and total_configured_active > 0:
            # Proportional renormalization
            active_weight = configured_w / total_configured_active
        else:
            active_weight = 0.0

        # Compute raw factor score
        active_dims = [d for d in dims if d["active_weight"] > 0]
        if active_dims and status == "ACTIVE":
            total_active_w = sum(d["active_weight"] for d in active_dims)
            factor_raw = 0.0
            for d in active_dims:
                norm_w = d["active_weight"] / total_active_w if total_active_w > 0 else 0
                factor_raw += d["value"] * norm_w
            contribution = factor_raw * active_weight
        else:
            factor_raw = None
            contribution = 0.0

        decomposition[factor_name] = {
            "factor_name": factor_name,
            "factor_name_zh": _zh(factor_name),
            "factor_status": status,
            "factor_status_zh": _zh(status),
            "configured_weight": configured_w,
            "active_weight": round(active_weight, 6),
            "raw_factor_score": round(factor_raw, 4) if factor_raw is not None else None,
            "weighted_contribution": round(contribution, 6),
            "primary_dimensions": [d["dimension"] for d in primary_dims],
            "primary_dimensions_zh": [_zh(d["dimension"]) for d in primary_dims],
            "auxiliary_dimensions": [d["dimension"] for d in aux_dims],
            "auxiliary_dimensions_zh": [_zh(d["dimension"]) for d in aux_dims],
            "excluded_dimensions": [d["dimension"] for d in excl_dims],
            "excluded_dimensions_zh": [_zh(d["dimension"]) for d in excl_dims],
            "dimensions_detail": dims,
            "reason": "; ".join(reasons) if reasons else "",
        }

    total_score = round(sum(
        d["weighted_contribution"] for d in decomposition.values()
    ), 6)
    decomposition["total_score"] = round(total_score, 4)
    return decomposition


def compute_factor_weighted_score(factor_scores: dict[str, list[dict]]) -> float:
    """Compute weighted factor score.

    Uses _compute_factor_decomposition which handles factor activation,
    DIAGNOSTIC_ONLY exclusion, and proportional weight renormalization.
    """
    decomp = _compute_factor_decomposition(factor_scores, FACTOR_WEIGHTS)
    return decomp.get("total_score", 0.0)


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------

def compute_completeness(dimensions: list[dict]) -> list[dict]:
    """Compute evidence completeness for each source.

    Adds: evidence_completeness, available_dimension_count, missing_dimensions
    """
    # Expected dimensions (excluding metadata)
    expected = [
        "citation_occurrence_count", "citation_run_coverage", "citation_volume_share",
        "unique_citation_urls", "source_diversity_ratio", "top1_url_share",
        "mean_citation_rank", "top3_occurrence_share",
    ]
    for row in dimensions:
        available = 0
        missing = []
        for dim in expected:
            val = row.get(dim)
            if val is not None:
                available += 1
            else:
                missing.append(dim)
        row["available_dimension_count"] = available
        row["expected_dimension_count"] = len(expected)
        row["evidence_completeness"] = available / len(expected) if expected else 0.0
        row["missing_dimensions"] = missing
    return dimensions


# ---------------------------------------------------------------------------
# Sample Adequacy
# ---------------------------------------------------------------------------

def compute_sample_adequacy(dimensions: list[dict]) -> list[dict]:
    """Compute sample adequacy for each source."""
    config = SAMPLE_ADEQUACY_CONFIG
    for row in dimensions:
        run_count = row.get("citation_run_count", 0)
        occ_count = row.get("citation_occurrence_count", 0)

        if run_count >= config["citation_run_count_high"] and occ_count >= config["occurrence_count_high"]:
            row["sample_adequacy"] = "HIGH"
        elif run_count < config["citation_run_count_low"] or occ_count < config["occurrence_count_low"]:
            row["sample_adequacy"] = "LOW"
        else:
            row["sample_adequacy"] = "MEDIUM"
    return dimensions


# ---------------------------------------------------------------------------
# Confidence V0
# ---------------------------------------------------------------------------

def compute_confidence_v0(
    dimensions: list[dict],
    prompt_count: int,
    model_count: int,
) -> list[dict]:
    """Compute confidence V0 for each source.

    Components:
    - sample_adequacy: from run count + occurrence count
    - evidence_completeness: from dimension availability
    - signal_consistency: from factor score internal consistency
    - cross_scope_validation: from prompt/model scope
    """
    for row in dimensions:
        components = {}

        # sample_adequacy
        sa = row.get("sample_adequacy", "MEDIUM")
        sa_score = {"HIGH": 1.0, "MEDIUM": 0.5, "LOW": 0.2}.get(sa, 0.5)
        components["sample_adequacy"] = sa_score

        # evidence_completeness
        ec = row.get("evidence_completeness", 0.0)
        components["evidence_completeness"] = ec

        # signal_consistency: check if factor scores point in same direction
        factor_scores = row.get("_factor_scores", {})
        consistency = _compute_signal_consistency(factor_scores)
        components["signal_consistency"] = consistency

        # cross_scope_validation
        csv_score = min(1.0, (prompt_count + model_count) / 4.0)
        components["cross_scope_validation"] = csv_score

        # Overall confidence
        avg = sum(components.values()) / len(components)
        if avg >= 0.70:
            level = "HIGH"
        elif avg >= 0.40:
            level = "MEDIUM"
        else:
            level = "LOW"

        row["confidence_components"] = components
        row["confidence"] = level
        row["confidence_score"] = round(avg, 3)
        row["confidence_spec_version"] = CONFIDENCE_SPEC_VERSION
        row["cross_scope_note"] = (
            f"Single prompt ({prompt_count}P), single model ({model_count}M) — "
            "cross-scope validation is limited."
            if prompt_count <= 1 and model_count <= 1
            else f"{prompt_count} prompts, {model_count} models."
        )

    return dimensions


def _compute_signal_consistency(factor_scores: dict) -> float:
    """Check if different factor scores are directionally consistent."""
    if not factor_scores:
        return 0.5
    values: list[float] = []
    for dims in factor_scores.values():
        for d in dims:
            val = d.get("value", 0)
            if val is not None:
                values.append(float(val))
    if len(values) < 2:
        return 0.5
    # Check if all values are on the same side of median
    median = sorted(values)[len(values) // 2]
    above = sum(1 for v in values if v > median)
    below = sum(1 for v in values if v < median)
    consistency = max(above, below) / len(values)
    return consistency


# ---------------------------------------------------------------------------
# Ranking Assembly
# ---------------------------------------------------------------------------

def apply_completeness_model(
    dimensions: list[dict],
    model: str,
) -> list[dict]:
    """Apply completeness model to adjust raw scores.

    Model A: RAW_NO_PENALTY — no adjustment
    Model B: LINEAR_PENALTY — score * (1 - penalty_rate * (1 - completeness))
    Model C: MINIMUM_COMPLETENESS_GATE — exclude below gate
    """
    for row in dimensions:
        raw = row.get("raw_evidence_score", 0.0)
        completeness = row.get("evidence_completeness", 0.0)

        if model == COMPLETENESS_MODEL_A:
            row["completeness_adjusted_score"] = raw
            row["completeness_model"] = COMPLETENESS_MODEL_A
        elif model == COMPLETENESS_MODEL_B:
            penalty = COMPLETENESS_LINEAR_PENALTY_RATE * (1.0 - completeness)
            row["completeness_adjusted_score"] = raw * (1.0 - penalty)
            row["completeness_model"] = COMPLETENESS_MODEL_B
        elif model == COMPLETENESS_MODEL_C:
            if completeness >= MINIMUM_COMPLETENESS_GATE:
                row["completeness_adjusted_score"] = raw
            else:
                row["completeness_adjusted_score"] = None  # excluded
            row["completeness_model"] = COMPLETENESS_MODEL_C

    return dimensions


def rank_candidates(
    dimensions: list[dict],
    score_key: str = "raw_evidence_score",
) -> list[dict]:
    """Rank candidates by a score key, handling None values."""
    ranked = sorted(
        dimensions,
        key=lambda r: (r.get(score_key) is None, -(r.get(score_key) or 0)),
    )
    for i, row in enumerate(ranked, 1):
        if score_key == "raw_evidence_score":
            row["evidence_rank_raw"] = i
        elif score_key == "completeness_adjusted_score":
            row["evidence_rank_adjusted"] = i
    return ranked


def compute_ranking_stability(
    raw_ranked: list[dict],
    adjusted_ranked: list[dict],
    gated_ranked: list[dict],
) -> dict:
    """Compare rankings across completeness models."""
    raw_ranks = {r["source_domain"]: r.get("evidence_rank_raw", 999) for r in raw_ranked}
    adjusted_ranks = {r["source_domain"]: r.get("evidence_rank_adjusted", 999) for r in adjusted_ranked}
    gated_ranks = {r["source_domain"]: r.get("evidence_rank_adjusted", 999) for r in gated_ranked}

    domains = set(raw_ranks.keys()) | set(adjusted_ranks.keys())

    # Count rank changes
    changes = 0
    top5_raw = {d for d, r in raw_ranks.items() if r <= 5}
    top5_adjusted = {d for d, r in adjusted_ranks.items() if r <= 5}
    top5_gated = {d for d, r in gated_ranks.items() if r <= 5}

    for d in domains:
        if raw_ranks.get(d, 999) != adjusted_ranks.get(d, 999):
            changes += 1

    stability = "STABLE"
    if changes >= len(domains) * 0.3:
        stability = "SENSITIVE"
    elif changes >= len(domains) * 0.1:
        stability = "MODERATELY_SENSITIVE"

    return {
        "ranking_stability": stability,
        "rank_changes_count": changes,
        "total_candidates": len(domains),
        "completeness_model_sensitive": stability != "STABLE",
        "top5_raw": sorted(top5_raw),
        "top5_adjusted": sorted(top5_adjusted),
        "top5_gated": sorted(top5_gated),
    }


def compute_rank_model_sensitivity(
    dimensions: list[dict],
) -> dict:
    """Compare domain rankings under log vs bucket rank models."""
    log_ranking = []
    bucket_ranking = []
    for row in dimensions:
        ranks = row.get("ranks", [])
        if not ranks:
            continue
        log_score = compute_rank_scores_for_source(ranks)["rank_log_score"] or 0
        bucket_score = compute_rank_scores_for_source(ranks)["rank_bucket_score"] or 0
        log_ranking.append((row["source_domain"], log_score))
        bucket_ranking.append((row["source_domain"], bucket_score))

    log_ranking.sort(key=lambda x: -x[1])
    bucket_ranking.sort(key=lambda x: -x[1])

    log_ranks = {d: i for i, (d, _) in enumerate(log_ranking, 1)}
    bucket_ranks = {d: i for i, (d, _) in enumerate(bucket_ranking, 1)}

    changes = 0
    for d in log_ranks:
        if log_ranks.get(d) != bucket_ranks.get(d):
            changes += 1

    sensitive = changes >= len(log_ranks) * 0.2 if log_ranks else False

    return {
        "rank_model_sensitive": sensitive,
        "rank_order_agreement": 1.0 - (changes / len(log_ranks)) if log_ranks else None,
        "log_top5": [d for d, _ in log_ranking[:5]],
        "bucket_top5": [d for d, _ in bucket_ranking[:5]],
        "rank_changes": changes,
        "total_compared": len(log_ranks),
    }


# ---------------------------------------------------------------------------
# Main V0 Ranking Pipeline
# ---------------------------------------------------------------------------

def run_citation_evidence_ranking_v0(
    db: Session,
    package_id: int,
) -> dict:
    """Run the full Citation Evidence Ranking V0 pipeline.

    This is the single entry point for computing evidence-based rankings
    from an Evidence Package.
    """
    package = db.get(OptimizationEvidencePackage, package_id)
    if not package:
        return {"error": f"Package #{package_id} not found"}

    run_ids = loads(package.source_run_ids_json, [])
    if not run_ids:
        return {"error": "No source runs in package"}

    references = db.query(ReferenceSource).filter(ReferenceSource.run_id.in_(run_ids)).all()
    runs = db.query(BrowserMonitorRun).filter(BrowserMonitorRun.id.in_(run_ids)).all()
    valid_runs = [r for r in runs if r.status in {"success", "partial_success"}]

    if not references:
        return {"error": "No reference data available for ranking", "source_run_ids": run_ids}

    # 1. Extract sources
    sources = extract_citation_sources(references, run_ids)
    total_runs = len(valid_runs)
    total_references = sources["total_references"]
    rank_available = sources["rank_available"]

    # 2. Raw dimensions
    dimensions = compute_raw_dimensions(sources, total_runs, total_references, rank_available)

    # 3. Check minimum sample
    qualified = []
    low_sample = []
    for row in dimensions:
        meets_run = row["citation_run_count"] >= MINIMUM_OBSERVED_SAMPLE["citation_run_count"]
        meets_occ = row["citation_occurrence_count"] >= MINIMUM_OBSERVED_SAMPLE["citation_occurrence_count"]
        if meets_run and meets_occ:
            qualified.append(row)
        else:
            row["sample_status"] = "LOW_SAMPLE"
            low_sample.append(row)

    # 4. Correlation matrix
    correlation_result = compute_correlation_matrix(dimensions)

    # 5. Build evidence factors (with global redundancy + zero-variance)
    dimensions_with_factors, zero_variance_report, redundancy_report = build_evidence_factors(
        dimensions, correlation_result, rank_available)

    # 6. Compute raw scores
    for row in dimensions_with_factors:
        row["raw_evidence_score"] = compute_factor_weighted_score(row.get("_factor_scores", {}))

    # 7. Completeness
    dimensions_with_factors = compute_completeness(dimensions_with_factors)

    # 8. Sample adequacy
    dimensions_with_factors = compute_sample_adequacy(dimensions_with_factors)

    # 9. Confidence
    prompt_ids = set(r.prompt_id for r in valid_runs if r.prompt_id)
    model_count = 1  # Single model (wenxin)
    dimensions_with_factors = compute_confidence_v0(
        dimensions_with_factors, len(prompt_ids), model_count
    )

    # 10. Rank scoring (if available)
    if rank_available:
        for row in dimensions_with_factors:
            ranks = row.get("ranks", [])
            if not hasattr(row, "get"):
                continue
            rank_result = compute_rank_scores_for_source([])
            # Find ranks from source data
            domain = row["source_domain"]
            ds = sources["domain_sources"].get(domain, {})
            source_ranks = ds.get("ranks", [])
            rank_result = compute_rank_scores_for_source(source_ranks)
            row.update({
                "rank_log_score": rank_result["rank_log_score"],
                "rank_bucket_score": rank_result["rank_bucket_score"],
            })

    # 11. Rank model sensitivity
    rank_model_sensitivity = None
    if rank_available:
        rank_model_sensitivity = compute_rank_model_sensitivity(dimensions_with_factors)

    # 12. Apply completeness models and rank
    # Model A: Raw
    raw_ranked = rank_candidates(dimensions_with_factors, "raw_evidence_score")

    # Model B: Linear penalty
    adjusted_for_b = apply_completeness_model(raw_ranked, COMPLETENESS_MODEL_B)
    adjusted_ranked = rank_candidates(adjusted_for_b, "completeness_adjusted_score")

    # Model C: Gate
    gated_for_c = apply_completeness_model(list(dimensions_with_factors), COMPLETENESS_MODEL_C)
    gated_ranked = rank_candidates(gated_for_c, "completeness_adjusted_score")

    # 13. Stability
    stability = compute_ranking_stability(raw_ranked, adjusted_ranked, gated_ranked)

    # 14. Platform-level aggregation
    platform_ranking = _build_platform_ranking(dimensions_with_factors, sources)

    # 15. Clean up internal structures for output
    for row in dimensions_with_factors:
        row.pop("_factor_scores", None)
        row.pop("urls", None)
        row.pop("ranks", None)
        row.pop("unique_urls", None)
        row.pop("domains", None)
        # Keep _decomposition for frontend
        # Convert sets to lists and add Chinese labels
        for k, v in list(row.items()):
            if isinstance(v, set):
                row[k] = sorted(v)
        row["confidence_zh"] = _zh(row.get("confidence", ""))
        row["sample_adequacy_zh"] = _zh(row.get("sample_adequacy", ""))
        if row.get("inferred_platform"):
            row["inferred_platform_zh"] = row["inferred_platform"]

    return {
        "scoring_spec_version": SCORING_SPEC_VERSION,
        "scoring_spec_fingerprint": compute_spec_fingerprint(),
        "ranking_scope": RANKING_SCOPE,
        "generated_at": datetime.utcnow().isoformat(),
        "package_id": package_id,
        "source_run_ids": run_ids,
        "total_runs": total_runs,
        "total_references": total_references,
        "unique_domains": len(sources["domain_sources"]),
        "unique_urls_global": len(sources["url_groups"]),
        "citation_rank_available": rank_available,

        "domain_ranking": raw_ranked,
        "platform_ranking": platform_ranking,
        "low_sample_candidates": low_sample,

        "correlation_matrix": correlation_result,
        "zero_variance_report": zero_variance_report,
        "redundancy_report": {k: sorted(v) for k, v in redundancy_report.items()},
        "rank_model_sensitivity": rank_model_sensitivity,
        "ranking_stability": stability,

        "known_limitations": KNOWN_LIMITATIONS,
        "usage_warnings": USAGE_WARNINGS,
        "config_snapshot": {
            "scoring_spec_version": SCORING_SPEC_VERSION,
            "scoring_spec_fingerprint": compute_spec_fingerprint(),
            "correlation_threshold": CORRELATION_THRESHOLD,
            "minimum_observed_sample": MINIMUM_OBSERVED_SAMPLE,
            "completeness_models": [COMPLETENESS_MODEL_A, COMPLETENESS_MODEL_B, COMPLETENESS_MODEL_C],
            "minimum_completeness_gate": MINIMUM_COMPLETENESS_GATE,
            "confidence_spec_version": CONFIDENCE_SPEC_VERSION,
            "rank_model_variants": ["rank_model_v0_log", "rank_model_v0_bucket"],
        },
    }


def _build_platform_ranking(
    dimensions: list[dict],
    sources: dict,
) -> list[dict]:
    """Aggregate domain-level dimensions to platform level."""
    platform_data: dict[str, dict] = defaultdict(lambda: {
        "inferred_platform": "",
        "domains": set(),
        "total_occurrences": 0,
        "total_runs": set(),
        "total_unique_urls": set(),
        "total_reference_ids": [],
        "scores": [],
        "completeness_values": [],
    })

    for row in dimensions:
        platform = row.get("inferred_platform", "UNKNOWN")
        pd = platform_data[platform]
        pd["inferred_platform"] = platform
        pd["domains"].add(row["source_domain"])
        pd["total_occurrences"] += row.get("citation_occurrence_count", 0)
        pd["total_runs"].update([row.get("citation_run_count", 0)])
        pd["total_unique_urls"].update(row.get("representative_urls", []))
        pd["total_reference_ids"].extend(row.get("reference_ids", []))
        if row.get("raw_evidence_score") is not None:
            pd["scores"].append(row["raw_evidence_score"])
        if row.get("evidence_completeness") is not None:
            pd["completeness_values"].append(row["evidence_completeness"])

    result = []
    for platform, pd in platform_data.items():
        avg_score = sum(pd["scores"]) / len(pd["scores"]) if pd["scores"] else 0.0
        avg_completeness = sum(pd["completeness_values"]) / len(pd["completeness_values"]) if pd["completeness_values"] else 0.0
        result.append({
            "inferred_platform": platform,
            "platform_semantics": "INFERRED_FROM_DOMAIN",
            "platform_semantics_zh": _zh("INFERRED_FROM_DOMAIN"),
            "domain_count": len(pd["domains"]),
            "domains": sorted(pd["domains"]),
            "total_citation_occurrences": pd["total_occurrences"],
            "unique_run_count": len(pd["total_runs"]),
            "avg_raw_evidence_score": round(avg_score, 3),
            "avg_evidence_completeness": round(avg_completeness, 3),
        })

    result.sort(key=lambda r: -r["avg_raw_evidence_score"])
    for i, r in enumerate(result, 1):
        r["platform_rank"] = i

    return result
