# RFC-RUNTIME-001 Read-only Projection Spike

```yaml
spike_id: RFC-RUNTIME-001-READ-ONLY-PROJECTION-SPIKE-001
executed_at: 2026-09-09
result_classification: SPIKE_PASS
rfc_revision: 004
rfc_maturity: FROZEN
contract_id: SC-RUNTIME-001@0.1.0
implementation_status: NOT_IMPLEMENTED
projection_kind: VIRTUAL_RUNTIME_PROJECTION
runtime_profile: runtime_stage_profile.single_prompt.v1
legacy_projection_profile: legacy_stage_projection.single_prompt.v1
production_cutover: NOT_STARTED
schema_changes: 0
database_writes: 0
```

## Frozen Contract

```text
RFC maturity = FROZEN
implementation status = NOT_IMPLEMENTED
```

The Spike is a read-only mechanical projection, not the production Runtime
implementation. It registers no API or frontend consumer and creates no
AnalysisContext, StageExecution, StageAttempt, ReviewDecision or current
pointer row.

## Normative Vectors

```text
input = dba2155c917c74e7f297ad0e5fe9a8639ef3f2f8289e3511fcc84e0d96cce10e / MATCH
fixed scope = d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66 / MATCH
source ref = 543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483 / MATCH
```

The Review-005 prompt value ending in `d831` was excluded as
`NON_SEMANTIC_REVIEW_PROMPT_TRANSCRIPTION_ERROR`.

## #19

```text
virtual context = virtual-context:1b0b427977d98b4d19c51d11eb2b71052175cd23efdac56e179e70f3e88d4954
root completeness = PARTIAL

stage completeness:
COMPLETE = 0
PARTIAL = 6
UNSAFE = 9
UNAVAILABLE = 1

strategy lineage = UNSAFE
current projection = UNRESOLVED
review risks = CURRENT_STATE_BOUND / OBJECT_ID_ONLY / UNBOUND combinations
blocking reasons = missing formal Root/Stage manifests, multiple PromptAnalysisRun and ShadowRun envelopes, mutable source/truth/review state, missing candidate and proposal manifests
```

The fixed Root contains Package `12@v8`, 40 Run refs, 1,207 Reference
observations and 899 Retrieval observations. The projection retains all 13
PromptAnalysisRun envelopes and all 13 exact-scope ShadowRun envelopes; it does
not select one by id, status or time.

## #40

```text
virtual context = virtual-context:3e8c9c6118c8c4d079917f353d3ce6feae23af823592633922af003444c06a07
root completeness = PARTIAL

stage completeness:
COMPLETE = 0
PARTIAL = 7
UNSAFE = 8
UNAVAILABLE = 1

strategy lineage = UNSAFE
current projection = UNRESOLVED
review risks = CURRENT_STATE_BOUND / OBJECT_ID_ONLY / UNBOUND combinations
blocking reasons = missing formal Root/Stage manifests, multiple mixed ShadowRun envelopes, mutable source/truth/review state, missing candidate and proposal manifests
```

The fixed Root contains Package `15@v2`, 6 Run refs, 174 Reference
observations and 258 Retrieval observations. Its single PromptAnalysisRun is
projected as PARTIAL. Candidate 50's absent PR4 lineage fields remain null and
Candidate 57 is never consulted.

## Determinism

```text
#19 run 1 hash = fa7cfc02166f6cf24e34f4e49d496f2edbbb67d423d35044b0d9bbc4ea562f2a
#19 run 2 hash = fa7cfc02166f6cf24e34f4e49d496f2edbbb67d423d35044b0d9bbc4ea562f2a
#19 diff = false

#40 run 1 hash = e99ecfdc490ca8ccea4255a4cfa9dd11d3eddbe0c88c3f845fd2bf0a6e1e3e57
#40 run 2 hash = e99ecfdc490ca8ccea4255a4cfa9dd11d3eddbe0c88c3f845fd2bf0a6e1e3e57
#40 diff = false
```

All 16 Stage identity slots are stable across both passes. Only uniquely
recoverable PARTIAL source sets receive `virtual-stage:` identities; UNSAFE or
UNAVAILABLE mappings correctly retain null instead of minting a winner.

## Contract Diff

```text
#19 stage expectation diff = 0
#40 stage expectation diff = 0
```

## Safety

```text
latest substitution = 0
semantic invention = 0
guessed ProductTruth binding/current Candidate/review authority/JSON path/source winner = 0
DB writes = 0
DB SHA before = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
DB SHA after = fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
```

SQLite is opened with `mode=ro`, `query_only`, and a write/DDL-denying
authorizer. Formal input/output manifests that cannot be recovered are null;
the implementation emits a separate hashed legacy source manifest rather than
relabeling current rows as formal Runtime output.

## Implementation Findings

1. The Frozen selector and canonicalization contracts are mechanically
   implementable against the fixed legacy database without semantic invention.
2. #19 and #40 both have deterministic source sets but cannot prove a
   production current lineage. Correctly returning UNSAFE is the successful
   behavior.
3. Historical Candidate Builder rows do not contain complete selected/omitted
   manifests, omission reasons or policy hashes. Those fields remain null and
   the Stage remains UNSAFE.
4. Mutable Product Truth, SourceDocument, Alignment and review rows cannot be
   upgraded into immutable historical Stage output or authoritative review.
5. The complete two-case, two-pass CLI replay took about 28 seconds locally and
   emitted a 2.4 MB diagnostic artifact. This is an implementation sizing fact,
   not a Contract mismatch.

## Validation

```text
focused tests = 8 passed
normative vectors = 3/3 MATCH
real deterministic replays = 2/2 MATCH
compileall app = PASS
git diff --check = PASS
result = SPIKE_PASS
```

The Spike stops here. It does not authorize Runtime persistence, Shadow status,
production workflow replacement, frontend changes, legacy repair or PR5-C.
