# 07 Decision Log

Status: ACTIVE

## 2026-08-05

- Decision: P0 priority is optimization loop, not broad daily trend dashboard.
- Decision: Use additive SQLAlchemy models and current SQLite startup sync for
  Alpha tables.
- Decision: Keep success definitions strict; `partial_success` stays distinct.
- Decision: Store experiment conclusion separately from computed metric deltas.
- Decision: Frontend implementation stays inside the existing single-page
  `App.tsx` structure for now to avoid a routing refactor.
- Decision: first real experiment primary metric is now
  `target_page_retrieval_rate`; `0 / valid_run_count = 0%` is a valid baseline
  when the target page has never entered retrieval candidates.
- Decision: `target_page_conversion_rate` remains the second-stage funnel
  metric and is `not_applicable` while `retrieved_count = 0`.
- Decision: first real experiment is `Prompt 19 目标页面检索进入实验`, targeting
  `https://www.aifabu.com/card` with baseline Runs `135-146`.
- Decision: new Action content-feature changes must be structured objects;
  legacy string lists are read only for compatibility.
- Decision: new human conclusions use uppercase enum values only.
- Decision: planned release and real confirmed publication are separate states;
  only `RELEASE_CONFIRMED` may start cooling.

## Earlier Context

- Wenxin browser audit is the current real-data path.
- Prompt business semantics remain: one Prompt is one question.
- Run labels should remain user-readable as `run#` and `Sample`.
