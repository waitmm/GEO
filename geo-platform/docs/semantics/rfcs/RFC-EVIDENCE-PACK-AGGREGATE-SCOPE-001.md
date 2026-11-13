# RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001 — Structured observation scope and evidence-set binding

```yaml
rfc_id: RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: IMPLEMENTED_OFFLINE_NOT_RELEASED
change_class: SEMANTIC_CHANGE
authors: [GEO M1.2]
created_at: 2026-11-09
definition_approved_by: Product Owner
definition_approved_at: 2026-11-10
definition_approval_reference: GEO M1.2 third real acceptance approval
production_cutover_approved_by: null
affected_contracts:
  - geo.evidence-pack.execution.v12
  - geo.evidence-pack.validation.v5
  - geo-evidence-pack-synthesis.v10
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

## Frozen Semantics

For Prompt v10 / Execution v12 / Validation v5:

1. A brand observation binds one closed predicate, one explicit scope and one server-owned Evidence Set.
   The initial v5 slice supports only `BRAND_LITERAL_ABSENCE + FROZEN_VALID_SCOPE + TARGET_BRAND +
   ALL_VALID_RUNS`; its value is the server-computed literal-match count. `SAMPLE` is not an accepted v5
   observation object and therefore cannot impersonate or be upgraded to the frozen aggregate scope. Supporting a
   structured SAMPLE object later requires a separately versioned contract. No predicate is accepted as an alias.
2. The server computes the observation from the complete frozen answers and the exact configured brand name and
   aliases under `geo.brand-literal-match.v1`. The model cannot choose Evidence Set members, claim a computed
   result, change the quantifier or upgrade UNKNOWN.
3. The immutable Evidence Set uses canonical JSON, stable Run ordering and duplicate rejection. Its identity hash
   binds schema/set kind, Project, Prompt, `input_scope_hash`, PromptVersion identity/hash, ProjectConfigurationVersion
   identity/hash, eligibility-rule version, included members and excluded members. Every included member binds
   Run ID, frozen status, complete-answer locator and answer hash. It also binds the brand-configuration hash and
   literal-match-rule version. The set hash does not include the Evidence Pack hash.
4. A separate immutable observation hash binds predicate, subject, quantifier, scope, Evidence Set ID, matching
   rule and the server-computed counts/result. Evidence Set membership proves the observed inputs; only the server
   computation proves the literal-absence result.
5. The server exposes a server-generated observation locator such as `[[observation:OBSERVATION_HASH]]` and a
   canonical business-readable observation sentence. `品牌表现与证据缺口` is a closed server fact block and must
   equal that heading, verified sentence and locator exactly. The model cannot append analysis, disclaimers or
   contradictory prose inside the block. Any raw aggregate target-brand fact elsewhere in the response is
   rejected; analysis may discuss strategy, future verification actions and evidence limitations without making
   another range fact. A
   neighbouring limitation or disclaimer cannot change the structured observation's scope.
6. v5 never infers SAMPLE or aggregate scope from a Markdown section. A full-answer locator remains usable as
   ordinary answer evidence in other sections, but it is not a v5 brand observation and cannot use the aggregate
   observation locator or imply `FROZEN_VALID_SCOPE` coverage.
7. Empty scope, missing/duplicate/extra members, ineligible Run, incomplete identity/hash, unknown brand identity,
   uncertain matching rule, stale answer, cross-Project/Prompt/version membership or unknown predicate fails
   closed. Invalid or uncertain answers are excluded with explicit reasons and cannot be counted as brand absence;
   if the selected frozen scope contains any unresolved member, the aggregate observation is UNKNOWN and no
   verified absence locator is produced. A complete, non-empty eligible set may legitimately compute zero matches.
8. Manual-import provenance remains `USER_ATTESTED_UNVERIFIED`; structural verification does not independently
   prove the third-party platform origin. The observation proves only what the frozen answer text literally contains.

The structured observation is server-owned input and persisted validation evidence. Prompt v10 teaches the model
to reproduce only the server-supplied canonical observation line; it does not ask the model to calculate facts.
The raw provider response remains immutable. Validation may reject but never silently add a missing locator,
rewrite provider prose or relabel a historical result.

## Frozen Object Shapes

```json
{
  "observation_type": "BRAND_LITERAL_ABSENCE",
  "scope": "FROZEN_VALID_SCOPE",
  "subject": "TARGET_BRAND",
  "quantifier": "ALL_VALID_RUNS",
  "evidence_set_id": "SERVER_GENERATED_HASH",
  "matched_count": 0,
  "valid_run_count": 22,
  "verification": "SERVER_VERIFIED"
}
```

`evidence_set_id` and `observation_id` are distinct SHA-256 identities over their respective canonical payloads.
The model is never an authoritative writer of either payload.

## Non-Goals

- No relaxation of Evidence, Truth, graded-delivery or aggregate-coverage rules.
- No automatic repair call, second model request, or multi-Agent runtime.
- No historical revalidation, result mutation or automatic success relabeling.
- No M1.1 database upgrade, M1.2 release or production cutover.

## Required Offline Cases Before Cutover

- Exact full-scope set passes only when every frozen valid Run and answer hash matches.
- Missing member, extra member, partial answer, stale hash, cross-Project/Prompt/version and fabricated set fail.
- Sample observation cannot masquerade as aggregate scope.
- Aggregate wording in a limitation/disclaimer does not change another claim's scope.
- Literal absence cannot satisfy recommendation, capability, superlative or causal predicates.
- Prompt v9 / Execution v11 / Validation v4 and all historical failures remain byte/meaning compatible.
- Parent/child partial-success, asset Evidence, usage settlement and immutable history remain unchanged.
- All 22 complete eligible answers absent passes; one literal target-brand match prevents all-absence verification.
- Empty scope, unresolved selected member and unknown brand configuration produce no verified absence observation.
- A valid observation plus an additional unsupported aggregate claim fails.

## Contract Review Gate

Definition Freeze is approved for M1.2 offline implementation and protected replay only. It does not authorize a
provider retry, M1.1 database migration, M1.2 release, production cutover or C1 sampling. Prompt v9 / Execution v11 /
Validation v4 and every prior stored result retain their original interpretation and status.

## Offline Implementation Result

Prompt v10 / Execution v12 / Validation v5 are implemented on the isolated M1.2 development branch. The server
builds the exact Evidence Set and computes the only initially supported predicate, `BRAND_LITERAL_ABSENCE`.
Validation rejects identity/member/hash drift, UNKNOWN scope, any raw aggregate target-brand fact outside the closed server
fact block and any provider text that does not reproduce the exact server observation. Pack construction, locator
parsing and prompt rendering are execution/prompt-version aware: v8/v9 prompt bytes and v11 pack/hash/reference
semantics remain frozen. The UI feature-detects v5 results and shows a business-readable range summary without
exposing set or observation hashes; historical results are not backfilled.

The protected replay of the third real failure used a local database copy and made zero external calls. The stored
v4 result remained unchanged and failed with its original range-evidence reason; the raw draft failed v5 because it
lacked the server observation. A shadow-only result in which the server rendered the verified 22-answer observation
passed v5. This proves the new deterministic binding path, not real model compliance or production readiness.

Detailed evidence is recorded in
`docs/geo-v1.0/M1_2_AGGREGATE_SCOPE_V5_OFFLINE_RESULT_2026-11-10.md`.

### Implementation compatibility note — 2026-11-13

Execution v14 keeps Prompt v11, Validation v6, the frozen aggregate predicate and all Evidence Set identity
requirements unchanged. It selects `geo.evidence-pack.valid-run-eligibility.v2`, which admits a non-empty
`partial_success` answer only where the Run already preserves a complete answer body and the partial state is the
separate citation-observation boundary. The Evidence Pack records `reference_complete`, the explicit
`UNKNOWN`/`PARSE_FAILED` citation state and manual-import provenance; none of those states becomes confirmed zero
citations or Product Truth. Citation-dependent denominators remain unchanged.

Execution v12/v13 continue selecting `geo.evidence-pack.valid-run-eligibility.v1`; their Run projection, Pack bytes,
hashes, validation meaning and stored results are not reinterpreted. This is an implementation alignment with
`SC-GRADED-DELIVERY-001`, `SC-RUN-IMPORT-001` and the existing single-Prompt partial-answer boundary, not a new
aggregate predicate or a production cutover.
