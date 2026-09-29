# 09 Open Issues And Risks

Status: ACTIVE

## 2026-09-29 Model B Human Gold Boundary

- The exact B1 set is ready, but no human Gold judgment has been submitted.
  Therefore no claim about Qwen's incremental value, false-challenge rate or
  task-level enablement is currently supported.
- B1 contains only seven high-impact objects selected before Qwen responses.
  It can diagnose these concrete behaviors but cannot authorize global
  Production Critic, all-relation routing or a general model-accuracy claim.
- A B1 Review simulates downstream improvement or degradation but has no formal
  Qualification, Truth, Citation Contribution, Strategy or public-claim effect.
  Any later routing policy needs the separately defined, outcome-independent B2
  validation set.

## 2026-09-29 Model B SiliconFlow Verification Boundary

- SiliconFlow Qwen transport and the bounded Shadow Critic contract are locally
  implemented. The key is configured and Model B is locally enabled. A
  non-business synthetic canary verified transport, and the later explicitly
  authorized seven-object Phase A run verified real business-payload admission
  for six original Phase A objects plus one independently recovered Supplemental
  object. Judgment quality remains unverified until Human Gold review; the
  Supplemental signal does not rewrite original Phase A statistics.
- Provider availability must not be interpreted as permission to override or
  mutate Model A, Qualification, Strategy, Truth or public Claim state. The
  current implementation enforces Shadow-only output.
- SiliconFlow changes its model catalog over time. The configured model identity
  is part of cache/audit identity, and availability must be checked before a
  future authorized business execution rather than silently substituting
  another Qwen model.
- Phase A shows that contract compliance and judgment quality are separate. Six
  of seven responses were admitted, but several disagreements may reflect Qwen
  over-reading ordinary semantics or confusing Strategy eligibility with public
  Claim eligibility. No disagreement is authoritative until Human Gold review.
- One Citation task exhausted the 1,200-token output ceiling. It remains failed
  with its full artifact; it was not retried or rewritten as a negative result.

## Single Prompt V1 Known Pitfalls

- `PromptAnalysisRun` recency is not by itself the whole current-chain truth.
  A latest dev-service restart orphan may be ignored only when it is explicitly
  marked as restart-interrupted, a completed analysis run already exists for the
  same Prompt, and all current review gates are complete. Do not broaden this
  fallback to ordinary LLM/model/parser/database failures.
- V1.1 Shadow binding must not rely only on entity-string inheritance from
  `AnswerClaim` prefixes. Table/tutorial answers may express the recommended
  option in `RecommendationEvent` and the reason in a following AnswerUnit. The
  allowed recovery is same-run explicit reason-span overlap, not broad paragraph
  guessing or historical HUMAN_CONFIRMED whitelisting.
- Formal V1.1 generation may use the Shadow module to create AnswerUnit /
  AnswerDecisionBinding input, but it must not run the audit-only Shadow Source
  Chain inside the `ANSWER_BINDING` stage. SourceClaim and EvidenceAlignment
  production work belongs to the later formal materialized stages, where ledger
  reuse, failures, and progress are visible.
- Long-running formal SourceClaim and EvidenceAlignment materialization must
  continuously publish lightweight progress through the active
  `PromptAnalysisRun` stage payload. A static `SOURCE_CLAIM` or
  `EVIDENCE_ALIGNMENT` message during many external LLM calls is a UX
  regression because Step 7 appears broken even when the backend is still
  processing. Progress reporting must stay observational; it must not change
  SourceClaim extraction identity, EvidenceAlignment candidate generation,
  verdict semantics, Gap, Strategy, Action, or Experiment behavior.
- A `citation-decision-v1` timeout after evidence review completion is not the
  same as a broken current citation chain. If `workflow/status` reports
  `READY_TO_GENERATE`, `PENDING_REVIEW`, `CONFIRMED`, or `NO_STRATEGY`, the UI
  must treat the heavy detail failure as non-blocking and must not render
  `0 current sources`, red citation-chain error, or `no strategy` from empty
  detail state.
- Step 7 StrategyCandidate generation must not be gated by a fresh full
  Citation Decision detail request when `workflow/status` is already
  `READY_TO_GENERATE`. Otherwise large prompts can appear to spin before the
  actual generation POST is even sent, and can keep spinning after success while
  optional detail refresh runs.
- Phase C1 has started and is limited to EvidenceAlignment semantic
  materialization. Do not use this as permission to start C2 Binding-aware
  Candidate Builder, wire planner recall estimates into production execution,
  add Alignment recall ladders, add concurrency, or change Benchmark / Gap /
  Strategy behavior.
- EvidenceAlignment materialization HIT is only a verdict cache for a semantic
  pair that the current candidate generator already needs to judge. It must not
  create current Prompt / Evidence Package membership by itself. Run and package
  lineage still comes from the current execution context.
- EvidenceAlignment materialization identity must not include Prompt Intent or
  Prompt Intent Embedding. Fact support is separate from query-relative
  decision relevance. If the Alignment LLM input changes beyond `reason` and
  `source_claim`, update the materialization identity or create a new contract.
- `SUPPORTS`, `NO_SUPPORT` / `NONE`, `RELATED`, and `CONTRADICTS` are all
  successful EvidenceAlignment materialization outcomes when returned by the
  judge. Negative or non-support verdicts must be written as DONE so reruns do
  not keep calling LLM.
- Phase B is conditionally accepted and implementation-frozen. Code, planner
  conservation, and unit-test validation pass; the final small production LLM
  smoke is deferred only because policy blocks sending real current-scope
  passages to DeepSeek. Keep `PHASE_B_PRODUCTION_SMOKE_DEFERRED` open for the
  current 9 `FAILED_RETRYABLE` SourceClaimMaterialization keys (#19=5, #40=4)
  and do not reselect samples.
- SourceClaim planner counts must remain conserved. `zero_claim_hit_count` is a
  subset of `materialization_hit_count`, not an additional state. A difference
  between `missing_count` and `lookup_first_llm_required` must be explained by
  `missing_no_external_llm_breakdown`, such as `llm_call_cache_hit`; never leave
  an unexplained missing/LLM delta.
- SourceClaim materialization identity is valid only while the real LLM input
  remains `{"passage": normalized_passage_text}` under the current
  prompt/schema contract. If future extraction prompts add title, URL, heading,
  section, source metadata, target brand, Prompt text, or evidence context,
  those semantic inputs must enter the materialization key or require a new
  contract.
- Legacy SourceClaim reuse must converge into
  `source_claim_materializations`. Planner may report `LEGACY_REUSABLE` in
  read-only mode, but runtime safe legacy reuse must backfill a DONE ledger row
  so future formal reuse comes through the ledger, not a permanent second cache
  heuristic over `source_claims`.
- Phase B SourceClaim incremental materialization is now implemented, but
  SourceClaim ledger HIT still must not be interpreted as an EvidenceAlignment
  verdict HIT. C1 adds a separate EvidenceAlignment ledger; C2 recall execution
  remains separate.
- SourceClaim zero-claim extraction must remain a DONE materialization. If a
  passage was successfully judged and returned `claims=[]`, reruns must not call
  LLM again just because no `source_claims` row exists.
- Legacy SourceClaim backfill must stay conservative. A SourceClaim row proves a
  claim exists, not automatically that the current passage snapshot was fully
  extracted. If prompt/schema metadata or SourceDocument freshness cannot be
  verified, treat it as needing materialization instead of guessing a HIT.
- V1.1 Incremental Materialization Phase A planner numbers expose Required /
  HIT / Missing / Stale and LLM amplification. Phase B has rewired SourceClaim
  lookup-first materialization, but EvidenceAlignment generation still needs
  later Phase C rewiring before the main chain becomes alignment-cache-aware and
  recall-cropped end to end.
- "重新运行当前主链" must not silently become a full-library recompute. Empty
  current citation scope (`doc_id_filter=[]`) means no current documents are
  eligible, not "scan all SourceDocuments". SourceClaim is a document-level
  fact and can be reused across Runs; repeated extraction rows must be deduped
  before EvidenceAlignment and evidence review. Review progress should count
  semantic evidence groups, while row counts remain audit-only lineage detail.
- The current implementation has a P0 mitigation for current-lineage scope,
  dedupe, and review inheritance, but it is not yet a full Stage-aware
  incremental runner. A future `resume-analysis` / `continue-pipeline` should
  decide the minimum missing stage, such as materialize package, derive Gap, or
  generate Strategy, instead of using `run-analysis` as a universal recovery
  button.
- Citation Decision Value is a business interpretation layer, not a new
  Citation Score. It must stay at `SourceDocument + supported_entity +
  capability/reason` grain. A page-level summary may say "high-value decision
  citation", but formal Strategy input must preserve the underlying capability
  values, alignment IDs, and observed Run coverage.
- Step 7 Channel Strategy must not regress to either extreme:
  `CONTENT_GAP -> always official site` or `Benchmark channel -> execution
  channel`. Planned channel roles must be explained by Citation Decision Value,
  Channel Aggregation, Product Truth, Capability Gap, Relevant Brand Asset, and
  Retrieval/Citation status. Concrete account/URL/title/Draft remains Step 8.
- Step 7 now has exactly one formal channel strategy decision source:
  `resolve_strategy_channels(...)`. Frontend, workflow, and downstream services
  must not re-infer `PRIMARY / SECONDARY / EXPERIMENTAL / OBSERVE /
  NOT_RECOMMENDED` from Gap or Benchmark platform. If channel roles change,
  update the Resolver and its fixtures rather than adding a second resolver.
- `EVIDENCE_GAP` is the regression canary for Step 7 channel policy. A strong
  third-party Decision Citation path must be allowed to become `PRIMARY` when
  Product Truth, asset expression, and retrieval have already passed. If tests
  force official site PRIMARY in that case, the old hardcoded policy has leaked
  back in.
- Current Step 7 StrategyCandidate selection must be context-bound and origin
  gated. Legacy `generate-v2/local-rule`, audit, test, regression, or shadow
  candidates may stay in history, but they must not become current even if they
  are latest, pending, accepted, or have existing experiments. The current
  user-flow candidate must carry current Prompt/Evidence Package/package
  version/V1.1 input context, `candidate_origin = USER_FLOW`, and complete
  Strategy Core.
- StrategyCandidate payloads are structured audit objects, not all fields are
  display strings. Frontend pages must normalize object fields such as
  `evidence_summary` into Chinese summaries before rendering; raw object
  rendering can white-screen the app after successful Step 7 generation.
- Citation Decision read and confirm paths must carry the same context identity,
  including the active `use_answer_binding_v1_1` input version. If GET renders
  V1.1-ready actions but POST confirm recomputes with old V1 defaults, Step 7
  will look clickable while the backend rejects candidate generation.
- Evidence review can become noisy when multiple Runs produce the same cited
  source, same source claim, and same SUPPORTS relation. The UI should group
  these duplicated Run-level alignments for review and provide one
  `确认这一组支持` action, while preserving every underlying Run-level
  EvidenceAlignment for lineage and coverage. Do not group by per-Run technical
  IDs such as `answer_unit:{id}:binding:{id}`; use the semantic reason key or
  equivalent readable reason text.
- Step 7 must be shown as `策略确认`, not `推荐动作`. The underlying legacy
  workflow key may remain `action` for compatibility, but user-facing state must
  be derived from current workflow readiness plus current
  Evidence-Package-scoped StrategyCandidate review status. Historical confirmed
  StrategyCandidates must not mark the current Step 7 as complete when evidence
  review or gap diagnosis is still pending.
- Step 7 must not wait on legacy `WorkflowConfirmation.gap/action` after the
  current Citation Decision V1 Gap result is available. Otherwise the page can
  display Step 6 as complete while Step 7 still says `等待缺口`. The current
  Step 7 gate is:
  current Prompt + current Evidence Package + evidence review done + Citation
  Gap decision done + current `OptimizationStrategyCandidate` state.
- Historical StrategyCandidate or Experiment rows can make Step 7/8 appear
  falsely complete if the frontend counts them without the current workflow
  context. Current main-chain cards must first verify the current Prompt,
  Evidence Package, evidence review, and gap state; historical rows may be
  shown only as historical context.
- Audit-generated StrategyCandidate or Experiment rows, such as rows reviewed by
  `phase3_audit` or `phase4_audit`, are acceptance evidence rather than current
  operator workflow progress. They must remain visible for audit, but must not
  become the default current strategy, enable Step 8, or complete Step 7/8 when
  a user is re-running the same Prompt.
- Workflow state can be misleading if a card mixes stale `continueResult`,
  historical Citation Decision data, or historical Experiment state with the
  current Prompt context. Every workflow card must use its own primary fact
  source and must verify current `prompt_id`, evidence package, and analysis
  context before rendering progress.
- The full `citation-decision-v1` detail endpoint can be slower than
  `workflow/status` on #19-sized data. If that detail request times out or is
  unavailable, frontend workflow cards must not substitute empty Citation
  Decision defaults for current state. Step 7 readiness and Step 8 locking
  remain owned by `workflow/status`.
- Citation Prominence, source title similarity, same-entity citation hints, and
  historical `RELATED` alignments can create false confidence if they are used
  as formal SUPPORTS evidence. They may explain visibility or audit clues, but
  only eligible V1 EvidenceAlignment may feed Benchmark, Gap, Strategy, Action,
  or Experiment.
- Missing or unavailable source正文 must degrade at source level, not block the
  entire Prompt and not become `CONTENT_VALID`. A source without valid正文 must
  not generate new SourceClaim or formal EvidenceAlignment.
- Product Truth confirmation is only about the target brand's real capability.
  It is not confirmation that a competitor article is true, and it must not be
  inferred from Benchmark evidence.
- StrategyCandidate, Action, and Experiment are different stages. A confirmed
  Strategy is not an Experiment; Experiment draft creation requires Step 8
  channel/asset/operation confirmation and frozen snapshots.
- Step 7 StrategyCandidate must explain the AI decision intervention direction
  before concrete execution planning. If the page only restates a Gap or leads
  with article/draft controls, users will misread Strategy as a content task.
  The required Step 7 Strategy Core fields are target decision change,
  strategic hypothesis, priority capabilities, intervention mechanism, primary
  intervention path, planned channels, channel roles, asset direction,
  execution sequence, required signals, non-goals, and attribution intent.
- Step 7 planned channels are not the whole StrategyCandidate. The UI must lead
  with `StrategyCandidate -> Human Review -> effective_payload` status before
  showing channel cards; otherwise users may think the system only selected a
  few channels and skipped strategy confirmation.
- Planned channel is not concrete execution channel. Step 7 may decide platform
  layer such as OFFICIAL_SITE / ZHIHU / BAIJIAHAO and its channel role, but Step
  8 must still confirm concrete account, URL, asset, title, section, content
  structure, Baseline, Action, and Experiment.
- Benchmark channel is not Strategy or execution channel. A Primary Benchmark
  from Zhihu must not automatically mean `planned_channel = ZHIHU` or
  "publish on Zhihu"; if Zhihu appears in planned channels it must have an
  explicit role and cannot be copied from Benchmark provenance alone.
- Step 8 must not mutate Strategy Core. If Step 8 attempts to change fields such
  as intervention mechanism, channel roles, required signals, or attribution
  intent, the backend must block or require review instead of silently creating
  an Action/Experiment.
- Asset Brief is not a Draft. It is the Step 8 fact-boundary brief for one
  concrete Action / Asset / Execution Path. It must not generate article
  paragraphs, FAQ, titles, or publishing copy; those belong to a later Draft
  step.
- Claim Matrix must keep target-brand Product Truth and Benchmark Evidence
  separate. A competitor SourceClaim can establish market benchmark context,
  but it must never become a target-brand claim. Target-brand claims require
  Product Truth; `UNKNOWN` stays review-required and `NOT_SUPPORTED` stays
  prohibited.
- Required signals must map back to Claim Matrix rows. If a required signal
  cannot be traced to an allowed target-brand claim, later Draft preparation
  should remain blocked rather than inventing unsupported copy.
- Confirmed Asset Brief does not mean content is published or experiment is
  active. It only means Step 8 has frozen the asset fact boundary; release still
  requires the existing Release Audit gate.
- Existing Step 8 draft experiments created before Asset Brief support may need
  in-place brief backfill. Backfill must not create duplicate Action or
  Experiment rows and must not change Evidence, Benchmark, Gap, or Strategy.
- User-facing workflow labels, empty states, and action buttons must be Chinese.
  English enums may remain in storage/API internals only when Chinese labels are
  also provided to the frontend.
- If a main-chain button opens the wrong module or a standalone module is added
  instead of being integrated into the single Prompt workflow, treat it as a
  product navigation bug rather than a cosmetic issue.
- Loading state must not be rendered as product state. When switching single
  Prompt context, the frontend must show an explicit loading notice until the
  current Prompt workflow/status returns; otherwise users may see a fake "only
  collection completed" state and lose the real next-step entrance.
- Loading state must be scoped to the operation that is actually running. Step
  4 evidence review, Step 7 strategy confirmation, and Step 8 experiment
  landing must not share one frontend spinner flag; otherwise a Step 7 action
  can make Step 4 look unfinished even when the backend review queue is empty.
- `NEEDS_CURRENT_ANALYSIS` means the current V1.1 formal evidence input is
  missing. It must not be described to operators as a generic "rerun the whole
  main chain" unless the implementation truly needs a full recompute. Legacy
  `RECOMMENDATION_EVENT_REASONS_JSON` SUPPORTS can remain reviewed evidence,
  but they do not automatically become V1.1 `ANSWER_DECISION_BINDING` input.
- Phase C2-A Binding-aware Candidate Builder is shadow-only. Do not cut over
  formal EvidenceAlignment execution yet. Local #19 comparison found
  `old_only_candidate_keys=395`, including 15 old-only SUPPORTS/CONTRADICTS
  semantic groups covering 360 row-level EvidenceAlignment rows. These 15
  groups must be reviewed before C2-B cutover; either confirm they are safe
  removals or adjust the proposed recall rule. #40 has no old_only
  SUPPORTS/CONTRADICTS in the current shadow comparison.
- Phase C2-A.1 narrowed the #19 blocker set. Of the 15 critical old-only
  semantic groups, 14 are machine-only with no same-run citation anchor and no
  AnswerUnit context, so they are classified as
  `LEGACY_UNPROVEN_CROSS_PRODUCT`. One HUMAN_CONFIRMED SUPPORTS group remains a true
  recall-loss blocker: `reason=可以自动生成加密短链`, `claim_id=267`,
  `final_exclusion_reason=TOPK_TRUNCATION`, `rank_before_topk=6`, `top_k=5`.
  C2-B cutover must not proceed until this single blocker is handled by a
  generalized recall rule or an explicit human deletion decision.
- Phase C2-A.2 re-audited SourceClaim #267 and confirmed it is not a legacy
  false positive: its passage says the system automatically generates encrypted
  jump links, so it genuinely supports `可以自动生成加密短链`. Rename the 14
  machine-only groups to `LEGACY_UNPROVEN_CROSS_PRODUCT`, not scope artifact.
  L2 Run-scope recall is now shadow-implemented and verified; L1 is explicitly
  `L1_UNAVAILABLE_BY_SCHEMA`. The remaining C2-B blocker is the #267
  TopK-boundary loss. Shadow policy simulation shows `TopK + margin0.05`
  recovers it with 92 candidates and external LLM estimate 61, but this policy
  is not cut over yet.
- Phase C2-A.3 clears the #267 blocker in shadow with
  `POLICY_D_TOPK_WITH_BOUNDARY_TIES`: claim #267 is rank 6, score 0.2222, and in
  the same cutoff tie bucket as rank 5. Final #19/#40 read-only shadow
  re-aggregation shows `TRUE_POSITIVE_RECALL_LOSS=0`, Benchmark core unchanged,
  Gap unchanged, Strategy unchanged, and `C2_CUTOVER_READY=true`. This is not a
  cutover: `cutover_allowed=false`, formal `run_evidence_alignment(...)` remains
  unchanged, and no LLM or formal EvidenceAlignment writes occurred.
- Phase C2-B has cut over formal EvidenceAlignment candidate membership to the
  shared Binding-aware Candidate Builder with
  `POLICY_D_TOPK_WITH_BOUNDARY_TIES`. The rollback flag
  `use_binding_aware_alignment_candidates_v1_1=false` restores the frozen legacy
  candidate path. Remaining risk: L1 Answer Context is still
  `L1_UNAVAILABLE_BY_SCHEMA`, so future L1 work must be a separate schema/context
  phase. Do not use historical `EvidenceAlignmentMaterialization`,
  `EvidenceAlignment`, or `LLMCallCache` rows as alternate candidate-membership
  sources; they are verdict/recovery history only.
- Phase D materialization execution reliability is implemented with ledger
  `owner_id` + `lease_expires_at`, atomic claim, bounded wait, retry cap, and
  resume semantics. External DeepSeek concurrency smoke remains deferred in the
  current environment as `PHASE_D_EXTERNAL_CONCURRENCY_SMOKE_DEFERRED`; Phase E
  must run a real production smoke before claiming end-to-end production
  readiness. Do not add Redis/Celery/generic cache layers to compensate unless a
  separate production architecture decision explicitly approves it.
- Phase E final acceptance reached `INTERNAL_PRODUCT_READY=true` but
  `EXTERNAL_PRODUCTION_VERIFIED=false` because real SourceClaim/Alignment
  production smoke still requires external DeepSeek access. Current blocker:
  `ENVIRONMENT_POLICY_EXTERNAL_LLM_SMOKE_DEFERRED`. Do not mark V1.1 as
  externally production verified until the immediate rerun proves external LLM
  calls drop to 0 after materialization.
- Phase E exposed a non-LLM performance risk: #19 read-only planner +
  production candidate dry-run took about one minute on the local DB. This does
  not invalidate A-D semantics, but future readiness work should profile planner
  query/materialization-plan construction separately from LLM execution instead
  of treating all slowness as model latency.
- `materialization-plan` is a slow diagnostic/readiness call on large prompts
  and must not be part of the blocking path for human evidence confirmation,
  Step 7/8 actions, or ordinary workflow status refresh. It may refresh in the
  background or through a dedicated manual refresh button; otherwise a
  successful `confirm-batch` can look stuck even after the backend has returned
  200 and DB state has advanced.
- Stronger operational rule after the #19 spinner incident:
  `materialization-plan` must not auto-run on Prompt/page load either. Repeated
  browser refreshes can stack minute-long planner requests and exhaust the
  SQLAlchemy connection pool, causing unrelated lightweight endpoints such as
  `review-queue`, `channels`, `experiments`, and `decision-market` to time out.
  Keep it manual-only until the planner is moved to a bounded background job or
  cached snapshot.
- The human review modal must not reuse app-wide `loading`. Review queue load,
  background analysis start, and per-alignment confirmation need separate
  loading states; otherwise unrelated project/evidence/strategy refresh work can
  make `加载待审核项` or review buttons look stuck while the backend endpoints are
  already returning normally.
- Evidence review confirmation must not automatically run the heavy
  `citation-decision-v1` view after every group. A successful confirmation only
  needs queue/status refresh; full current-chain display refresh belongs behind
  the explicit `刷新主链路` action. Otherwise the first fast confirmation can leave
  a slow background decision view request that makes the second confirmation
  appear stuck.
- Page-level effects must also avoid auto-running `citation-decision-v1` while
  `evidence_review` is incomplete. Workflow progress and the review entry can
  be driven by `workflow/status`; the full Citation Decision view is not needed
  until evidence review is done or the user explicitly asks to refresh the main
  chain. If this guard is removed, every workflow status change during review can
  restart a heavy decision view request.
- Heavy Citation Decision requests that were already in flight before the
  workflow returns to evidence review must be explicitly invalidated or timed
  out on the frontend. Otherwise the review queue endpoints can return quickly
  while stale `citationDecisionLoading` still makes the page look stuck.
- Step 7 display must trust `workflow/status` current-chain identifiers before
  locally loaded strategy-list data. If `current_strategy_candidate_ids` exists
  but `strategyData.candidates` is empty because a heavy request failed or has
  not returned yet, the UI must show the backend current status such as
  `PENDING_REVIEW`, not fall through to `无策略`.
- Dev-server restarts must close orphan `PromptAnalysisRun.RUNNING` rows. In the
  local SQLite/FastAPI stack, a killed background thread cannot finish its DB
  status update; leaving the row as `RUNNING` makes the frontend poll work that
  no longer exists and can amplify request pressure.
- Human review POST buttons should remain bounded even in local SQLite lock or
  connection pressure incidents. A timeout should release the button and tell the
  user to reload the review queue, because retrying an idempotent batch
  confirmation is preferable to an indefinite spinner.
- Step 7 generation must not call the full `citation-decision-v1` detail path.
  The current Step 7 button should consume a lightweight, current-package
  strategy input derived from already materialized formal evidence. Reusing
  `confirm_citation_decision_vertical_slice()` for current Step 7 can rebuild
  source analysis and make a strategy click look like an indefinite spinner.
- Workflow Step 7 must not use legacy SUPPORTS review progress as current
  readiness. A Prompt can have fully reviewed historical SUPPORTS rows and
  still have `formal_v1_1_support_count = 0`; that state must not automatically
  become `NO_STRATEGY`. If current answer decision reasons match SUPPORTED
  Product Truth, Step 7 should generate an explicit
  `ANSWER_DECISION_EVIDENCE_GAP` candidate with empty `benchmark_evidence_ids`,
  not a fake Benchmark and not an empty strategy result.
- `ANSWER_DECISION_EVIDENCE_GAP` must not be inferred from `SUPPORTS = 0`
  alone. Check the same decision reason for eligible SUPPORTS and CONTRADICTS;
  only the absence of both can produce the simple evidence-gap class. Persist
  the reason IDs and gap cause in the Candidate payload so future UI and audits
  do not mistake the strategy for a Benchmark-backed result.
- Step 7 source mapping now has versioned URL identity and explicit Data Health.
  Do not regress to comparing canonicalized URL keys directly against raw URL
  database columns. `references > 0 && mapped = 0` is a pipeline-invalid state,
  not evidence that no channel exists.
- Historical PR1 checkpoint: mapping coverage was restored before Channel
  Aggregation/Resolver policy changed. PR3-B has since superseded #54 with an
  explainable replacement; #54 must remain historical and must not be confirmed.

- No Alembic migration history. SQLite additive sync is acceptable for Alpha but
  not enough for production.
- `httpx` is not installed in the current backend venv, so FastAPI TestClient
  based API tests are not currently available.
- Browser collection can still be blocked by Wenxin login/captcha/security
  checks.
- Source-depth analysis is still first-pass evidence aggregation; future work
  should add source angle, freshness, authority, content-shape, and citation
  reason classifications.
- Daily trend analysis exists only as Prompt daily report primitives; project-
  level trend synthesis is deferred until after P0 loop validation.
- Software smoke does not prove real SEO/GEO improvement. Real experiments need
  actual release evidence, enough cooling time, new collection, and human review.
- The first real experiment has locked a strict zero baseline for
  `target_page_retrieval_rate`: Prompt 19 target page retrieval entry is
  `0 / 12 = 0%`. Do not reinterpret this as a conversion-rate baseline;
  `target_page_conversion_rate` remains not applicable until the page enters
  retrieval candidates.
- Worktree is intentionally dirty during Alpha development. Before an Alpha
  baseline commit, separate source/docs/tests from tracked fixture artifacts and
  ignored local runtime files. Do not commit `.env`, SQLite DBs, browser
  profiles, cookies, storage state, untracked monitoring artifacts, `dist`, or
  dependency folders.
- External official-site publication is outside this repository. Do not write
  `released_at`, enter cooling, or claim `REAL_EXPERIMENT_STARTED` until the
  user confirms the target page has actually been published.
- PR2 Channel Evidence Landscape shows a current #19 lineage gap that must not
  be hidden by channel volume: 192 formal SUPPORTS rows all fail
  `SOURCE_NOT_REFERENCED_IN_RUN`. The current reason observations and aligned
  SourceDocuments do not share the required same-Run Citation lineage, so all
  1,207 current Citation observations remain Peripheral. Do not promote their
  channels to Decision Citation, weaken Phase 2A eligibility, or use historical
  human confirmation as a channel whitelist. Any correction belongs to a
  separately approved upstream lineage/data investigation, not PR2/PR3 display
  logic.
- Source mapping cardinality has two distinct causes and must remain explicit:
  #19 contains four reference URLs with multiple content snapshots, while #40's
  extra two aggregation documents are retrieval-only and not 1:N reference
  matches. Future aggregation must keep raw document memberships, unique
  document identities, Citation observations, URLs, Runs, and semantic
  relations separate; using any one as a substitute for another reintroduces
  row explosion.
- Retrieval rows with no URL may place an author/source label in the legacy
  `domain` field. Without a resolvable URL or existing deterministic domain
  mapping these rows must stay `UNKNOWN`; treating the label as a channel would
  fabricate Channel Evidence.
- Historical PR3-A checkpoint: the resolver was Shadow-only and #54 still
  carried the empty-channel official-site decision. PR3-B has now cut over and
  preserved #54 with immutable supersede reason
  `CHANNEL_RESOLUTION_INVALID_DUE_TO_SOURCE_MAPPING_FAILURE`.
- Path D reason relevance is a deterministic opportunity signal, not formal
  EvidenceAlignment. It can reuse source titles, snippets, document text, and
  SourceClaims (including rows excluded from Phase 2A) only to decide whether a
  channel hypothesis is worth testing. These inputs must never be promoted to
  Decision Citation, Answer Support, Benchmark, Product Truth, or PRIMARY.
- Chinese bigram lexical relevance can over-match shared topic vocabulary and
  miss paraphrases. Before PR3 Cutover, manually audit the #19 TEST hypotheses
  for Baijiahao, Bilibili, Zhihu, and Sohu at Decision-Reason level. Do not fix
  uncertainty with a new LLM judge, weighted channel score, or a hardcoded
  channel whitelist.
- A Path D eligible result is still suppressed as a formal TEST when the same
  scope already has an observed Path A/B Decision/Benchmark channel. This keeps
  #40 focused on its proven Zhihu signal. Path D diagnostics remain visible for
  audit, but cannot silently expand the execution portfolio.
- PR3-B is now cut over for the current Single Prompt Step 7 generation path.
  Candidate #54 is immutable superseded history and #56 is the current #19
  candidate. Do not treat #55 as current: it was an intermediate migration row
  that failed the existing strategy-core/evidence-context Gate because the
  first frozen-action reconstruction omitted several provenance fields; it was
  preserved and superseded after the reconstruction was fixed.
- Do not collapse proposed and active intervention state. A pending Strategy may
  carry `proposed_intervention_mode=CONFIRMED_CHANNEL_INTERVENTION`, but
  `active_intervention_mode` must remain null until Strategy confirmation and
  all Step 8 gates pass.
- Path C Product Truth and Path D TEST relevance are reason-scoped. Future
  serializers, editors, or migrations must preserve each channel's
  `decision_reason_ids`; candidate-level truth/relevance union is not sufficient
  and can incorrectly let Reason A borrow Reason B evidence.
- The #19 ordinary `generate-current-v1` endpoint can still spend more than 120
  seconds before Resolver execution in `_current_step7_strategy_rows_for_package`
  due to repeated SourceDocument-to-Reference/Retrieval matching. This is not a
  Channel Resolver or LLM delay. PR3-B used the already frozen #54 action for the
  one-time migration. A later, explicitly scoped performance fix should reuse
  PR1 URL memberships or add a bounded cached Step 7 input; do not respond by
  reintroducing the heavy `citation-decision-v1` detail call or weakening
  evidence lineage.
- PR4-A Theme grouping and portfolio priority are derived views, not new facts.
  Never persist an LLM-created reason, Product Truth, channel, asset, metric, or
  causal statement into the current Candidate. Multi-reason Themes must stay
  inside the deterministic compatibility graph, and all model fields outside
  the strict schema must fail closed rather than be ignored.
- Channel role and execution priority are different dimensions. A deferred
  TEST remains TEST; it must not be serialized as OBSERVE. A TEST P1 remains a
  validation hypothesis and must not be upgraded to PRIMARY or treated as a
  proven rollout channel.
- Strategy coverage has two visible contexts: the union of current reason Runs
  is the Strategy `total_analyzable_runs`, while all valid Evidence Package Runs
  are audit context. Do not restore the old `count / max reason count` display
  or mix package-valid and decision-bearing denominators in one label.
- PR4-A.1 proved the external-provider safety chain only with synthetic,
  non-sensitive data. DeepSeek returned parseable JSON that contradicted its
  own bounded decision (`NEEDS_HUMAN` plus three selected channels); the code
  rejected the whole proposal and preserved the deterministic baseline. This
  is a useful provider-path PASS, not a claim that the model itself obeyed the
  schema and not a real #19/#40 replay.
- Real #19/#40 external LLM replay remains deferred because project-data egress
  has not been authorized. Do not send those Strategy objects externally or
  claim real-data hallucination audit PASS without explicit authorization.
- `use_llm=true` must never mean “always call LLM.” For a uniquely determined
  Strategy, the expected runtime is `SKIPPED_NOT_NECESSARY` with zero external
  calls. Reintroducing a whole-Strategy prompt would reopen role mutation,
  unknown-object, cost, and nondeterministic-priority risks.
- Bounded proposal validation must remain all-or-nothing. Do not repair an
  illegal field and keep the rest of the model output, do not relax the contract
  on retry, and do not turn historical human review into an allowed-ID or
  channel whitelist.
- Theme coverage must remain the exact union of member Reason Run IDs. A sum of
  member coverage double-counts overlapping Runs; a model-generated count or
  title can introduce unsupported strategy facts.
- PR4-B is now the formal current Step 7 synthesis path. #19 current is #57;
  #56 is immutable `DEFERRED` history with reason
  `SUPERSEDED_BY_VALIDATED_STRATEGY_SYNTHESIS_V1`. Do not restore #56 as current
  or treat the supersede marker as evidence that its underlying Resolver result
  was invalid.
- Shadow and Production must continue to call the same synthesis core. Any
  future validator, ambiguity policy, Theme rule, or portfolio rule added to
  only one path invalidates the production-vs-shadow parity guarantee.
- The formal persistence gate must remain before current-candidate supersede.
  A synthesis/context/validator failure must leave the previous current
  Candidate intact; do not reorder this into a supersede-then-generate flow.
- External Strategy LLM remains disabled by default. Ambiguity with the flag
  off must preserve deterministic Strategy truth and surface human review; it
  must not become `NO_STRATEGY` or `FAILED`.
- A fresh #19 read-only action reconstruction again exceeded three minutes,
  this time inside repeated Evidence lineage URL matching. This remains a
  separate pre-synthesis performance risk. PR4-B used #56's frozen grounded
  payload for the one-time Cutover and did not weaken lineage or add a second
  strategy-generation truth source.
- PR4 synthesis payload and frontend rendering are separate contracts. A valid
  Candidate can silently regress to Reason-level coverage and flat Resolver
  channels if the UI reads `structured_payload` instead of
  `strategy_decision_view`. Keep `strategy_view_mode` as the explicit branch:
  valid synthesis uses Decision View only; invalid/missing synthesis uses the
  Legacy fallback only.
- Candidate #50 predates persisted PR4 Decision/Audit views and must remain
  immutable. Its current compatibility view is a read-only projection through
  the shared deterministic synthesis core. Do not persist that projection into
  #50, create a replacement Candidate merely for presentation, or let the
  projection call external LLM. A future migration may materialize views only
  under a separately approved immutable-artifact contract.
- Product and audit language must remain separated. Resolver roles, Path
  labels, `NO_ELIGIBLE_BENCHMARK`, lineage rules, IDs, and raw provenance are
  audit data; exposing them in the primary Strategy Decision View makes the
  operator-facing recommendation look contradictory even when synthesis is
  correct.
- A confirmed Strategy with Step 8 `READY_TO_CREATE` normally has no Action or
  Experiment yet. The Step 8 entry must open configuration in this state; it
  must not treat missing draft IDs as a reason to return or only show a toast.
  Existing-draft lookup and new-draft configuration are distinct branches.
- Step 8 asset discovery is supporting data, not an entry gate. Open the form
  before loading PageSnapshots and handle snapshot failure locally; otherwise
  a slow asset endpoint recreates the same apparent no-response failure.
- The frontend must not rebuild executable channels from raw
  `planned_channels`. It consumes backend `execution_channel_options`, which
  excludes deferred TEST and OBSERVE. Adding those channels, changing Role, or
  changing Strategy Core still requires returning to Step 7.
- PR5-A is a read-only execution compiler, not a new Step 8 truth source. Its
  ephemeral snapshot and proposals must not be persisted, treated as confirmed,
  or used to create Action/Experiment until separately approved PR5-B/C/D gates
  implement human edit, revalidation, freeze, and one-proposal-per-experiment
  persistence.
- PageSnapshot is not ManagedAsset. Historical customer URLs and snapshots must
  not silently become `UPDATE_MANAGED` candidates. Until an explicit managed
  asset lifecycle exists, production replay correctly uses an empty managed
  asset snapshot and `CREATE_NEW`.
- Validator `VALID` does not imply proposal `READY_FOR_REVIEW`. Asset type,
  packaging, observation window, or multiple high-fit assets may be completely
  safe yet remain `NEEDS_HUMAN_SELECTION`. Do not collapse these states or
  auto-select the first candidate in a future UI.
- PR5-A target assertions currently accept the repository's positive truth
  value (`SUPPORTED`, with compatibility for `TRUE`) only when provenance is
  `MANUAL_CONFIRMED`. Do not compare `product_truth_status` to
  `MANUAL_CONFIRMED`; truth value and provenance are separate fields.
- The Product Truth schema currently has no approved alias registry. Execution
  titles and sections therefore use exact `capability_label` text. Adding
  deterministic synonyms, shorter capability labels, or marketing rewrites
  would create an unreviewed factual vocabulary and needs a separate contract.
- New external assets have no historical selected-asset measurement. Their
  retrieval/citation metric status is `NOT_MEASURABLE_YET`, not a zero baseline.
  Prompt/brand metrics may still use the frozen Evidence Package run scope.
- Candidate #50 remains immutable and is projected only for compatibility.
  Never write PR5 structures back into #50 or reinterpret its
  `BENCHMARK_BACKED_STRATEGY` as an Evidence Gap merely to normalize schemas.
- PR5-A.2 freezes self-contained one-asset Package candidates. A future UI or
  persistence path must not reconstruct Package meaning from outer proposal
  fields, auto-select FULL/P1, or allow `asset_count != 1` without a new
  attribution contract.
- An unresolved Asset Package has only package-specific Section Plan
  candidates. The empty top-level selected Section Plan is intentional until
  package selection; treating the first candidate as selected would silently
  change user scope.
- Section provenance must remain purpose-specific. Reintroducing a fixed
  seven-section template, publishing `PLANNING_QUESTION`, inventing OPERATION
  steps, or copying all proposal Reasons/Truths/signals into every section is a
  quality regression even if every referenced ID exists.
- TEST hypotheses are keyed by frozen evidence patterns, not channel name.
  Distinct profiles that normalize to the same hypothesis text must fail the
  quality gate. BAIJIAHAO and ZHIHU must retain their current retrieval-exposure
  distinction unless upstream Resolver evidence genuinely changes.
- `PR5-A = FROZEN` means the read-only Shadow contract passed safety and
  quality acceptance. It does not authorize PR5-B cutover, proposal
  persistence, frontend prefill, Action/Experiment creation, or ManagedAsset
  lifecycle changes.
- `PR5-B = FROZEN` only authorizes ephemeral human review and deterministic
  revalidation. `READY_FOR_CONFIRMATION` / `ready_for_freeze=true` must never
  be rendered or consumed as an already persisted execution freeze; PR5-C is
  still required.
- Step 8 must not restore the legacy blank form or call the old
  `execution-plan` creation endpoint from PR5-B. Legal package/type/section and
  observation choices come from the PR5-A proposal; the frontend is not a
  second execution-planning truth source.
- Human edits are overlays, not patches to PR5-A. Immutable fields must be
  rejected even when placed outside `human_edits`; silently dropping or
  correcting an illegal Role, baseline, Product Truth, scope, metric, or merge
  attempt breaks the audit contract.
- Removing a proposal from this run is `DEFERRED_BY_HUMAN`, not a Role change
  and not a validator failure. Independent channel proposals may not be merged
  into one future Experiment.
- A visual default is not a human selection. Boolean choices rendered through
  controls whose option contract is string/number must use explicit UI enum
  values and convert once at the API boundary; an uncontrolled first option
  can look selected while the edit overlay remains unset.
- `SC-RUNTIME-001@0.1.0` is Definition FROZEN and its isolated persistence
  implementation is `PARTIAL`; live production Runtime adoption remains not
  started. The read-only #19/#40 Spike is `SPIKE_PASS` evidence only;
  its `virtual:` Context/Stage identities, legacy source hashes and completeness
  results must never enter workflow current state, Review API, Strategy,
  Action, Experiment, PR5 or cache.
- The Runtime Spike proves both fixed cases are honestly `UNSAFE`, not that
  their historical lineage can be repaired. Any future Runtime Shadow phase
  must preserve null formal manifests/reviews and require separate Product
  Owner authorization; do not backfill a latest winner.
- Runtime Phase 1A persistence is isolated and `PARTIAL`, not deployed. Do not
  import `RuntimeBase` into the production `app.models.Base`, apply migration
  `20260910_01` to the real database, or call `RuntimePersistence` from the
  workflow until Phase 1B is separately authorized. Doing so would silently
  turn an accepted storage spine into live dual-write/cutover behavior.
- The full backend suite currently has five reproducible failures outside
  Runtime Phase 1A: two old batch-delete contract tests, one Wenxin conversation
  reset test and two legacy Step 8 strategy-plan tests. Phase 1A focused tests
  are green and its production call-sites are zero; these failures remain a
  separate baseline maintenance item and must not be hidden as a Runtime pass.
- Runtime Phase 1B is blocked by two Frozen mapping gaps, not by storage code.
  `ANSWER_SEMANTIC` has no registered closed-enum `member_kind` literals or
  durable per-Run successful-zero member, and Legacy creates AnswerUnits inside
  the would-be `BINDING` execution instead of exposing them as a committed
  upstream Stage output. Do not add a production capture hook, infer zero from
  missing rows, or synthesize the missing dependency edge until independent
  Definition Review resolves `SEM-CONFLICT-003/004`.
- The Phase 1B Stage-output/binding review found additional non-instrumentation
  blockers. Production Source Qualification currently scans the global
  SourceDocument table without a Prompt/Run partition; Product Truth uses
  heuristic Reason text matching without an immutable reviewed binding; Gap
  confirmation is a mutable Prompt-level singleton with no target Gap output;
  and Execution Proposal can select a latest/current Candidate when no ID is
  supplied. These are `LEGACY_SEMANTIC_AMBIGUITY`, not missing observer fields.
  Do not bind them to a current Package/Candidate, URL-match them after the fact,
  or treat a targeted RFC amendment alone as sufficient to resume full Phase
  1B.
- Semantic maturity and implementation status are independent. A behavior may be `OBSERVED + PRODUCTION`; production usage or a historical phase label such as “FROZEN” must not automatically promote it to a new-governance `FROZEN` Contract.
- Chat authorizes the active task but is not durable semantic truth. Decisions that must control future work have to enter a versioned Contract, RFC, Product Definition, Decision Log, or equivalent repository artifact.
- `APPROVED RFC` authorizes implementation, Shadow, Replay, and validation only. It does not supersede current production semantics; production replacement always requires separate, explicit Product Owner cutover approval.
- Golden real-data replays must use the exact snapshot manifest IDs and hashes. If the fixed local DB object is unavailable, return `SNAPSHOT_INPUT_UNAVAILABLE`/`LOCAL_DB_REQUIRED`; never substitute the latest Evidence Package, Candidate, or Run scope.
- `SEM-CONFLICT-001` remains OPEN: current production Resolver Path C can use confirmed Product Truth and the authority gate for OFFICIAL_SITE PRIMARY, while the Foundation/Citation Split candidate would resolve foundation need and citation intervention separately. Keep production behavior unchanged until Definition Review and a later independent cutover decision.
- `SEM-CONFLICT-002` remains OPEN: the ACTIVE older P0 target-page/editable-asset gate and current PR5-A/B `CREATE_NEW` proposal behavior need Product Owner scope/version clarification. Until then PR5-B stays ephemeral and PR5-C remains blocked as semantic risk.
- PR5-C affects proposal persistence, Action/Experiment identity, baseline/snapshot freeze, asset relationships, and Step 8 transitions. Treat it as `SEMANTIC_RISK`: dependency analysis and read-only investigation are allowed; production implementation is not.
- Single-Prompt Core V2 depends on the existing collector for real first-slice
  acceptance. The current Wenxin worktree fails the independent-conversation
  reset test and unconditionally emits an empty Retrieval candidate list.
  Until the producer contract is repaired and a real new-Prompt sample is
  replayed, V2 is control-plane/fixture ready but
  `BLOCKED_BY_COLLECTOR_CONTRACT` for production collection acceptance. Do
  not infer independence from configured Run mode or interpret missing
  Retrieval output as an observed zero.
- V2 uses an intentional Alembic branch from `20260819_01` so deployment does
  not imply Runtime migration authorization. Operators must target the V2
  branch explicitly until migration governance decides how independent heads
  are merged; applying every head would also apply the gated Runtime artifact.
- Fifth-slice V2 retest is implemented but has no authorized real external
  positive replay. Browser execution behavior, live observed-condition capture
  and real post-publication Answer Semantic costs remain unverified outside
  isolated tests. Do not describe fixture acceptance as a measured campaign.
- Historical Baselines may not contain per-Run observed-condition fields added
  for new Retests. They must remain `PLAN_DECLARED_ONLY`/unknown limitations;
  never reconstruct them from current mutable Run, Prompt or Project state.
- `USER_REPORTED` publication and even `MATCHED` conformance do not verify the
  online page or establish causality. Comparison is descriptive only; temporal,
  condition and per-metric eligibility must remain visible.
- The V1 monitoring regression suite currently has one pre-existing failure:
  `test_prepare_collection_mode_raises_when_conversation_cannot_reset`. Fifth-
  slice frozen task creation does not touch that collector behavior, but a real
  V2 retest still depends on the unresolved Wenxin conversation-reset contract.
- The current full backend baseline is 555 passed / 7 failed. In addition to the
  Wenxin reset failure, the remaining failures are two old batch-delete contract
  tests, two Legacy Step 8 strategy-plan tests and two Runtime Projection Spike
  real-data expectation tests. They are outside the Fifth Slice and were not
  weakened or repaired as part of retest delivery; keep them visible until their
  owning contracts are handled independently.
- V2 now exposes missing independent-session proof and missing Retrieval output
  as backend-authored warnings in both API and UI. This improves truthfulness
  but does not resolve the producer defect; collector repair and a new real
  replay are still required before production collection acceptance.
- Single-Prompt V2 second-slice #44 has a real AnswerSemantic acceptance result,
  but external SourceClaim/Alignment integration is intentionally not verified:
  the one-time authorization excluded page-content export. Eight locally
  recalled passages and all dependent alignments remain `NOT_EVALUATED`, not
  `NO_SUPPORT`. A later separately authorized acceptance is required before
  claiming full external evidence diagnosis.
- The fixed #44 immutable result reports 25 technically successful snapshots,
  but a post-publication audit found one CSDN security-verification page. Treat
  effective evidence-ready content as at most 24 for that ResultVersion. The
  new deterministic challenge gate prevents future V2 executions from treating
  matching pages as content-ready, but immutable history must not be rewritten.
- Four #44 source snapshots remain `FETCH_FAILED`; Retrieval observation and
  independent-session proof remain unavailable; all 116 anchor bindings are
  `UNPROVEN`; Project 1 Truth is empty; and no DiagnosisReview has been appended.
  `READY_FOR_REVIEW` must not be interpreted as evidence complete or fact
  confirmed.
- DeepSeek JSON mode with V4's default thinking returned empty/non-JSON content
  in two pre-acceptance executions. V2 now explicitly disables thinking for the
  bounded JSON extractor, records that generation control in contract/cache
  identity, limits an execution to one HTTP attempt and preserves safe finish/
  length metadata on failure. Legacy DeepSeek callers retain their prior default.
- V2 persists total provider token usage, but not prompt/completion/cache token
  breakdown or billed amount. The authorized #44 result records 2,417 total
  tokens; its actual fee is unknown and must not be reconstructed as a charged
  amount from public list pricing.
- V2 strict response admission now blocks known structural defaults and clear
  grounding/normalization violations, but it is not a complete natural-language
  truth detector. Ambiguous attribution, conditional recommendation and weakly
  grounded paraphrase remain `SEMANTIC_REVIEW_REQUIRED`; reviewers must not
  treat these visible items as effective Evidence or Product Truth.
- Synthetic malicious-output fixtures verify deterministic authority and
  consumption gates only. Real DeepSeek prompt-injection resistance is still
  `NOT VERIFIED`, and the fixed #44 authorization did not permit external
  SourceClaim/Alignment calls. Do not report those integrations as production-
  verified from local fixtures or AnswerSemantic success.
- `LLMCallCache` is a recovery source, not an authority bypass. V2 rejects
  cached payloads that do not satisfy the current admission version and does
  not auto-call externally in `CACHE_ONLY`; incompatible cached work remains
  failed/not evaluated until separately authorized processing is available.
- The #44 immutable result still reports 25 historical technical successes.
  Current safety projection blocks one verification page and publishes at most
  24 eligible sources plus an effective relation whitelist; neither 24 nor the
  whitelist means every remaining page has received complete quality review.
- Single-Prompt V2 third-slice strategy is isolated from V1 and does not resolve
  global `SEM-CONFLICT-001`. Do not call V1 Channel Evidence/Resolver/PR4
  runners from the V2 strategy entry: their latest-Package reads and historical
  OFFICIAL_SITE PRIMARY equivalence remain incompatible with the V2 contract.
- A completed V2 DiagnosisReview is only the strategy entry gate. It does not
  approve every Reason, Truth relation, Alignment or anchor. Current safety
  eligibility, exact review snapshot and consumed object IDs must continue to
  match; otherwise the old strategy is history-only and writes return 409.
- `Foundation=UNKNOWN`, zero PRIMARY and zero qualified directions are valid
  outcomes. Never replace them with an official-site fallback or an empty
  StrategyCandidate. #44 currently remains class A with no review and must not
  be used as a real positive strategy acceptance case.
- V2 channel TEST qualification is deterministic and non-causal. It states a
  verifiable hypothesis from an eligible relation and target applicability; it
  does not prove that publishing on the channel will improve recommendation.
  Real external SourceClaim/Alignment remains unverified, so current #44 has no
  qualified channel direction.
- V2 fourth-slice execution is real-code but positive acceptance is synthetic.
  #44 has no DiagnosisReview or accepted Strategy, so no real proposal,
  confirmation or publication exists. Do not report fixture publication as a
  completed customer execution loop.
- The current V2 asset lifecycle supports CREATE_NEW only. SourceDocument,
  PageSnapshot, planned specs and caller-supplied IDs do not prove ownership or
  edit permission; UPDATE must remain rejected until an explicit ManagedAsset
  identity and permission proof exist.
- Publication records are USER_REPORTED facts, not fetched or system-verified
  pages. Backend conformance evaluates only submitted, mechanically checkable
  fields. Missing or unstructured content remains NOT_EVALUABLE; MATCHED does
  not prove that the live page was fetched or that an intervention caused an
  outcome.
- Fourth-slice Baseline is frozen for future measurement but no retest or effect
  comparison exists. Retrieval observation and independent-session limitations
  remain attached, and an unavailable asset metric must not be represented as a
  zero baseline.
- The 2026-09-14 real V2 Baseline for Project 3 / Prompt 40 completed three
  successful Runs, and each captured HTML had one current question node.
  Nevertheless the collector persisted `collection_mode=single_continuous` and
  `sampling_mode=UNKNOWN` against a `single_independent` plan. Treat the HTML and
  distinct local UUIDs as case evidence only, not a proven collector capability;
  a future Retest must preserve the condition conflict and suppress unsupported
  deltas.
- The frozen #40 Analysis status still returns the stale blocker code
  `NEXT_STAGE_NOT_IMPLEMENTED` after raw-result freeze even though V2 Diagnosis
  now exists. Do not interpret this wording as the actual Diagnosis readiness
  contract or bypass exact-version checks; correct it as a separate minimal UI/
  status defect before relying on that message for user guidance.
- The 2026-09-14 authorized #40 Answer Semantic replay exposed a production
  response-contract gap: the prompt omitted the non-empty selection-criterion
  shape and all three responses were correctly rejected as `FAILED_SCHEMA`.
  The local implementation is now aligned under Answer Prompt/Schema v2, uses
  one strict object shape, preserves market criteria independently, and blocks
  all-failed results from review/revision/Strategy. This is implementation- and
  test-verified only. Do not describe the historical ResultVersion as zero
  recommendation or the repair as provider-verified. The formal replay endpoint
  covers all fixed Runs 260/261/262, so a new explicit three-Run authorization
  is required before validating DeepSeek against the repaired contract.
- The authorized repaired-contract replay verified the strict non-empty
  `selection_criteria` shape, but exposed an exact-grounding sensitivity in
  Wenxin text. Runs 261/262 contained invisible separators around section
  labels; DeepSeek omitted one separator from `answer_span`, causing the entire
  otherwise structured response to fail `FAILED_GROUNDING`. This is the correct
  current safety outcome and must not be bypassed with fuzzy acceptance or
  post-hoc span rewriting. Any future remediation must preserve immutable-text
  identity while defining an auditable normalization/offset contract; this
  replay is frozen and no retry remains authorized.
- The same replay emitted a machine-only lexical `PARTIALLY_COVERS` suggestion
  from an `壹伴助手` Reason to target-brand Truth #2. It did not mutate Truth and
  is not confirmed coverage, but it demonstrates that lexical overlap alone can
  propose a cross-subject Reason-to-Truth relation. Downstream consumers must
  continue requiring subject eligibility and explicit review; do not treat
  review completion as automatic confirmation of this relation.
- **The confirmed U+200C grounding defect is locally remediated, but the failed
  responses are not fully recoverable from audit storage**: only the response
  hash, finish reason, length and 240-character excerpt are retained. The first
  failed span in Runs 261/262 is proven to differ only by one `U+200C`; all
  remaining events, Reasons and criteria are still unknown until a separately
  authorized full replay. Do not infer that both Runs will pass from fixture
  coverage.
- **Grounding equivalence must remain narrowly versioned**: current V2 permits
  only exact unique or same-line unique U+200C equivalence. Adding whitespace,
  NFKC, arbitrary control-character removal, fuzzy similarity or first-match
  fallback would change the evidence identity contract and requires explicit
  review. A located subspan also does not hide adjacent negation/condition;
  semantic admission consumes its raw line context.
- **Historical source failure wording remains immutable**: the fixed #40 result
  still contains `SOURCE_CONTENT_PARTIAL_FAILURE=35`, while the current read-only
  projection correctly classifies all 35 as not fetched due to disabled external
  fetch and zero as actual fetch failures. Consumers must use the current status
  projection for eligibility and keep the old label as historical audit only.
- **Human review does not validate Product Truth or source evidence**: the V2
  event review only decides whether the frozen answer presents an entity as an
  option in that local scenario. Even `CONFIRM_INCLUDE_AS_OPTION` must retain its
  original speech act and cannot establish brand capability, citation binding or
  channel effectiveness. Those remain separate Truth and Evidence gates.
- **Historical bundled source flow remains unsafe outside the release app**: the
  old second-slice route can still run Answer before source completion and bundle
  source/evidence work. The GEO 1.0 release app resolves this with Analysis-owned
  manifests, manual source completion and an exact Evidence gate, and does not
  register the bundled route. Do not re-enable the old route, use latest snapshots,
  treat not-fetched as no support or manually write evidence rows. Historical #40
  still has 35/35 sources not fetched and is not migrated into the release path.
- **GEO 1.0 first real acceptance is partial, not Evidence-complete**: the
  release database now contains a real Analysis/Context, 38-source Citation
  Manifest, one immutable READY Snapshot and a 3/3-admitted Answer ResultVersion.
  It still has 37 PENDING sources and no Answer Review, Completion Manifest or
  Evidence Result. Candidate fetch files must not be treated as READY; manual
  source disposition and exact Review remain mandatory.
- **Release SQLite is intentionally single-host/single-writer scoped**: the
  runtime uses one API process and one business worker. Do not add a second
  worker or share the database file across hosts. API review writes and worker
  writes must stay short; external browser/LLM waits cannot hold write
  transactions.
- **The host stdlib SQLite is not the release DBAPI**: the verified release
  runtime uses statically built pysqlite3/SQLite 3.51.3. A missing package or an
  unsafe version must block migration/startup; never bypass the check to make a
  deployment start. Source downloads are pinned by SHA-256.
- **Wenxin independent-session behavior is live-verified for the first release
  case, but one Run is citation-partial**: three final Runs recorded distinct
  conversation identities and `PRE_SUBMIT_ZERO_TURN_DOM_GATE`. Two earlier
  attempts failed during release integration and were retained rather than
  hidden. Run 3 is valid `partial_success`, so its citation completeness
  limitation must remain in downstream interpretation.
- **Queued and running have different restart semantics**: `QUEUED` and
  `EVIDENCE_QUEUED` are durable work requests; `COLLECTING`, `RUNNING` and
  `EVIDENCE_RUNNING` have uncertain external side effects after process loss and
  therefore become explicit interruption/failure. Do not auto-retry them on
  startup.
- **Frozen release Runs 2/3 retain a known false citation-partial status**: the
  saved pages contain all 28/24 references, but the then-active parser removed
  reference #23 because its title contained `复制`. The parser regression is
  fixed and both artifacts replay as complete, but immutable Raw Result
  `raw-v1:c10d6ba7d06dee7e` remains 27/23 until a formal resample creates a new
  result. Do not interpret the missing row as a Wenxin or network omission.
- **Release automatic source fetch is real-run accepted but Source Completion is
  still blocked**: corrected Analysis `92bb12a5-edcc-43c7-b848-ca60267a2672`
  froze 46 unique sources and the formal worker produced 30 READY snapshots plus
  16 MANUAL_REQUIRED items, with zero automatic waivers. Artifact hashes and the
  859 persisted passages are intact after restart. This proves automatic-first
  acquisition, not a complete Evidence input: the 16 unresolved sources still
  require explicit manual content or human waiver before a Completion Manifest
  can exist. The legacy `acquire_cited_sources()` runner remains prohibited
  because it writes V1 `SourceDocument` workflow state.
- **Auto-fetch summary aggregation previously lagged settled disposition rows**:
  the real run exposed `AUTO_FETCH_PENDING` at preparation level while all 46
  children were already READY or MANUAL_REQUIRED. The transaction now flushes
  before aggregation and startup reconciles only fully settled stale summaries;
  it does not repeat network fetches. Keep the restart regression because this
  status otherwise leaves the page polling forever despite correct child data.
- **Explicit Run selection is for analysis scope, not post-hoc experiment
  sampling**: release users can now combine historical and new Runs into an
  immutable AnalysisContext, but a future Baseline/Retest still has to satisfy
  its predeclared sampling plan. Selecting Runs after seeing favorable outcomes
  cannot be presented as an unbiased effectiveness measurement. Input
  fingerprints prevent stale selection, not selection bias.
- **The current release DB does not contain the zero-event Answer objects named
  in the latest work order**: the live database has 9 Runs and 3 Analysis/
  Context records, but zero DiagnosisExecution, DiagnosisResult and Review
  rows. The older object IDs must not be reconstructed from documentation,
  inserted manually or treated as current Evidence input. A current Answer
  Result must be created through the formal endpoint under a new, explicit LLM
  authorization, then reviewed against its exact version.
- **Pre-rebuild release artifacts are audit-only unless their immutable content
  is still available**: reconciliation found the old `2om.cn` Snapshot ID and
  hashes in documentation, but neither its database row nor its artifact file
  survives in the current workspace or known backups. A hash without retrievable
  bytes cannot be rebound into the current Source Completion Manifest. Do not
  reconstruct the row from notes or treat domain equality as version proof.
- **Task actor metadata is not an external-authorization ledger**: Runs 4-9
  preserve Task, Analysis, timestamps, session evidence and `created_by`, but no
  dedicated authorization artifact. Before any new browser, fetch or LLM call,
  authorization must be matched to the exact current Context and operation;
  `created_by` or an earlier case's budget cannot be used as implied consent.
- **A newer Analysis may exist without becoming the selected main case**: an
  explicit page action created an all-Runs Analysis and started source fetching
  while Runs 4/5/6 remained the declared main input. Preserve both histories,
  but never infer current ownership from creation time or reuse source output
  across their different Context/Manifest identities.
- **The authorized Runs 4/5/6 Answer result is reviewable, not yet reviewed**:
  Diagnosis `b0a35004-3c12-46f1-af49-76c903031c6f` has three admitted answers,
  three option events requiring explicit decisions and one legal zero-event
  answer. Evidence must not consume the event Reasons until the exact Review is
  appended, and the empty Truth snapshot must remain `UNRESOLVED`.
- **Local LLM cost audit currently retains total tokens, not billing splits**:
  the three Answer cache rows retain 7441 total tokens but not separate input,
  cache-hit and output token counts. Cost can therefore be reported only as a
  conservative upper estimate unless the provider bill is inspected. Never
  label that estimate as an actual deduction. Before Evidence, fix a request
  envelope from the exact reviewed Reasons and completed sources and retain the
  actual usage returned by each call.
- **Source refresh state must never own manual mutation loading**: the release
  UI previously reused one loading flag for background polling, manual content,
  waiver and completion actions. This made settled pages appear stuck and could
  encourage duplicate clicks. Refresh and mutation state are now separate;
  retain the zero-loading-button production render check when changing source
  polling or action concurrency.
- **Pasted HTML is input material, not evidence content**: manual HTML source is
  accepted only through the established primary-content extractor and V2
  content Gate. `SUSPECT`/`EMPTY` output stays unresolved, partial output cannot
  claim `FULL_PAGE`, and only the extracted clean text is frozen. Do not bypass
  this path by storing markup as a passage or by treating extraction success as
  evidence sufficiency.
- **Transient toast is not sufficient feedback for source disposition**: a
  manual HTML submission can legitimately receive 422 from the content Gate.
  The outcome and exact reason must remain visible in the source workspace;
  otherwise a correct rejection is indistinguishable from a dead button. Keep
  both success-after-filter-removal and row-local rejection feedback covered by
  frontend acceptance.
- **Product Truth writes and diagnosis Truth snapshots have different
  lifecycles**: the release UI now supports explicit target-brand fact entry,
  but an existing DiagnosisResult remains bound to its original Truth-set hash.
  Operators must explicitly create and review a Truth reprojection before
  Strategy can consume the new fact. The reprojection copies exact Answer and
  Evidence results without recomputing them, records the exact prior Review and
  does not inherit its approval automatically. Never mutate the old result or
  treat a saved project fact as an already confirmed applicability relation.
- **External capability signals are not competitor Product Truth**: competitor
  Reasons and Market Criteria may trigger target-brand fact verification and may
  carry a bounded target-applicability match. They cannot prove the competitor's
  capability, cannot write a target fact, and cannot become a direct cross-brand
  Reason-to-Truth coverage row. Preserve source subject, grounded text and this
  boundary in future Strategy changes. Legacy empty-Truth rows must also be
  classified from their grounded subject; `truth_id=null` is not permission to
  display an external subject as a target-brand relation. When the same Run and
  grounded reason already belong to a target-brand recommendation, the external
  entity is a co-recommended option rather than a new target capability gap; it
  must not duplicate fact review or Strategy applicability.
- **Existing composite target facts are not automatically publishable**: the
  current release database contains previously entered statements that combine
  multiple capabilities or remain UNKNOWN. Current projection marks these
  `VERIFY_FIRST`; do not split them automatically, infer supported fragments or
  let historical review status bypass the statement eligibility Gate.
- **Reason Evidence is not whole-answer Citation Contribution**: Result
  `diag-v2:5435e5989f2a7c2f` evaluates a bounded Reason-to-Claim plan and remains
  `REASON_EVIDENCE_BASELINE`. Do not infer full-answer coverage, citation
  disposition coverage, answer anchors, or generation influence from it.
- **P1 is intentionally one Run**: Run 1 was chosen by a frozen technical rule,
  not by semantic outcome. P1 must produce all-citation disposition and a real
  calibration baseline before any nine-Run expansion. Fixture success or a
  planned-but-unauthorized external call is not a completed P1.
- **Content correspondence is not causal attribution**: even a direct textual
  reuse does not prove that the model consumed a cited page. Keep
  `answer_anchor` and `generation_influence` independent and conservative.
