# 09 Open Issues And Risks

Status: ACTIVE

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
