# PR5-A Evidence-Constrained Execution Proposal Shadow

## Status

PR5-A implements a deterministic, read-only compiler from confirmed Step 7
strategy semantics to Step 8 execution proposals. It is not a production
cutover and does not persist any proposal object.

```text
PR5-A Shadow contract = FROZEN
PR5-B production cutover = NOT STARTED
```

```text
DB writes = 0
External LLM calls = 0
Action / Experiment created = 0
ManagedAsset / ExecutionSnapshot created = 0
Step 8 state modified = NO
```

## Product Principle

Step 8 is proposal review, not a blank form. The system should derive every
execution choice that is uniquely determined by confirmed inputs and expose
real ambiguity to the operator.

> Execution Proposal cannot create product truth. It can only package
> confirmed truth into an executable plan.

The compiler is closed-world and deterministic. `UNKNOWN` remains unknown;
competitor evidence may inform planning context but cannot become a target
brand assertion.

## Truth Sources

Production replay reads only:

```text
candidate.effective_payload
+ validated Strategy Synthesis structure
+ frozen Resolver/channel result
+ Evidence Package
+ confirmed TargetBrandCapabilityTruth
```

Frontend Decision View prose is never a planning input. Candidate #50 is an
explicit `READ_ONLY_COMPATIBILITY_PROJECTION`; the projection is not written
back to the historical Candidate.

Product Truth value and provenance remain separate. In the current schema a
publishable target assertion requires:

```text
product_truth_status in {TRUE, SUPPORTED}
+ truth_source = MANUAL_CONFIRMED
```

`source_reference` may be empty for manually confirmed truth. Because the
current schema has no `approved_aliases`, PR5-A treats aliases as an empty set
and uses only the exact `capability_label` in factual wording.

## Logical Objects

PR5-A creates ephemeral response objects only:

```text
ExecutionProposalPortfolio
ExecutionInputSnapshot
ExecutionConstraint
InterventionProposal
ManagedAssetSnapshot / ManagedAssetCandidate / NewAssetSpec
ClaimUsagePolicy
AssetPackage / TitleCandidate / SectionPlan / ContentBlockPlan
ChannelOpportunityProfile / ProposalQualityAudit
ValidationPlan
```

`PageSnapshot != ManagedAsset`. Existing page snapshots do not make an asset
eligible for `UPDATE_MANAGED`. No ManagedAsset table is added in PR5-A.

## Attribution Unit

The future persistence contract is fixed:

```text
1 InterventionProposal
-> 1 selected AssetPackage
-> 1 concrete asset
-> 1 Action
-> 1 Experiment
```

The portfolio is only a planning container. PRIMARY and each priority TEST are
independent proposals; deferred TEST and OBSERVE channels do not enter the
active portfolio.

## Asset Resolution

Operation, resolution, and readiness are independent:

```text
asset_operation = CREATE_NEW | UPDATE_MANAGED
resolution = RESOLVED | NEEDS_HUMAN_SELECTION | INVALID
proposal_readiness = READY_FOR_REVIEW | NEEDS_HUMAN_SELECTION | BLOCKED_BY_CONSTRAINT
```

All validators may be `VALID` while readiness is
`NEEDS_HUMAN_SELECTION`. This means the candidates are safe and traceable but
the evidence does not determine one unique choice.

With zero managed assets, operation is deterministically `CREATE_NEW` and only
a `NewAssetSpec` is produced. A single fully compatible managed asset selects
`UPDATE_MANAGED`; multiple equally high-fit assets require human selection.
Fit is categorical, not a weighted score.

## Claims And Content

Claim policy is proposition-aware and records subject, predicate, object,
qualifier, polarity, and speech act. It separates:

```text
TARGET_ASSERTION_ALLOWED / TARGET_ASSERTION_FORBIDDEN
PLANNING_CONTEXT_ALLOWED / PLANNING_QUESTION
PUBLISHABLE_QUESTION_ALLOWED
UNKNOWN_MUST_REMAIN_UNKNOWN
COMPETITOR_CONTEXT_ONLY / COMPARISON_RESTRICTED
```

`PLANNING_QUESTION` is never automatically publishable. Titles use canonical
segments and exact confirmed Product Truth wording. Asset Package candidates
are self-contained review objects and each still represents exactly one
concrete asset. Unresolved package alternatives each receive their own Section
Plan candidate; the compiler does not silently select FULL or P1 scope.

Section purposes are eligible capabilities, not a fixed seven-section
template. Each section consumes the minimum purpose-specific provenance.
Unsupported OPERATION is omitted, FAQ accepts only publishable confirmed-truth
questions, and Content Blocks exactly inherit rather than expand Section
scope. PR5-A produces content block plans, not full copy.

## Baseline And Metrics

The Evidence Package run scope is the immutable experiment baseline. Strategy
coverage remains a separate Run-ID union:

```text
#57 baseline_run_ids = Package #12 v8 fixed 40 Runs
#57 strategy_analyzable_run_ids = 15 Runs
```

Metrics are projected only from calculators already present in the system.
Each metric records measurement level, calculator, baseline semantics, and one
of:

```text
BASELINE_AVAILABLE
ZERO_OBSERVED
NOT_MEASURABLE_YET
NOT_APPLICABLE
CALCULATION_FAILED
```

A new external asset has no asset-level historical measurement, so selected
asset retrieval/citation metrics are `NOT_MEASURABLE_YET`, never zero. Prompt
and brand-level package metrics can still use the fixed baseline.

Observation candidates reuse the existing Experiment resampling rule: three
single independent samples, queued only after publication/cooling confirmation.
PR5-A creates no new duration preset or schedule registry.

## Validation

Every canonical build and future edit must rerun:

```text
SnapshotValidator
ChannelRoleValidator
AssetFitValidator
ClaimGroundingValidator
TitleClaimValidator
SectionProvenanceValidator
BaselineValidator
MetricEligibilityValidator
```

The read-only endpoint is:

```text
GET /api/optimization/workflow/{project_id}/{prompt_id}/execution-proposal-shadow
```

`candidate_id` is optional. A confirmed current candidate is preferred; a
current USER_FLOW candidate without a confirmed effective payload is handled
only as an explicitly labeled compatibility projection.

## Current Replay

#57 compiles to three active proposals: OFFICIAL_SITE PRIMARY, BAIJIAHAO TEST,
and ZHIHU TEST. BILIBILI and SOHU remain deferred planning data. The official
proposal is `CREATE_NEW`; its PRODUCT_PAGE / FEATURE_PAGE / HELP_DOC type and
all-theme versus P1-focused package are legitimate human selections. Each TEST
uses one minimal ARTICLE asset and one independent future experiment identity.

All five audit propositions -- automatic encrypted short link, platform filing,
whitelist, anti-blocking, and seven-day 95% effectiveness -- remain forbidden
target assertions because no exact confirmed Product Truth supports them.

#40 uses Candidate #50 through `READ_ONLY_COMPATIBILITY_PROJECTION`; its
OFFICIAL_SITE PRIMARY, ZHIHU SECONDARY, and `BENCHMARK_BACKED_STRATEGY`
semantics remain unchanged.

PR5-B/C/D, persistence, Step 8 UI prefill, and production cutover remain out of
scope.

## PR5-A.2 Final Quality Audit

The final #19/#57 replay preserved the original title, 40 fixed baseline Runs,
15 Strategy Runs, and semantic input hash
`ac733bf1b2e20ff6a87708365487f3d3d4d9574d3d12a7d8cd70ad0fe4b90cfb`.
The official proposal exposes two unresolved one-asset packages:

```text
FULL_STRATEGY_SCOPE = T1/T2/T3, excluded = none
P1_FOCUS = T1/T2, excluded = T3
asset types = PRODUCT_PAGE / FEATURE_PAGE / HELP_DOC
asset_package_resolution_status = NEEDS_HUMAN_SELECTION
```

Package-specific sections no longer copy all provenance. PRODUCT_TRUTH uses
one confirmed truth at a time; SCENARIO uses planning context without target
assertions; BOUNDARY carries unknown/restricted claims; VALIDATION carries only
the package's metrics, signals, and baseline; OPERATION is absent. P1
VALIDATION excludes T3's required signal.

The two active TEST proposals remain T1/two-Reason minimum ARTICLE assets, but
their deterministic hypotheses now consume distinct frozen evidence profiles:

```text
BAIJIAHAO = 40 references / 16 retrievals / 2 claims / 11 documents
pattern = EXISTING_RETRIEVAL_EXPOSURE

ZHIHU = 40 references / 0 retrievals / 1 claim / 6 documents
pattern = REFERENCE_ENVIRONMENT_WITHOUT_RETRIEVAL
```

Final result:

```text
8 safety validators = VALID
asset_package_quality = PASS
title_grounding_quality = PASS
section_quality = PASS
claim_usage_quality = PASS
channel_hypothesis_quality = PASS
metric_measurement_quality = PASS
baseline_quality = PASS
overall_quality = PASS
external LLM calls = 0
DB writes / Action / Experiment / ManagedAsset / Step 8 changes = 0
```

#40/#50 compatibility replay is also VALID/PASS and retains OFFICIAL_SITE
PRIMARY, ZHIHU SECONDARY, and `BENCHMARK_BACKED_STRATEGY`. PR5-A is therefore
frozen. Do not enter PR5-B without a separate instruction.
