# RFC-RUNTIME-001 Definition Review 003

```yaml
review_id: RFC-RUNTIME-001-REVIEW-003
reviewer_role: INDEPENDENT_RUNTIME_DEFINITION_REVIEWER
reviewed_at: 2026-09-09
reviewed_revision: 002
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
Spike implementable without semantic invention = NO
```

Revision 002 closes Root membership leakage, immutable snapshot behavior,
Attempt completion authority, Review supersession, and the fixed
`STRATEGY_LINEAGE` completeness roll-up. Three Definition gaps remain. They
permit independent Implementers to produce different hashes, recognize
different Product Truth binding authorities, or enumerate different legacy
source sets while each appears to follow the RFC.

This review does not reopen the stable Runtime object model and does not require
a storage design, ORM model, SQL fencing implementation, migration, or
production cutover.

## Sources Reviewed

```text
docs/semantics/rfcs/RFC-RUNTIME-001.md (Revision 002)
docs/semantics/reviews/RFC-RUNTIME-001.review-001.md
docs/semantics/reviews/RFC-RUNTIME-001.review-002.md
docs/semantics/00_DOMAIN_MODEL.md
docs/semantics/01_SEMANTIC_CONTRACTS.md
docs/semantics/03_DEFINITION_REVIEW_CHECKLIST.md
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
#40 candidate_input_contract_hash = null
latest substitution = NOT USED
```

## Review-002 Closure Verification

```text
B1 ROOT_PROJECTION_SELECTION_LEAKAGE = VERIFIED_CLOSED
B2 DETERMINISTIC_MANIFEST_IDENTITY_GAP = REOPENED_BLOCKER
B3 PRODUCT_TRUTH_PROJECTION_SELECTION_GAP = REOPENED_BLOCKER
B4 STAGE_ATTEMPT_COMPLETION_AUTHORITY_GAP = VERIFIED_CLOSED
B5 REVIEW_SUPERSESSION_CONTRACT_GAP = VERIFIED_CLOSED
B6 LEGACY_STAGE_PROJECTION_GAP = REOPENED_BLOCKER
```

## Root

```text
membership intrinsic = YES / VERIFIED_CLOSED
snapshot immutable = YES / VERIFIED_CLOSED
manifest deterministic = NO / REOPENED_BLOCKER
```

Root membership is now determined only by the Context creation boundary,
original Prompt/Acquisition/Run lineage, immutable snapshot availability, and
independence from Step 2-8 outputs. Baseline, metric, Strategy, or downstream
consumer need no longer promotes a field into Root.

`EvidencePackageRootProjection` is also unambiguously a fixed immutable
snapshot. Re-querying Package, Prompt, Run, Reference, Retrieval, or artifact
tables to rebuild an existing projection is forbidden. Later Product Truth,
Document, Alignment, or Package API mutation therefore cannot alter an existing
Root projection.

The remaining Root defect is deterministic identity, not membership or
immutability. `semantic_manifest_canonicalization.v1` specifies ordering and
scalar intent but does not specify the exact canonical byte representation to
which SHA-256 is applied. In particular, the RFC does not freeze:

```text
the serialized shape of FIELD_ABSENT/FIELD_PRESENT_NULL/VALUE/EMPTY_COLLECTION;
object/array delimiters, string escaping and canonical JSON byte rules;
finite-decimal edge-case normalization and normative examples;
the interpretation of source timestamps that have no timezone offset;
the concrete target-URL canonicalization contract/version and algorithm.
```

Two implementations can therefore satisfy the prose while producing different
Root, Stage, Review, legacy source-set, and virtual-identity hashes.

## ProductTruth Projection

```text
binding source = CONTRACT_GAP
selection deterministic = CONDITIONAL ONLY; NOT CLOSED
UNKNOWN/FALSE = PRESERVED / PASS
legacy version risk = EXPLICIT PARTIAL/UNSAFE / PASS
```

Given a valid immutable `reason_product_truth_binding.v1` manifest, the member
selection rule is now deterministic: only bound facts enter, every unbound
Reason emits `UNRESOLVED`, conflicts block consumption, and
PARTIALLY_SUPPORTED/FALSE/UNKNOWN remain explicit members.

The binding manifest itself, however, has no existing formal Source of Truth.
Repository search finds no registered Contract or persisted binding object with
this identity. The observed schema has one mutable
`TargetBrandCapabilityTruth` row per project/brand/capability and production
code still contains heuristic Reason/text-to-truth matching. Neither can satisfy
the proposed formal binding contract.

Revision 002 defines a binding member shape, but does not define or reference:

```text
the producer/owner of the reusable binding;
the authoritative source object or candidate-contract status;
how a binding becomes formally valid rather than merely supplied;
the immutable binding version lifecycle and correction authority.
```

The legacy profile correctly says Candidate hints cannot become `BOUND` and
that historical Product Truth versions are unavailable. That prevents a
forbidden legacy inference, but it does not turn the named future binding into
an existing or fully defined Candidate Contract.

## Attempt Authority

```text
fencing closed = YES
late attempt = AUDIT-ONLY; CANNOT PUBLISH
single completion = EXACTLY ONE AUTHORITATIVE SUCCESS
```

The monotonic `attempt_authority_generation`, current-generation publication
condition, immutable successful completion, and single atomic publication
invariant determine the winner in the lease-reclaim race. SQL/CAS mechanics are
properly left to Implementation Design.

## Review Chain

```text
linear = YES
branch = ONE WRITER SUCCEEDS; OTHER REVIEW_CONFLICT
cycle = REVIEW_CONFLICT_INVALID_GRAPH
cross-target = INVALID
contract-version boundary = SEPARATE TARGET LINEAGE
```

The exact ReviewTarget, one-predecessor append-only chain, expected state
version, invalid graph handling, and contract-version separation close Review
authority. Review remains a decision over immutable output; correction/edit
creates new semantic lineage.

## Legacy Profile

```text
16-stage mapping complete = NO / REOPENED_BLOCKER
latest fallback = FORBIDDEN / PASS
#19 = fixed expected classes and UNSAFE roll-up; source-set identity not closed
#40 = fixed expected classes and UNSAFE roll-up; source-set identity not closed
```

Revision 002 now supplies all 16 Stage rows, fixed #19/#40 expected classes,
allowed projections, forbidden interpretations, and no-latest rules. It also
correctly leaves all `ContextStageSelection` values null and all formal legacy
review authority unresolved unless immutably hash-bound.

The remaining defect is the exact source manifest, not the expected class. The
generic source member key includes “Stage-specific fixed-scope semantic identity
fields named below,” but several rows do not actually enumerate those fields or
their payload extraction paths. Examples include:

```text
matching current docs/quality rows;
matching claim materializations/claims;
matching ShadowResults and matching materialization rows;
benchmark/gap/channel fields embedded in the fixed Candidate payload;
fixed Reason/ProductTruth hints named by Candidate payload.
```

The per-case tables repeat these labels and counts, but do not freeze exact
source refs, exact JSON field paths, or a complete mechanical selector/member
schema. An Implementer can include a different set of matching materialization
rows or a different Candidate subtree and still report the required Stage class
and overall `UNSAFE`. This changes `source_ref_set_hash`, virtual Stage identity,
known-fact output, and diagnostics.

## Completeness

```text
objectives defined = YES FOR THIS SPIKE: STRATEGY_LINEAGE
critical stages defined = YES: Root + 15 Stages through STRATEGY_SYNTHESIS
aggregation deterministic = YES
UNSAFE behavior = CLOSED
PARTIAL behavior = CLOSED FOR FIXED SPIKE TARGETS
UNAVAILABLE behavior = CLOSED
```

The RFC is allowed to define only the objective exercised by Spike B. It
explicitly fixes `STRATEGY_LINEAGE`, its current-critical closure, and the
precedence:

```text
unreadable fixed Root object -> UNAVAILABLE
else critical UNSAFE -> UNSAFE
else critical UNAVAILABLE -> UNAVAILABLE
else any Root/critical PARTIAL -> PARTIAL
else COMPLETE
```

This is deterministic even though it differs from a generic severity ordering.
Future `ROOT_LINEAGE`, `EXECUTION_LINEAGE`, or `CURRENT_STATE` objectives require
new versioned rules when they enter scope; they are not required to implement
the currently authorized fixed Strategy projection.

For `UNSAFE`, authoritative Strategy/current selection/actions are forbidden.
For the fixed PARTIAL Stage projections, known immutable refs may be displayed
as non-authoritative history with null missing fields. For `UNAVAILABLE`, the
exact missing fixed ref is reported and no replacement is queried.

## Virtual Projection

```text
identity deterministic = NO
profile-version-bound = YES
production isolation = YES
```

Virtual Context and Stage identities include the projection profile version and
are isolated from production Review, Strategy, Action, Experiment, Pointer, and
cache consumers. Their hash inputs are not yet deterministic because the common
canonical byte contract and several legacy `source_ref_set` member definitions
remain open.

## Spike Value

```text
#19 UNSAFE still useful = YES
#40 UNSAFE still useful = YES
```

Spike PASS does not require either historical case to become COMPLETE. A valid
Spike can still prove Root projection behavior, expose all 16 Stage mappings,
show the first unsafe lineage boundary, report review binding gaps, prove that
Candidate omission is not NO_SUPPORT, and return null current Pointer/selection
without fallback. The blockers above concern whether those outputs can be
produced identically by independent Implementers.

## New Blocking Issues

### RT3-B1 Canonical hash bytes and Stage member identities are not closed

```text
category = IDENTITY_SCOPE_DRIFT / DETERMINISTIC_MANIFEST_IDENTITY_GAP
RFC sections = 7.3-7.5, 9.1, 20.4-20.6
reopens = Review-002 B2
```

`semantic_manifest_canonicalization.v1` must define one exact serialized byte
contract, or normatively bind to an existing canonical format and provide
conformance vectors. Field-state envelopes, timestamp/decimal edge cases, and
the target-URL canonicalization version must not be selected by the
Implementer.

The Stage profile must also define or reference exact versioned contracts for
identity terms that are currently labels rather than mechanical identities,
including at least:

```text
normalized semantic-content hash;
normalized claim tuple hash;
binding scope key;
qualification subject/rule key;
signal source identity;
strategy structural identity and channel-portfolio member key;
proposal asset logical key and portfolio-decision key.
```

It is sufficient to reference exact owning Stage contracts; this RFC need not
duplicate every field. An undefined phrase is not an exact member identity.

### RT3-B2 Product Truth binding has no formal Source of Truth

```text
category = CONTRACT_GAP / FORBIDDEN_INFERENCE_RISK
RFC sections = 9.1 Product Truth Projection Selector, 15.2, 20.4
reopens = Review-002 B3
```

Define or reference `reason_product_truth_binding.v1` as an explicit Candidate
Contract with Source of Truth, producer/owner, immutable identity/version,
validity/authority rule, correction behavior, and allowed consumer. It may
remain a reusable input rather than a new Runtime Stage or table. Existing
heuristic matching and Candidate payload hints must remain forbidden substitutes.

### RT3-B3 Legacy source selectors and source manifests remain under-specified

```text
category = LEGACY_STAGE_PROJECTION_GAP / IDENTITY_AMBIGUITY
RFC sections = 20.4, 20.6, 20.7
reopens = Review-002 B6
```

For each affected Stage, freeze either:

```text
the exact #19/#40 source-ref set in the immutable case Manifest;
```

or:

```text
an exact mechanical selector, relation/JSON paths, source member payload schema,
and expected source_ref_set_hash/conformance result.
```

The Stage expected completeness tables and row counts remain valid but do not
replace deterministic source-set identity.

## Non-blocking Implementation Notes

```text
database table/column names for future formal Runtime objects;
ORM mappings and indexes;
SQL compare-and-swap or lock implementation;
lease duration, heartbeat interval and worker technology;
canonical JSON library chosen to implement the frozen byte contract;
API route and response DTO names;
physical event-table versus equivalent append-only relation storage;
Section 17 contains a duplicated initial-claim generation sentence;
future objectives outside the fixed STRATEGY_LINEAGE Spike scope.
```

## Open Decisions

```text
definition = canonical bytes and identity subcontracts;
             Product Truth binding Source of Truth;
             exact legacy source manifests/selectors

implementation = storage shape;
                 ORM/index design;
                 CAS/locking SQL;
                 executor/lease mechanics;
                 endpoint/DTO naming;
                 read-only query organization
```

## Final Recommendation

```text
REVISE
```

Return only RT3-B1 through RT3-B3 to the RFC Author. Preserve all verified
closures and the fixed #19/#40 expected completeness results. After a focused
Revision 003, repeat independent Definition Review against the same snapshot
Manifests and exact database hash.

Do not Freeze, implement Spike B, modify production code/schema, migrate data,
or cut over while these three Definition choices remain open.
