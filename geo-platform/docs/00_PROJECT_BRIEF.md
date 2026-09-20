# 00 Project Brief

Status: ACTIVE

GEO Platform is a local Alpha tool for auditing AI answer visibility, brand
presence, recommendation quality, and citation-source behavior.

The current production-like path is Wenxin web audit:

```text
Project -> Prompt -> Batch/Task -> BrowserMonitorRun -> ReferenceSource/RetrievalCandidate -> Analytics/Optimization
```

The product should help answer:

- Is the brand mentioned for a specific user question?
- Is the brand merely mentioned or explicitly recommended?
- Which sources are retrieved and cited?
- What concrete optimization action should be taken?
- Did a fixed retest show a measurable change after the action?

P0 is not a generic analytics BI system. P0 is the first trustworthy optimization
loop using existing real collection data.

## Single-Prompt Core V2 Delivery State

V2 is an isolated, incremental replacement path; it does not reinterpret V1
history or activate the generic Runtime RFC work.

```text
Slice 1: explicit Analysis/Task ownership + immutable AnalysisContext = delivered
Slice 2: recommendation/citation/truth diagnosis components + exact-version review = delivered
Slice 2 safety: strict V2 LLM admission + grounded consumption + read-only current eligibility = delivered
Slice 3: reviewed diagnosis -> evidence-constrained strategy candidate = delivered
Slice 4: confirmed strategy -> execution skeleton -> confirmation -> user-reported publication = delivered
Slice 5: exact publication -> frozen retest -> descriptive before/after comparison = delivered
Effect attribution / Experiment = not in V2 scope
```

Delivery status above describes implemented code slices, not a completed real
end-to-end workflow. A 2026-09-16 production-path audit found that the V2
second-slice implementation runs Answer Semantic before source content
completion and exposes no pre-diagnosis manual source-completion gate, despite
the second-slice contract placing the immutable SourceSnapshot set first.
Therefore V2 evidence diagnosis is currently:

```text
component implementation = delivered
source-first product workflow = NOT DELIVERED
real evidence E2E acceptance = BLOCKED
```

The source-first repair was approved through the R2 + R3 delivery contract and
is now implemented as the GEO 1.0 first-slice release path. Its dedicated app,
release migration, source-preparation workspace, immutable manifests and exact
Evidence gate are engineering-accepted. The formal release database is separate
from the legacy development database and contains only the approved first-slice
allowlist.

This does not mean the real positive evidence chain is complete. The first
release acceptance has now created a real Analysis/Context, frozen 38-source
Citation Manifest, one real immutable source Snapshot, and a 3/3-admitted Answer
ResultVersion. A later DOM audit found that those frozen Run answer texts include
Wenxin's search/thinking region before the final Markdown answer. The immutable
result remains available for audit, but current eligibility marks it
`ANSWER_CONTENT_BOUNDARY_NOT_INDEPENDENT`; it cannot be reviewed or consumed by
Evidence. New collection separates the platform-reported search observation into
its own artifact and stores only the final Markdown as `answer_text`. The remaining
37 sources also still require human disposition. Candidate fetch files and
fixture output are not reported as completed evidence.
See `docs/GEO_1_0_FIRST_SLICE_OPERATIONS.md` for the executable workflow and
`docs/GEO_1_0_R3_EXECUTION_CONTRACT.md` for the frozen boundary.

The fixed #44 production result is
`diag-v1:1449c44916fe5c55`. It has four grounded recommendation Reasons, 30
reference observations / 29 source identities, an empty target-brand Truth
snapshot with four `UNRESOLVED` relations, and no human review. Retrieval and
independent-session proof remain unavailable. The one-time external authorization
covered only Prompt/answer semantic extraction; page-content SourceClaim and
Alignment work remains explicitly not evaluated.

The immutable #44 result continues to report 25 technically successful content
snapshots. A current read-only safety projection blocks one verification page,
so effective evidence-ready content is at most 24; this upper bound does not
claim that all remaining content is quality verified. Strict V2 LLM admission
is locally validated, while real-provider injection resistance and external
SourceClaim/Alignment remain not verified.

The third slice introduces an A/B/C readiness contract before strategy
creation. Unreviewed or reviewed-but-ineligible input produces an explicit
readiness report and no empty candidate. Foundation and channel intervention
are independent; zero PRIMARY is valid; TEST remains a non-causal hypothesis.
The fixed #44 result is currently class A with no review, Foundation UNKNOWN
and zero qualified directions, so no real #44 strategy was created. Positive
B/C behavior is fixture-validated only.

The fourth slice adds deterministic execution content skeletons, asset production
briefs, immutable proposal revisions, append-only confirmations and user-reported
publication history. Foundation publication surfaces never create a channel Role;
only FULLY_COVERS confirmed Truth may enter PUBLIC_CONTENT; the current real asset
path is CREATE_NEW only. Baseline comes exclusively from the exact immutable V2
AnalysisContext. #44 remains blocked before strategy and has zero fourth-slice
objects; the complete positive execution/publication chain is fixture-validated,
not yet verified on a real accepted V2 strategy.

The fifth slice adds an exact historical-publication retest path with frozen
Prompt, planned Run identities, a separate measurement identity and independent
browser/LLM authorization. It reports Run-level brand mention, V2 semantic
recommendation, target official-reference and exact published-URL reference
metrics with explicit denominators, unknowns and per-metric comparability. Values
are descriptive observations only; no result can claim causal lift, channel
effectiveness or strategy success. #44 remains blocked before strategy and has no
retest object. The positive fifth-slice chain is fixture-validated; no real
external retest or semantic call was authorized.
