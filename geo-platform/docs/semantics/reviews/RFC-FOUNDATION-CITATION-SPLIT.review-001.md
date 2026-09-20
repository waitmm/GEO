# Definition Review: RFC-FOUNDATION-CITATION-SPLIT

```yaml
review_id: RFC-FOUNDATION-CITATION-SPLIT-REVIEW-001
reviewer_role: INDEPENDENT_SEMANTIC_REVIEWER
reviewed_at: 2026-09-08
reviewed_rfc_status: DRAFT
reviewed_rfc_maturity: CANDIDATE
reviewed_implementation_status: NOT_IMPLEMENTED
change_classification: SEMANTIC_RISK
production_code_changes: 0
database_writes: 0
```

## Review Result

```text
Status: NEEDS_REVISION
Contracts Referenced:
  SC-PT-001@1.0.0
  SC-GAP-001@1.0.0
  SC-CHANNEL-001@1.1.0
  SC-STRATEGY-001@1.1.0
  SC-HISTORY-001@1.0.0
  SC-SCOPE-001@1.0.0
  SC-FOUNDATION-001@0.1.0
Golden Snapshot IDs:
  CASE-SYN-001
  CASE-REAL-019@2026-09-08
  CASE-REAL-040@2026-09-08
Freeze Recommendation: NO
```

## Blocking Issues

### B1. Proposed domain objects lack independent definitions

The RFC names `Foundation Requirement` and `Citation Intervention`, but does not define for each:

```text
identity / scope key
source of truth
legal inputs
output schema and states
owner step
allowed consumers
mutability / versioning
terminal states
```

Therefore the review cannot prove that the two concepts are orthogonal rather than two labels feeding the same channel-priority decision. This is an `IDENTITY_SCOPE_DRIFT` blocker and a `CONTRACT_GAP`.

### B2. The decisive independent state combination is unspecified

The RFC does not explicitly define the following as a legal final semantic result:

```text
FoundationRequirement = REQUIRED
CitationInterventionRole.PRIMARY = NONE
```

It also does not define whether zero Citation PRIMARY channels is legal, how that state is represented, or which consumer may proceed. Leaving role mapping to later review means the proposed definition is not yet complete enough to freeze.

### B3. Citation intervention eligibility remains under-specified

The phrase `eligible decision citation / bounded channel experiment evidence` is not a complete eligibility contract. A same-reason Decision Citation is strong evidence, but current contracts still require scope, target applicability, intervention fit, lineage and other gates. The proposed text does not define those gates or the meaning and provenance of `bounded channel experiment evidence`.

This leaves `PARTIAL_PREMISE_FALLACY`, `HIDDEN_FALLBACK`, and causal interpretation unresolved.

### B4. CASE-REAL-040 does not challenge the proposed semantics

The RFC lists #19 but does not include #40 in its Golden Cases. It only says #40 production semantics must remain unchanged. It does not specify proposed results for this combination:

```text
Foundation requirement = independently evaluated
ZHIHU same-scope Decision Citation = 6/6 Runs
Benchmark = present
```

The review therefore cannot verify that Citation evidence controls Citation intervention selection without Foundation silently reasserting official-site priority.

### B5. Foundation's forbidden boundary is incomplete

The RFC correctly says Product Truth can prove that a real capability is available to carry, but it does not explicitly forbid Foundation from selecting:

```text
robots / schema
specific URL or slug
title
section plan
publishing account/location
asset instance
```

Without this boundary, `FoundationRequirement` can leak from Step 6/7 into Step 8 execution facts. This is a `CROSS_STEP_LEAKAGE` blocker.

### B6. UNKNOWN behavior is operational, not semantic

`Unknown Behavior` currently says to retain production behavior while the RFC is unresolved. That is a safe rollout rule, but it does not define the proposed contract's result when Foundation need, Citation eligibility, target applicability, or intervention fit is UNKNOWN.

The RFC must prevent `UNKNOWN_UPGRADE`; the current draft does not yet specify how.

### B7. Historical compatibility has a guard but no transition contract

The draft correctly forbids changing #57/#50 and production Path C. It does not define:

```text
new contract version identity
shadow input/output identity
new StrategyCandidate lineage
old Candidate preservation
supersedes timing
cutover and rollback boundary
```

The current no-mutation guard passes, but historical compatibility is incomplete for approval.

## Non-Blocking Issues

- All 16 registry Contracts have `approved_by`, `approved_at`, and `approval_reference` set to `null`. No historical PR freeze was treated as new Semantic Freeze approval.
- The RFC is correctly marked `DRAFT + CANDIDATE + NOT_IMPLEMENTED`.
- `SEM-CONFLICT-001` is registered as OPEN and current production behavior is preserved.
- The RFC correctly forbids Product Truth from proving that a channel will enter Retrieval/Citation.
- The RFC correctly separates Definition approval from Production Cutover approval.

## Category Error Audit

```text
CATEGORY_ERROR = CONFIRMED_IN_CURRENT_BEHAVIOR
CAUSAL_REVERSAL = RISK_NOT_RESOLVED
PARTIAL_PREMISE_FALLACY = OPEN
HIDDEN_FALLBACK = OPEN
MAGIC_THRESHOLD = NOT_OBSERVED_IN_RFC
CROSS_STEP_LEAKAGE = OPEN
UNKNOWN_UPGRADE = OPEN
HISTORICAL_MUTATION = CURRENTLY_GUARDED, TRANSITION_INCOMPLETE
IDENTITY_SCOPE_DRIFT = BLOCKING
SHADOW_PRODUCTION_LEAK = CURRENTLY_GUARDED
EVIDENCE_TO_ACTION_JUMP = RISK_NOT_RESOLVED
```

Current implementation evidence:

- `_evidence_path_precedence()` selects Path C whenever `first_party_authority_required` is true, even if another evidence path is eligible.
- The same function then forces `OFFICIAL_SITE` to PRIMARY when that authority need is true.
- This maps a truth-origin/authority requirement directly into Citation channel priority. The current behavior is observable production semantics, but the categories are not independently represented.

## Causal Audit

```text
PASS:
  Product Truth is not claimed to prove channel effectiveness.

BLOCK:
  "bounded channel experiment evidence" has no defined provenance,
  causal status, version, or eligibility gate.

REQUIRED:
  Presentation and structural outputs must distinguish foundation need,
  observed citation evidence, test hypothesis, and proven experiment effect.
```

## Identity / Scope Audit

```text
FoundationRequirement identity = UNDEFINED
CitationIntervention identity = UNDEFINED
shared reason scope = UNDEFINED
prompt/package/run scope = UNDEFINED
historical/new candidate lineage = INCOMPLETE
Result = BLOCK
```

## Forbidden Inference Audit

```text
Product Truth alone => channel effectiveness = FORBIDDEN, PASS
DRAFT => production override = FORBIDDEN, PASS
Foundation => Step 8 asset details = NOT EXPLICIT, BLOCK
Decision Citation alone => PRIMARY = NOT EXPLICITLY FORBIDDEN, BLOCK
UNKNOWN => positive eligibility = NOT EXPLICITLY FORBIDDEN, BLOCK
```

## Golden Cases

### CASE-SYN-001

The case distinguishes current and proposed semantics, but the proposed result only states that Product Truth cannot establish Citation PRIMARY. It lacks the complete output object/state assertions needed for automated or manual acceptance.

### CASE-REAL-019

The immutable snapshot is adequate for preserving current production behavior. The RFC still needs a proposed shadow assertion that explicitly permits `Foundation REQUIRED + Citation PRIMARY NONE` without rewriting Candidate #57.

### CASE-REAL-040

The immutable snapshot is adequate, but the RFC does not currently adopt it as a proposed-semantic challenge. It must show how 6/6 same-scope Zhihu Decision Citation participates in Citation intervention while Foundation is independently resolved.

## Counterexamples

The RFC does not yet provide a complete state matrix. Definition Review requires at least:

```text
Foundation REQUIRED / Citation PRIMARY NONE
Foundation NOT_REQUIRED / Citation PRIMARY present
Foundation REQUIRED / Citation PRIMARY present
Foundation UNKNOWN / Citation evidence present
Foundation REQUIRED / Citation eligibility UNKNOWN
same-reason Decision Citation present but intervention fit fails
```

This list identifies missing coverage only. Selecting the states, schemas and transitions is the RFC Author's responsibility, not the Reviewer's.

## Step Boundary

```text
current draft = insufficient
required clarification = Foundation producer step, Citation Role producer step,
allowed consumers, and an explicit prohibition on Step 8 execution details
```

## Historical Compatibility

```text
#57 immutable = PASS
#50 immutable = PASS
new contract version = MISSING
shadow lineage = MISSING
new Candidate rule = MISSING
supersedes/cutover timing = MISSING
```

## Contract Gaps

```text
1. Formal FoundationRequirement object/contract.
2. Formal CitationIntervention eligibility/output contract.
3. Relationship contract between those outputs and existing Channel Role.
4. Proposed UNKNOWN behavior.
5. Historical/shadow/cutover lineage.
```

## Freeze Recommendation

```text
NO
```

The problem statement and safety boundary are directionally sound, but the definition is not yet precise enough for Product Owner Definition Freeze. Return the RFC to its Author as `NEEDS_REVISION`. Do not implement, Shadow, Freeze, or Cutover from this draft.
