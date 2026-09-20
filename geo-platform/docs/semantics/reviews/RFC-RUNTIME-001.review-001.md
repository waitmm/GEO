# Definition Review: RFC-RUNTIME-001

```yaml
review_id: RFC-RUNTIME-001-REVIEW-001
reviewer_role: INDEPENDENT_RUNTIME_DEFINITION_REVIEWER
reviewed_at: 2026-09-08
reviewed_rfc_status: DRAFT
reviewed_rfc_maturity: CANDIDATE
reviewed_implementation_status: NOT_IMPLEMENTED
change_classification: SEMANTIC_RISK
production_code_changes: 0
schema_changes: 0
database_writes: 0
spike_started: false
```

## Status

```text
Status = NEEDS_REVISION
Freeze Recommendation = NO
```

The five-lineage separation is directionally correct, and the RFC already closes
many important failure modes. It is not yet precise enough for an Implementer to
build the #19/#40 read-only Runtime Projection without choosing additional
business semantics.

## Contracts / Sources Reviewed

```text
docs/semantics/00_DOMAIN_MODEL.md
docs/semantics/01_SEMANTIC_CONTRACTS.md
docs/semantics/02_GOLDEN_SEMANTIC_CASES.md
docs/semantics/03_DEFINITION_REVIEW_CHECKLIST.md
docs/semantics/04_CONFLICT_REGISTER.md
docs/semantics/05_RUNTIME_SEMANTIC_MAP.md
docs/semantics/rfcs/RFC-RUNTIME-001.md
docs/semantics/snapshots/CASE-REAL-019.manifest.json
docs/semantics/snapshots/CASE-REAL-040.manifest.json
backend/app/models/db.py
backend/app/modules/optimization/service.py
```

Contracts referenced:

```text
SC-HISTORY-001@1.0.0
SC-SCOPE-001@1.0.0
SC-EVIDENCE-003@1.0.0
SC-STEP7-001@1.0.0
SC-STEP8-001@1.0.0
SC-EXPERIMENT-001@1.0.0
SC-RUNTIME-001@0.1.0 (proposed only)
```

Golden Snapshot IDs:

```text
CASE-REAL-019@2026-09-08
CASE-REAL-040@2026-09-08
database sha256 = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
```

The local database hash, Package `12@v8`/`15@v2`, Run counts, and Candidate
`#57`/`#50` identities matched the fixed manifests during this review.

## Root / Stage

```text
root definition = PARTIAL, BLOCKED BY ROOT_STAGE_LEAKAGE
stage definition = SOUND META-MODEL, CONCRETE STAGE CONTRACTS MISSING
circularity = POSSIBLE UNDER THE CURRENT FULL EVIDENCEPACKAGE PAYLOAD
```

The selected conceptual boundary is valid:

```text
AnalysisContext = immutable acquisition/root lineage
StageExecution = progressively consumed/produced lineage
```

However, the RFC currently freezes the full EvidencePackage payload as Root
input while also classifying Product Truth, SourceDocument content, Alignment,
Benchmark and Gap as Stage-only objects. The current Package builder reads those
objects while producing `package_payload_json`:

```text
service.py:6953-7016 -> source_analysis(...)
service.py:8061-8077 -> SourceDocument enrichment, Alignment, Gap and Strategy-like derivation
service.py:8333-8377 -> SourceDocument and EvidenceAlignment-derived Benchmark data
service.py:8887-8924 -> TargetBrandCapabilityTruth and Gap data
```

Without a Root-safe Package projection definition, the future runtime must
either consume pre-Context Stage semantics as Root input or require those Stages
to produce the Package needed to create their own Context.

## Identity

```text
Context = PARTIAL
StageExecution = PARTIAL
StageAttempt = PASS
ReviewDecision = PARTIAL
CurrentPointer = CONTEXT POINTER PASS; STAGE/REVIEW AUTHORITY PARTIAL
```

Passes:

- `context_id != context_fingerprint` is explicit.
- Same fingerprint with different Context IDs is explicitly legal.
- A fingerprint cannot select or merge an existing business lineage.
- StageExecution and StageAttempt are separated.
- Attempts are append-only and remain attached to one logical execution.

Open identity gaps:

- The canonical field set and normalization rules for `context_fingerprint` are
  not defined.
- The Root manifest includes Package identity and creation metadata, while the
  RFC also permits different Package identities to have equal fingerprints. It
  does not state which lineage-only fields are excluded from equivalence.
- `root runtime contract profile/version` is not enumerated, and the rule that
  assigns a version/flag to Root versus a Stage is not closed.
- `stage scope key` is not defined per Stage or partition.
- The authority identity for append-only ReviewDecisions is not defined.

## Lifecycle

```text
retry = PASS
recompute = PASS AT META-MODEL LEVEL
resume = PARTIAL; concrete missing/incomplete policy depends on absent Stage Contracts
replay = PASS FOR EXPLICIT SELECTION; output reproducibility semantics need clarification
new context = PARTIAL; Root profile and Root-safe Package payload are unresolved
```

The required sequence below is expressible:

```text
Attempt 1 FAILED
Attempt 2 FAILED
Attempt 3 SUCCEEDED
=> one StageExecution + three immutable StageAttempts
```

Successful output immutability and successful zero-member output are both
defined correctly. Recompute creates a new StageExecution and does not overwrite
old successful output.

## Review

```text
immutable binding = PASS
partition model = PASS AT OBJECT LEVEL
append-only history = PASS AT HISTORY LEVEL
authoritative review selection = NOT DEFINED
```

The exact StageExecution/output or completed partition binding includes member
refs, count and hash. A moving query such as `all current SUPPORTS` is correctly
forbidden as a review target.

The missing part is authority. `supersedes` is required only "when applicable",
but the RFC does not define the single authoritative decision per review target,
the authority scope/version, or what happens when two append-only decisions do
not form one valid supersession chain. Therefore `authoritative reviews` in the
current projection is not deterministically derivable yet.

## Invalidation

```text
dependency-driven = PASS AS THE DEFAULT PROPAGATION PRINCIPLE
over-invalidation risk = CONTROLLED BY CONSUMED EDGES
under-invalidation risk = BLOCKING
```

The Product Truth A/B counterexample passes for dependency propagation: only
consumers of A and their descendants should become stale.

The direct invalidation model is missing. Section 14 says a Stage loses current
eligibility only when a consumed input is superseded/invalidated/replaced, while
Sections 21-22 also permit privileged direct Context/Stage invalidation and
reactivation. The RFC does not define direct invalidation, its authority, its
cascade root, or the compatibility condition for reactivation. An executor or
projection would have to invent whether a contract defect, revoked review, or
manual safety invalidation can make an unchanged Stage ineligible.

## Candidate Audit

```text
selected manifest = PASS
omitted manifest = PASS
omission explainability = PASS
```

Candidate Builder is correctly promoted to a first-class runtime contract.
Selected and omitted considered pairs, policy/version, score/rank, TopK,
threshold and tie boundary are required. `OMITTED_BY_CANDIDATE_POLICY` is
correctly separated from a judged negative verdict.

## Current Authority

```text
explicit pointer = PASS FOR CONTEXT; PARTIAL FOR STAGES
latest fallback = EXPLICITLY FORBIDDEN
optimistic concurrency = REQUIRED
```

`CurrentContextPointer` has a closed scope, one target-or-empty rule,
workflow-track separation, state version and audit history.

The Stage selection relation does not yet define:

```text
exact stage scope key and cardinality;
selection eligibility gates;
whether successful recompute is selected automatically or by a privileged action;
how partition-level selection relates to full-stage selection;
how authoritative ReviewDecision participates in selection;
how a failed selection transition leaves the previous selection.
```

Allowing “pointers, activation events or an equivalent projection” is a valid
storage choice, but the above business transition semantics cannot be delegated
to implementation.

## External Mutation

```text
SourceDocument refetch = CONCEPTUALLY PASS; current selection transition unresolved
Product Truth correction = PARTIAL
```

The SourceDocument attack is handled correctly at the lineage level: content B
must be a new immutable version, A remains historical, and only actual
descendants of A become stale.

The Product Truth rule still permits an unresolved choice between “new immutable
fact/projection version” and “equivalent immutable Stage output”. Those are not
the same identity or ownership model. The Human Override table also combines
Strategy review and Strategy edit into one row. A ReviewDecision can accept or
reject an immutable output; an edit must identify which new semantic output and
StageExecution it creates before that output can be reviewed. The RFC must make
that distinction deterministic for each listed correction type.

## Legacy

```text
#19 = FIXED IDS VERIFIED; PROJECTION RESULT UNDER-SPECIFIED
#40 = FIXED IDS VERIFIED; NULL PR4 LINEAGE PRESERVED
backfill safety = PASS AS A PROHIBITION, PARTIAL AS A SPIKE OUTPUT CONTRACT
```

The RFC correctly rejects fabricated context IDs, hashes and feature profiles,
and allows `PARTIALLY_MAPPABLE` / `UNSAFE_TO_BACKFILL` Legacy Compatibility
Projection states. Legacy, Shadow and Golden tracks cannot become Production
current.

For the recommended Spike, however, the RFC simultaneously requires projecting
a Context fingerprint and acknowledges that #19/#40 lack immutable historical
SourceDocument/Product Truth/Alignment lineage. It does not state which Root,
Stage, review and pointer fields must be `null`, unavailable or warning-only for
each fixed case. #40's missing PR4 hashes are explicit; equivalent expectations
for the rest of the legacy Runtime projection are not complete.

## Backend / Frontend

```text
backend authority = PASS
frontend boundary = PASS
```

The backend exclusively owns current, ready, complete, blocked, allowed actions
and historical eligibility. The frontend is correctly limited to presentation,
loading, tab/expanded state, sort/filter and unsubmitted form edits. Authority
unavailability cannot be replaced by empty or latest local fallbacks.

## Atomicity / Concurrency

```text
completion invariant = PASS
storage independence = PASS
```

A Stage cannot become SUCCEEDED before its output set, immutable manifest,
member count and hash are atomically visible. The RFC does not require Postgres,
Redis, Celery or any particular storage mechanism. Pointer and review writes
require optimistic preconditions, and lease ownership is explicit.

## Golden Cases

```text
CASE-REAL-019 = IDENTITY VERIFIED; EXPECTED LEGACY PROJECTION INCOMPLETE
CASE-REAL-040 = IDENTITY VERIFIED; NULL-HASH RULE PASS; EXPECTED LEGACY PROJECTION INCOMPLETE
RT-SYN-001..006 = COVER IMPORTANT NORMAL/BOUNDARY CASES
UNKNOWN/PARTIAL/UNSAFE LEGACY CASE = MISSING
DIRECT INVALIDATION/REACTIVATION CASE = MISSING
AUTHORITATIVE REVIEW CHAIN CASE = MISSING
```

The fixed manifests are used correctly and no `latest` substitution occurred.
The synthetic cases cover fingerprint independence, zero output, immutable
review partitions, candidate omission, edge-driven invalidation and review
write concurrency. They do not yet close the unresolved authority and legacy
projection behavior listed above.

## Blocking Issues

### RT-B1 Root Package contains Stage semantics

```text
category = ROOT_STAGE_LEAKAGE / CIRCULAR_CONTEXT_DEPENDENCY
RFC section = 7.4-7.7
```

**Problem:** The full EvidencePackage payload is required in the Root manifest,
but its observed builder consumes objects the RFC assigns to downstream Stages.

**Counterexample:** A Package created while SourceDocument, Alignment and Product
Truth rows exist freezes derived Benchmark/Gap data. The proposed Context then
runs Source/Alignment/Gap Stages again. The Implementer must choose whether the
frozen derivation is authoritative Root input, ignored legacy data, or a Stage
output, and each choice changes lineage semantics.

**Required clarification:** Define the exact Root-safe EvidencePackage
projection and the handling of any non-Root fields in the current Package
payload. State the unique Context creation precondition without requiring a
Stage output produced under that Context.

### RT-B2 Context fingerprint and Root profile are not closed

```text
category = IDENTITY_AMBIGUITY / LINEAGE_GAP
RFC section = 7.3-7.4, 7.8, 10
```

**Problem:** The RFC does not define the canonical fingerprint field set,
normalization/version, lineage-only exclusions, or the exact content of the
Root runtime contract profile.

**Counterexample:** Context A uses Package 12 and Context B uses a semantically
equivalent Package 16. Depending on whether Package ID, actor/time and profile
fields are hashed, their fingerprints can be equal or different. Both outcomes
are currently conforming readings.

**Required clarification:** Specify the versioned fingerprint contract and the
rule assigning every semantic configuration to Root or a named Stage. Preserve
the already correct rule that equal fingerprints never merge lineage IDs.

### RT-B3 Concrete Stage Contracts and object governance are missing

```text
category = LINEAGE_GAP / STEP_BOUNDARY_LEAKAGE
RFC section = 8-11, especially 9:493-517
```

**Problem:** The RFC defines what every Stage Contract must declare, but does not
provide the contracts needed by Spike B. The Step-to-stage table is explicitly
“candidate” and does not freeze exact Stage types, scope keys, dependencies,
partial-output policies, review gates, completion predicates, Source of Truth,
owners or allowed consumers for the five new runtime objects.

**Counterexample:** An Implementer can legally model AnswerUnit and Binding as
one Stage or two, make Candidate Builder a partition of Alignment or a separate
Stage, and select different dependency edges. All produce different stale and
readiness projections for #19/#40.

**Required clarification:** Provide the minimum versioned Stage Contract/DAG and
new-object governance needed for the read-only Spike. Storage tables and worker
technology may remain deferred.

### RT-B4 Current Stage and Review authority are ambiguous

```text
category = CURRENT_FALLBACK / IDENTITY_AMBIGUITY
RFC section = 12.4, 17, 18.2-18.4
```

**Problem:** `stage scope key`, current Stage transition rules and the single
authoritative ReviewDecision chain are not defined.

**Counterexample:** Two successful Strategy executions exist under one Context,
and two reviewers append decisions against the same output without one valid
supersedes reference. The RFC forbids `latest`, but provides no deterministic
winner for either Stage or review authority.

**Required clarification:** Define Stage-selection scope/cardinality and
transition eligibility, plus ReviewDecision authority scope, state version and
mandatory supersession/conflict behavior. Do not select by row order or time.

### RT-B5 Human edits conflate decision lineage with output lineage

```text
category = CATEGORY_ERROR / LINEAGE_GAP
RFC section = 13, 15.2
```

**Problem:** “review/edit” and “fact/projection version or equivalent Stage
output” leave multiple legal identity models. A human decision and a corrected
semantic output are different objects.

**Counterexample:** A reviewer edits one Strategy reason and confirms it. One
implementation appends only ReviewDecision; another creates a new Strategy
StageExecution; a third mutates an “effective” output before appending review.
The resulting dependency and history semantics differ.

**Required clarification:** For every listed override type, state whether it
creates a reusable object version, a new StageExecution output, a ReviewDecision,
or a defined combination, and identify the exact stale edges. Keep review
targets immutable.

### RT-B6 Direct invalidation and reactivation are undefined

```text
category = INVALIDATION_GAP
RFC section = 14, 21-22
```

**Problem:** Edge-driven propagation is defined, but direct privileged
invalidation/reactivation is named without semantics and conflicts with the
word “only” in the consumed-input invariant.

**Counterexample:** A validator defect invalidates a successful Alignment Stage
without changing its recorded input hashes. It is unclear whether this action
is legal, whether descendants become stale, and what evidence permits
reactivation.

**Required clarification:** Distinguish direct invalidation roots from
dependency-propagated staleness and define their auditable authority, cascade and
reactivation compatibility rules.

### RT-B7 Cache compatibility can still be invented by implementation

```text
category = CACHE_COMPATIBILITY_GAP
RFC section = 10, 16
```

**Problem:** Provider/model lineage is conditional, and an “explicit
compatibility rule” is required but not governed. The authority, version,
allowed equivalence dimensions and unknown behavior of that rule are absent.

**Counterexample:** A SourceClaim materialization changes from model M1 to M2
with identical normalized input and prompt/schema versions. One Implementer
reuses the result because the semantic contract is unchanged; another misses
the cache because the model changed. Both can cite the current text.

**Required clarification:** Define the compatibility contract identity and its
closed inputs, including provider/model behavior, and require unknown
compatibility to miss rather than reuse. Implementation may choose storage, not
semantic equivalence.

### RT-B8 Spike B legacy output contract is incomplete

```text
category = LEGACY_SCOPE_FABRICATION / LINEAGE_GAP
RFC section = 20, 26, 28
```

**Problem:** The no-fabrication rule is correct, but Spike B's required output
does not define how unavailable Root fingerprints, Stage manifests, review
bindings and current pointers are represented for the fixed legacy cases.

**Counterexample:** #19 has fixed Package/Candidate/Run IDs but no historical
immutable SourceDocument/Product Truth/Alignment manifests. A projection could
hash today's rows, return null, or mark the entire Context unsafe. Only one may
be intended, but the RFC does not decide.

**Required clarification:** Add fixed expected projection states for #19/#40,
including nullable/unavailable fields, partial lineage warnings and which facts
remain assertable. Add unknown/failure Golden cases that prevent current-row
reconstruction.

## Non-blocking Issues

1. Make atomic publication explicit for completed review partitions as well as
   full successful Stage output.
2. Clarify that REPLAY guarantees exact selected inputs/configuration and audit
   lineage; byte-identical external LLM output is not implied unless the exact
   materialized response is reused under a compatible contract.
3. Replace “candidate” wording for workflow tracks and Stage names when their
   semantic identities are eventually frozen, while still allowing different
   storage enum labels.
4. Define retention/archive integrity during implementation design; it need not
   block the read-only Spike definition.

## Category Error Audit

```text
CATEGORY_ERROR = BLOCKING IN HUMAN REVIEW/EDIT CLASSIFICATION
CAUSAL_REVERSAL = NOT INTRODUCED
PARTIAL_PREMISE_FALLACY = NOT INTRODUCED
HIDDEN_FALLBACK = LATEST FALLBACK FORBIDDEN; AUTHORITY GAP REMAINS
MAGIC_THRESHOLD = CANDIDATE POLICY MUST BE VERSIONED, PASS
CROSS_STEP_LEAKAGE = PRODUCT STEPS PRESERVED; ROOT/STAGE PACKAGE LEAKAGE BLOCKS
UNKNOWN_UPGRADE = FORBIDDEN GENERALLY; LEGACY SPIKE OUTPUT INCOMPLETE
HISTORICAL_MUTATION = FORBIDDEN, PASS
IDENTITY_SCOPE_DRIFT = BLOCKING FOR FINGERPRINT/STAGE/REVIEW SCOPE
SHADOW_PRODUCTION_LEAK = FORBIDDEN, PASS
EVIDENCE_TO_ACTION_JUMP = NOT INTRODUCED
```

## Causal Audit

```text
Result = PASS
```

The RFC does not change Evidence, Benchmark, Gap, Resolver, Strategy or Step 8
causal semantics. Cache reuse is not treated as evidence, and Candidate omission
is not treated as a negative Judge verdict.

## Identity / Scope Audit

```text
AnalysisContext identity = PARTIAL
Context fingerprint = BLOCKING AMBIGUITY
StageExecution identity = META-MODEL PASS, STAGE SCOPE REGISTRY MISSING
StageAttempt identity = PASS
ReviewDecision identity = BINDING PASS, AUTHORITY SCOPE MISSING
CurrentContextPointer identity = PASS
Current Stage selection identity = MISSING
Result = BLOCK
```

## Forbidden Inference Audit

```text
same fingerprint => same business lineage = FORBIDDEN, PASS
latest row => current = FORBIDDEN, PASS
cache hit => same Context = FORBIDDEN, PASS
omitted candidate => NO_SUPPORT = FORBIDDEN, PASS
mutable query => reviewed set = FORBIDDEN, PASS
legacy partial data => fabricated exact lineage = FORBIDDEN, PASS
successful output => mutable recompute target = FORBIDDEN, PASS
full current Package payload => Root-safe acquisition input = NOT FORBIDDEN, BLOCK
multiple unsuperseded reviews => implicit authority = NOT RESOLVED, BLOCK
unknown cache compatibility => reuse = NOT EXPLICITLY FORBIDDEN, BLOCK
```

## Counterexamples

Pass:

```text
latest Candidate cannot replace explicit current;
reviewed partition cannot grow;
source refetch creates immutable B and preserves A;
retry creates a new Attempt under the same StageExecution;
Stage contract change creates a new execution, not a new Context by itself;
zero members can be successful;
pointer concurrent writes conflict;
rollback preserves both Contexts.
```

Not closed:

```text
full Package payload already contains Stage-derived semantics;
equivalent Package IDs under the fingerprint contract;
two successful StageExecutions with no explicit activation decision;
two ReviewDecisions with no valid supersession chain;
human Strategy edit versus review-only confirmation;
direct invalidation with unchanged input hashes;
model/provider change under cache compatibility;
legacy #19 projection with unavailable historical manifests.
```

## Step Boundary

```text
Product Step 1-8 order = PRESERVED
Product Step != Runtime DAG = EXPLICIT, PASS
Step 7/8 ownership = PRESERVED
Collection upstream boundary = DIRECTIONALLY PASS
Root-safe EvidencePackage boundary = BLOCK
Runtime Stage owner/consumer registry = MISSING
```

## Historical Compatibility

```text
#57 mutation = FORBIDDEN, PASS
#50 hash fabrication = FORBIDDEN, PASS
legacy current fallback = FORBIDDEN, PASS
unsafe historical backfill = FORBIDDEN, PASS
read-only projection exact null/warning semantics = MISSING
```

## Contract Gaps

```text
1. Root-safe EvidencePackage projection and unique Context creation predicate.
2. Versioned context fingerprint and Root profile contract.
3. Minimum Stage Contract/DAG registry for Spike B.
4. Current Stage selection and authoritative ReviewDecision contracts.
5. Human correction/edit operation-to-lineage mapping.
6. Direct invalidation/reactivation contract.
7. Versioned cache/materialization compatibility contract.
8. Fixed legacy Runtime projection schema and Golden expectations for #19/#40.
```

## Open Decisions

Must be resolved before Definition Freeze:

```text
which Package fields are Root-safe;
exact fingerprint/profile semantics;
minimum Stage types, scopes and dependencies;
selection and review authority transitions;
human edit/correction lineage;
direct invalidation/reactivation;
cache compatibility identity and UNKNOWN behavior;
legacy Spike projection null/partial semantics.
```

May remain for implementation design after Definition Freeze:

```text
SQL table names and indexes;
storage enum labels;
pointer/event physical representation;
SQLite transaction technique;
worker/queue/lease technology;
RBAC role names and session/IP retention;
archive and capacity policy;
frontend visual design.
```

## Spike Readiness

```text
Read-only Projection Spike implementable
without semantic invention = NO
```

The Spike scope and write boundary are otherwise correct:

```text
DB writes = 0
migration = none
executor replacement = none
frontend cutover = none
fixed Manifest ids only
```

## Freeze Recommendation

```text
Freeze Recommendation = NO
```

Return `RFC-RUNTIME-001` to the RFC Author as `NEEDS_REVISION`. The RFC should
retain its core five-lineage architecture, but the eight blocking definition
gaps above must be resolved before Product Owner Definition Freeze or Spike B.
Do not implement, migrate, start the Spike, or cut over production behavior from
this draft.
