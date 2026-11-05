# RFC-EVIDENCE-PACK-QUALITY-GATE-001 — Final-draft leakage and brand-observation relevance

```yaml
rfc_id: RFC-EVIDENCE-PACK-QUALITY-GATE-001
status: APPROVED
semantic_maturity: FROZEN
implementation_status: IMPLEMENTED_OFFLINE_NOT_RELEASED
change_class: SEMANTIC_CHANGE
authors: [GEO M1.2]
created_at: 2026-11-05
definition_approved_by: Product Owner
definition_approved_at: 2026-11-05
definition_approval_reference: GEO M1.2 real quality Gate closure instruction after bb4c619
production_cutover_approved_by: null
production_cutover_approved_at: null
production_cutover_approval_reference: null
affected_contracts:
  - geo.evidence-pack.execution.v10
  - geo.evidence-pack.validation.v4
  - SC-MULTI-DRAFT-ARTIFACT-001@1.0.0
supersedes: null
```

## Problem

The first real HELP_DOC + FAQ generation completed and was persisted, but the drafts contained internal
authoring/runtime instructions and the shared brand-observation section lacked directly relevant answer
evidence. Prompt instructions alone did not make either failure deterministic.

## Current Semantics

Execution v9 uses Prompt v8 and Validation v3. Validation v3 checks section shape, locator validity,
asset structure, numeric claims and cross-asset duplication, but it does not reject explicit internal
authoring instructions or determine whether a valid answer locator is observationally related to the
brand statement. Historical v9 results keep that interpretation.

## Observed Failure

The protected 2026-11-05 real-quality replay produced two persisted failed child assets. Both included
internal Product Truth/Evidence authoring language, while `品牌表现与证据缺口` did not bind its conclusion
to a supporting answer observation. The raw response, frozen scope and usage remain outside Git.

## Proposed Semantics

Execution v10 continues to render the byte-compatible Prompt v8, but binds Validation v4:

1. A final HELP_DOC or FAQ body fails independently when it exposes explicit internal runtime identifiers,
   directs an editor/reviewer to operate internal Evidence Pack/Product Truth artifacts, or otherwise emits
   the known internal authoring workflow. Backticks and code fences do not hide visible leakage.
2. Ordinary final-user wording such as “证据不足时需核实官方来源，发布前确认适用条件” remains legal.
3. `品牌表现与证据缺口` requires at least one valid answer locator that is observationally related to the
   stated target-brand mention/absence. A syntactically valid but unrelated locator is insufficient.
4. A sample-level absence statement requires the exact whole-answer locator; a selected substring cannot
   prove absence.
5. An aggregate statement (`全部`, `整体`, `均未`, count-like scope) requires whole-answer coverage for every
   valid Run in the frozen scope. One Run cannot stand in for the whole scope.
6. A recommendation, superlative or capability statement requires the corresponding predicate in the cited
   whole answer. Brand-name occurrence alone proves neither recommendation, rank nor capability; a selected
   substring cannot remove negation or competitor context.
7. Ambiguous relationship wording is fail-closed. Explicitly internal prompt/runtime instructions are blocked,
   while ordinary UI “system message”, file editing and user tool operations remain legal final-user language.

This is a deterministic minimum observation anchor. It does **not** prove that an answer locator supports a
product capability, causal explanation or general truth. Product Truth and existing Evidence/graded-delivery
constraints remain authoritative for those claims.

## Non-Goals

- No general semantic entailment scorer or new model call.
- No weakening of Evidence, numeric-claim, Product Truth or graded-delivery gates.
- No Prompt v8 rewrite, no v7/v9 revalidation and no historical result mutation.
- No M1.1 database upgrade, production cutover, external sampling or provider authorization.

## Affected Domain Objects

- `AgentResultVersion`: immutable parent result; no identity change.
- `DraftArtifactVersion`: leakage failure is child-scoped; one failed child does not erase a passing sibling.
- Evidence references: remain exact frozen locators and retain their original Run ownership.

## Contract Diff

```text
old contract/version: geo.evidence-pack.execution.v9 + validation.v3 + prompt.v8
new contract/version: geo.evidence-pack.execution.v10 + validation.v4 + prompt.v8
allowed inference diff: valid locator may satisfy the brand section only after deterministic observation checks
forbidden inference diff: unrelated/partial locator, one-Run aggregate proof, name-only recommendation proof
unknown behavior diff: ambiguous brand support fails closed with BRAND_SECTION_EVIDENCE_RELEVANCE_REQUIRED
step boundary diff: final-draft validation adds two deterministic gates; generation and persistence boundaries stay unchanged
```

## Golden Cases

- Normal: a sample-level “target brand not mentioned” statement plus the exact whole-answer locator passes.
- Normal: a mention statement plus an answer excerpt containing the target brand passes.
- Boundary: normal user-facing verification language passes without an internal-leak issue.
- Boundary: two requested assets preserve independent validation; a FAQ leak does not fail HELP_DOC.
- Failure: the first real failed drafts replay with `INTERNAL_AUTHORING_INSTRUCTION_LEAK`.
- Failure: capability text plus a random valid answer locator fails relevance.
- Failure: a partial answer range cannot prove absence.
- Failure: an aggregate statement with only one of multiple valid Runs fails.
- Failure: “recommended/best/supports” fails when the cited answer only mentions the brand.

## Identity / Scope Impact

No identity, dedupe, lineage or frozen-scope rule changes. Validation v4 is selected only by execution v10.
Execution v9 continues to route to Prompt v8 and Validation v3. Historical output is read as originally stored.

## UNKNOWN Semantics

Missing brand identity, missing answer evidence, ambiguous relation or insufficient aggregate coverage fails
closed. The service does not invent a locator, select a random valid locator or reinterpret unavailable evidence
as a legal zero.

## Step Boundary And Allowed Consumers

The server validates the provider response after response audit/usage handling and before business success.
The gate may reject a child or shared brand section; it cannot modify Product Truth, approve publication,
rewrite the raw provider response or mutate a prior result.

## Implementation Plan

Implement under v10/v4, replay protected real output, run targeted and full regressions, then prepare a no-call
preflight. A future real retry requires a separate model/fee authorization.

## Historical Compatibility And Migration

No database migration and no historical backfill. Prompt v7/v8 renderers and execution v8/v9 mappings stay
available. New child-regeneration requests freeze Prompt/Execution/Validation identities; a historical queued
request without that identity fails before the provider instead of silently adopting v10. Rollback selects the
prior implementation for new development requests; it does not rewrite v10 data.

## Cutover Gate

- Targeted false-positive/false-negative cases pass.
- First protected real failure is caught without printing or committing its body.
- Asset independence and v9 history compatibility pass.
- Full applicable regression passes.
- Product Owner separately authorizes a real provider retry and any later M1.2 release.

## Approval Gates

Definition Freeze and offline implementation are approved by the referenced instruction. Real model use,
M1.1/M1.2 deployment and production cutover are not approved by this RFC.
