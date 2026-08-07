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
