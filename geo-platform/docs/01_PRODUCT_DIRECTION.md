# 01 Product Direction

Status: ACTIVE

The current direction is:

```text
AI/GEO brand visibility audit -> source diagnosis -> optimization experiment loop
```

Near-term priority:

1. Use real Wenxin browser-audit data already in the database.
2. Detect candidate GEO problems at Prompt/sample level.
3. Require URL-level target-page retrieval/citation metrics before calling a
   real baseline valid.
4. Record human-confirmed optimization actions.
5. Lock baseline samples before changes.
6. Attach fixed validation samples after release/cooling.
7. Compare metrics and require a human conclusion.

Current hard boundary:

```text
SOFTWARE_LOOP_READY != REAL_EXPERIMENT_STARTED
```

The first real experiment should not start until a target official page has
strict `RetrievalCandidate` URL evidence and the external release is manually
confirmed.

Deferred until after P0:

- Multi-platform collector expansion.
- Large trend dashboards.
- Postgres/Alembic migration.
- Automated website modification.
- Complex source authority scoring.
- Device/location/browser matrix collection.
