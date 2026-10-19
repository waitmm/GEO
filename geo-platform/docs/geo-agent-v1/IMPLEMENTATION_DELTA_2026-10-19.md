# GEO Agent Experiment V1 — Implementation Delta

Date: 2026-10-19

This repository change implements the frozen package
`GEO_Agent_Parallel_Experiment_V1_2026-10-19` as an isolated shadow lane in
Optimize. The reviewed addendum supplied on 2026-10-19 is authoritative where
it tightens the original package.

## Semantic classification

- Overall work: `SEMANTIC_RISK / EXPERIMENT_SHADOW_ONLY`.
- Isolated storage, API, runner and UI plumbing: `IMPLEMENTATION_CHANGE`.
- No new Semantic RFC is required because this lane cannot approve, replace or
  mutate formal V2 Analysis, ResultVersion, Review, Truth, Gate or publication
  records.
- `SC-GRADED-DELIVERY-001` has priority over older wording. L1/L2 facts must be
  grounded; L3 is instruction-only and not publicly consumable; L4 is a
  deterministic recovery package with zero model calls.
- P0 deliberately caps the raw-first Agent at `L2_PARTIALLY_GROUNDED`: it does
  not treat a readable snapshot as the fully qualified per-block binding needed
  for L1. L2 remains `VERIFY_FIRST`; low-evidence output is
  `L3_ACTIONABLE_WITHOUT_FACT_CLAIMS` and no-answer recovery is
  `L4_RECOVERY_PACKAGE`.

## Frozen implementation baseline

- Git baseline: `codex/geo-integration@d715964`.
- Development branch: `experiment/geo-agent-v1` in an independent worktree.
- Input identity is anchored server-side to exact Project, Prompt,
  PromptVersion, ProjectConfigurationVersion, Analysis, Context, explicit
  Monitor run IDs, Citation manifest, optional Source completion manifest,
  optional BrandContextVersion and Product Truth snapshot hashes.
- No `latest` fallback is permitted. Ambiguous or mismatched identity blocks
  before any model call and before any Agent result is created.
- External model, sampling, crawling and publication calls remain disabled
  until a separate explicit authorization and budget is recorded.

## Persistence boundary

Agent state exists only in `agent_experiment_runs`, `agent_events`,
`agent_checkpoints` and `agent_result_versions`. Events, checkpoints and result
versions are append-only; the run's frozen identity is immutable. Formal V2
tables are read-only inputs to this experiment.
