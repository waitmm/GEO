# 05 Optimization Loop Spec

Status: ACTIVE

## Objective

Build a reliable Alpha loop:

```text
Problem discovery -> Optimization action -> Fixed retest -> Effect conclusion
```

The loop must separate software validation from real business effectiveness.

## Objects

`OptimizationIssue` records an observed problem:

- project/prompt/cluster scope
- issue type
- status
- severity and confidence
- observation window and sample count
- observed facts
- possible causes
- supporting run evidence

`OptimizationAction` records what will be changed:

- action type
- target URL/type
- owner/priority
- action summary/detail
- content feature changes
- release note/evidence

`content_feature_changes` must be written as structured objects for new
experiments:

```json
[
  {
    "feature": "DIRECT_ANSWER_BLOCK",
    "before": false,
    "after": true,
    "description": "新增直接回答视频二维码制作方法的摘要",
    "location": "教程区顶部"
  }
]
```

Legacy `list[str]` values are read as `LEGACY_NOTE` objects for compatibility.
Do not write new legacy strings.

`OptimizationExperiment` records retest design and outcome:

- hypothesis
- target/control/sentinel Prompt scopes
- environment scope
- sample plan
- baseline run IDs and metrics
- validation run IDs and metrics
- comparison
- confounders
- human conclusion

`OptimizationEvidencePackage` records a versioned, deterministic B1 fact report:

- project/prompt scope
- schema and metric spec version
- source Run IDs
- target page URLs
- environment snapshot
- package payload
- package hash
- status and supersession pointer

The package payload should include metric rows with:

```text
metric_name
value
numerator
denominator
source_run_ids
calculation_status
```

Current B1 payload sections:

- summary
- metric snapshot
- platform gap matrix
- content type distribution
- candidate-not-cited summary
- time distribution
- content structure summary
- representative sources
- raw Run drilldown
- validation notes
- unified drilldowns:
  `metric_name`, `filter_dimension`, `filter_value`, `run_ids`,
  `candidate_ids`, `citation_ids`, and `representative_urls`

Evidence Package generation is deterministic for the same inputs. Repeated
generation with the same source Run IDs, target URLs, environment snapshot, and
payload hash should return the existing package rather than creating a duplicate
version. Existing packages are append-only; metric/parser upgrades should create
a new version instead of mutating a package already used for audit.

The old Prompt daily report is collection-history compatibility only. It must
not be treated as the primary optimization analysis, final recommendation
surface, or experiment conclusion.

## Required State Path

```text
candidate -> confirmed -> in_action -> validating -> resolved
```

Actions:

```text
draft -> released
```

Experiments:

```text
draft -> baseline_locked -> cooling -> validating -> analyzing -> completed
```

The system may compute deltas, but only a human conclusion can close an
experiment or mark an issue resolved.

Human conclusion enum:

```text
EFFECTIVE
PARTIALLY_EFFECTIVE
MIXED_RESULT
NO_MEASURABLE_EFFECT
NEGATIVE_EFFECT
INSUFFICIENT_EVIDENCE
```

Legacy values are read through compatibility mapping only:

```text
positive -> EFFECTIVE
neutral -> NO_MEASURABLE_EFFECT
negative -> NEGATIVE_EFFECT
inconclusive -> INSUFFICIENT_EVIDENCE
```

## Fixed Retest Task

An experiment can create a fixed Wenxin retest queue from its target Prompt
scope:

- creates a `MonitoringBatch`
- creates one `BrowserMonitorTask`
- creates `Prompt x sample_count` queued/pending `BrowserMonitorRun` rows
- marks the experiment as `validating`
- returns the generated Run IDs so they can be collected and later attached as
  validation samples

Default behavior should queue runs only. Immediate browser execution must remain
an explicit opt-in because Wenxin collection may hit login or captcha checks.

## Release Boundary

The system must not mark a real external page as released unless a human
confirms that the page is actually published.

Action status should distinguish:

```text
PLANNED
READY_FOR_MANUAL_RELEASE
RELEASE_CONFIRMED
```

Saving a planned release note can move the action to
`READY_FOR_MANUAL_RELEASE`, but it must not write `released_at`, enter cooling,
or create validation claims. Only `RELEASE_CONFIRMED` may write `released_at`
and move linked experiments to `cooling`.

`RELEASE_CONFIRMED` must go through an explicit release audit. It requires:

- accepted human Hypothesis;
- successful PRE_RELEASE page snapshot;
- successful POST_RELEASE page snapshot;
- deployed feature changes;
- release note;
- confirmer and confirmation timestamp;
- canonical and robots/index checks.

After release confirmation, the following fields are frozen for audit and must
not be silently overwritten:

- baseline Run IDs;
- evidence package ID;
- accepted Hypothesis ID;
- pre-release snapshot ID;
- released_at;
- release_confirmed_by;
- deployed feature changes;
- measurement plan.

If a release record is wrong, add a correction audit record with reason,
operator, and timestamp. Preserve the old record and invalidate or version the
experiment when necessary.

Page snapshots store:

```text
url
http_status
final_url
canonical_url
captured_at
raw_html
html_hash
title
meta_description
h1
main_text
main_text_hash
section_headings
structured_data
internal_links
robots_directives
snapshot_type
capture_status
capture_error
```

Failed captures may be recorded for diagnostics, but they are not valid
PRE/POST release evidence.

## B2 Platform Boundary

B2 can read B1 platform/content/time matrices and explain them. It may propose
platform intervention hypotheses only from Evidence Package facts. It must not
recalculate, fill gaps, or invent platform advantages, counts, representative
URLs, authors, or dates.

## Citation Source Analysis

The optimization evidence chain should include source-level diagnostics for both
final citations and retrieval candidates that were not cited.

Raw collector records are stored per Run and per reference position, so the
same source can appear multiple times when several samples cite it or when the
same URL is captured with tracking parameters. The evidence-chain API should
deduplicate display rows by normalized URL first, and by domain + title when URL
is missing. Keep aggregated fields such as occurrence count, covered Run IDs,
reference positions, and candidate ranks so the UI does not show duplicate
cards while the citation volume remains explainable.

Current analysis angles:

- ownership: official, competitor, brand-related, or third-party
- content format: guide, FAQ, comparison, documentation, news, article, homepage
- prompt match: overlap between Prompt terms and visible source text
- brand signal: official domain or brand name appearance
- freshness signal: recent/stale/unknown visible date cues
- authority signal: official/institutional/structured-content cues
- platform: domain-first platform classification, including Baijiahao, Zhihu,
  WeChat official account, Douyin, Xiaohongshu, Bilibili, or ordinary web
- author/date: visible author and published-date signals parsed from title,
  URL, domain, or snippet when the collector exposes them
- risk flags: competitor source, stale source, generic page, high match but not
  cited, missing URL
- source score: reproducible 0-100 score led by answer citation behavior. The
  strongest factors are how many answer samples cite the source, total citation
  occurrences, and average citation position. Ownership, content format, Prompt
  match, freshness, authority, account identity, answer usage, and URL
  availability are secondary explanatory factors.
- account identity: platform account/source classification such as Baijiahao,
  Zhihu, WeChat official account, Douyin, Xiaohongshu, Bilibili, or ordinary web
- answer usage: whether the cited/candidate source appears reflected in the
  saved answer text

This is a reproducible rule layer. It explains visible evidence; it does not
claim to know the model's hidden ranking algorithm.

## Citation Score Strategy

`source_score` is a legacy answer-citation contribution score, not a generic
webpage quality score and not a V1 decision signal. New citation analysis rows
must expose `citation_prominence_level`, computed only from observable citation
behavior: run coverage, citation frequency, citation position, and cross-run
stability. Sort V1 citation analysis rows by citation prominence and citation
behavior, not by `source_score`.

## Citation Decision Support And Benchmark Tier

V1 source analysis also exposes deterministic read-model fields:

- `decision_support_level`: `RECOMMENDATION_REASON`, `CANDIDATE_OR_EVALUATION`,
  `FACT_ONLY`, or `NONE`.
- `has_contradiction`: independent boolean derived from valid
  `EvidenceAlignment.relation = CONTRADICTS`.
- `benchmark_tier`: `PRIMARY_BENCHMARK`, `SECONDARY_BENCHMARK`,
  `REFERENCE_ONLY`, or `NOT_EVALUABLE`.

Only V1 `EvidenceAlignment` rows with `SUPPORTS` can create decision support.
Legacy `RELATED` is excluded and must not be upgraded to partial support.

`benchmark_tier` is determined by content status, relevance, and decision
support. `citation_prominence_level` is only a same-tier sort signal and cannot
upgrade an unsupported or unavailable source into a benchmark. The system must
allow `PRIMARY_BENCHMARK = 0` when no valid support evidence exists.

## Source Gap V1

Step 4B-1 adds source-level gap analysis as a deterministic read model only. It
does not create Priority, Action Route, StrategyCandidate, or Experiment output.

Inputs are limited to:

- Benchmark Evidence from Primary/Secondary benchmark source rows.
- `TargetBrandCapabilityTruth`.
- Existing Brand Asset evidence from successful `PageSnapshot` content.

Allowed `source_gap_type` values:

- `CONTENT_GAP`
- `EVIDENCE_GAP`
- `PRODUCT_GAP`
- `NO_GAP`
- `UNKNOWN`
- `null`

If no Primary/Secondary Benchmark exists, source gap analysis must stop with
`source_gap_type = null` and
`source_gap_precondition = NO_ELIGIBLE_BENCHMARK`. `UNKNOWN` is reserved for
sources that entered gap analysis but lack reliable Product Truth, Brand Asset,
or Benchmark Evidence. `REFERENCE_ONLY` sources must not be used to force a
competitive gap.

## Priority And Action Route V1

Step 4B-2 adds deterministic `priority_level` and `action_route` fields. It
does not by itself execute changes. The V1 vertical slice may consume these
fields to build reviewed StrategyCandidate and Experiment draft payloads.

Allowed `priority_level` values:

- `PRIORITY_HIGH`
- `PRIORITY_MEDIUM`
- `NOT_PRIORITY`
- `UNRESOLVED`
- `null`

Allowed `action_route` values:

- `CONTENT`
- `EVIDENCE`
- `PRODUCT`
- `NO_ACTION`
- `UNRESOLVED`
- `null`

Mapping:

- `PRIMARY_BENCHMARK + CONTENT_GAP/EVIDENCE_GAP/PRODUCT_GAP` ->
  `PRIORITY_HIGH`.
- `SECONDARY_BENCHMARK + CONTENT_GAP/EVIDENCE_GAP/PRODUCT_GAP` ->
  `PRIORITY_MEDIUM`.
- `NO_GAP` -> `NOT_PRIORITY + NO_ACTION`.
- `PRIMARY/SECONDARY + UNKNOWN` -> `UNRESOLVED + UNRESOLVED`.
- `REFERENCE_ONLY + source_gap_type = null` -> `NOT_PRIORITY + null`.
- `NOT_EVALUABLE + source_gap_type = null` -> `null + null`.

Citation Prominence is only a same-priority sort signal and must not change the
priority tier.

## Citation Decision Vertical Slice V1

After Priority and Action Route are available, the system can generate a
minimal vertical proposal:

```text
Source Analysis
-> Recommended Action
-> Channel Opportunity
-> Human Confirmation
-> StrategyCandidate
-> InterventionPlan
-> Experiment Draft
-> Fixed Retest / Recommendation Outcome
```

The proposal is derived from existing entities only. It does not introduce a
parallel Evidence, Benchmark, Opportunity, or Experiment model.

Phase 0/1 handoff clarification:

- The single Prompt V1 main chain is
  `采集样本 -> 答案决策识别 -> 目标品牌事实 -> 引用证据 -> 对标来源 -> 缺口诊断 -> 策略候选 + 策略确认 -> 实验方案落地`.
- Step 7 must be implemented with the existing
  `OptimizationStrategyCandidate` and `effective_payload` gate. It is not a
  standalone "confirm recommended action" module.
- Step 8 creates Action/Experiment only after the effective payload is human
  reviewed and validated.
- Any Experiment created from a StrategyCandidate must bind the exact
  confirmed `effective_payload` snapshot at creation time, including candidate
  id, payload version, payload hash, confirmed actor/time, and source evidence
  package id.
- `DISCOVERABILITY_GAP` must be based on a brand asset relevant to the current
  Prompt and capability. Arbitrary project assets or the newest snapshot cannot
  prove discoverability.
- Formal consumers of `EvidenceAlignment` must use a lineage-valid read model:
  Prompt, Run, RecommendationEvent, AnswerUnit/Binding when applicable,
  ReferenceSource/RetrievalCandidate, SourceDocument, SourceClaim, and
  EvidenceAlignment must be consistent.

Hard boundaries:

- `recommended_action` is proposal-only until human confirmation.
- Only `CONTENT` and `EVIDENCE` routes can be materialized into content/channel
  experiments.
- `PRODUCT_GAP` remains a high-value product finding, but it must not create
  external content claims until Product Truth changes.
- `REFERENCE_ONLY`, `NOT_EVALUABLE`, `LEGACY_RELATED`, and Citation Prominence
  alone must not generate StrategyCandidate or Experiment output.
- Human-confirmed proposals reuse the existing `StrategyCandidate` review and
  `effective_payload` execution gate.
- Experiments remain drafts until baseline, release confirmation, cooling,
  validation runs, analysis, and human conclusion are completed.

Recommendation Outcome compares fixed baseline and validation runs across:

- candidate before/after;
- recommendation before/after;
- target reason before/after;
- citation before/after.

The outcome is an observation summary only. It must not automatically mark the
experiment effective.

Primary scoring factors:

- `answer_citation_coverage`: up to 30 points. Higher when more answer samples
  cite the same source.
- `answer_citation_frequency`: up to 12 points. Higher when the source appears
  more often across all final citations.
- `answer_reference_position`: up to 8 points. Higher when the average citation
  position is closer to the top.
- `current_row_cited`: 5 points when this specific Run cites the source.
- `answer_usage`: up to 10 points when title/domain signals are reflected in
  the saved answer text.

Secondary explanatory factors:

- `ownership`: official and brand-related sources get more explanatory weight
  than ordinary third-party or competitor sources.
- `format`: comparison, guide, FAQ, and documentation formats get more weight
  than generic homepage/channel pages.
- `prompt_match`: visible source text overlap with the Prompt.
- `freshness`: recent or explicitly updated source signals.
- `authority`: official, institutional, or structured-content signals.
- `account_identity`: confirmed official account, possible official account,
  brand-named unverified account, platform account unknown, or unknown.
- `url_available`: whether a resolvable URL is available.

Platform and account classification is domain-first. The host/domain decides
known platforms first, for example `bilibili.com` and `b23.tv` are Bilibili,
`baijiahao.baidu.com` is Baijiahao, `zhihu.com` is Zhihu, and
`mp.weixin.qq.com` is WeChat official account. Title keywords are only a
fallback when the domain does not identify a known platform. This prevents a B
station page whose title mentions "公众号" from being mislabeled as a WeChat
official account.

## Why A Source Was Cited

The UI should explain citation basis separately from score:

- Platform: Baijiahao, Zhihu, WeChat official account, Douyin, Xiaohongshu,
  Bilibili, or ordinary web.
- Account: confirmed official, possible official account, brand-named
  unverified, platform account unknown, or unknown.
- Author/date: show visible author and date when available. If the collector
  only exposes title/URL/snippet, leave unknown rather than inventing a name.
- Content structure: comparison/ranking, guide/how-to, FAQ, cases/reviews,
  price/cost, feature list, update signal, official docs.
- Time: visible years, fresh/update claims, stale/unknown time signal.
- Answer behavior: how many answer samples cite it, citation rate, total
  occurrences, and average citation position.
- Cross-source comparison: explain the source's relative advantages against all
  cited sources in the same evidence chain. This must focus on source-side
  advantages such as official/brand relationship, platform type, account
  identity, content structure, author/date visibility, freshness, authority, and
  Prompt match. Do not present outcomes such as high citation rate, high score,
  or strong reference rank as the advantage itself.

Do not collapse citation basis into a single opaque score. The score is for
ordering; the citation basis is for deciding what to optimize.
