# RFC-MULTI-DRAFT-ARTIFACT-001 — Frozen Optimize With Versioned Draft Assets

```yaml
rfc_id: RFC-MULTI-DRAFT-ARTIFACT-001
status: APPROVED
change_class: SEMANTIC_CHANGE
owner: Product Owner
approved_at: 2026-10-30
approval_reference: GEO M1.2 B-line explicit approved semantic change
target_contract: SC-MULTI-DRAFT-ARTIFACT-001@1.0.0
```

## Decision

`AgentResultVersion` continues to represent exactly one immutable Optimize result over an exact frozen
Project/Prompt/Run scope. It is no longer interpreted as exactly one manuscript. Explicit typed content
deliverables may be persisted as append-only `DraftArtifactVersion` children; the first admitted types are
`HELP_DOC` and `FAQ`.

Each child freezes its exact parent result, scope, logical artifact id, version/previous version, body hash,
Evidence, QA, failure and creation actor. A failed child is retained independently. The derived parent delivery
state is `SUCCESS`, `PARTIAL_SUCCESS`, or `FAILED`; it does not rewrite the parent result. Existing result rows
with no child rows remain readable as `LEGACY_SINGLE_DRAFT` and are never backfilled by inference.

Feedback and export bind an exact child version. Regeneration is server-budgeted, targets one logical child,
and appends a new child version under the same parent. It cannot mutate the parent, sibling assets or the prior
child. Cross-project or cross-Prompt access is rejected without disclosing the foreign object.

## Boundaries

- Child content does not upgrade Product Truth, Evidence grade, publication eligibility or Review/Gate state.
- Missing or invalid child content stays failed/UNKNOWN; no sibling may fill it by implication.
- Client requests contain no Token, price or request limit. Server policy is frozen with the regeneration request.
- The implementation reuses the existing Agent Experiment Evidence Pack/Strategy/QA result. It creates no second
  Optimize chain and makes no production V2 write.
- Untyped historical deliverables remain the old single-draft read model; the system does not guess their type.

## Cutover

The Product Owner authorization covers Definition Freeze and the M1.2 internal-Beta persistence/API, offline
generation contract and formal UI cutover. It does not enter M1.1, authorize a real provider call or authorize a
production deployment. New tables are additive and append-only; the legacy parent payload and
`deliverable_markdown` remain intact.
