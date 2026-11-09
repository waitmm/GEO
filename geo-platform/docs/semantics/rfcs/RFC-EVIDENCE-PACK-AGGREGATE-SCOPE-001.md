# RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001 — Structured observation scope and evidence-set binding

```yaml
rfc_id: RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001
status: PROPOSED
semantic_maturity: REVIEW_REQUIRED
implementation_status: NOT_STARTED
change_class: SEMANTIC_CHANGE
authors: [GEO M1.2]
created_at: 2026-11-09
definition_approved_by: null
definition_approved_at: null
production_cutover_approved_by: null
affected_contracts:
  - geo.evidence-pack.execution.v11
  - geo.evidence-pack.validation.v4
  - RFC-EVIDENCE-PACK-QUALITY-GATE-001
supersedes: null
```

## Problem

The third real HELP_DOC + FAQ request produced valid bare locators and usable draft structure, but an aggregate
22-answer brand observation bound only two full-answer locators. Validation v4 rejected the result. Protected
replay then showed that v4 detected aggregate scope from an adjacent limitation sentence rather than the actual
claim; removing that limitation made the same under-supported aggregate claim pass.

Natural-language regex over an entire section is therefore insufficient to bind a claim's observation type,
scope and evidence members. More Prompt prose does not make that relationship deterministic.

## Current Semantics

Validation v4 requires exact whole-answer evidence for absence and all valid frozen Runs for an aggregate
observation. It infers whether a section is aggregate from natural-language patterns and then compares referenced
Run IDs with the full valid Run set. Historical v10/v11 results retain this interpretation.

## Proposed Semantics

For a new, independently versioned execution/validation contract:

1. Every brand observation declares a structured observation type and scope: `SAMPLE` or `FROZEN_VALID_SCOPE`.
2. The server builds an immutable aggregate evidence-set object from the exact sorted full-answer locators,
   Run identities, answer hashes, Prompt/Project versions and `input_scope_hash`.
3. The object receives a server-generated locator such as `[[answer_set:SET_HASH]]`; the model cannot submit or
   alter its membership.
4. `FROZEN_VALID_SCOPE` must cite the exact matching evidence set. The validator expands the set and applies the
   existing whole-answer checks to every member; a random, partial or cross-scope set fails closed.
5. `SAMPLE` continues to cite explicit full-answer locators and cannot use aggregate wording or imply full-range
   coverage.
6. Literal brand absence remains an answer observation only. It cannot prove non-recommendation, capability,
   rank, causality or Product Truth.
7. Missing, ambiguous or mismatched scope remains UNKNOWN/failed. The server does not silently insert a locator,
   rewrite the model's claim or reinterpret a prior result.

The structured binding may be embedded in the single Markdown response as a narrowly specified machine-readable
line, but the service—not the model—owns set identity and membership. A future Prompt identity may teach this
shape; it is not another prose-only quality patch.

## Non-Goals

- No relaxation of Evidence, Truth, graded-delivery or aggregate-coverage rules.
- No automatic repair call, second model request, or multi-Agent runtime.
- No historical revalidation, result mutation or automatic success relabeling.
- No M1.1 database upgrade, M1.2 release or production cutover.

## Required Offline Cases Before Approval

- Exact full-scope set passes only when every frozen valid Run and answer hash matches.
- Missing member, extra member, partial answer, stale hash, cross-Project/Prompt/version and fabricated set fail.
- Sample observation cannot masquerade as aggregate scope.
- Aggregate wording in a limitation/disclaimer does not change another claim's scope.
- Literal absence cannot satisfy recommendation, capability, superlative or causal predicates.
- Prompt v9 / Execution v11 / Validation v4 and all historical failures remain byte/meaning compatible.
- Parent/child partial-success, asset Evidence, usage settlement and immutable history remain unchanged.

## Contract Review Gate

`SEMANTIC_CONTRACT_REVIEW_REQUIRED`.

No implementation or real provider retry is authorized by this proposal. Product Owner approval must freeze the
observation shape, evidence-set identity/hash members, failure semantics, version names and historical boundary
before code work begins.
