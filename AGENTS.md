# GEO Workspace Notes

Primary project code lives in `geo-platform/`.

Before changing this repository, read:

1. `geo-platform/AGENTS.md`
2. `geo-platform/docs/00_PROJECT_BRIEF.md`
3. `geo-platform/docs/05_OPTIMIZATION_LOOP_SPEC.md`
4. `geo-platform/docs/08_DEVELOPMENT_LOG.md`
5. `geo-platform/docs/semantics/00_DOMAIN_MODEL.md`
6. `geo-platform/docs/semantics/01_SEMANTIC_CONTRACTS.md`
7. `geo-platform/docs/semantics/02_GOLDEN_SEMANTIC_CASES.md`
8. `geo-platform/docs/semantics/04_CONFLICT_REGISTER.md`

Before core business changes, classify the work as `IMPLEMENTATION_CHANGE`,
`SEMANTIC_CHANGE`, or `SEMANTIC_RISK`. A semantic change without an approved
RFC must stop with `SEMANTIC_CONTRACT_REVIEW_REQUIRED`; semantic risk permits
investigation and shadow/replay only.

Local startup from this workspace root:

```bash
./scripts/dev.sh
```
