# RFC-RUNTIME-002: Stage Output Binding & Ownership

```yaml
rfc_id: RFC-RUNTIME-002
status: DRAFT
semantic_maturity: CANDIDATE
implementation_status: NOT_IMPLEMENTED
authors: [Semantic RFC Author]
created_at: 2026-09-10
definition_approved_by: null
definition_approved_at: null
definition_approval_reference: null
production_cutover_approved_by: null
production_cutover_approved_at: null
production_cutover_approval_reference: null
affected_contracts:
  - SC-RUNTIME-001@0.1.0
  - SC-HISTORY-001@1.0.0
  - SC-PT-001@1.0.0
  - SC-UNKNOWN-001@1.0.0
  - SC-GAP-001@1.0.0
  - SC-STRATEGY-001@1.1.0
  - SC-SCOPE-001@1.0.0
proposed_contract: SC-RUNTIME-001@0.2.0
supersedes: null
production_behavior_change: NONE
phase_1b_status: NOT_STARTED
```

## Problem

`RFC-RUNTIME-001` froze the Runtime Context, immutable Stage lifecycle,
16-Stage DAG, review and current-selection invariants. Phase 1A implemented the
isolated persistence spine. Phase 1B then stopped because several Legacy
operations do not expose an unambiguous canonical output or exact dependency
binding.

The blocking category error is:

```text
business object currently visible in a database row
!=
object proven to be produced or consumed by this StageExecution
```

The Stage mapping review found that post-hoc queries would have to choose a
current/latest object or reconstruct a relation that the producing operation
never recorded. This RFC defines prospective producer ownership and exact
binding semantics. It does not repair historical data and does not authorize
implementation.

## Classification

```text
SEMANTIC_CHANGE
```

This RFC changes or completes `scope`, `producer`, `ownership`, `review target`,
`current selection` and three Stage dependency/member definitions. It therefore
requires independent Definition Review and Product Owner Definition Freeze
before implementation.

## Current Semantics

The following `SC-RUNTIME-001@0.1.0` invariants remain controlling until a new
version is frozen:

- AnalysisContext Root, Stage inputs, outputs and dependency edges are
  immutable manifests with canonical hashes.
- Review targets one exact immutable output or partition and never edits it.
- A correction creates a new reusable-object version or StageExecution output.
- Current Context and Stage selection are explicit, versioned operations;
  recompute does not auto-promote.
- UNKNOWN, UNRESOLVED, zero and failure are distinct states.
- latest/current/project/prompt fallback is never exact lineage.
- Historical #19/#40 projection remains PARTIAL/UNSAFE/UNAVAILABLE as recorded;
  it is not promoted by this RFC.

This RFC preserves the single Prompt Step 1-8 business sequence. It adds no
Step 9 and does not move Strategy execution details into Step 7.

## Current Production Audit

### Product Truth

`recommendation.py::upsert_target_brand_capability_truth()` receives a Project,
capability label/key and truth value/provenance. It mutates one
`TargetBrandCapabilityTruth` row. The API and Step 3 UI do not submit a Prompt,
Reason member ref/hash, immutable fact-value version, binding assertion or
supersession ref.

Current Step 3 is the natural producer of a Product Truth fact decision, but no
existing production action qualifies as a formal Reason/ProductTruth binding
producer.

```text
PROSPECTIVE_BINDING_PRODUCER_GAP
```

The current capability-label/token match and Candidate `product_truth_ids` are
Legacy compatibility evidence only. They are not a prospective binding.

### Source Qualification

`api.py::_run_analysis_pipeline()` calls
`run_source_qualification(db, project)` before source acquisition and without
`doc_ids`. The qualification runner queries all SourceDocuments; its Project
argument does not constrain that query. Content quality is written by document
and content hash, while ownership is recomputed from Project/domain data and is
not persisted.

The current operation is a global maintenance operation, not a Context-scoped
Stage producer. New documents fetched afterward cannot have consumed that
invocation's qualification output.

### Gap

Gap objects are assembled by deterministic helpers and later copied into
StrategyCandidate JSON. `workflow_confirm_decision()` upserts one mutable
`WorkflowConfirmation(project_id, prompt_id, step_key="gap")`; the request does
not name a Gap StageExecution, output manifest/hash or member set.

```text
LEGACY_GAP_REVIEW_BINDING = UNSAFE
PROSPECTIVE_GAP_REVIEW_CAPTURE_GAP
```

### StrategyCandidate

`service.py::_create_vertical_strategy_candidate()` creates, commits, refreshes
and returns the exact Candidate. The producer already knows `candidate.id`,
Package and structured payload at the creation boundary. This is the correct
prospective capture point.

`review_strategy_candidate(candidate_id, ...)` also has an exact Candidate ID.
However, it mutates `review_status` and `effective_payload_json`. A direct
acceptance copies the machine payload; an edited acceptance merges and
revalidates new human content. These are different semantic operations.

```text
CANDIDATE_EFFECTIVE_PAYLOAD_CONFLICT
```

`execution_proposal_shadow::_candidate_and_mode(candidate_id=None)` may choose a
current/latest Candidate. That invocation is not capture-eligible.

## Proposed Semantics

### Producer-bound lineage

Runtime captures an output only where the business producer knows the exact
output identity:

```text
producer operation
-> exact output/ref returned or committed
-> canonical output manifest
-> Shadow Runtime capture
```

The following is forbidden:

```text
producer operation
-> later database query
-> latest/current/closest row
-> claimed output binding
```

An eligible Stage must have an explicit Context, exact input manifest, exact
dependency edges, deterministic output membership, immutable output hash and a
known review target or `NOT_REQUIRED` review policy.

### Reusable fact and Context projection

A reusable fact retains its natural business scope. A Context Stage never
changes that ownership. It selects exact immutable fact versions into a new
Context-owned projection:

```text
ReusableFactVersion
        + fixed Context member scope
        -> Context Stage projection
```

Changing a reusable fact creates a new version. It does not rewrite an old
projection or Context Root.

## Affected Domain Objects

### ProductTruthFact

```text
meaning = one target-brand capability fact identity
natural scope = Project + target-brand identity/version + capability key
owner = Step 3 Product Truth
not = Reason binding, Gap, Benchmark, SourceClaim or Strategy
```

### ProductTruthFactValueVersion

An immutable version contains:

```text
fact object ref
fact_value_version_id
value = TRUE | FALSE | UNKNOWN
truth provenance/source ref
producer command ref
actor/time
contract version
supersedes version ref or null
payload hash
```

Its identity is:

```text
product_truth_fact_value.v1
+ ProductTruthFact identity
+ fact_value_version_id
```

The value and provenance participate in the immutable payload hash. Same
identity with different payload is an identity conflict.

### ReasonProductTruthBindingVersion

This object answers only:

> Which exact target Product Truth fact-value version is formally bound to this
> exact Decision Reason member?

It contains:

```text
binding_version_id
Reason output member ref/hash
target-brand identity/version
ProductTruthFact ref
ProductTruthFactValueVersion ref/hash
binding_status = BINDS | DOES_NOT_BIND | UNKNOWN
producer command ref
confirmation actor/time
binding contract version
supersedes binding version ref or null
```

`DOES_NOT_BIND` and `UNKNOWN` target one explicit Reason/fact pair and do not
prove that no other valid fact can bind the Reason. No fuzzy, label, keyword,
Candidate or LLM relation can produce `BINDS`.

### SourceContentVersion

```text
natural scope = canonical source identity + immutable fetched content version
identity = source identity + fetch contract/version + content version id
payload = fetch outcome + exact content hash + acquisition environment/ref
```

Fetch failure is an immutable versioned outcome, not absence.

### SourceQualificationFactVersion

`Source Qualification` is a mixed model, not one global truth:

1. `SourceContentQualityFactVersion` is reusable by exact
   `SourceContentVersion + quality contract/version`.
2. `SourceOwnershipFactVersion` is reusable only within
   `Project + target-brand/version + competitor-set/version + canonical source
   identity + ownership contract/version`.

Ownership is relational to the target Project; it is not globally reusable by
URL alone.

### GapOutput

`GapOutput` is the immutable output manifest of one `GAP` StageExecution. Its
member identity remains Reason-scoped. It is not the Prompt's mutable "current
gap" and is not `WorkflowConfirmation`.

### StrategyCandidateLineage

The persisted Candidate ID is a business lineage anchor. It is not by itself an
immutable Strategy output version. Machine generation and a human edit can
produce distinct immutable `STRATEGY_SYNTHESIS` outputs under the same
Candidate lineage.

## Answer Semantic And Binding Amendment

The prior Phase 1B blockers must be resolved before the four ownership paths
can form an end-to-end lineage.

### ANSWER_SEMANTIC closed member kinds

`runtime_stage.answer_semantic.v2` uses only:

```text
RECOMMENDATION_EVENT
DECISION_REASON
SELECTION_CRITERION
ANSWER_UNIT
RUN_NO_DECISION
RUN_SKIPPED_EMPTY_ANSWER
```

Each member identity is:

```text
run_id
+ member_kind
+ source_span_start
+ source_span_end
+ member_ordinal
```

`RUN_NO_DECISION` and `RUN_SKIPPED_EMPTY_ANSWER` use `-1/-1/0` for
span/ordinal and include an exact reason code in the payload. They are mutually
exclusive with semantic content members for that Run.

An LLM/network/schema/grounding failure is not `RUN_NO_DECISION`. It remains a
failed/incomplete StageAttempt and prevents successful whole-Stage publication.

The prospective Answer Semantic producer must create and freeze AnswerUnits
before `BINDING` starts. Current Legacy `run_answer_semantic()` is therefore not
capture-eligible until the producer boundary is changed. Historical missing
rows remain uninterpreted.

### BINDING ownership

`BINDING` consumes exact `ANSWER_UNIT` and `DECISION_REASON` members from the
selected `ANSWER_SEMANTIC` output. It never creates or edits AnswerUnits.

For every eligible AnswerUnit it emits one or more exact bindings or one
explicit unbound member:

```text
BINDING member:
  answer_unit_ref/hash
  reason_ref/hash
  binding_scope_type
  binding_ordinal
  decision_role
  binding_strength

UNBOUND member:
  answer_unit_ref/hash
  reason_ref = null
  binding_scope_type = NONE
  binding_ordinal = 0
  binding_strength = NONE | LOW
```

The current Shadow function that creates AnswerUnits and Bindings in one call
is Legacy compatibility behavior and is not a compliant prospective producer.

## Source Fetch And Qualification Amendment

The proposed `SC-RUNTIME-001@0.2.0` dependency correction is:

```text
Root Reference/Retrieval source universe
-> SOURCE_FETCH
-> SOURCE_QUALIFICATION

SOURCE_FETCH -> SEGMENTATION
SOURCE_FETCH + SOURCE_QUALIFICATION -> SOURCE_CLAIM through the existing
SEGMENTATION dependency
```

Specifically:

```text
SOURCE_FETCH dependencies:
  remove SOURCE_QUALIFICATION
  consume exact Root source-universe members directly

SOURCE_QUALIFICATION dependencies:
  add SOURCE_FETCH
```

This corrects the Frozen order; it does not authorize changing production code.

The Context source universe is the closed union of exact Reference and
Retrieval observation members in the AnalysisContext Root. It is not all
Project documents, all Prompt documents or all currently qualified documents.
Each universe member retains its Root observation ref and canonical source
identity. Multiple observations may reuse one fact version but remain distinct
projection members.

For every source-universe member, `SOURCE_QUALIFICATION` emits:

```text
QUALIFIED
REJECTED
UNKNOWN
NOT_EVALUABLE_FETCH_FAILURE
```

If a fetch succeeded but a required quality/ownership fact is absent, the
member is `MISSING`; the Stage remains INCOMPLETE and cannot publish a
successful output. Missing never defaults to qualified or rejected.

## PRODUCT_TRUTH_PROJECTION Contract

The projection scope is every `DECISION_REASON` member in one exact selected
`ANSWER_SEMANTIC` output. It consumes only:

```text
fixed Reason manifest
formal ReasonProductTruthBindingVersion refs
exact ProductTruthFactValueVersion refs/hashes named by those bindings
authoritative fact reviews
target-brand identity/version
projection config/version
```

For each Reason:

```text
valid bindings
-> emit every exact BOUND fact-value member

no valid binding
-> emit exactly one UNRESOLVED member

incompatible selected bindings or identity conflicts
-> emit CONFLICT and block formal downstream consumption
```

The chosen missing-binding behavior is:

```text
MECHANICAL UNRESOLVED OUTPUT
```

The projection Stage may complete with a closed UNRESOLVED partition, but
downstream Stages requiring a positive Product Truth must emit/enter their
contractual blocked state. They may not drop the Reason or choose another fact.

## GAP Output And Review Contract

One `GAP` StageExecution outputs `GapManifest/runtime_stage.gap.v2` containing:

```text
context_id
stage_execution_id
exact input manifest/dependency hash set
gap contract/config version
one member for every input Reason
member count and set-semantics output manifest hash
```

Each Reason member has one terminal class:

```text
GAP
NO_GAP
UNKNOWN
BLOCKED_INPUT
```

`GAP` includes the existing reason-level subtype and evidence. `NO_GAP` is a
positive no-gap result. `UNKNOWN` is insufficient evidence. `BLOCKED_INPUT`
names the exact blocking upstream member/status. None may be represented by a
missing row.

A Gap Review request must include:

```text
context_id
gap_stage_execution_id
gap_output_manifest_ref/hash
reviewed member refs and member count
review contract version
expected prior review version for CAS
decision
actor
```

The ReviewDecision targets the exact full manifest or an explicit immutable
partition. A Prompt ID or `step_key=gap` alone is invalid. Review does not
auto-select the output.

Editing Gap classification/content creates a new validated human-authored GAP
StageExecution output. A separate ReviewDecision targets that new output.

## StrategyCandidate Output And Review Contract

### Machine generation

The producer is the Candidate create transaction in
`_create_vertical_strategy_candidate()`. Capture occurs only after the commit
returns the exact Candidate ID and before the result loses its in-memory input
scope.

The machine Strategy output binds:

```text
candidate_id
candidate lineage ref
immutable structured/original payload hash
strategy synthesis contract/config version
exact Gap/Theme/Channel and all required upstream output refs/hashes
Strategy output manifest/hash
```

No later Candidate query participates in this binding.

### Review without edit

`ACCEPTED`, `REJECTED`, `DEFERRED` or `REOPEN` without semantic content change
creates an append-only ReviewDecision targeting the exact machine Strategy
output. It creates no new Strategy output.

### Review with edit

`ACCEPTED_WITH_EDITS` is not a mutation of the machine output and is not merely
a ReviewDecision. Deterministic merge plus successful revalidation creates a
new human-authored `STRATEGY_SYNTHESIS` StageExecution output under the same
Candidate lineage. A separate CONFIRM ReviewDecision targets that new output.

Invalid edits create neither a successful output nor a confirming review.

### effective_payload semantics

For prospective Runtime:

```text
effective_payload
= Legacy compatibility/materialized view of the explicitly selected,
  authoritatively reviewed Strategy output
```

It is not a Strategy output identity, not a review target and not a source from
which Runtime discovers the selected version. Its mutable Legacy row may remain
during Shadow, but the Runtime output captured at the producer/review boundary
is immutable.

For historical Candidates, including #57 and #50, `effective_payload` remains
Legacy projection evidence only. No historical human-authored StageExecution
is reconstructed from it.

### Current selection

After authoritative review, an explicit `ContextStageSelection` operation may
select the exact Strategy StageExecution/output for the SHADOW track. Candidate
status, Candidate ID, WorkflowConfirmation, created time or latest row never
selects it automatically.

## Execution Proposal Binding

An `EXECUTION_PROPOSAL` invocation is capture-eligible only when its request
names:

```text
context_id
explicit selected Strategy StageExecution/output ref/hash
authoritative Strategy ReviewDecision ref/hash
candidate_id as the business lineage anchor
exact RUN_METRICS baseline output refs
exact PRODUCT_TRUTH_PROJECTION refs
exact ManagedAsset/NewAsset input snapshot refs
compiler config/version
```

`candidate_id` alone is insufficient when a Candidate lineage has machine and
human-edited Strategy outputs. Omitted Candidate/output identity, latest/current
selection, or rereading mutable Product Truth/asset state makes the invocation
`PHASE_1B_CAPTURE_INELIGIBLE`.

## Required Binding Tables

### Product Truth Binding

| Field | Definition |
| --- | --- |
| Producer | New explicit Step 3 Reason-scoped Product Truth binding confirmation; no current action qualifies |
| Natural Scope | BindingVersion: exact Reason output member + target-brand ProductTruth fact-value version |
| Context Projection Scope | Every Reason in one selected ANSWER_SEMANTIC output |
| Exact Input | Reason ref/hash, target-brand version, ProductTruth object and fact-value version/ref/hash, actor, command id |
| Exact Output Identity | `reason_product_truth_binding.v1 + binding_version_id + complete bound refs/hashes` |
| Output Manifest | Immutable binding version manifest; PRODUCT_TRUTH_PROJECTION separately emits BOUND/UNRESOLVED/CONFLICT |
| Review Owner | Step 3 human confirmation; fact review and binding confirmation remain distinct records |
| Capture Point | Successful Step 3 confirmation command return/commit where all refs are present |
| Stale Trigger | Only projections/descendants that actually consumed a superseded binding or fact version |
| Legacy Rule | Mutable truth rows and Candidate IDs remain compatibility evidence; never BOUND |
| Forbidden Inference | label/keyword/fuzzy/LLM/project scan/Candidate hint/current fact row |

### Source Qualification Binding

| Field | Definition |
| --- | --- |
| Producer | Context-scoped qualification operation after exact SourceFetch output; current global runner does not qualify |
| Natural Scope | Content quality by SourceContentVersion; ownership by Project/brand/competitor-set/source/version |
| Context Projection Scope | Closed Root Reference/Retrieval source-universe members only |
| Exact Input | Root observation refs, SOURCE_FETCH content/failure refs, quality/ownership config and reusable fact refs |
| Exact Output Identity | Root observation identity + qualification subject type + qualification rule key |
| Output Manifest | Per-observation QUALIFIED/REJECTED/UNKNOWN/NOT_EVALUABLE; MISSING blocks publication |
| Review Owner | NOT_REQUIRED in profile v1; future review needs a separate contract |
| Capture Point | Qualification producer result before scope variables are discarded |
| Stale Trigger | Only projection/descendants consuming an old content, quality or ownership fact version |
| Legacy Rule | Global SourceQuality/ownership rows remain UNSAFE/PARTIAL projection evidence |
| Forbidden Inference | all-document scan, URL winner, current quality row, project/prompt fallback |

### Gap Review Binding

| Field | Definition |
| --- | --- |
| Producer | Explicit Step 6 GAP Stage operation; correction is a new human-authored GAP StageExecution |
| Natural Scope | One AnalysisContext + exact GAP StageExecution |
| Context Projection Scope | Every Reason in the selected upstream scope |
| Exact Input | Metrics, Answer Semantic, Product Truth projection, Alignment, Benchmark refs and config |
| Exact Output Identity | Reason identity per member; full manifest bound to StageExecution/input hash |
| Output Manifest | Immutable GAP/NO_GAP/UNKNOWN/BLOCKED_INPUT partition and output hash |
| Review Owner | Human Step 6 review of exact full output or named immutable partition |
| Capture Point | Gap producer return; then exact review request/commit with target refs |
| Stale Trigger | Change to an actually consumed upstream output/review or corrected Gap selection |
| Legacy Rule | Prompt-level WorkflowConfirmation is UNSAFE audit evidence only |
| Forbidden Inference | `step_key=gap`, current Prompt gap, latest Candidate gap JSON, timestamp/ID matching |

### StrategyCandidate Binding

| Field | Definition |
| --- | --- |
| Producer | `_create_vertical_strategy_candidate()` create transaction and exact return |
| Natural Scope | Candidate lineage under Project + Prompt + EvidencePackage; output version under StageExecution |
| Context Projection Scope | One exact selected upstream manifest set in one AnalysisContext |
| Exact Input | Metrics, Reasons, Truth projection, Benchmark, Gap, Channel Resolution and synthesis config refs/hashes |
| Exact Output Identity | Strategy header/theme/channel members plus exact `candidate_id` and output hash |
| Output Manifest | Immutable machine or separately created human-authored StrategyManifest |
| Review Owner | Step 7 review of exact Strategy output; edit creates new output then separate review |
| Capture Point | Candidate commit/return; edited output at deterministic merge/revalidation result |
| Stale Trigger | Actual consumed upstream selection/review change; review change only affects its real consumers |
| Legacy Rule | Existing Candidate/effective payload retained; historical output versions are not reconstructed |
| Forbidden Inference | latest/pending/accepted Candidate query, WorkflowConfirmation as selector, effective payload as identity |

## Stage Binding Contracts

The following affected Stage contracts use the required uniform template.

### ANSWER_SEMANTIC

```text
Stage = ANSWER_SEMANTIC
Producer = prospective Answer Semantic operation including committed AnswerUnit production
Natural Object Scope = one Root Run answer snapshot
Runtime Context Scope = exact eligible Run members in one AnalysisContext
Exact Inputs = Prompt snapshot, Run answer snapshot, extractor config
Exact Output Identity = run + closed member kind + span + ordinal
Output Manifest Members = events, reasons, criteria, units, zero/empty deterministic terminals
Zero / Unresolved Semantics = RUN_NO_DECISION or RUN_SKIPPED_EMPTY_ANSWER; failures are not zero
Review Target = exact full output or immutable Run/member partition
Downstream Consumers = PRODUCT_TRUTH_PROJECTION, BINDING, GAP, STRATEGY_SYNTHESIS
Invalidation Inputs = exact Prompt/answer/config or authoritative review change
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = producer result after all Run partitions are terminal
Legacy Projection Rule = existing Events/envelopes remain PARTIAL/UNSAFE
Forbidden Inference = missing row => zero; latest PromptAnalysisRun; reconstructed AnswerUnit
```

### BINDING

```text
Stage = BINDING
Producer = binding operation that consumes, but never creates, Answer Semantic members
Natural Object Scope = exact AnswerUnit-to-Reason relation
Runtime Context Scope = selected ANSWER_SEMANTIC output and Root observations
Exact Inputs = AnswerUnit/Reason refs/hashes, Root observations, binding config
Exact Output Identity = AnswerUnit + Reason/null + scope + ordinal
Output Manifest Members = BINDING or explicit UNBOUND per eligible AnswerUnit
Zero / Unresolved Semantics = closed UNBOUND member; missing member is incomplete
Review Target = exact output/partition
Downstream Consumers = ALIGNMENT_CANDIDATE_BUILD
Invalidation Inputs = consumed Answer Semantic member/review or config change
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = binding producer return after exact input manifest is fixed
Legacy Projection Rule = current combined AnswerUnit/Binding ShadowRun remains UNSAFE
Forbidden Inference = assigning an internally created AnswerUnit to a prior Stage
```

### SOURCE_FETCH

```text
Stage = SOURCE_FETCH
Producer = run-scoped acquisition operation over the closed Root source universe
Natural Object Scope = canonical source + immutable fetch/content version
Runtime Context Scope = exact Root Reference/Retrieval observations
Exact Inputs = source-universe manifest, acquisition environment/config
Exact Output Identity = canonical source identity + content/failure version
Output Manifest Members = fetched/reused exact content version or explicit failure per source member
Zero / Unresolved Semantics = empty universe is legal zero; fetch failure is an explicit member
Review Target = NOT_REQUIRED
Downstream Consumers = SOURCE_QUALIFICATION, SEGMENTATION
Invalidation Inputs = actual consumed source universe/config/version
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = fetch/reuse decision where exact document version is known
Legacy Projection Rule = mutable SourceDocument rows remain UNSAFE/PARTIAL
Forbidden Inference = current document by URL, closest canonical match, Qualification-before-Fetch edge
```

### SOURCE_QUALIFICATION

```text
Stage = SOURCE_QUALIFICATION
Producer = context-scoped projection operation after SourceFetch
Natural Object Scope = reusable content-quality and project-relative ownership fact versions
Runtime Context Scope = closed Root source universe
Exact Inputs = Root observation refs, SourceFetch output, fact/config refs
Exact Output Identity = Root observation + subject type + rule key
Output Manifest Members = QUALIFIED/REJECTED/UNKNOWN/NOT_EVALUABLE per observation
Zero / Unresolved Semantics = legal zero for empty universe; MISSING keeps Stage incomplete
Review Target = NOT_REQUIRED in profile v1
Downstream Consumers = SOURCE_CLAIM, ALIGNMENT_CANDIDATE_BUILD, BENCHMARK, CHANNEL_EVIDENCE
Invalidation Inputs = only exact consumed fact/content/config refs
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = scoped qualification result boundary
Legacy Projection Rule = global runner rows remain compatibility evidence only
Forbidden Inference = global/project/prompt scan, URL matching after execution, current row selection
```

### PRODUCT_TRUTH_PROJECTION

```text
Stage = PRODUCT_TRUTH_PROJECTION
Producer = deterministic Context projection over formal Step 3 bindings
Natural Object Scope = reusable Truth facts/bindings; Context owns only projection
Runtime Context Scope = every Reason in one selected Answer Semantic output
Exact Inputs = Reason, binding, fact-value, authoritative fact review and config refs/hashes
Exact Output Identity = Reason + binding status + fact version/unresolved/conflict + ordinal
Output Manifest Members = BOUND members or exactly one UNRESOLVED/CONFLICT terminal per Reason
Zero / Unresolved Semantics = no Reasons is legal zero; missing binding is UNRESOLVED, never dropped
Review Target = fact and binding reviews are inputs; projection itself has no separate review
Downstream Consumers = GAP, CHANNEL_RESOLUTION, STRATEGY_SYNTHESIS, EXECUTION_PROPOSAL
Invalidation Inputs = exact consumed Reason/binding/fact/review/config refs
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = projection result after binding set is fixed
Legacy Projection Rule = Candidate truth IDs and text matches remain UNSAFE hints
Forbidden Inference = project scan, labels, keywords, LLM rematch, Candidate hints
```

### GAP

```text
Stage = GAP
Producer = deterministic Gap builder over an exact upstream selection
Natural Object Scope = one immutable GapOutput and its member partitions
Runtime Context Scope = one AnalysisContext and selected upstream outputs
Exact Inputs = Answer Semantic, Product Truth projection, Evidence Alignment,
               Benchmark and gap-policy refs/hashes
Exact Output Identity = gap_output_id + canonical output hash
Output Manifest Members = reason/capability-level gaps, explicit no-gap members,
                          UNKNOWN and NOT_EVALUABLE members
Zero / Unresolved Semantics = closed no-gap manifest is legal zero; unresolved
                              upstream facts remain explicit and cannot become no-gap
Review Target = one exact GapOutput or immutable declared member partition
Downstream Consumers = CHANNEL_RESOLUTION, STRATEGY_SYNTHESIS
Invalidation Inputs = only exact consumed upstream output/review/config refs
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = Gap builder return after immutable output persistence
Legacy Projection Rule = Prompt-level WorkflowConfirmation remains UNSAFE metadata
Forbidden Inference = Prompt/step confirmation as output selector, Candidate gap copy,
                      latest Gap, current UI state
```

### STRATEGY_SYNTHESIS

```text
Stage = STRATEGY_SYNTHESIS
Producer = exact StrategyCandidate creation boundary
Natural Object Scope = machine Strategy output or separately authored edited output
Runtime Context Scope = one AnalysisContext and exact selected upstream manifests
Exact Inputs = Metrics, Reasons, Product Truth projection, Benchmark, Gap,
               Channel Evidence/Resolution and synthesis-config refs/hashes
Exact Output Identity = strategy_output_id + canonical output hash; a Candidate ID
                        may identify the machine output only when that mapping is explicit
Output Manifest Members = themes, reason coverage, channel roles, constraints,
                          baselines and explicit no-strategy/needs-human terminals
Zero / Unresolved Semantics = no-strategy is a closed output, never inferred from no row;
                              ambiguity is needs-human, not failure
Review Target = one exact immutable Strategy output or partition
Downstream Consumers = EXECUTION_PROPOSAL
Invalidation Inputs = only actual consumed upstream output/review/config refs
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = Candidate commit/return; edited output commit after validation
Legacy Projection Rule = existing Candidate/effective payload retained as Legacy data
Forbidden Inference = latest/accepted Candidate query, WorkflowConfirmation,
                      effective_payload as identity, in-place mutation of reviewed output
```

### EXECUTION_PROPOSAL

```text
Stage = EXECUTION_PROPOSAL
Producer = deterministic PR5 execution-proposal planner
Natural Object Scope = immutable proposal output under one exact accepted Strategy output
Runtime Context Scope = one AnalysisContext and exact selected Strategy output/review
Exact Inputs = selected Strategy output ref/hash, exact ACCEPTED review ref,
               permitted asset facts, baselines, constraints and planner config
Exact Output Identity = proposal_output_id + canonical output hash
Output Manifest Members = channel/asset proposals, defer decisions, restricted facts,
                          metrics and explicit no-proposal/needs-human terminals
Zero / Unresolved Semantics = closed no-proposal is legal; missing accepted Strategy is
                              unresolved/ineligible, not zero
Review Target = exact proposal output or immutable declared partition
Downstream Consumers = Step 8 human review; Action/Experiment only after their own contract
Invalidation Inputs = exact Strategy output/review, asset fact, baseline or config change
Current Selection = explicit ContextStageSelection only
Prospective Capture Point = planner return after immutable proposal persistence
Legacy Projection Rule = PR5 shadow/current rows remain historical compatibility data
Forbidden Inference = omitted candidate, latest/current Candidate, Candidate ID without
                      exact selected output, effective_payload, Prompt-level fallback
```

## Cross-Stage Binding Gate

A StageExecution is eligible for prospective Phase 1B capture only when all of
the following are true before the operation starts:

1. Its producer boundary is named and can return one complete immutable output
   manifest or one explicit terminal result.
2. Every input dependency is supplied by exact object/output ID and canonical
   hash, not discovered after the operation.
3. Reusable facts are separated from their Context projection.
4. Every review input names the exact immutable target and target hash.
5. The producer can expose the exact output before any latest/current lookup can
   change the referent.
6. Zero, UNKNOWN, UNRESOLVED, NOT_EVALUABLE and failure are represented by
   distinct closed states.
7. A correction creates a new version/output and declares supersession; it does
   not mutate a reviewed output.
8. Dependency changes can mark downstream output STALE by comparing persisted
   refs/hashes only.

Failure of any item makes the Stage ineligible. Runtime instrumentation may
record an operation ID or carry refs already known to the producer, but it may
not invent business ownership, choose a current object or reconstruct lineage
after commit.

## Phase 1B Stage Eligibility

This table separates a Stage's local capture feasibility from minimum-slice
feasibility. `CONDITIONAL` means its current mapping may be instrumented only
after every upstream blocker named here is resolved and tested.

| Stage | Prospective Status | Blocking Requirement |
| --- | --- | --- |
| RUN_METRICS | MAPPABLE_WITH_NON_SEMANTIC_INSTRUMENTATION | Exact Root Run-set and metric manifest must be passed through producer return |
| ANSWER_SEMANTIC | REQUIRES_RFC_AMENDMENT | Closed member kinds, zero terminals and AnswerUnit ownership defined here require freeze and implementation |
| PRODUCT_TRUTH_PROJECTION | REQUIRES_LEGACY_SEMANTIC_CHANGE | Step 3 lacks an explicit Reason/ProductTruth binding producer and immutable fact-value versions |
| BINDING | REQUIRES_RFC_AMENDMENT | AnswerUnit must be owned by ANSWER_SEMANTIC before Binding begins |
| SOURCE_FETCH | REQUIRES_LEGACY_SEMANTIC_CHANGE | Must consume the closed Root source universe directly and expose exact content versions |
| SOURCE_QUALIFICATION | REQUIRES_LEGACY_SEMANTIC_CHANGE | Current global, pre-fetch runner is not a Context projection producer |
| SEGMENTATION | CONDITIONAL | Exact SourceFetch content-version inputs and passage output identity must be exposed |
| SOURCE_CLAIM | CONDITIONAL | Existing ledger can support capture only after exact passage/config inputs are selected |
| ALIGNMENT_CANDIDATE_BUILD | CONDITIONAL | Requires exact Binding, SourceClaim and qualification manifests |
| EVIDENCE_ALIGNMENT | CONDITIONAL | Existing materialization can support capture only for exact candidate-set inputs |
| BENCHMARK | CONDITIONAL | Must bind exact qualified evidence/alignment inputs and emit a closed output |
| GAP | REQUIRES_LEGACY_SEMANTIC_CHANGE | No immutable GapOutput identity or exact review target exists |
| CHANNEL_EVIDENCE | CONDITIONAL | Must consume exact Gap/Benchmark/source projections, never Prompt-wide fallback |
| CHANNEL_RESOLUTION | CONDITIONAL | Must consume exact channel-evidence and policy manifests |
| STRATEGY_SYNTHESIS | CONDITIONAL | Machine producer exists, but exact upstream lineage and edit-as-new-output are missing |
| EXECUTION_PROPOSAL | REQUIRES_LEGACY_SEMANTIC_CHANGE | Must require exact accepted Strategy output/review; optional/latest selection is forbidden |

`RUN_METRICS` being locally mappable does not authorize an isolated Phase 1B
resumption. The minimum acceptance slice below requires all 16 Stage types.

## Minimum Phase 1B End-to-End Slice

After this RFC is independently reviewed, frozen and implemented, Phase 1B may
resume only with one newly created prospective AnalysisContext whose Root and
all Stage selections are explicit. The slice must exercise these Stage types:

```text
RUN_METRICS
ANSWER_SEMANTIC
PRODUCT_TRUTH_PROJECTION
BINDING
SOURCE_FETCH
SOURCE_QUALIFICATION
SEGMENTATION
SOURCE_CLAIM
ALIGNMENT_CANDIDATE_BUILD
EVIDENCE_ALIGNMENT
BENCHMARK
GAP
CHANNEL_EVIDENCE
CHANNEL_RESOLUTION
STRATEGY_SYNTHESIS
EXECUTION_PROPOSAL
```

This list is a required coverage set, not a claim that the DAG is a simple
linear pipeline. In particular:

```text
AnalysisContext Root source observations
  -> SOURCE_FETCH
  -> SOURCE_QUALIFICATION

SOURCE_FETCH
  -> SEGMENTATION

ANSWER_SEMANTIC
  -> PRODUCT_TRUTH_PROJECTION
  -> BINDING

BINDING + SOURCE_CLAIM + SOURCE_QUALIFICATION
  -> ALIGNMENT_CANDIDATE_BUILD
```

The minimum slice passes only if:

- every StageExecution records its exact input and output manifests;
- every dependency edge is derived from those persisted refs/hashes;
- Product Truth contains at least one exact binding or explicit UNRESOLVED
  projection member;
- Source Qualification contains a closed result for every Root source member;
- Gap has an immutable output identity and any review targets that identity;
- Strategy machine output is immutable, and any edit is a distinct output;
- Execution Proposal binds an exact accepted Strategy output and review;
- one upstream version change demonstrates dependency-derived STALE without
  current/latest inference;
- `ContextStageSelection` remains SHADOW-only and no production selector changes;
- no Legacy output is rewritten, backfilled or promoted to SAFE.

The slice may use deterministic zero members where the business input genuinely
contains no members. It may not fabricate zero outputs to avoid exercising a
binding contract.

## Review Ownership And Corrections

Review is a relation, not a mutable property that replaces an output.

```text
ReviewDecision =
  review_id
  target_output_ref
  target_output_hash
  target_partition_ref | null
  decision
  reviewer
  reviewed_at
  rationale
```

Rules:

- Direct acceptance creates a ReviewDecision over the exact machine output.
- A requested edit creates a new human-authored output with its own ID/hash and
  `derived_from_output_ref`; acceptance then targets that new output.
- Rejecting output A does not mutate or delete A.
- A Prompt-level workflow confirmation may remain UI progress metadata, but it
  is not an authoritative review or output selector.
- Review changes invalidate only consumers that persisted that exact review as
  an input.

For current `ACCEPTED_WITH_EDITS`, the Legacy row and `effective_payload` remain
historical. Prospective runtime capture must not reinterpret the mutated
effective payload as proof that an immutable edited output existed.

## Current Selection And Staleness

`ContextStageSelection` selects one exact completed StageExecution output for a
Context. Selection is explicit and versioned. It cannot be derived from:

```text
status = ACCEPTED
created_at maximum
ID maximum
current UI row
effective payload presence
Prompt-level confirmation
```

Staleness is mechanical:

```text
output is STALE
iff
one persisted consumed input ref/hash or authoritative review ref/hash
differs from the newly selected dependency set
```

An upstream object changing somewhere in the Project does not make an output
stale unless that exact object/version was consumed or a Context selection is
explicitly changed. Recompute creates a new output; it does not overwrite or
auto-select it.

## UNKNOWN, Zero And Failure

Every Stage contract must close its eligible member universe and distinguish:

| State | Meaning | Downstream Rule |
| --- | --- | --- |
| ZERO | Producer completed and proved no eligible members/results | May be consumed as a closed result |
| UNKNOWN | Required fact cannot currently be determined | Preserve explicitly; do not coerce to false |
| UNRESOLVED | Required relation/selection is absent or conflicting | Block consumers that require that relation |
| NOT_EVALUABLE | Input exists but the contract says evaluation is not possible | Preserve with reason code |
| FAILED_RETRYABLE | Producer did not complete due to retryable failure | Not a completed output |
| FAILED_FINAL | Producer failed terminally | Not ZERO and not a valid positive/negative result |

No missing row has semantic meaning by itself.

## Legacy Compatibility

This RFC is prospective.

- Historical objects and reviews remain immutable under their original
  contracts and observed implementation.
- No lineage backfill is authorized.
- Historical projection may remain `PARTIAL`, `UNSAFE` or `UNAVAILABLE`.
- A Legacy object may be copied into a newly authored prospective object only by
  an explicit business operation with declared provenance; copying is not
  reconstruction of the historical StageExecution.
- latest, timestamp-nearest, ID-max, Prompt/Project fallback and post-hoc joins
  remain forbidden as exact lineage.
- #19/#40 historical Candidate, Gap, Product Truth and evidence semantics are not
  rewritten by this RFC.

## Contract Diff

`SC-RUNTIME-001@0.1.0` remains authoritative until Product Owner freeze. A
future `SC-RUNTIME-001@0.2.0` would add only the following definition changes:

| Area | 0.1.0 | Proposed 0.2.0 |
| --- | --- | --- |
| Answer Semantic | Member universe/AnswerUnit ownership incomplete | Closed member kinds; AnswerUnit belongs to Answer Semantic |
| Binding | Combined Legacy boundary tolerated as unsafe | Consumes pre-existing AnswerUnit and emits relation/unbound only |
| Source Fetch | Qualification dependency inherited from Legacy map | Consumes closed Root source universe directly |
| Source Qualification | Canonical output/scope unresolved | Mixed reusable facts plus Context observation projection, after Fetch |
| Product Truth | Formal binding required but producer not settled | Step 3 fact version and explicit Reason binding producer contracts |
| Gap | Output and review owner unresolved | Immutable GapOutput plus exact output/partition review |
| Strategy | Candidate lineage incomplete | Machine and human-edited outputs are separate immutable outputs |
| Execution Proposal | Candidate binding under-specified | Exact accepted Strategy output and review are mandatory inputs |

This is a targeted semantic amendment. It does not change Step 1-8 ownership,
Benchmark eligibility, Product Truth meaning, EvidenceAlignment verdicts,
Channel Resolver semantics, Strategy channel roles or Step 8 creation timing.

## Golden Cases

### CASE-RUNTIME-BIND-001: Exact Product Truth binding

```text
Given Reason R1@hash-r1 and ProductTruthFactValue V3@hash-v3
And Step 3 records an explicit BOUND binding B1 from R1 to V3
When PRODUCT_TRUTH_PROJECTION runs for a Context containing R1
Then its manifest contains R1 + B1 + V3 with all refs/hashes
And no Project-wide truth lookup is performed
```

### CASE-RUNTIME-BIND-002: Missing Product Truth binding

```text
Given Reason R2 has no formal binding
When PRODUCT_TRUTH_PROJECTION runs
Then it emits one UNRESOLVED member for R2
And it neither drops R2 nor selects a similar capability fact
```

### CASE-RUNTIME-BIND-003: Qualification projection is closed

```text
Given the Root source universe contains observations O1 and O2
And exact fetched content versions and qualification facts exist for O1
But O2 has no required qualification result
When SOURCE_QUALIFICATION completes
Then O1 references exact reusable fact versions
And O2 is MISSING/UNRESOLVED
And unrelated Project documents are absent
```

### CASE-RUNTIME-BIND-004: Gap review targets output

```text
Given GAP outputs immutable G1 with members GM1..GM4 and hash H1
When a user accepts that Gap
Then the review request and ReviewDecision name G1, H1 and the reviewed partition
And a later G2 does not inherit G1's review
```

### CASE-RUNTIME-BIND-005: Strategy producer capture

```text
Given Strategy synthesis creates Candidate C57 and immutable machine output S1
When the create transaction returns
Then Runtime captures S1/C57 at that boundary
And performs no Candidate lookup to identify the output
```

### CASE-RUNTIME-BIND-006: Edited strategy is a new output

```text
Given reviewer edits S1 into validated S2
When the edit is accepted
Then S1 remains immutable
And S2 has its own ID/hash with derived_from = S1
And the acceptance review targets S2
```

### CASE-RUNTIME-BIND-007: Execution Proposal exact input

```text
Given S1 and S2 exist under Candidate C57
And only S2 has the selected ACCEPTED review
When EXECUTION_PROPOSAL runs
Then it consumes S2 and that exact review
And Candidate C57 alone is insufficient input
```

### CASE-RUNTIME-BIND-008: Sixteen-Stage prospective capture

```text
Given one new AnalysisContext with fixed Root members
When the full Shadow profile executes
Then all 16 Stage types produce immutable manifests or explicit terminals
And every edge is proven from persisted input/output refs and hashes
And one changed selected dependency marks only actual descendants STALE
```

## Counterexamples

### COUNTEREXAMPLE-001: Candidate hint promoted to binding

`candidate.product_truth_ids` contains a fact ID near Reason R1. Treating this as
a formal ReasonProductTruthBinding is invalid because neither the actor,
decision, Reason version nor binding contract is known.

### COUNTEREXAMPLE-002: Global qualification scan

A qualification runner returns 500 current Project documents while the Context
Root contains 17 source observations. Selecting the 17 matching URLs after the
run is post-hoc reconstruction, not a Context Stage output.

### COUNTEREXAMPLE-003: Prompt-level Gap confirmation

Two Gap outputs G1 and G2 exist for the same Prompt. A
`WorkflowConfirmation(step_key="gap")` cannot prove which output or member set
was reviewed and is therefore not an authoritative Stage review.

### COUNTEREXAMPLE-004: Effective payload as output identity

Candidate C57 has original machine structure S1 and edited effective structure
S2. A consumer that receives only C57 or reads the current `effective_payload`
cannot prove which immutable Strategy output and review it consumed.

### COUNTEREXAMPLE-005: Latest Candidate recovery

Querying the latest accepted Candidate after Strategy generation may return a
concurrent or historical object. Timestamp-nearest and ID-max variants are
equally invalid.

## Definition Gaps And Blocking Issues

The following are explicit blockers, not implementation details for a Phase 1B
implementer to decide:

| ID | Gap | Required Definition/Business Change Before Capture |
| --- | --- | --- |
| RFC-RUNTIME-002-GAP-001 | `PROSPECTIVE_BINDING_PRODUCER_GAP` | Establish Step 3 as an explicit Reason/ProductTruth fact-version binding action, including review and supersession lifecycle |
| RFC-RUNTIME-002-GAP-002 | `SOURCE_QUALIFICATION_SCOPE_AND_ORDER_CONFLICT` | Split reusable fact production from Context projection and run projection over exact post-fetch source versions |
| RFC-RUNTIME-002-GAP-003 | `PROSPECTIVE_GAP_REVIEW_CAPTURE_GAP` | Persist immutable GapOutput and require its ID/hash/member partition in the review action |
| RFC-RUNTIME-002-GAP-004 | `CANDIDATE_EFFECTIVE_PAYLOAD_CONFLICT` | Represent a validated edit as a distinct immutable Strategy output; retain effective payload only as a compatibility/materialized view |
| RFC-RUNTIME-002-GAP-005 | `EXECUTION_PROPOSAL_SELECTED_OUTPUT_GAP` | Require exact accepted Strategy output/review and remove optional/latest selection from prospective capture |
| SEM-CONFLICT-003 | Answer Semantic member/zero definition | Resolve through this RFC's closed member-kind and terminal-state amendment if approved |
| SEM-CONFLICT-004 | AnswerUnit producer ownership | Resolve through this RFC's Answer Semantic ownership amendment if approved |

No Stage beyond `RUN_METRICS` is independently capture-eligible today. Because
the acceptance rule requires a cross-stage slice through reusable fact
projection, Gap, Strategy and review/current selection, Phase 1B cannot continue
with a reduced scope under the present definitions.

## Non-Goals

This RFC does not:

- change Product Truth values or infer target-brand capabilities;
- change SourceClaim or EvidenceAlignment semantic judgments;
- change Benchmark, Gap or Channel Resolver business rules;
- select Strategy channels, assets, URLs, titles or sections;
- create Action or Experiment objects;
- clean, migrate or reclassify historical #19/#40 data;
- define Runtime Agent behavior;
- authorize schema, API, service, workflow or frontend implementation;
- authorize Phase 1B, Phase 1C, Cutover or PR5-C.

## Post-Freeze Implementation Sequence

This section is planning guidance only and grants no implementation authority.
After independent review and Product Owner Definition Freeze, work should be
split into auditable increments:

1. Implement immutable fact/output identity and exact review-target contracts
   for the four blocking domains without enabling Runtime capture.
2. Correct prospective AnswerUnit ownership and SourceFetch/Qualification DAG
   behavior behind non-production gates.
3. Add producer-bound instrumentation that only carries identities already
   known by each operation.
4. Run contract fixtures and one prospective 16-Stage Shadow capture with zero
   production selection changes.
5. Audit manifests, reviews, STALE propagation and forbidden-query telemetry.
6. Return for Phase 1B acceptance; do not auto-enter Phase 1C or Cutover.

## Shadow Acceptance Evidence

The future implementer must report:

```text
Context Root hash =
16 Stage executions represented =
exact input manifests =
exact output manifests =
explicit terminal members =
formal Product Truth bindings/unresolved members =
closed Source Qualification members =
Gap output/review target match =
Strategy create-bound output ID/hash =
edited Strategy output lineage =
Execution Proposal selected Strategy output/review =
latest/current fallback count = 0
post-hoc reconstruction count = 0
dependency-derived STALE check = PASS
production selector writes = 0
Legacy backfill writes = 0
```

## Rollback And Historical Safety

Before any future Cutover, Runtime instrumentation must be removable without
changing Legacy object production or selection. A failed Shadow capture records
an explicit Runtime failure and leaves the business transaction's existing
behavior under its then-approved rollout contract; it must not guess a manifest
to make the Shadow appear complete. Historical objects and approvals are never
deleted or rewritten by rollback.

## Decision Requested

Independent Semantic Review must decide whether the proposed producer,
ownership, scope, review-target, correction and Stage dependency definitions are
complete enough for Product Owner Definition Freeze. The reviewer must not edit
the RFC while reviewing it.

If accepted, the Product Owner may freeze a new Runtime contract version. Until
then:

```text
SC-RUNTIME-001@0.1.0 remains authoritative
RFC-RUNTIME-002 is CANDIDATE
Runtime Phase 1B is BLOCKED
production behavior is unchanged
```

## Completion Report

### Product Truth

```text
formal binding producer = no current formal producer; proposed explicit Step 3
                          Reason-scoped fact/binding confirmation
binding source of truth = immutable ReasonProductTruthBindingVersion plus exact
                          ProductTruthFactValueVersion
projection scope = every Reason in the selected Answer Semantic output
prospective capture = binding/fact identity at Step 3 action; deterministic
                      Context projection at Stage producer return
legacy behavior = capability heuristic and Candidate truth IDs remain
                  compatibility evidence only
remaining ambiguity = exact Step 3 API/UI lifecycle requires post-freeze design;
                      no current action satisfies the contract
```

### Source Qualification

```text
natural scope = mixed: reusable content-quality and project-relative ownership
                fact versions plus Context observation projection
reusable fact = versioned by source/content/project-relative subject and
                qualification contract inputs as applicable
context projection = one closed result per exact Root source observation
source universe = fixed Context Root observations with exact SourceFetch versions
prospective capture = after SourceFetch at the scoped projection producer boundary
legacy behavior = global pre-fetch runner output remains PARTIAL/UNSAFE evidence
```

### Gap Review

```text
Gap output identity = immutable GapOutput ID + canonical manifest hash
review target = exact Gap output/hash and declared member partition
current legacy binding = UNSAFE; Prompt-level WorkflowConfirmation is not unique
prospective capture = Gap builder return and exact review request
correction semantics = new Gap output lineage followed by a separate review
```

### StrategyCandidate

```text
producer = _create_vertical_strategy_candidate() create transaction/return
exact output binding = exact candidate/machine Strategy output ID and hash plus
                       consumed upstream refs/hashes
effective_payload semantics = Legacy compatibility/materialized view, not output
                              identity; edited structure must become a new output
prospective capture = at Candidate create return and edited-output create return
implicit selection = forbidden
```

### Phase 1B

```text
capture-eligible stages = RUN_METRICS individually, after non-semantic instrumentation
blocked stages = all remaining stages directly or transitively under the gate
minimum end-to-end slice = one prospective Context expressing all 16 Stage types
acceptance rule = exact producer/input/output/review/dependency lineage for the
                  full slice; no inference, silent skip or production selection
```

### Legacy

```text
backfill = forbidden
UNSAFE allowed = yes, explicitly labeled and isolated from prospective lineage
latest fallback = forbidden
```

### Blocking Issues

```text
PROSPECTIVE_BINDING_PRODUCER_GAP
SOURCE_QUALIFICATION_SCOPE_AND_ORDER_CONFLICT
PROSPECTIVE_GAP_REVIEW_CAPTURE_GAP
CANDIDATE_EFFECTIVE_PAYLOAD_CONFLICT
EXECUTION_PROPOSAL_SELECTED_OUTPUT_GAP
SEM-CONFLICT-003
SEM-CONFLICT-004
```

### Safety

```text
production code diff = 0
Schema diff = 0
DB writes = 0
Phase 1B = NOT STARTED
```

## Author Disposition

```text
READY_FOR_DEFINITION_REVIEW
```
