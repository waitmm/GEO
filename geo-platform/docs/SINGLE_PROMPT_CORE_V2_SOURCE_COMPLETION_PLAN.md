# Single-Prompt Core V2 - Source Completion First Remediation Plan

Status: `SUPERSEDED_IN_PART_BY_R3 / IMPLEMENTATION_IN_PROGRESS`
Date: 2026-09-20
Classification: `SEMANTIC_CHANGE / PRODUCT_OWNER_APPROVED`
Implementation: `FIRST_SLICE_IN_PROGRESS`
Production cutover: `AUTHORIZED_FOR_SOURCE_COMPLETION_AND_EVIDENCE_GATE_ONLY`

> 2026-09-20 R3 override: Citation Manifest 冻结后，Source Preparation 与
> Answer Semantic 可以独立推进；Evidence 才要求 Source Completion Manifest、
> 精确 Answer ResultVersion 和精确 Review 汇合。本文早期“Answer 必须等待全部
> 来源处置”的表述已被覆盖。正式执行契约见
> `GEO_1_0_R3_EXECUTION_CONTRACT.md`。

## 产品负责人审批摘要

### 这次纠正什么

现有第二段文档本来写的是：

```text
冻结 AnalysisContext
-> 冻结引用正文 SourceSnapshot
-> 识别回答推荐语义
-> 判断引用证据关系
```

实际代码却是：

```text
回答语义
-> 引用正文
-> 证据关系
```

页面还把三类外部操作合成一个“开始诊断”按钮。结果就是 #40 已经完成人工回答语义审核，但 35 个唯一引用
仍然全部未抓取，passage、SourceClaim 和有效 Alignment 都是 0。当前不能继续生成策略。

### 拟审批的正确业务顺序

| 顺序 | 用户看到的阶段 | 系统工作 | 人工动作 | 完成条件 |
| --- | --- | --- | --- | --- |
| 1 | 采样 | 创建固定 Run、采集回答和引用 | 显式启动采样 | Raw Result 和 Context 冻结 |
| 2 | 引用资料清单 | 从固定回答汇总引用、按 URL 去重并保留 Run lineage | 核对 35 个来源范围 | 来源集合及 hash 固定 |
| 3 | 引用正文补齐 | 先复用兼容快照，再按授权抓取、解析正文和 passage | 对抓不到的同一 URL 补正文，或明确放弃 | 每个来源为 READY 或 WAIVED，数量守恒 |
| 4 | 回答语义识别 | 对固定回答识别候选、推荐、理由和市场标准 | 只审核高影响歧义 | 精确 Answer 结果和 Review 冻结 |
| 5 | 引用证据判断 | Reason + passage 先确定性召回，再增量做 SourceClaim/Alignment | 审核关键关系 | 失败、未召回、未评估、零 Claim、无支持分开 |
| 6 | 品牌事实与诊断 | 将目标品牌 Truth 与 Reason/证据按边界核对 | 补充或确认目标品牌自身事实 | 未知仍可保留，不能借竞品推出事实 |
| 7 | 策略 | 只从合格部分生成方向 | 确认策略 | 无官网兜底、无 Benchmark 渠道自动升级 |
| 8 | 执行及后续 | 执行骨架、确认、人工发布、复测 | 每一步显式操作 | 沿用现有 V2 精确版本链 |

这里“引用正文先行”指先完成抓取、人工补充、解析和不可变快照，不是先把所有 passage 全量送给 LLM。
SourceClaim/Alignment 必须等回答 Reason 已确定后再按候选裁剪执行，避免重新出现笛卡尔积和无效 token 消耗。

### 来源完成的硬规则

1. 自动抓取失败不能写成空正文成功，也不能写成“没有证据”。
2. 人工只能补充固定引用清单中同一 URL 的正文，不能把新网页伪装成原回答引用。
3. 抓不到时允许用户明确放弃，但必须永久保留 `WAIVED_WITH_LIMITATION`。
4. 所有来源必须逐条落入 READY 或 WAIVED 后，才能冻结 Source Completion Manifest。
5. 未授权、抓取中、可重试、等待人工补充都不是完成状态。
6. 普通 GET、刷新和轮询不能触发抓取、LLM 或业务写入。
7. 网页抓取、Answer LLM、SourceClaim LLM、Alignment LLM 是四种独立授权，不能互相扩大。

### 计划分五个开发阶段

| 阶段 | 只交付什么 | 本阶段不做什么 | 阶段验收后停止点 |
| --- | --- | --- | --- |
| Phase 1 | Analysis 归属的来源准备身份、引用清单、状态守恒、自动复用/抓取、Manifest | 不跑 Answer/证据 LLM | 先审后端对象、API 和迁移 |
| Phase 2 | 来源补齐页面、同源正文人工提交、校验、放弃、409 版本保护 | 不改变 Answer 语义 | 本地无外部调用走查页面 |
| Phase 3 | Source Manifest 成为 Answer 的后端硬 Gate；拆开授权 | 不跑 SourceClaim/Alignment | 合成全链回归后停止 |
| Phase 4 | 精确 Answer Result + Review + Manifest 继续证据计算；生成子结果版本 | 不自动生成 Strategy | 完成证据审核视图后停止 |
| Phase 5 | 经单独授权，用真实 #40 完成 35 来源和证据验收 | 不预设必须产生策略 | 提交真实验收报告后停止 |

### 当前 #40 怎么继续

现有 Answer 结果和人工审核保持不变，不要求用户重做：

```text
现有 Analysis/Context/Raw Result
-> 新建 SourcePreparation
-> 完成固定 35 来源
-> 冻结 Manifest
-> 从现有 ResultVersion + Review 继续 Evidence
-> 产生新的不可变子 ResultVersion
```

禁止重新采样、重跑三条 Answer、查询 latest、手工 SQL 补状态或直接跳到 Strategy。

### 本次需要审批的五项

1. 新 V2 Analysis 必须先完成来源处置，再启动 Answer Semantic。
2. Source Manifest 只有 `READY_*` 和显式 `WAIVED_WITH_LIMITATION` 可以作为终态。
3. 人工正文仅补固定引用清单中的同一来源；额外调研来源以后单独设计。
4. 当前 #40 复用精确的已审核 Answer，通过通用 Evidence continuation 继续，不重跑 Answer。
5. 按 Phase 1-5 逐段开发、逐段验收，不一次性把全部改动切入生产。

本摘要和后文都只是待审批计划。审批前不改代码、不建 migration、不抓网页、不调用 LLM。

## 1. Purpose

This document is the proposed repair plan for the V2 workflow after collection.
It is intentionally a plan, not an implementation record.

The product rule proposed for approval is:

> After a sampling result is frozen, the first business operation is to inventory
> the citations actually observed in those Runs and complete an explicit content
> disposition for every unique source. The system fetches and reuses content first;
> sources it cannot complete are presented for human supplementation or explicit
> waiver. Answer semantics and evidence diagnosis cannot silently bypass this gate.

This does not modify the frozen V1 Steps 1-8. It repairs the isolated
Single-Prompt Core V2 path and restores the order already stated in
`SINGLE_PROMPT_CORE_V2_SECOND_SLICE.md`:

```text
exact AnalysisContext
-> immutable SourceSnapshot set
-> recommendation event/reason diagnosis
-> citation diagnosis
```

Because it changes the visible V2 workflow order, API handoff and primary status
source, Product Owner review is required before implementation.

## 2. What Is Wrong Today

### 2.1 Contract and implementation diverged

The second-slice document places the immutable SourceSnapshot set before Answer
Semantic. The current implementation does the opposite:

```text
compute_diagnosis()
-> ANSWER_SEMANTIC
-> SOURCE_SNAPSHOT
-> EVIDENCE_DIAGNOSIS
```

The frontend exposes one `开始诊断` action. It does not ask the user to inspect
the reference inventory, authorize source fetch, supplement failed content or
finalize a source manifest first.

The request defaults are also unsafe for a staged product flow:

```text
source_snapshot_policy = REUSE_OR_FETCH
evidence_llm_policy = ALLOW_EXTERNAL
```

This means one opaque operation can combine Answer Semantic, page fetching,
SourceClaim and Alignment unless a caller knows to override the defaults.

### 2.2 The missing product capability is not just a button

Existing V2 code has an immutable `SinglePromptSourceSnapshot`, fetching,
content hashing, passage splitting and a challenge-page gate. It does not have:

- a pre-diagnosis source preparation execution owned by the exact Analysis;
- a complete, conserved source disposition manifest;
- a V2 manual-content path bound to the exact observed source URL;
- a hard backend gate before Answer Semantic;
- a reviewed Answer -> Evidence continuation that avoids rerunning Answer;
- separate source-fetch, Answer LLM, SourceClaim LLM and Alignment LLM grants;
- a user-visible source completion step with explicit failures and limitations.

### 2.3 Why this survived earlier development

The failure is procedural as well as technical:

1. Slice delivery was reported from module and fixture coverage, not from a
   prerequisite-complete real workflow.
2. #44 reused historical snapshots, which hid the absence of a manual source
   completion path.
3. #40 ran `REUSE_ONLY`, so all 35 sources remained not fetched while Answer
   Semantic and its review still advanced.
4. Tests checked Answer, SourceSnapshot and Evidence components, but did not
   assert that the product blocks Answer until source disposition is complete.
5. The UI grouped multiple externally active stages under one diagnosis action.
6. Documentation marked Slice 2 as delivered without separately reporting the
   source-first production gate and real evidence completion status.

The repair must therefore include contracts, backend gates, UI ordering and
end-to-end acceptance. Adding manual paste alone would not fix the workflow.

## 3. Current Real #40 Baseline

The following values were read from the formal V2 API on 2026-09-16. They are
the fixed real acceptance baseline, not general business rules:

```text
Project = 3
Prompt = 40
Analysis = ecb4ff1a-fbc7-4aa4-93cc-ed8172ffa811
Context = ctx-807c3737-2ee3-42d4-87a8-cb466755555f
Raw Result = raw-v1:79ea2aca2cb58ca4

Diagnosis = bd154212-9291-42ab-8966-b981136e10f0
ResultVersion = diag-v1:dbbbd68addd737f9
Review = review-52312343-ec21-4214-94ae-20368eca5e86

valid Runs = 3
reference observations = 77
unique source identities = 35
content ready = 0
not fetched = 35
actual fetch failures = 0
passages = 0
SourceClaims = 0
Alignment evaluated = 0
Alignment not evaluated = 770
anchors = UNPROVEN
```

The 13 held Answer events were all reviewed as
`CONFIRM_INCLUDE_AS_OPTION`. That review confirms only the local answer speech
act. It does not confirm source content, Product Truth, citation binding or
channel effectiveness.

The next valid business operation for this case is source completion. It is not
Strategy generation and it is not another Answer Semantic replay.

## 4. Correct V2 Product Flow

### 4.1 Top-level sequence

```text
0. Configure Project / Prompt / sampling plan
1. Create Analysis and planned Run identities
2. Collect Runs
3. Freeze Raw Result and AnalysisContext
4. Build exact reference inventory
5. Complete source content
6. Freeze Source Completion Manifest
7. Extract and review Answer Semantic
8. Build candidates and evaluate SourceClaim / Alignment
9. Review target-brand Truth relationships and diagnosis
10. Generate and review Strategy
11. Generate and confirm execution skeleton
12. Record user-reported publication
13. Retest and descriptive comparison
```

Steps 4-6 are the first operation after collection. They prepare evidence input;
they do not themselves assert that a source supports a Reason.

### 4.2 Why SourceClaim and Alignment are not run before Answer Semantic

Source content can and should be fetched, frozen, parsed and split before Answer
Semantic. SourceClaim/Alignment should not be run over every passage at that
point because candidate scope depends on admitted and reviewed Reasons.

The intended order inside evidence processing is:

```text
frozen source passages
+ reviewed Answer Reasons
-> deterministic candidate recall
-> SourceClaim only for recalled/missing passages
-> Alignment only for eligible pairs
```

This preserves the source-first business flow while avoiding an expensive
SourceClaim run over irrelevant passages.

## 5. Source Completion Contract

### 5.1 Exact source scope

The required set is derived only from Reference observations in the frozen Raw
Result. Deduplication uses the versioned URL identity contract while preserving:

- every observed original URL;
- Reference IDs, Run IDs and reference positions;
- titles and domains as observed;
- occurrence count;
- canonicalization version and source key.

The user cannot edit an observed URL into a different source. A new research URL
is a supplemental research source, not an observed citation. Supplemental
research is outside this remediation.

### 5.2 Mutually exclusive source states

Every required source must have exactly one current disposition:

```text
NOT_STARTED
NOT_AUTHORIZED
FETCHING
FETCH_FAILED_RETRYABLE
AWAITING_MANUAL_CONTENT
MANUAL_CONTENT_PENDING_VALIDATION
READY_REUSED
READY_FETCHED
READY_MANUAL
CONTENT_BLOCKED
FETCH_FAILED_FINAL
WAIVED_WITH_LIMITATION
```

Meanings:

- `READY_REUSED`: a compatible immutable content snapshot was reused.
- `READY_FETCHED`: the authorized fetch produced valid immutable content.
- `READY_MANUAL`: manually supplied content passed identity/content validation.
- `CONTENT_BLOCKED`: fetched or supplied content is a verification/interstitial
  page and cannot enter evidence.
- `FETCH_FAILED_FINAL`: the authorized fetch exhausted its declared retry scope.
- `WAIVED_WITH_LIMITATION`: the user explicitly chose to continue without this
  source; the limitation remains in every downstream result.
- `NOT_AUTHORIZED`, retryable and manual-pending states are not terminal and
  cannot be hidden as failures or empty success.

`CONTENT_BLOCKED` and `FETCH_FAILED_FINAL` should normally offer manual
supplementation. They become final manifest dispositions only after the user
either supplies valid content or explicitly waives the source.

### 5.3 Conservation equation

The backend must publish a non-overlapping equation:

```text
required_unique_sources
= ready_reused
 + ready_fetched
 + ready_manual
 + waived_with_limitation
 + nonterminal_not_started
 + nonterminal_not_authorized
 + nonterminal_fetching
 + nonterminal_retryable
 + nonterminal_manual_required
 + nonterminal_manual_validation
```

Challenge pages and final fetch failures remain visible diagnostic reasons for
the corresponding nonterminal/manual-required or waived disposition. No source
may disappear into an unexplained delta.

### 5.4 Completion gate

`SOURCE_SCOPE_DISPOSITION_COMPLETE` is true only when:

```text
1. the required source set matches the frozen Raw Result;
2. no fetch or validation task can still mutate the set;
3. every source is READY_* or WAIVED_WITH_LIMITATION;
4. all READY_* snapshots have immutable content/passages and hashes;
5. manifest counts conserve exactly;
6. the manifest has an immutable version and hash.
```

The gate means every source has an explicit outcome. It does not claim every
source was successfully retrieved.

Answer Semantic cannot start before this gate on new V2 Analyses. A manifest
with zero consumable sources may proceed only if every source was explicitly
waived; downstream Evidence then remains unavailable and cannot generate a
positive or negative conclusion.

## 6. Manual Source Supplementation

### 6.1 Allowed operation

Manual supplementation is bound to one exact source identity from the frozen
reference inventory. Required input:

```text
source_key
canonical_url and observed URL (read-only)
manual clean text or supported text artifact
source title (optional correction, preserved as user supplied)
source access date/time if known
submitted_by
submission note
base source-manifest version/hash
```

The backend records the submitted artifact, computes its SHA-256, runs the same
content quality gate, parses passages with a versioned parser and creates a new
immutable snapshot. Manual content never mutates a prior fetch snapshot.

### 6.2 Validation

The minimum deterministic checks are:

- exact Project/Analysis/Context/source ownership;
- stale manifest rejection with HTTP 409;
- non-empty text and bounded size/type;
- challenge/interstitial-page rejection;
- stable content and passage hashes;
- no cross-source or cross-project snapshot reuse without compatible identity;
- no silent URL replacement;
- audit of submitter, time, source and processing version.

Manual submission proves what content the operator supplied for that URL. It
does not prove that the live page currently contains it, that the answer used
it, or that its claims are true.

### 6.3 User waiver

When content cannot be obtained, the user may explicitly select
`WAIVED_WITH_LIMITATION` and provide a reason. Waiver:

- does not create empty passages or zero Claims;
- does not turn relations into `NO_SUPPORT`;
- remains in Diagnosis, Strategy and later measurement limitations;
- can be superseded only by a new manifest version with valid content.

## 7. Minimum Identity and Persistence Design

The implementation should add only the minimum V2-owned identities:

```text
SourcePreparationExecution
-> immutable SourceCompletionManifest version
-> immutable SourceSnapshot entries
```

Logical objects do not require one table each, but their identities and hashes
must be explicit.

Recommended mapping for implementation review:

1. Add an Analysis-owned source preparation execution with idempotency,
   authorization, attempt and progress fields.
2. Make new SourceSnapshots owned by that exact preparation/Analysis rather
   than by a Diagnosis that has not started yet.
3. Preserve existing diagnosis-owned snapshots as immutable history. Do not
   rewrite or migrate them automatically.
4. Persist one immutable manifest payload/hash containing the required source
   set, every terminal disposition and all consumed snapshot IDs/hashes.
5. Require Diagnosis/Evidence inputs to reference the exact manifest ID/hash.

The migration design must prevent a snapshot from having ambiguous ownership.
It must not use `latest snapshot`, timestamp-nearest or max-ID matching.

## 8. Execution and API Plan

Exact route naming may follow existing V2 conventions, but the capabilities and
gates are fixed for implementation review.

### 8.1 Source preparation

```text
POST /analyses/{analysis_id}/source-preparations
GET  /analyses/{analysis_id}/source-preparations/{preparation_id}
POST /.../{preparation_id}/fetch
POST /.../{preparation_id}/sources/{source_key}/retry
POST /.../{preparation_id}/sources/{source_key}/manual-content
POST /.../{preparation_id}/sources/{source_key}/waive
POST /.../{preparation_id}/finalize
```

Creation freezes the reference inventory. Fetch is a separate authorized
operation. GET and polling are read-only.

### 8.2 Answer Semantic

The existing Diagnosis start must be narrowed or wrapped so it requires:

```text
analysis_id/context_id/raw hash
source_manifest_id/hash
explicit Answer LLM policy and budget
idempotency key
```

It must not implicitly authorize source fetch, SourceClaim or Alignment. New V2
requests should default every external operation to disabled/cache-only until
the user explicitly starts that stage.

### 8.3 Evidence continuation

Add one formal continuation that consumes:

```text
exact DiagnosisResultVersion/hash
exact DiagnosisReview ID/snapshot hash
exact SourceCompletionManifest ID/hash
SourceClaim policy/budget
Alignment policy/budget
idempotency key
```

It creates a new immutable child ResultVersion. It reuses the reviewed Answer
objects by exact identity and must not rerun Answer Semantic or inherit a review
from a different result.

The continuation records candidate/non-candidate, cache hit, zero Claim,
SourceClaim failure, Alignment result/failure and every upstream limitation.

### 8.4 Separate authorization categories

The UI and API must never collapse these grants:

```text
A. source page fetch
B. Answer Semantic LLM
C. SourceClaim passage LLM
D. Alignment pair LLM
```

Each grant records exact inputs, provider, maximum calls/retries and permitted
payload. Exhaustion stops the affected stage without widening scope.

## 9. Frontend Plan

The V2 page should show the following sequence after Raw Result freeze:

### Step A - Reference inventory

- 77 observations / 35 unique sources for the current #40 fixture;
- observed title, URL, domain, Runs, positions and occurrence count;
- no content claim yet.

### Step B - Source content completion

- buttons for authorized automatic fetch and selected retry;
- one row per unique source with immutable status;
- manual content action for blocked/failed sources;
- explicit waiver with persistent warning;
- counts for ready, waiting for user, retryable, blocked and waived;
- exact conservation and manifest version/hash.

The primary action remains disabled while the manifest has nonterminal entries.
The UI explains exactly which sources require action.

### Step C - Answer Semantic

- explicit provider/call scope;
- no source fetch or evidence LLM side effect;
- event and market-criteria review as currently implemented.

### Step D - Evidence relation

- available only after exact Answer review and source manifest completion;
- shows candidate recall before LLM execution;
- SourceClaim and Alignment authorization/cost scope separately;
- failed, not recalled, not evaluated, zero Claim and no support remain distinct.

### Step E onward

Truth relation, diagnosis review, Strategy, execution, publication and Retest
continue to consume exact immutable upstream versions. They cannot infer
readiness from frontend text or a generic `REVIEW_COMPLETED` flag.

The current single `开始诊断` action must be retired for new V2 analyses after
cutover. Existing historical results remain viewable.

## 10. Current #40 Continuation Without Repeating Work

The current #40 chain is historical because Answer Semantic and review happened
before source completion. It must not be rewritten.

After the new source path is approved and implemented:

1. Create SourcePreparation for the exact existing Analysis/Context/Raw hash.
2. Build the same fixed 35-source inventory; do not query latest references.
3. Fetch/reuse sources only under a new explicit authorization.
4. Present unsuccessful sources for manual supplementation or explicit waiver.
5. Finalize an immutable manifest.
6. Start Evidence continuation from the exact existing ResultVersion and Review.
7. Do not rerun the three Answers or ask the user to repeat event review.
8. Publish a child Diagnosis ResultVersion with evidence results and inherited
   limitations explicitly referenced, not silently copied.

This is a generic exact-version continuation path. It must not hardcode Prompt
40, Project 3 or the expected source count.

## 11. Delivery Plan and Stop Gates

### Phase 0 - Product approval

Deliverables:

- this reviewed plan;
- agreed source states and completion semantics;
- agreed manual supplementation/waiver boundary;
- approval of the V2 user-visible order.

Stop gate: no code or migration before explicit approval.

### Phase 1 - Source preparation backend

Deliverables:

- minimum migration and Analysis-owned preparation identity;
- frozen reference inventory;
- source state conservation;
- automatic reuse/fetch with explicit authorization;
- immutable SourceSnapshots and manifest;
- no Answer or Evidence execution.

Acceptance:

- fixed input never uses latest;
- GET has no writes/fetches;
- all counts conserve;
- challenge, retryable and unauthorized are not empty success;
- existing diagnosis/source history remains unchanged.

Stop for Product Owner/API review before frontend cutover.

### Phase 2 - Manual source completion and page

Deliverables:

- source inventory/completion page;
- manual same-source content submission;
- validation, versioning and stale-write rejection;
- explicit waiver and permanent limitation;
- exact progress and allowed actions from backend.

Acceptance:

- a blocked source can become `READY_MANUAL` only through a validated new
  snapshot;
- a new URL cannot masquerade as an observed citation;
- unresolved rows prevent manifest finalization;
- internal errors are visible and do not spin indefinitely.

Stop for real local UI walkthrough with no external fetch.

### Phase 3 - Source-first Answer Gate

Deliverables:

- Diagnosis requires the exact finalized source manifest;
- Answer LLM authorization is separate;
- the old bundled defaults are removed from the new product path;
- existing historical diagnosis pages remain read-only compatible.

Acceptance:

- Answer cannot start with `NOT_AUTHORIZED` or manual-pending sources;
- Answer start triggers no fetch, SourceClaim or Alignment;
- legal all-waived manifest retains evidence-unavailable limitation;
- V1 behavior is unchanged.

Stop for synthetic end-to-end regression.

### Phase 4 - Reviewed Answer to Evidence continuation

Deliverables:

- exact ResultVersion + Review + manifest continuation;
- deterministic candidate recall;
- lookup-first SourceClaim and Alignment;
- separate external budgets;
- immutable child Diagnosis ResultVersion;
- evidence review view.

Acceptance:

- no Answer rerun;
- no review carry-forward from a different version;
- no Cartesian-product LLM execution;
- not recalled/not evaluated/failure/zero Claim/no support remain distinct;
- anchor remains UNPROVEN without answer citation binding.

Stop before Strategy. No automatic downstream generation.

### Phase 5 - Authorized real #40 acceptance

This phase requires separate user grants for page fetching and LLM passage/pair
processing. Development authorization is not external-operation authorization.

Acceptance report must include:

- 35-source conservation;
- automatic ready/reused/failed counts;
- manual/waived sources and reasons;
- frozen manifest ID/hash;
- exact reviewed Answer handoff;
- recalled passage and SourceClaim counts;
- Alignment evaluated/not-evaluated/failure counts;
- external calls, cache hits, tokens and unknown costs;
- all unresolved anchors, Truth relationships and sampling limitations.

No expected Strategy or positive effect is predeclared.

## 12. Test Matrix

### Source identity and content

- duplicate observed URLs consolidate without losing Run lineage;
- canonicalization version is frozen;
- content hash and passage hash are immutable;
- reused snapshot must match source identity and parser/content contract;
- challenge pages cannot become ready;
- failed fetch is not zero content;
- manual content belongs to the exact source and Project;
- manual artifact creates a new snapshot, never overwrites one;
- unsupported URL replacement is rejected;
- source counts conserve in every state.

### Workflow and authorization

- source manifest is required before Answer;
- every external stage is denied by default;
- GET, refresh and polling produce zero business writes/calls;
- source authorization cannot authorize Answer or evidence LLM;
- Answer authorization cannot authorize fetch/SourceClaim/Alignment;
- retries respect the exact source/job and declared budget;
- duplicate POSTs are idempotent;
- stale manifest/result/review writes return 409.

### Semantic consumption

- Answer consumes only fixed Runs;
- evidence consumes only reviewed eligible Reasons;
- market criteria do not become brand Reasons;
- waived/failed source does not become `NO_SUPPORT`;
- legal zero Claim remains a successful empty extraction;
- SourceClaim never becomes Product Truth;
- SUPPORTS never upgrades an UNPROVEN anchor;
- cross-subject Truth suggestions remain UNRESOLVED without explicit review;
- partial or unknown Truth cannot enter public claims.

### Compatibility

- old immutable #44/#40 results and reviews do not change;
- V1 APIs and Steps 1-8 remain unchanged;
- no latest Package/Candidate/Truth fallback;
- no historical review is copied by cache/materialization;
- existing source caches are recovery inputs only after current validation.

## 13. Documentation Corrections Required With Implementation

On approval and at each implementation checkpoint, update:

- `00_PROJECT_BRIEF.md`: distinguish code slices from real source-first E2E
  readiness;
- `SINGLE_PROMPT_CORE_V2_SECOND_SLICE.md`: record the enforced source-first
  gate and exact handoffs;
- `SINGLE_PROMPT_CORE_V2_REAL_E2E_ACCEPTANCE.md`: keep the real #40 status;
- `08_DEVELOPMENT_LOG.md`: modules, migration, tests and data impact;
- `09_PRODUCT_ITERATION_LOG.md`: visible workflow and gate changes;
- `09_OPEN_ISSUES_AND_RISKS.md`: close only after real acceptance;
- `../产品纲要.md`: update the V2 user flow only after cutover approval.

No document may say the evidence diagnosis is production-complete merely
because fixture tests pass or Answer Semantic succeeded.

## 14. Explicit Non-Goals

- no V1 main-chain redesign;
- no Runtime RFC or generic 16-stage engine;
- no Agent;
- no multi-Prompt aggregation;
- no arbitrary supplemental web research in the observed-citation set;
- no automatic Product Truth creation;
- no automatic review or Strategy generation;
- no article generation, publication or Retest in this remediation;
- no real external fetch/LLM call without a separate exact authorization.

## 15. Approval Questions

Implementation should begin only after the Product Owner confirms:

1. Source disposition completion is a hard prerequisite before Answer Semantic
   for new V2 Analyses.
2. `READY_*` or explicit `WAIVED_WITH_LIMITATION` are the only terminal manifest
   outcomes.
3. Manual content may supplement only an already observed exact source; new
   research sources remain separate.
4. Current #40 should reuse its exact reviewed Answer result and proceed through
   a generic Evidence continuation after source completion, without rerunning
   Answer Semantic.
5. The five implementation phases and stop gates above are approved in order.

Until approval, the repository state is:

```text
Plan = DRAFT_FOR_PRODUCT_OWNER_REVIEW
Code change = 0
Migration = 0
External operation = 0
Current #40 next stage = BLOCKED_BY_SOURCE_COMPLETION_PATH
```
