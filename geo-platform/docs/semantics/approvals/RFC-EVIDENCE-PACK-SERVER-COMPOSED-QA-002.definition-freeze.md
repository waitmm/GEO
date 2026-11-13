# RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002 Definition Freeze

```yaml
rfc_id: RFC-EVIDENCE-PACK-SERVER-COMPOSED-QA-002
decision: APPROVED
contract: geo-evidence-pack-synthesis.v11 / geo.evidence-pack.execution.v13 / geo.evidence-pack.validation.v6 / geo.evidence-pack.qa-composition.v1
approved_by: Product Owner
approved_at: 2026-11-13
approval_reference: GEO M1.2 QA 服务端组合契约批准及自动执行令
cutover_scope: M1.2 development branch offline implementation, deterministic tests and protected replay only
external_calls_authorized: false
production_release_authorized: false
affects_m1_1: false
```

Freeze covers a server-owned public QA limitation derived from the exact server-verified aggregate Observation.
The immutable Provider response remains the audit source. Only a QA-section sentence that deterministically
restates that exact Observation, optionally with a negative inference boundary, may be excluded from the delivery
projection. Source offsets, fragment hash, reason, Observation/Evidence Set identities, composition version and
final delivery hash are recorded.

This is not a general text rewriter. Diagnosis, strategy, HELP_DOC and FAQ bodies are never normalized by this
contract. Capability, recommendation, rank, causal or uncertain restatements remain blocked; retained model QA
continues through Evidence, Truth, number and internal-authoring checks. Unknown equivalence fails closed. A shared
unsafe claim fails both assets, while safe QA redundancy does not; existing body-level partial-success behavior is
unchanged. Historical v4/v5 results, bytes, statuses, ledgers and child assets are not reinterpreted or relabelled.

This approval does not authorize a fifth Provider request, M1.2 release, main merge, M1.1 database upgrade,
production cutover or C1 collection.
