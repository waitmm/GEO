# RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001 Definition Freeze

```yaml
rfc_id: RFC-EVIDENCE-PACK-AGGREGATE-SCOPE-001
decision: APPROVED
contract: geo-evidence-pack-synthesis.v10 / geo.evidence-pack.execution.v12 / geo.evidence-pack.validation.v5
approved_by: Product Owner
approved_at: 2026-11-10
approval_reference: GEO M1.2 third real acceptance approval
cutover_scope: M1.2 development branch offline implementation, deterministic tests and protected replay only
external_calls_authorized: false
production_release_authorized: false
affects_m1_1: false
```

Freeze covers a server-computed `BRAND_LITERAL_ABSENCE` observation bound to a non-empty exact Evidence Set,
with separate set and observation hashes. The set freezes Project, Prompt, input scope, exact prompt/configuration
versions, eligibility rules, complete-answer Run members/hashes/locators, explicit exclusions and the brand literal
matching rule. The observation freezes predicate, subject, quantifier, scope, set identity and computed counts.

The server owns membership and result computation. The model may only reproduce the canonical verified observation
line and locator in a closed brand-fact block; the block accepts no adjacent model prose. Raw frozen-answer-scope
assertions outside that block, contradictions, or recommendation/capability/rank/causal inferences remain blocked.
The initial v5 slice does not accept SAMPLE as a structured observation, so a single answer cannot impersonate the
aggregate set. Missing or uncertain identity, members, answers, brand rules or scope remains UNKNOWN; unknown is
never a legal zero. Prompt renderer, Pack builder and locator parser are version-isolated; historical v8/v9 prompt
bytes and v11/v4 Pack/hash/reference semantics and results are not reinterpreted, rewritten or relabelled.

This approval does not authorize a fourth provider request, M1.1 database upgrade, M1.2 release, production
cutover or C1 collection.
