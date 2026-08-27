# 09 Open Issues And Risks

Status: ACTIVE

## Single Prompt V1 Known Pitfalls

- Step 7 must be shown as `策略确认`, not `推荐动作`. The underlying legacy
  workflow key may remain `action` for compatibility, but user-facing state must
  be derived from current Evidence-Package-scoped StrategyCandidate review
  status whenever available.
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
- Benchmark channel is not execution channel. A Primary Benchmark from Zhihu
  must not automatically mean "publish on Zhihu"; channel selection belongs to
  Step 8.
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
