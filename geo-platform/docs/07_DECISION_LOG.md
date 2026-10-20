# 07 Decision Log

Status: ACTIVE

## 2026-10-20 Internal Beta Product Convergence

- M1 is the 爱短链 internal Beta: employees use the existing Monitor and isolated
  Evidence Pack Optimize lane to obtain diagnosis, strategy, complete copy and QA,
  then copy/export and append feedback to an exact result version.
- M1 ships for employee trial before M2 begins. M2 must onboard 八木屋 through the
  same project, brand, Prompt and data configuration, without brand-specific core code.
  M3 generalization follows evidence from both internal teams.
- A desired brand association is optimization intent, never Product Truth. User-supplied
  brand context remains independently unverified until the existing Truth and evidence
  qualification rules admit a public claim.
- Saved historical model results and new generation are distinct product states. Reading
  a saved result cannot be shown as a newly successful task.
- Old experiment budget is not daily-use authorization. Daily model calls require an
  explicit deployment authorization and remain fail-closed by default.
- Evidence Pack remains an isolated experimental result namespace. This decision does not
  replace formal V2 or authorize production deployment, publishing or a semantic cutover.

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
