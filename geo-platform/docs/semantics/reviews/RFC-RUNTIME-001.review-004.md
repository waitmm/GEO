# RFC-RUNTIME-001 Definition Review 004

```yaml
review_id: RFC-RUNTIME-001-REVIEW-004
reviewer_role: INDEPENDENT_RUNTIME_DEFINITION_REVIEWER
reviewed_at: 2026-09-09
reviewed_revision: 003
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

Revision 003 closes the Product Truth binding authority gap and makes the
canonical scalar/collection byte grammar and all 16 legacy row selectors
substantially mechanical. Two hash-affecting choices remain undefined: the
non-configuration `input_role` literals in future Stage input manifests, and
the canonical object shape of each legacy source member's
`fixed_scope_values`. Those choices allow independent Implementers to hash the
same semantic inputs differently.

This review does not reopen B1, B4, B5, the Runtime DAG, attempt fencing,
review authority, invalidation, current selection, completeness aggregation,
or frontend/backend authority.

## Sources Reviewed

```text
docs/semantics/rfcs/RFC-RUNTIME-001.md (Revision 003)
docs/semantics/reviews/RFC-RUNTIME-001.review-003.md
docs/semantics/snapshots/CASE-REAL-019.manifest.json
docs/semantics/snapshots/CASE-REAL-040.manifest.json
backend/app/models/db.py
backend/app/modules/optimization/service.py
backend/geo_v0.db (read-only verification)
```

Fixed snapshot verification:

```text
database sha256 = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
#19 Package = 12@v8, Runs = 40, Events = 99
#19 PromptAnalysisRuns = 13, ShadowRuns = 13, fixed-run Alignments = 32997
#19 Candidate = 57, status = ACCEPTED
#40 Package = 15@v2, Runs = 6, Events = 24
#40 PromptAnalysisRuns = 1, ShadowRuns = 7, fixed-run Alignments = 660
#40 Candidate = 50, status = PENDING_REVIEW
#40 candidate_input_contract_hash = null
latest substitution = NOT USED
```

## B2

```text
canonical bytes deterministic = YES
16-stage member identities = NO
hash envelope = YES
virtual identity stability = NO

result = REOPENED_BLOCKER
```

The byte-level contract at RFC lines 337-471 now freezes UTF-8 behavior,
Unicode and line-ending handling, typed scalar framing, object-key order,
field states, set/order behavior, duplicate handling, SHA-256, and the typed
hash envelope. The grammar is prefix/length framed, so examples such as
`["a", "bc"]` and `["ab", "c"]` cannot collide through delimiter ambiguity.
The no-Unicode-normalization rule is explicit and correctly leaves any
upstream normalization to a versioned owning Stage Contract.

The remaining failure is in the Stage input member identity registry. The
common identity at RFC lines 1064-1072 includes the exact `input_role`, but the
16-row table at lines 1078-1095 does not assign exact non-configuration role
literals to its input sources. Only `CONFIGURATION` is fixed at line 1076.

For the same `RUN_METRICS` BrowserMonitorRun input, for example, one compliant
Implementer can emit:

```text
input_role = RUN
```

while another can emit:

```text
input_role = ROOT_RUN
```

Both can use the same registered source manifest type/ref/version/hash and the
same specialization described in the table, but the common member identity
and Stage `input_set_hash` differ. The same freedom exists wherever a Stage has
multiple named source classes, including GAP and STRATEGY_SYNTHESIS.

This is a definition-level identity choice, not a Python/SQL implementation
choice. Revision 003 must either freeze an exact input-role token matrix for
all 16 Stage contracts or normatively derive the token from an already frozen
field. Until then, the required 16/16 mechanical identity test fails.

The virtual Context formula is byte-stable in isolation, but virtual Stage and
future Stage identity stability cannot receive an unconditional PASS while a
Stage input identity component remains implementation-selected.

## B3

```text
formal binding source = YES
producer = YES
identity = YES
version lifecycle = YES
legacy heuristic isolation = YES
UNRESOLVED = YES
consumer discipline = YES

result = VERIFIED_CLOSED
```

Revision 003 now separates the observed historical mechanism from future
formal authority:

```text
historical production = capability text/token heuristic and Candidate hints
formal future source = immutable Step 3 human binding confirmation
```

`reason_product_truth_binding.v1` is explicitly a CANDIDATE,
NOT_IMPLEMENTED logical Contract, which is valid at Definition Review. RFC
lines 1186-1241 freeze its unique producer, required Reason and fact-version
refs/hashes, target-brand identity, assertion, human confirmation metadata,
semantic identity, validity conditions, and forbidden heuristic/LLM/project
scan paths.

Binding and projection are no longer conflated. The binding is the reusable
Reason-to-ProductTruth relation fact; `PRODUCT_TRUTH_PROJECTION` is the unique
Runtime Stage producer that consumes exact selected binding/fact versions for
one Context. GAP, CHANNEL_RESOLUTION, STRATEGY_SYNTHESIS and
EXECUTION_PROPOSAL may consume only that projection and may not rematch.

No binding produces an explicit `UNRESOLVED` member rather than dropping the
Reason. FALSE, PARTIALLY_SUPPORTED and UNKNOWN fact versions remain explicit.
Corrections append new Reason, fact, binding and projection lineage rather than
mutating history.

Candidate 57/50 `product_truth_ids` remain historical hints with no binding
authority. The fixed legacy Product Truth projections therefore remain UNSAFE;
the Spike is forbidden to rerun today's text heuristic to upgrade them.

B3 final answers:

```text
reason_product_truth_binding.v1 Source of Truth = YES
Producer = YES
Identity = YES
Lifecycle/versioning = YES
Legacy compatibility semantics = YES
```

## B6

```text
16-stage exact selectors = YES FOR ROW/JSON SOURCE SELECTION
ambiguous selectors = 0
latest fallback = 0
JSON paths = YES
source-set hash = NO
#19 = FIXED SOURCES/EXPECTATIONS VERIFIED; HASH NOT YET UNIQUE
#40 = FIXED SOURCES/EXPECTATIONS VERIFIED; HASH NOT YET UNIQUE

result = REOPENED_BLOCKER
```

The fixed symbols M/P/R/C/O/S/D/Q, case-specific Candidate JSON columns,
integer-array rules, exact JSON path sets, ProductTruth hint-id extraction,
required version/hash-state fields, and all 16 selector predicates are now
mechanical. Multiple rows are retained, fixed objects are verified rather than
replaced, and there is no latest/current winner fallback. Candidate 50's absent
PR4 contract/hash values remain absent under the fixed rule.

The remaining ambiguity is inside the hashed legacy source member itself. RFC
lines 2146-2156 require:

```text
fixed_scope_values = the exact predicate values that admitted the row
```

but do not freeze the field's canonical object keys or value shape. For one
`recommendation_events` row admitted by project/prompt equality plus
`run_id IN R`, two Implementers can both truthfully encode the stated predicate
values as, for example:

```text
{project_id, prompt_id, selected_run_id}
```

or:

```text
{manifest_project_id, manifest_prompt_id, allowed_run_ids}
```

The selected row and `source_ref` are identical, but the canonical source
member bytes and `source_ref_set_hash` differ. Similar choices exist for tuple
joins through O/D/Q and intersections through materialization observation
arrays.

Because `fixed_scope_values` is part of every source member and the canonical
member array is part of the hash payload at RFC lines 2172-2188, this is a B6
source-manifest identity blocker even though the 16 database selectors
themselves are now exact. Revision 003 must freeze one normative
`fixed_scope_values` schema/derivation for each selector class, or remove that
field from semantic hashing in a versioned contract. The reviewer does not
select either design.

The fixed database and Manifests still support the stated expectations:

```text
#19 Stage counts = COMPLETE 0 / PARTIAL 6 / UNSAFE 9 / UNAVAILABLE 1
#19 STRATEGY_LINEAGE overall = UNSAFE
#40 Stage counts = COMPLETE 0 / PARTIAL 7 / UNSAFE 8 / UNAVAILABLE 1
#40 STRATEGY_LINEAGE overall = UNSAFE
```

An UNSAFE result remains a valid Spike outcome. The blocker is only that the
same fixed outcome cannot yet be accompanied by one uniquely reproducible
legacy `source_ref_set_hash` and virtual Stage identity.

## New Contradictions

```text
NONE
```

Revision 003 does not directly contradict the already verified Runtime,
Attempt, Review, invalidation, completeness, current-selection, or backend
authority semantics.

## Implementation-only Notes

```text
physical table/column representation for reason_product_truth_binding.v1
binding_version_id allocation mechanism
ORM models and indexes
SQL/CAS and locking details
canonicalization helper/library names
query organization and performance
API route and DTO names
```

These do not block Definition Freeze and were not used to reopen B2 or B6.

## Final Recommendation

```text
REVISE
```

A new Implementer can now choose the same legacy database rows and can
implement the same Product Truth authority model, but still must invent:

```text
the exact non-configuration input_role token for Stage input members;
the canonical fixed_scope_values object placed in legacy source members.
```

Therefore Revision 003 has not yet reached the standard that a new Implementer
can build the Read-only Projection Spike from the RFC with no semantic
invention. Return only these two narrow identity closures to the RFC Author.
Do not Freeze, start Spike B, change schema/data, or modify production behavior.
