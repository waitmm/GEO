# GEO Workspace Notes

Primary project code lives in `geo-platform/`.

Read the applicable AGENTS.md chain, including `geo-platform/AGENTS.md`, once.
Then select context by task type; this is not a mandate to read every product
document for every task:

- Documentation-only T25 relay smoke: read the frozen unit definition supplied
  by the controller (or its exact entry in `docs/geo-v1.0/tasks.json`), the target
  section and adjacent context, and the independent acceptance conditions only.
  Do not read product briefs, semantic registries or historical logs unless the
  change actually depends on them. Do not run startup or product test suites.
- Relay tooling: read the relevant relay instructions, implementation and tests.
  Follow a concrete dependency when needed, without widening into product work.
- Product implementation: read the current brief and applicable optimization
  spec sections, relevant contracts, golden cases and conflicts. Consult the
  development log only for the affected feature or a known failure.
- Core business/semantic work: follow the project Semantic Change Guard below;
  selective reading does not waive any applicable contract or review.

Locate headings/symbols first, then read bounded sections. Reuse context already
read in this session unless it changed or was truncated; request only the missing
range. If a real dependency is unclear, expand that dependency, not every file.

Always preserve the formal GEO chain, immutable raw/frozen versions, exact
project/Prompt/Run scope and evidence ownership. Never replace fixed inputs with
`latest`, invent facts/acceptance, weaken gates or access credentials/production
data. External calls require the current explicit authorization and budget.
Relay work cannot merge main or reset historical failures/UNKNOWN usage.

Before core business changes, classify the work as `IMPLEMENTATION_CHANGE`,
`SEMANTIC_CHANGE`, or `SEMANTIC_RISK`. A semantic change without an approved
RFC must stop with `SEMANTIC_CONTRACT_REVIEW_REQUIRED`; semantic risk permits
investigation and shadow/replay only.

Local startup from this workspace root:

```bash
./scripts/dev.sh
```
