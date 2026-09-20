# Definition Review: RFC-RUNTIME-001 Revision 001

```yaml
review_id: RFC-RUNTIME-001-REVIEW-002
reviewer_role: INDEPENDENT_RUNTIME_DEFINITION_REVIEWER
reviewed_at: 2026-09-09
reviewed_revision: 001
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
Read-only Projection Spike implementable
without semantic invention = NO
```

Revision 001 closes most of the architectural ambiguity found in Review 001.
It now separates Root, Stage, Attempt, Review, validity and current selection in
a coherent model. It does not yet close the construction and canonical identity
of the Root projection, the full behavior of several Stage contracts, concurrent
Stage completion authority, malformed Review graphs, or the per-Stage legacy
projection required from the fixed #19/#40 manifests.

Those are Definition issues because different conforming implementations can
produce different fingerprints, current eligibility, authoritative review or
legacy lineage results. SQL tables, indexes and worker technology remain outside
this review.

## Sources Reviewed

```text
docs/semantics/rfcs/RFC-RUNTIME-001.md (Revision 001)
docs/semantics/reviews/RFC-RUNTIME-001.review-001.md
docs/semantics/05_RUNTIME_SEMANTIC_MAP.md
docs/semantics/snapshots/CASE-REAL-019.manifest.json
docs/semantics/snapshots/CASE-REAL-040.manifest.json
backend/app/models/db.py
backend/app/modules/optimization/service.py
backend/geo_v0.db (read-only verification)
```

Fixed snapshot verification:

```text
database sha256 = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
#19 Package = 12@v8, Run count = 40, Candidate = 57
#40 Package = 15@v2, Run count = 6, Candidate = 50
latest substitution = NOT USED
```

## Review-001 Closure Verification

```text
B1 ROOT_STAGE_LEAKAGE = REOPENED
B2 CONTEXT_FINGERPRINT_GAP = REOPENED
B3 MINIMUM_STAGE_DAG_GAP = REOPENED
B4 CURRENT_REVIEW_SELECTION_GAP = REOPENED FOR REVIEW GRAPH;
                                  STAGE SELECTION CLOSED
B5 HUMAN_EDIT_LINEAGE_GAP = CLOSED
B6 INVALIDATION_REACTIVATION_GAP = CLOSED
B7 CACHE_COMPATIBILITY_GAP = CLOSED
B8 LEGACY_LINEAGE_PROJECTION_GAP = REOPENED
```

### B1 Root / Stage

The full Package payload is now correctly excluded from Root. However,
`browser_monitor_run_root_snapshot.v1` still selects Root fields through
downstream-dependent phrases:

```text
eligibility-relevant error/outcome fields
brand observation fields consumed by baseline metrics
timestamps when consumed by baseline window
required raw acquisition artifacts when named as consumed
```

`RUN_METRICS` configuration is expressly excluded from Root identity, so it
cannot determine which acquisition fields enter the Root snapshot. A Root
profile must freeze an unconditional field set or an unconditional acquisition
artifact rule. Otherwise two metric configurations can change Root content
without changing the Root profile, or an Implementer must consult Stage logic
while constructing Root.

### B2 Root Identity

The Context fingerprint payload and top-level canonical JSON rules are now
explicit. The nested `EvidencePackageRootProjection` identity is not yet fully
closed. The RFC does not give one exact semantic payload for
`evidence_package_root_projection_hash`; it describes a projection schema, an
envelope exclusion list and a generic “Root-safe content” set.

The following remain ambiguous:

```text
target_page_urls member identity, normalization, dedupe and order;
RunOriginalOutputSnapshot member semantic key and duplicate rule;
whether observation annotations enter semantic hash or audit envelope;
whether projection member refs/count/nested hashes enter semantic hash;
the exact null/absent rule for optional per-Run fields;
the `canonical_url_hash/url` fallback rule in observation member keys.
```

Therefore Package A and Package B with equivalent observed content can still
receive equal or unequal projection hashes depending on Implementer choices.
Package row identity itself is correctly excluded, and equal fingerprints with
different Package refs/Context ids are correctly allowed.

### B3 Stage Profile

The 16 Stage names, scope, dependency DAG, input/output classes and review units
are now fixed. This closes the former freedom to merge Answer/Binding or fold the
Candidate Builder into Alignment.

The profile is still not a complete executable semantic contract in three
places:

1. `SOURCE_FETCH`, `SOURCE_CLAIM` and `EVIDENCE_ALIGNMENT` completion rows allow
   per-member failure/block outcomes, but do not decide whether the whole Stage
   is `SUCCEEDED`, `PARTIAL/BLOCKED` or selectable, nor which downstream
   consumers may consume the remaining members.
2. Stage input/output set hashes have no versioned canonical member identity,
   sorting, dedupe and null contract. Naming `RunMetricManifest` or
   `GapManifest` does not by itself make `input_set_hash`/`output_set_hash`
   deterministic.
3. `PRODUCT_TRUTH_PROJECTION` says it freezes a Reason-scoped subset, but does
   not define the selection relation from Reason/capability scope to exact
   ProductTruth fact-value versions and explicit UNKNOWN members.

For example, given Project facts PT#1/#2/#3/#4 and Reasons requiring PT#1/#2,
one Implementer may use capability-key equality, another semantic-family
matching and another all target-brand facts. These produce different projections
and descendants while all satisfy the current text.

`RUN_METRICS` itself is a valid Stage, not a display-only pseudo Stage. It has
independent Root inputs, metric configuration, an immutable output manifest and
downstream consumers. The problem is the reverse leakage from its consumption
rules into Root construction, not its existence in the DAG.

### B4 Current And Review Authority

`ContextStageSelection` is now closed enough: selection is explicit, scoped,
optimistically versioned, never based on latest, never automatic after
RECOMPUTE, and blocked when the selected output becomes stale or invalid.
Compute success, current eligibility, review acceptance and selection are
separate checks.

The Review authority graph is not fully closed. Valid writes require the current
authoritative decision and expected state version, which prevents ordinary
branching. But the RFC does not declare supersession acyclic, single-parent, or
how imported malformed cycles are classified:

```text
R2 supersedes R3
R3 supersedes R2
```

Such a graph has zero non-superseded leaves and can currently be projected as
either PENDING, CONFLICT or invalid data. That changes review authority. The
definition must reject cycles and specify the projection state for malformed
historical graphs. It should also state that the review contract/version
required by the selected Stage Contract is the only authority scope considered;
parallel v1/v2 review scopes must not both silently qualify the same consumer.

### B5 Human Lineage

CLOSED. Review is a decision on immutable content; correction creates a new
Stage output or reusable fact-value version. The normative operation table gives
owner semantics for Decision Reason, Product Truth, Evidence relation, Binding,
Gap, Strategy and Execution Proposal. Product Truth correctly remains a
versioned reusable fact consumed by a new Context projection rather than being
forced into a new persistence model inside ReviewDecision.

### B6 Validity

CLOSED. `STALE` is a versioned/audited eligibility relation derived through
exact consumed edges. `INVALIDATED` is an explicit privileged event/relation
with target, prior state, reason, actor, time and optimistic version. Reactivation
preserves invalidation history, requires compatibility and does not automatically
restore descendants. Replacement branches stop propagation.

The storage choice between persisted projection and recomputable relation can
remain Implementation Design provided both expose the same audited state and
edge-driven result.

### B7 Cache

CLOSED. `semantic_cache_compatibility_signature.v1` requires exact semantic
input, normalization, semantic/materialization contract, prompt/schema,
provider/model revision or deterministic sentinels, deterministic config,
tools/extractors and upstream hashes. Exact equality is the only v1 hit rule;
missing or unverifiable fields miss. The per-Stage policy assigns Candidate
Builder TopK/tie/recall configuration to its signature, so a policy change also
changes its output dependency hash for Alignment.

The implementation profile still needs to enumerate concrete config fields, but
it may not choose their meaning or omit semantic-affecting fields. That is
Implementation Design under the stated all-fields rule, not a new semantic
equivalence rule.

### B8 Legacy Projection

The generic `COMPLETE/PARTIAL/UNSAFE/UNAVAILABLE` boundaries and the fixed Root,
Strategy, overall, Pointer and selection expectations for #19/#40 are now
correct. In particular, Candidate #57/#50 is a fixed projection target, not a
historical current winner.

The required Spike output nevertheless asks for all 16 Stage nodes, all
plausible source refs, available member manifests, review bindings, eligibility
and blocking reasons. Revision 001 freezes no legacy source-to-Stage mapping or
per-Stage expected projection for either fixed case. The Runtime Semantic Map
describes current object classes but does not decide, for example, which mutable
AnswerEvent/Binding/Claim/Alignment rows may be listed as one Stage's fixed
plausible sources without reconstructing them from current scope rules.

Implementers can therefore disagree on both the source set and the Stage-level
`PARTIAL/UNSAFE/UNAVAILABLE` result while still returning the mandated overall
`UNSAFE`. This remains a legacy interpretation decision, not merely a query
implementation detail.

## New Blocking Issues

### RT2-B1 RootProjection construction and identity are not closed

```text
category = ROOT_STAGE_LEAKAGE / IDENTITY_AMBIGUITY
RFC sections = 7.3-7.5
reopens = Review-001 B1, B2
```

**Required revision:** replace conditional downstream-consumption phrases with
an exact Root snapshot schema; define the exact semantic hash payload and every
nested manifest's canonical member key, sorting, duplicate and null rules.

### RT2-B2 Minimum Stage contracts still leave validity and hash choices

```text
category = MINIMUM_STAGE_CONTRACT_GAP
RFC sections = 8.2, 9.1, 9.4
reopens = Review-001 B3
```

**Required revision:** freeze per-Stage whole-execution outcome/selectability
for member failures/skips/blocks, partial-consumer policy for profile v1, and a
versioned canonical input/output manifest hash contract.

### RT2-B3 ProductTruthProjection member selection is undefined

```text
category = LINEAGE_GAP / FORBIDDEN_INFERENCE_RISK
RFC sections = 9.1, 15.2
reopens = Review-001 B3
```

**Required revision:** define or reference a versioned selector that emits the
exact Reason-to-fact/UNKNOWN member mapping, including member identity, conflict
behavior and projection hash. Do not let the Spike infer relevance from labels
or current ProductTruth rows.

### RT2-B4 StageAttempt completion authority has a lease race

```text
category = ATOMICITY / EXECUTION_AUTHORITY_GAP
RFC sections = 8.3-8.7, 17
new blocker = YES
```

**Counterexample:** Attempt A loses/lets its lease expire; Attempt B reclaims the
same StageExecution; A submits output late while B also succeeds. Atomic output
publication and one active owner do not say whether only the current lease owner
may commit or which attempted output can win.

**Required revision:** require one authoritative successful completion per
StageExecution, condition completion on current attempt/lease authority, reject
late/lost-lease commits, and keep losing Attempt output only as non-semantic
attempt audit if retained. The SQL locking technique remains deferred.

### RT2-B5 Review supersession graph validity is incomplete

```text
category = REVIEW_GRAPH_GAP
RFC sections = 12.4-12.5
reopens = Review-001 B4
```

**Required revision:** declare the supersession graph append-only, acyclic and
single-parent; reject a self/future/cross-scope supersedes edge; classify any
imported cycle or malformed edge as `REVIEW_CONFLICT` or a separately named
blocking invalid state. Bind each consuming Stage Contract to the exact review
contract/version authority scope it accepts.

### RT2-B6 Legacy Stage mapping and virtual hash identity are not deterministic

```text
category = LEGACY_PROJECTION_GAP / IDENTITY_AMBIGUITY
RFC sections = 20.4-20.6, 28
reopens = Review-001 B8
```

**Required revision:** for #19/#40, freeze the source mapping rule and expected
projection class for every Stage, or explicitly require `selected=null` and list
the exact fixed source-ref sets for stages that cannot be uniquely mapped.
Define canonical serialization, sorting and duplicate rules for
`source-ref-set-hash` and virtual identity. A virtual ID may be omitted for an
ambiguous winner, but repeated projection of a uniquely mapped source set must
produce the same ID.

## RootProjection

```text
construction closed = NO
freeze boundary closed = YES
deterministic identity = NO
Package row identity excluded from semantic equivalence = YES
same semantic projection may share fingerprint across Contexts = YES
```

The `AFTER_ACQUISITION_ROOT_PROJECTION_FREEZE` boundary is adequate: a formal
Context cannot become executable until immutable Run/Reference/Retrieval and
artifact snapshots plus hashes are atomically visible. Current mutable Run rows
cannot substitute after creation. The remaining defect is deciding the exact
snapshot and its identity before that boundary.

## RuntimeStageProfile

```text
16 nodes valid = YES
RUN_METRICS is a real Stage = YES
input/output contracts sufficient = NO
DAG sufficient = YES
review gate topology sufficient = YES
```

## Current

```text
context pointer = CLOSED
stage selection = CLOSED
selection vs compute eligibility vs review = CLOSED
review authority = NOT CLOSED FOR MALFORMED/CROSS-VERSION GRAPH
latest fallback = FORBIDDEN / CLOSED
```

A `SUCCEEDED` output with required Review pending may exist and remain
compute-valid, but cannot be selected for formal production consumption. A
selected output whose review is reopened blocks current consumption; descendants
that consumed the superseded review become stale through their exact edges.

## Human Lineage

```text
review vs correction = CLOSED
correction owner semantics = CLOSED
Product Truth reusable-version boundary = CLOSED
```

## Validity

```text
STALE representation = CLOSED AS VERSIONED/AUDITED ELIGIBILITY RELATION
INVALIDATED = CLOSED AS IMMUTABLE PRIVILEGED EVENT/RELATION
reactivation = CLOSED
dependency propagation = CLOSED
replacement branch stops stale propagation = YES
automatic descendant reactivation = FORBIDDEN
```

## Cache

```text
stage-declared compatibility = CLOSED
materialization contract change forces mismatch = YES
Candidate Builder policy change enters signature = YES
legacy missing signature field = LEGACY_COMPATIBILITY_UNKNOWN / MISS
relaxed v1 equivalence = FORBIDDEN
```

## Legacy Projection

```text
PARTIAL/UNSAFE boundary = CLOSED
#19 Root/Strategy/overall expectation = CLOSED
#40 Root/Strategy/overall expectation = CLOSED
16-node per-Stage source mapping = NOT CLOSED
unsafe behavior = PARTIALLY CLOSED
```

When overall lineage is `UNSAFE`, the Spike may show fixed Root facts, uniquely
known partial projections, candidate source refs, diagnostics and warnings. It
must not select a winner, declare readiness, declare authoritative Strategy or
mint a current Pointer/Stage selection. These prohibitions are closed; the exact
per-Stage facts that qualify for display are not.

## Virtual Projection

```text
identity = NOT CLOSED
stable replay = NOT PROVABLE FOR UNIQUE STAGE SOURCE SETS
production isolation = CLOSED
```

Virtual Context/Stage identities are forbidden consumers for Review, Strategy,
Action, Experiment, cache and current production APIs. That isolation is sound.

## Golden Determinism

```text
root fingerprint deterministic = NO
stage input/output hash deterministic = NO
virtual source-ref-set hash deterministic = NO
fixed #19/#40 latest isolation = YES
```

The fixed #19/#40 formal Root and Stage hashes correctly remain null. That does
not test the new deterministic contracts. Add synthetic concrete manifests with
expected hashes after the hash rules are closed; do not reconstruct missing
legacy hashes with current code.

## Open Decisions

### Definition Blockers

```text
exact unconditional Root snapshot field contract;
exact RootProjection semantic hash payload and nested canonicalization;
per-Stage member-failure/selectability and partial-consumer semantics;
versioned Stage input/output manifest hash contract;
ProductTruthProjection selector/member identity;
authoritative StageAttempt completion under lease reclaim;
Review supersession graph validity and active contract-version scope;
#19/#40 per-Stage legacy source mapping and virtual identity hash.
```

### Implementation-only

```text
SQL table and column names;
indexes and ORM mappings;
database-specific compare-and-swap/locking SQL;
lease duration and worker runtime;
API paths and response DTO names;
JSON serialization library implementing the frozen canonical contract;
physical event table versus equivalent append-only relation storage;
attempt log transaction placement outside the semantic output commit boundary.
```

## Spike Readiness

```text
Read-only Projection Spike implementable
without semantic invention = NO
```

The Spike must not start. Its output would currently encode reviewer/implementer
choices in Root hashes, Product Truth membership, per-Stage legacy mappings and
virtual IDs, defeating its purpose as a test of the proposed semantics.

## Freeze Recommendation

```text
Freeze Recommendation = NO
```

Return the six blocking issues to the RFC Author. Do not modify production code,
schema or database; do not implement the Spike; do not freeze the RFC. After a
focused Revision 002, repeat independent Definition Review against the same
fixed #19/#40 manifests.
