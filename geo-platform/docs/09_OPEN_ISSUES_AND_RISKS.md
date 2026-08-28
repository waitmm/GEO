# 09 Open Issues And Risks

Status: ACTIVE

## Single Prompt V1 Known Pitfalls

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
- User-facing workflow labels, empty states, and action buttons must be Chinese.
  English enums may remain in storage/API internals only when Chinese labels are
  also provided to the frontend.
- If a main-chain button opens the wrong module or a standalone module is added
  instead of being integrated into the single Prompt workflow, treat it as a
  product navigation bug rather than a cosmetic issue.

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
