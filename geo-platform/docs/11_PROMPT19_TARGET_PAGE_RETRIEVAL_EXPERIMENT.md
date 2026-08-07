# 11 Prompt 19 Target Page Retrieval Experiment

Status: READY_FOR_MANUAL_RELEASE

## Experiment Identity

- Name: `Prompt 19 目标页面检索进入实验`
- Project: `3` / 爱短链品牌监测
- Prompt: `19` / 抖音跳转链接
- Target page: `https://www.aifabu.com/card`
- Issue: `#21`
- Action: `#13`
- Experiment: `#13`

## Historical Evidence Window

```text
baseline_run_ids = [135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146]
answer_eligible_run_count = 12
citation_eligible_run_count = 12
retrieval_eligible_run_count = 0
captured_candidate_total = 240
citation_total = 360
target_page_retrieval_rate = null
target_page_conversion_rate = null
retrieval_metrics_status = insufficient_retrieval_candidates
```

Interpretation:

- This is not a failed collection overall: answers and final citations are
  usable.
- It is not a valid retrieval/funnel baseline: historical retrieval candidates
  are incomplete.
- Captured candidates show no target-page hit in the top-20 captured scope, but
  this must not be promoted to complete `target_page_retrieval_rate = 0/12`.
- The first-stage goal remains retrieval entry, but a new retrieval-eligible
  baseline must be collected before release confirmation.

## Locked Recollected Baseline

```text
baseline_run_ids = [173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184]
evidence_package_id = 7
answer_eligible_run_count = 12
citation_eligible_run_count = 12
retrieval_eligible_run_count = 12
target_page_retrieval_rate = 0 / 12 = 0%
target_page_conversion_rate = not_applicable
experiment_release_blocked = false
experiment_released_at = null
```

Probe Runs `170-172` confirmed the fixed collector can capture at least 30
candidates per Run. Full baseline Runs `173-184` were then collected and locked
into Experiment `#13`.

## Baseline Snapshot

```text
url = https://www.aifabu.com/card
http_status = 200
snapshot_id = 3
snapshot_type = PRE_RELEASE
capture_status = success
canonical_url = https://www.aifabu.com/card
```

Observed page signals:

- Title: `抖音卡片_微信卡片_直播间卡片-爱短链`
- H1: `抖音获客私域 点击跳转加好友`
- Existing copy mentions 抖音跳转, 跳转链接, 私信卡片, 小风车, 企微,
  小程序, QQ, and FAQ signals.
- Gap: the page is still framed more like a card/product landing page than a
  complete "抖音跳转链接" intent answer page.

## Evidence Packages

```text
accepted_baseline_package_id = 1
historical_downgrade_package_id = 6
latest_b1_fact_package_id = 7
latest_schema_version = b1.v4
latest_metric_spec_version = metric.v3
```

Package `#1` is preserved and associated with the accepted Hypothesis. Package
`#6` preserves the historical downgraded evidence. Package `#7` is the current
retrieval-eligible B1 Gate report with platform matrix, content type
distribution, time distribution, content-structure summary, retrieval
eligibility status, and unified drilldowns.

Retrieval coverage note:

```text
retrieval_coverage_status = INCOMPLETE
valid_run_count = 12
incomplete_run_count = 12
retrieval_candidate_count = 240
reference_count = 360
common_candidate_count_per_run = 20
suspected_fixed_collection_limit = true
minimum_retrieval_candidate_count = 30
```

Historical Run artifacts for `135-146` contain only
`csaitab/searchresult?pn=0&rn=20` responses, and each saved
`searchresult-1.json` has `data.results = 20`. The 30 final references were
captured successfully, but the historical retrieval candidate denominator is
not complete. This means `target_page_retrieval_rate`,
`target_page_conversion_rate`, candidate-not-cited, platform
candidate-to-citation, and content-type conversion are all unavailable for this
historical window. Captured candidates remain auditable as
`captured_candidates` only.

## Strategy Candidate

```text
strategy_candidate_id = 4
evidence_package_id = 7
experiment_id = 13
provider = local_rule
model = local-rule-v1
prompt_version = strategy_prompt.v1
review_status = PENDING_REVIEW
target_metric = target_page_retrieval_rate
```

The strategy candidate is grounded in Package `#7` and the PRE_RELEASE snapshot.
It is not accepted yet, and it has not been converted into a live experiment
plan.

## Accepted Hypothesis

```text
hypothesis_id = 1
status = ACCEPTED
evidence_package_id = 1
experiment_id = 13
target_metric = target_page_retrieval_rate
baseline_value = 0/12
expected_direction = increase
current_status = historical_acceptance_only; superseded by Package #7 baseline
```

Observed problem:

```text
目标页面在12次独立采样中未进入任何一次检索候选，基线为0/12。
```

Current caveat: this accepted Hypothesis predates the b1.v4 retrieval
eligibility downgrade. It remains preserved for audit history. Package `#7` and
Strategy Candidate `#4` are the current release-preparation references.

Hypothesized cause remains intentionally probabilistic:

```text
目标页面可能未充分覆盖“抖音跳转链接”意图所需的平台限制、实现路径、操作步骤和失败排查信息。
```

## Planned Page Variables

- `TITLE_H1_INTENT_ALIGNMENT`: make Title/H1 explicitly target "抖音跳转链接".
- `DIRECT_ANSWER_BLOCK`: add a concise direct answer explaining what 抖音跳转链接
  is, what destinations are possible, and which route is compliant.
- `STEP_LIST`: add concrete steps for creating, mounting, testing, and tracking
  a Douyin jump link/card.
- `POLICY_BOUNDARY`: explain Douyin platform constraints, allowed paths, and
  unsafe promises to avoid.
- `TROUBLESHOOTING`: add common failure reasons such as review rejection, risk
 提示, failed mounting, invalid landing page, or broken redirects.
- `INDEXABILITY_CHECK`: confirm canonical, crawlability, and visible HTML
  content after publication.

## Release Boundary

Do not set `released_at`.

Do not move Experiment `#13` into cooling.

Experiment `#13` currently has:

```text
release_blocked = false
release_blocked_reason =
```

Only after the external page is manually updated and the user confirms live
publication evidence should Action `#13` become `RELEASE_CONFIRMED`; then the
experiment may enter cooling and later collect validation Runs.
