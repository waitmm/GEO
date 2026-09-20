# RFC-RUNTIME-001 Definition Review 005

```yaml
review_id: RFC-RUNTIME-001-REVIEW-005
reviewer_role: INDEPENDENT_RUNTIME_DEFINITION_REVIEWER
reviewed_at: 2026-09-09
reviewed_revision: 004
reviewed_rfc_status: DRAFT
reviewed_rfc_maturity: CANDIDATE
reviewed_implementation_status: NOT_IMPLEMENTED
review_scope:
  - B2_DETERMINISTIC_MANIFEST_IDENTITY_GAP
  - B6_LEGACY_STAGE_PROJECTION_GAP
production_code_changes: 0
schema_changes: 0
database_writes: 0
spike_started: false
review_prompt_erratum: NON_SEMANTIC_REVIEW_PROMPT_TRANSCRIPTION_ERROR
```

## Status

```text
Status = APPROVED
Freeze Recommendation = YES
Spike implementable without semantic invention = YES
```

Revision 004 closes the two identity gaps reopened by Review 004. An
independent Implementer can derive every Stage input role and every legacy
fixed selector scope from the RFC without choosing a literal, object shape,
ordering rule, hash payload or historical winner.

This review does not reopen B1, B3, B4, B5, the Runtime DAG, attempt fencing,
review authority, invalidation, current selection, completeness aggregation,
or frontend/backend authority.

## Sources Reviewed

```text
docs/semantics/rfcs/RFC-RUNTIME-001.md (Revision 004)
docs/semantics/reviews/RFC-RUNTIME-001.review-004.md
docs/semantics/snapshots/CASE-REAL-019.manifest.json
docs/semantics/snapshots/CASE-REAL-040.manifest.json
backend/geo_v0.db (identity verification only)
```

Fixed snapshot verification:

```text
database sha256 = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
#19 fixed input = Package 12@v8, 40 Run ids, Candidate 57 ACCEPTED
#40 fixed input = Package 15@v2, 6 Run ids, Candidate 50 PENDING_REVIEW
#40 candidate_input_contract_hash = null
latest substitution = NOT USED
```

## B2

```text
StageInputRole.v1 = UNIQUE LEGAL ROLE REGISTRY
literal count = 5
16-stage coverage = 16/16
input categories = 74/74
unregistered role assignments = 0
duplicate Stage/source-class assignments = 0
CONFIGURATION assignments = 16/16, exactly one per Stage
free-form roles = 0
aliases/localized labels in canonical bytes = FORBIDDEN
canonical member identity = COMPLETE
independent input_set_hash recalculation = MATCH

result = VERIFIED_CLOSED
```

The five literals are exactly:

```text
ROOT_MANIFEST
UPSTREAM_STAGE_OUTPUT
REUSABLE_INPUT
AUTHORITATIVE_REVIEW
CONFIGURATION
```

The normative Stage/Input Role matrix makes the role decision before
implementation. In particular, every Stage configuration has exactly one
`CONFIGURATION` row, while reusable objects, upstream outputs, Root manifests
and authoritative reviews have their own explicit matrix assignments. The
common member identity includes the role, source type, immutable source ref,
source contract version and consumed semantic hash.

The RFC's prefix grammar, typed field states, UTF-8 object-key ordering, SET
ordering and exact hash envelope remove delimiter, language-representation and
unordered-map choices from Stage input canonicalization.

## B6

```text
LegacyFixedScopeValues.v1 = COMPLETE
LegacyScopeKey.v1 keys = 15/15
value kinds = 5/5
canonical structure = ONE FOUR-FIELD OBJECT
16-stage scope profiles = 16/16
16-stage selector registry match = 16/16
unknown scope keys = 0
optional scope keys = 0
free-form scope = 0
latest/current winner = 0
source member identity = MECHANICAL
fixed_scope hash = MATCH
source_ref_set hash = MATCH
independent recalculation = MATCH

result = VERIFIED_CLOSED
```

The closed value-kind registry is exactly:

```text
SCALAR_ID
VERSION_INTEGER
SET_ID_LIST
SHA256
STRING
```

Each selector consumes one fixed scope profile with a complete required-key
set and no optional keys. Missing required Manifest values produce
`UNAVAILABLE`; competing lineage produces `UNSAFE`. Null wildcards, inferred
replacement, greatest-id/time selection and current/latest winner logic are
forbidden.

The two identity responsibilities are separate:

```text
fixed_scope_values
= the complete legal read boundary for one selector

source member identity
= the exact object admitted into the Stage projection
```

The fixed scope cannot select a winner. Each admitted member binds the exact
scope hash, and the member identity is the frozen tuple of projection profile,
Stage, selector, scope profile, fixed scope hash, source ref and source kind.
Equal identities with different content make the Stage `UNSAFE`; neither first
nor last wins.

For #19 and #40, the immutable case Manifest, exact database identity and
legacy projection profile determine the same fixed scopes, source sets,
`source_ref_set_hash` values and virtual identities on every replay. Candidate
50's missing newer lineage fields remain absent and cannot be replaced from a
newer Candidate.

Virtual identities use the `virtual:` namespace and bind the projection
profile and `source_ref_set_hash`. They are restricted to display, comparison
and Golden validation. Production pointers, reviews, Strategy, Action,
Experiment, cache and PR5 consumers are forbidden.

## Normative Vectors

```text
input_set_hash:
expected = dba2155c917c74e7f297ad0e5fe9a8639ef3f2f8289e3511fcc84e0d96cce10e
actual   = dba2155c917c74e7f297ad0e5fe9a8639ef3f2f8289e3511fcc84e0d96cce10e
MATCH

fixed_scope_hash:
expected = d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66
actual   = d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66
MATCH

source_ref_set_hash:
expected = 543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483
actual   = 543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483
MATCH
```

The values above were rebuilt from semantic objects with an independent
canonicalizer, then compared byte-for-byte with the RFC's normative canonical
lines before hashing. All three canonical byte comparisons also match.

The Review-005 request text quotes the `source_ref_set_hash` as
`543fa710799ecc38c938ef4437248298216789268bff3ae90803594e9be34d831`.
That value is not the Revision 004 RFC expected value and does not hash the
RFC's normative canonical bytes. It is a review-request transcription error,
not an RFC contract ambiguity. The RFC value ending in `a483` is independently
reproducible.

```text
erratum_classification = NON_SEMANTIC_REVIEW_PROMPT_TRANSCRIPTION_ERROR
```

## New Contradictions

```text
NONE
```

Revision 004 does not change the previously verified Runtime semantics and
does not weaken virtual projection isolation or the no-latest rule.

## Implementation-only Notes

```text
physical schema and ORM representation
canonicalization helper/library placement
selector query organization and performance
API route and projection DTO names
read-only Spike diagnostics and rendering
```

These choices remain Implementation Design. None requires a new semantic
literal, scope shape, canonicalization rule or legacy selection rule.

## Final Recommendation

```text
APPROVE
```

```text
Status = APPROVED
Freeze Recommendation = YES
Read-only Projection Spike implementable without semantic invention = YES
```

Definition Review ends here. Product Owner Definition Freeze remains a
separate decision. This approval does not Freeze the RFC, authorize the Spike,
change schema/data, or authorize production cutover. No Review 006 is needed.
