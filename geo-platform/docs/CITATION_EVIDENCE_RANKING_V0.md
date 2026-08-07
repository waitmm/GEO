# Citation Evidence Signal Ranking V0

**Status**: FROZEN (`scoring.v0`, 2026-08-07)

## 1. Purpose

Citation Evidence Signal Ranking V0 computes a relative, evidence-based ranking of citation sources (domains and inferred platforms) within a single Evidence Package.

V0 answers the question:

> *Which citation sources show stronger observable citation evidence signals in the current Evidence Package?*

V0 does **not** answer:

- Which platform is most effective for GEO
- Which platform has the highest probability of GEO success
- Where to publish content for guaranteed citation inclusion
- Whether citation signals predict experiment uplift

## 2. Scope

| Dimension | Value |
|-----------|-------|
| Scoring spec | `scoring.v0` |
| Scope | **Within-package relative** |
| Input | One Evidence Package per ranking run |
| Output | Domain ranking + Inferred Platform ranking |
| Frozen | Yes — formula changes require `scoring.v1` |

## 3. Factor Activation Rules

Factors are dynamically activated based on evidence data:

| Status | Condition |
|--------|-----------|
| **ACTIVE** | Has ≥1 DISCRIMINATIVE + NON_REDUNDANT + PRIMARY dimension |
| **DIAGNOSTIC_ONLY** | Has dimensions but all are AUXILIARY/NON_DISCRIMINATIVE (no independent PRIMARY) |
| **NON_DISCRIMINATIVE** | All dimensions have zero variance across candidates |
| **UNAVAILABLE** | No dimension data exists |

Active weights are normalized proportionally to configured weights:

```
active_weight_i = configured_weight_i / sum(configured_weight of ACTIVE factors)
```

## 4. Current Factor Configuration

| Factor | Configured Weight | Package #7 Status |
|--------|------------------|-------------------|
| `citation_strength` | 0.35 | ACTIVE |
| `rank_strength` | 0.25 | ACTIVE |
| `source_diversity` | 0.20 | DIAGNOSTIC_ONLY |
| `cross_run_presence` | 0.20 | NON_DISCRIMINATIVE |

### Package #7 Active Weights

```
citation_strength: 0.35 / 0.60 = 0.5833
rank_strength:     0.25 / 0.60 = 0.4167
```

## 5. Package #7 Example (Real Data)

**Evidence**: Package #7, Prompt #19 ("抖音跳转链接"), 12 runs (173–184), 372 citation references.

### Domain Ranking (Top 5)

| Rank | Domain | Score | Occurrences | Unique URLs | Top1 Share |
|------|--------|-------|-------------|-------------|-----------|
| 1 | bilibili.com | 38.70 | 72 | 6 | 16.7% |
| 2 | mbd.baidu.com | 35.38 | 60 | 5 | 20.0% |
| 3 | zhuanlan.zhihu.com | 28.23 | 48 | 4 | 25.0% |
| 4 | douyin.com | 14.00 | 24 | 2 | 50.0% |
| 5 | news.sohu.com | 13.91 | 24 | 2 | 50.0% |

### Platform Ranking

| Rank | Platform | Score | Domains | Occurrences |
|------|----------|-------|---------|-------------|
| 1 | BILIBILI | 38.70 | 1 | 72 |
| 2 | ZHIHU | 17.43 | 2 | 60 |
| 3 | SOHU | 13.91 | 1 | 24 |
| 4 | BAIJIAHAO | 13.89 | 6 | 120 |
| 5 | DOUYIN | 12.21 | 3 | 48 |

*Platform assignments are INFERRED_FROM_DOMAIN, not parser-native.*

## 6. Scoring Semantics

| Term | Meaning |
|------|---------|
| Evidence Score | Relative citation signal strength within this Package. Not a probability. |
| Confidence | Data support for the ranking judgment (LOW/MEDIUM/HIGH). Not success probability. |
| Platform Rank | Aggregated from domain ranking. Always drill down to domains. |

## 7. Diagnostic-Only Dimensions

The following are preserved for diagnostic display but do not participate in current Package #7 scoring:

- `source_diversity`: All dimensions correlated with `citation_occurrence_count` (r=1.00)
- `cross_run_presence`: Zero variance (all domains 12/12 run coverage)

These can become ACTIVE again in future Packages if independent signal exists.

## 8. Known Limitations

### SIGNAL_SCOPE_LIMITATION
Current active signals mainly reflect citation frequency and rank strength. Predictive value for GEO uplift has not been validated.

### PLATFORM_AGGREGATION_LIMITATION
Inferred platforms are derived from domains. Domains mapped to the same platform may not represent the same content ecosystem.

### CITATION_SOURCE_CONCENTRATION_LIMITATION
Package #7: 372 occurrences from 31 unique URLs; 10/17 domains have 100% top1 URL share. Whether concentration implies persistence remains unverified.

### COMPLETENESS_VALIDATION_LIMITATION
All ranked domains have 100% completeness. Completeness model behavior under real missing-data conditions remains untested.

## 9. What V0 Can / Cannot Conclude

### CAN

- Rank citation sources by relative signal strength within a Package
- Decompose scores into traceable factor contributions
- Detect and handle redundant dimensions
- Identify zero-variance dimensions
- Provide confidence assessment (sample adequacy, completeness, consistency, cross-scope)

### CANNOT

- Prove causal relationship between platform and citation
- Predict experiment success probability
- Identify the single best publishing platform
- Generalize across different prompts or models
- Reliably rank channel × content combinations (content body unavailable)

## 10. Version Immutability

`scoring.v0` is frozen. Any change to:
- Factor weights
- Rank model formulas
- Correlation threshold
- Completeness model
- Confidence rules
- Redundancy handling

must increment to `scoring.v1`.

The spec fingerprint (`scoring_spec_fingerprint`) is a deterministic SHA-256 hash of all canonical scoring parameters. Same config → same fingerprint. Any V0 parameter change → fingerprint change.

## 11. Future Validation Plan

| Validation | Question | Status |
|-----------|----------|--------|
| Multi-Prompt | Same ranking across different prompts? | Not started |
| Multi-Model | Same ranking across different AI models? | Not started |
| Temporal | Stable over time or point-in-time? | Not started |
| Citation Content | What content features drive citation? | Not started |
| Real Experiment | Does ranking predict experiment uplift? | Not started |

Future data may validate, weaken, or reject V0 hypotheses. All outcomes are acceptable.

## 12. Reproducibility

V0 ranking is deterministic: same Package + same spec + same input → same ranking.

To reproduce: run `run_citation_evidence_ranking_v0(db, package_id=7)` with the frozen `ranking_config.py`.
