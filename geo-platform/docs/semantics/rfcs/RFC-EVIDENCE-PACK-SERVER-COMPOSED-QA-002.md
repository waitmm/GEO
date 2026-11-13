# RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002 — Server-owned aggregate limitations in QA

```yaml
rfc_id: RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002
status: APPROVED
semantic_maturity: FROZEN
implementation_status: IMPLEMENTED_OFFLINE_NOT_RELEASED
change_class: SEMANTIC_CHANGE
authors: [GEO M1.2]
created_at: 2026-11-11
definition_approved_by: Product Owner
definition_approved_at: 2026-11-13
production_cutover_approved_by: null
affected_contracts:
  - geo.evidence-pack.execution.v12
  - geo.evidence-pack.validation.v5
  - geo-evidence-pack-synthesis.v10
  - RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001
  - geo.evidence-pack.execution.v13
  - geo.evidence-pack.validation.v6
  - geo-evidence-pack-synthesis.v11
  - geo.evidence-pack.qa-composition.v1
supersedes: null
```

## Problem

Validation v5 correctly centralizes the only authoritative frozen-scope brand fact in a closed server block. The
fourth real HELP_DOC + FAQ response reproduced that block correctly, but also wrote a safe QA limitation that
repeated the verified 22-answer literal-absence observation and explicitly denied recommendation, ranking and
causal inferences. v5 rejected it because the repeated scope fact was outside the closed block.

That rejection is correct under the frozen v5 definition. It also shows that asking a free-form model to avoid
all harmless range restatements across a long Markdown result remains brittle. Adding more Prompt prose or a wider
aggregate regex would not make evidence ownership deterministic.

## Frozen Definition

Introduce a new, separately versioned execution/validation profile; do not alter v5 or any stored result.

1. The Provider raw response remains immutable and fully archived. The server never relabels the fourth result.
2. The server remains the only authority for aggregate brand observation identity, members, predicate and result.
3. The public `品牌表现与证据缺口` block continues to be rendered from the exact server Observation.
4. Aggregate evidence limitations in `QA 与事实限制` become a server-owned sub-block derived from the same
   Observation. At minimum it must state that literal absence does not prove recommendation status, ranking,
   capability or cause. The server text and its Observation identity are versioned and hashed.
5. The model is no longer an authoritative writer of aggregate-scope QA. Only a sentence inside `QA 与事实限制`
   that deterministically restates the exact verified Observation, optionally with a negative inference boundary,
   may be excluded from the candidate delivery in a recorded normalization step. Its source offsets, fragment
   hash, reason, Observation/Evidence Set identities and original raw response remain auditable. This is not a
   silent mutation. Diagnosis, strategy and both draft bodies are never rewritten by this contract.
6. Any model text that asserts product capability, recommendation, rank or cause remains ineligible; exclusion of
   an aggregate sentence cannot supply Evidence or Truth for another claim.
7. Non-aggregate model QA may remain only if it independently passes existing Product Truth, Evidence, numeric,
   internal-instruction and asset-specific checks.
8. Historical Prompt v10 / Execution v12 / Validation v5 results retain their original bytes, status and meaning.

## Why this is a semantic change

v5 says any raw aggregate target-brand fact outside the closed block rejects the entire result and that validation
never rewrites Provider prose. The proposal changes public-delivery composition and parent/asset eligibility for a
detected class of Provider text. It therefore requires Product Owner Definition Freeze before implementation.

## Frozen Version And Eligibility Decisions

- New work uses Prompt v11 / Execution v13 / Validation v6 / QA Composition v1. v5 bytes and status stay frozen.
- Composition applies only to `QA 与事实限制`; unknown equivalence fails closed.
- Positive or uncertain capability/recommendation/ranking/causal assertions remain ineligible and cannot be
  legalized by exclusion. Retained QA still runs internal-instruction, numeric, Evidence and Truth checks.
- The server limitation is derived from the exact Observation, versioned and hashed, and is displayed separately
  from model analysis. Exported draft bodies contain no internal validation workflow instructions.
- An unsafe shared QA assertion fails the shared Gate for both assets. A safe redundant Observation does not fail
  either asset. Body-level failures retain existing independent child and partial-success behavior.

## Required Offline Cases

- Fourth real response replays only in a protected copy; historical v5 stays FAIL.
- Exact Evidence Set/Observation produces both canonical fact block and canonical QA limitation.
- One Run with target-brand presence prevents absence limitation generation.
- UNKNOWN, missing member, wrong hash/version/project/prompt and fabricated Observation fail closed.
- Model capability, recommendation, rank and causal claims cannot be legalized by normalization.
- Removed fragments are hashed and visible in audit metadata but absent from copy/export content.
- HELP_DOC and FAQ preserve independent Evidence, QA, feedback, export and partial-success behavior.
- v4/v5 history, ledgers, result hashes and child artifacts remain unchanged.

## Gate Result

Definition Freeze is approved for M1.2 development-branch offline implementation, deterministic tests and protected
shadow replay. Production cutover is not approved. No Provider retry, fifth model request, M1.2 release, M1.1
migration or C1 collection is authorized by this RFC.
