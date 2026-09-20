# Single-Prompt Core V2 Real E2E Acceptance

Status: `BASELINE_CAPTURED / ANSWER_SEMANTIC_REVIEW_COMPLETED / SOURCE_COMPLETION_BLOCKED`

## Current Acceptance Stop (2026-09-16)

The latest formal API state is:

```text
Diagnosis = bd154212-9291-42ab-8966-b981136e10f0
ResultVersion = diag-v1:dbbbd68addd737f9
Review = review-52312343-ec21-4214-94ae-20368eca5e86

Answer admission = 3/3
held events reviewed = 13/13 CONFIRM_INCLUDE_AS_OPTION
reference observations = 77
unique sources = 35
content ready = 0
not fetched = 35
passages = 0
SourceClaims = 0
Alignment evaluated = 0
Alignment not evaluated = 770
```

The review confirms only the local `INCLUDE_AS_OPTION` speech acts. It does not
confirm source evidence, Product Truth or citation binding. The real case is now
blocked by the missing source-first completion path. It must not proceed to
Strategy, and it must not rerun Answer Semantic merely to fetch sources.

The proposed next implementation is documented in
`SINGLE_PROMPT_CORE_V2_SOURCE_COMPLETION_PLAN.md`: complete the exact 35-source
scope, freeze a manifest, then continue Evidence from this exact reviewed result.
The plan is awaiting Product Owner approval and has not initiated source fetch,
page-content LLM calls or business writes.

## Fixed Case

```text
Project = 3
Prompt = 40
Prompt text = 长链接缩短
Analysis = ecb4ff1a-fbc7-4aa4-93cc-ed8172ffa811
Task = 53
Sampling plan hash = f810f0f4e146dc0b55a12c3871920377bca312de9a1084e3acd83345482078c2
Context = ctx-807c3737-2ee3-42d4-87a8-cb466755555f
Raw result = raw-v1:79ea2aca2cb58ca4
Raw output SHA-256 = 79ea2aca2cb58ca4f300bf8c9ada017e2b875157d70eee76b46bd4b78ae0353c
Run scope SHA-256 = 2d029eb8189db743957cc84f70beb50956463edb9f022a1e06d25240ee94da6c
```

The Analysis was created by the production V2 API. It did not reuse an old
answer and did not create a Diagnosis, Strategy or Retest.

## Baseline Runs

| Run | Status | Retry | Answer SHA-256 | Characters | References |
| --- | --- | ---: | --- | ---: | ---: |
| 260 | success | 0 | `2062fb69cbc385dbd54df518ae079d75fec43b0e9ca06095923a9ddfee2f8d2d` | 1653 | 24 |
| 261 | success | 0 | `2778e2df7da35f93969e00c8fa32e6693e49a9531ede00e118f32a5a39f4f834` | 1800 | 26 |
| 262 | success | 0 | `89984d12122d5b7c53750923c8f65b6fe4eac5f19de9124343cca7ee55304345` | 1725 | 27 |

All three submitted `original_query`, `page_query` and `retrieval_query` values
are exactly `长链接缩短`. The immutable Context is the exact answer scope for a
future Answer Semantic authorization.

## Session Evidence

The frozen plan requested `single_independent`. Each Run has a different local
collector conversation UUID, and each captured page HTML contains exactly one
`conversation-flow-question-container` for the current question. This is useful
case evidence that no prior answer turn was appended in these three captures.

It is not formal independent-session proof. The collector recorded:

```text
actual collection_mode = single_continuous
sampling_mode = UNKNOWN
independent-session proof = UNAVAILABLE
model revision = unavailable
```

Retrieval candidates are also unavailable. Neither limitation is a zero result.

## Frozen Reference URL Scope

The 77 reference observations resolve to 35 canonical URL identities:

```text
http://m.article.atlantisoul.com/hytnews/0905/7403_1773.htm
http://m.article.lianjuyunshang.cn/jjxnews/0905/24164_476.htm
http://m.wap.cshexing.com/fnznews/0830/article_895512.htm
http://tbsz.cn
https://3wt.cn/news/QRcode/34412.html
https://88fa.cn
https://aifabu.com
https://aifabu.com/details/43949
https://aifabu.com/details/44780
https://aifabu.com/duanlian
https://baijiahao.baidu.com/s?for=pc&id=1862494718980399625&wfr=spider
https://baijiahao.baidu.com/s?for=pc&id=1862868401454912726&wfr=spider
https://baijiahao.baidu.com/s?for=pc&id=1862953220239565175&wfr=spider
https://baijiahao.baidu.com/s?for=pc&id=1864190281489235594&wfr=spider
https://baijiahao.baidu.com/s?for=pc&id=1866495281290163395&wfr=spider
https://baijiahao.baidu.com/s?for=pc&id=1875365976217612155&wfr=spider
https://baijiahao.baidu.com/s?for=pc&id=1875366249728063696&wfr=spider
https://baike.baidu.com/item/Bitly/67703330
https://baike.baidu.com/item/tinyurl/8300813
https://bitly.com/pages/products/url-shortener
https://ixiaguo.com/adl-dl.html
https://linklyhq.com
https://meilikeai.cn
https://pzurl.cn
https://shlink.io
https://shoturl.cn
https://tqw.lqurl.cn/details/44991
https://web.lqurl.cn
https://yiban.io/blog/35875
https://yiban.io/blog/36967
https://yiban.io/blog/37242
https://yiban.io/blog?p=35887
https://yiban.io/blog?p=37628
https://yiban.io/blog?p=38961
https://zhuanlan.zhihu.com/p/2023360919120478745
```

This list was the fixed scope considered for the separately authorized Answer
Semantic task. No URL was fetched and no page or passage was sent to a model.

## Authorized Answer Semantic Diagnosis

The production V2 Diagnosis API consumed the exact frozen AnalysisContext:

```text
Diagnosis = 40cdde15-f4ba-4ce8-803e-7e04ddd44931
Input fingerprint = ef2048da4898b179bd0121a41fe7b21368ccc16a1b72441808f029b3c593f177
ResultVersion = diag-v1:8d44fcac42659f31
Result SHA-256 = 8d44fcac42659f314e43448991cfa70ee005d21069c148f7bcb86790402827a8
Reviewable set SHA-256 = 68eb9e2fcc5b271d36d2657a6efad8b2db9bed3da2d9ed9bb4d92e731d62bf07
Provider = deepseek
Model = deepseek-v4-flash
External requests = 3
LLM cache hits = 0
Provider token usage = 10163 total tokens
Provider-reported cost = unavailable
```

All three responses reached `finish_reason=stop`, but all three were rejected
by the V2 strict response gate as `FAILED_SCHEMA`. The model emitted non-empty
`selection_criteria` entries with `criterion`, `criterion_scope` and
`answer_span`; the current strict contract accepts a string or an object with
`normalized_reason`, `reason_span` and optional `reason_scope`. Unknown fields
were not ignored, missing fields were not defaulted, and no invalid payload was
converted into a zero-event result.

The accepted result therefore contains zero effective events and zero Reasons,
plus three explicit Answer Semantic failures. It is not evidence that the
answers contain no recommendation. No DiagnosisReview was created.

## Fixed Raw-Answer Observation

These observations come directly from the immutable answer text, not from an
accepted model result:

| Run | Target-brand occurrence | Effective semantic result | Anchor |
| --- | --- | --- | --- |
| 260 | `爱短链` appears only in three reference-list titles; it does not appear in the answer body. | `FAILED_SCHEMA`; no valid object/reason | `UNPROVEN` |
| 261 | `爱短链` appears only in four reference-list titles; it does not appear in the answer body. | `FAILED_SCHEMA`; no valid object/reason | `UNPROVEN` |
| 262 | Six reference-list titles mention `爱短链`; the answer body also lists it as one option under `营销推广场景`, alongside `缩链` and `摩尔短链`. | `FAILED_SCHEMA`; no valid object/reason | `UNPROVEN` |

The answer bodies contain no `[n]` citation markers. A reference-list
observation is not promoted to a recommendation-reason binding. Since there is
no admitted Reason set, cross-Run Reason grouping and Reason-to-Truth relations
are both empty and remain unassessed.

The Diagnosis used `REUSE_ONLY` for source snapshots and `CACHE_ONLY` for
evidence LLM work. None of the 35 URL identities had a reusable immutable V2
snapshot, so all 35 are explicitly `FETCH_DISABLED`, with zero passages,
SourceClaims, candidate relations or Alignment calls. This is an authorization
limit, not `NO_SUPPORT`.

## Stop Point

```text
Browser samples = 3
Browser retries = 0
DeepSeek Answer Semantic calls = 3
DeepSeek SourceClaim/Alignment calls = 0
Source fetches = 0
Diagnosis rows = 1
Diagnosis ResultVersions = 1
Diagnosis reviews = 0
Strategy rows for this Analysis = 0
Retest rows for this Analysis = 0
```

The authorized Answer Semantic attempt is complete and frozen with explicit
failures. The three-call allowance is exhausted. A future retry requires a
separate implementation correction and a new explicit external-call
authorization; this result must not be revised in place or treated as an empty
semantic answer.

## Answer Contract Repair Status

The integration defect exposed by the replay has been repaired locally without
changing the frozen execution or result above. The production Answer prompt now
uses the strict response model as its structural source and documents the only
accepted non-empty market-criterion object. The current versions are:

```text
Prompt = single_prompt_v2.answer_semantic.safety.v2
Schema = single_prompt_v2.answer_semantic.strict.v2
Admission = single_prompt_v2_llm_admission.v2
Projection = single_prompt_answer_semantic_projection.v2
```

The complete criterion path is now strict admission, fixed-answer span
grounding, conservative normalized projection, independent market-criterion
persistence, API return and dedicated UI display. A market criterion has no
brand Reason, Truth or Evidence authority. `unresolved_items` is displayed only
as an unresolved issue collection.

The existing failed #40 ResultVersion is dynamically projected as
`NO_CONSUMABLE_RESULT`: 0 admitted, 3 failed, only `VIEW` allowed. Backend
revision/review endpoints and Strategy readiness independently enforce this;
the strategy blocker is `NO_CONSUMABLE_ANSWER_SEMANTIC_RESULT`.

No external request was made to validate the repaired contract. The existing
Diagnosis endpoint has Context scope and would replay Runs 260, 261 and 262; it
cannot honor a single-Run authorization. A new replay requires explicit
authorization for at most those three requests and must create a new immutable
Diagnosis execution/result rather than changing this historical failure.

The current Analysis status payload exposes the legacy blocker text
`NEXT_STAGE_NOT_IMPLEMENTED` even though the V2 Diagnosis API now exists. This
wording is inaccurate but was not changed during the authorized Baseline run.

## Authorized Answer Semantic Replay After Contract Repair

A new explicit three-Run authorization replayed the same frozen Context through
the formal Diagnosis API with `REUSE_ONLY + CACHE_ONLY` evidence policies:

```text
Diagnosis = c48054e3-1f4a-4cb5-b21c-9d6f584af273
ResultVersion = diag-v1:5a9bf1bd51178074
Result hash = 5a9bf1bd5117807412d8d993af78518a14417910fa5624e812645155dabbc1d2
Reviewable set hash = e0d88ce022142ba59e58bd63e7bfa07372ff42369413b844e46e58965bf96002
External Answer requests = 3
LLM cache hits = 0
Provider token usage = 12,714
Provider cost = UNKNOWN
```

The repaired strict Schema accepted the response shape. Run 260 completed as
`DONE_WITH_REVIEW_REQUIRED`: seven option events were grounded, four were
conservatively consumable and three retained semantic-review requirements. One
independent market criterion was grounded and persisted; it did not become a
brand Reason, Truth relation or Evidence claim.

Runs 261 and 262 were rejected as `FAILED_GROUNDING`. Their first returned
`answer_span` omitted an invisible separator present in the immutable Wenxin
answer, so an exact span could not be located. The whole response was rejected;
no event or market criterion was salvaged, no retry occurred, and the failures
were not converted to zero events.

Target-brand observation remains conservative. In Runs 260/261, `爱短链`
appears only in reference-list titles. Run 262 does list `爱短链` in the answer
body as one marketing-scenario option, but that Run's model response failed
grounding and therefore produced no consumable target-brand event. Reference
titles remain observations, not recommendation evidence.

The result is review-eligible only for its admitted subset and permanently
retains `ANSWER_SEMANTIC_PARTIAL_FAILURE=2`. It also retains independent-session
and Retrieval limitations, 35 unavailable source contents, 245 unevaluated
Evidence relations and 245 unproven anchors. Wenxin model revision remains
unavailable in the frozen Run conditions. No Review or Strategy was created.

One lexical `PARTIALLY_COVERS` relation was emitted as a machine suggestion
between an `壹伴助手` reason and target-brand Truth #2. This did not update
Product Truth and must not be interpreted as confirmed target-brand coverage;
the subject mismatch requires explicit review before any downstream use.

The old failed ResultVersion `diag-v1:8d44fcac42659f31` remains unchanged. No
source page was fetched, no SourceClaim/Alignment model was called, and no
sampling, Truth mutation, Review, Strategy or Retest followed this replay.

## Local Raw-Span Remediation After Replay

Read-only inspection of the frozen #40 answers and retained failure excerpts
confirmed the first grounding difference for both failed Runs:

```text
Run 261 raw offsets = 1162:1212
Run 262 raw offsets = 1190:1240
Difference in each = raw contains U+200C ZERO WIDTH NON-JOINER at local index 6
Text/number/punctuation/negation/condition changes = none in the inspected span
```

V2 now permits only a unique same-line match that removes `U+200C` from the
matching view. Raw answers, Context and hashes are unchanged. Exact matching
still wins; other Unicode characters, ambiguity, cross-paragraph joining and
semantic changes remain rejected. Projection records both model and raw spans,
raw offsets/hash and the exact transformation rule.

The retained audit contains only a 240-character excerpt, not the complete
failed response. Local tests therefore prove the confirmed first-span repair
and negative boundaries, not complete recovery of Runs 261/262. No new
Diagnosis or paid replay was performed.

The same read-only pass corrected two consumption views without rewriting the
immutable result. The historical 壹伴助手 → 爱短链 Truth #2 machine relation is
now exposed as an unconfirmed target-capability-fit suggestion with current
effective relation `UNRESOLVED`. The 35 source rows are exposed as not fetched
because external fetch was disabled, rather than as 35 network failures.

Post-patch integrity remains:

```text
ResultVersion = diag-v1:5a9bf1bd51178074 (unchanged)
Result hash = 5a9bf1bd5117807412d8d993af78518a14417910fa5624e812645155dabbc1d2
Diagnosis reviews = 0
Strategy executions = 0
Project #3 target-brand Truth rows = 4
External LLM calls = 0
Source fetches = 0
```

## Authorized Answer Semantic Replay After Raw-Span Repair

On 2026-09-15, the fixed Project 3 / Prompt 40 Context was replayed once more
through the formal whole-Context Diagnosis API after exact preflight of the
Analysis, Context, Raw Result and all three answer hashes. The execution used
source `REUSE_ONLY`, evidence LLM `CACHE_ONLY` and `max_attempts=1`:

```text
Diagnosis = bd154212-9291-42ab-8966-b981136e10f0
ResultVersion = diag-v1:dbbbd68addd737f9
Result hash = dbbbd68addd737f913bf579e63314029aa17f7642e3c83eb18f6125a74522084
Reviewable set hash = a8df525719079a4df0aeb27e590b10dcc90e8d2fb0bf7ef7bc0808beed523112
External Answer requests = 2
LLM cache hits = 1
Provider token usage = 8,598
Provider cost = UNKNOWN
```

All three Answers passed strict Schema, grounding and result admission. Run 260
was recovered from a cache entry that passed the current admission contract;
Runs 261 and 262 were new DeepSeek calls. The new Run 261 response matched the
raw answer exactly. Run 262 exercised the restricted unique U+200C matching
rule. There were no failed spans, failed events, schema failures or legal-zero
answers.

The result contains 22 `INCLUDE_AS_OPTION` events and three independent market
criteria. Every Run is `DONE_WITH_REVIEW_REQUIRED`: 13 events remain in
semantic review because the scenario-list wording does not contain an explicit
option cue. This is a conservative review state, not a model or grounding
failure. `爱短链` appears as one Run 262 marketing-scenario option and remains
review-required; reference-list appearances in Runs 260/261 do not become
recommendations.

No source content was fetched and no SourceClaim/Alignment model was called.
The result reports 35 `SOURCE_CONTENT_NOT_FETCHED`, zero actual fetch failures,
zero evaluated Alignments and unproven reference anchors. Two cross-subject
`壹伴助手`/`壹伴助手插件` to `爱短链` Truth #2 matches remain unconfirmed
capability-fit suggestions with effective relation `UNRESOLVED`.

The old result `diag-v1:5a9bf1bd51178074` remains unchanged. No DiagnosisReview,
Strategy or downstream object was created. The new result is ready for a human
review of the admitted set; review was not completed automatically.
