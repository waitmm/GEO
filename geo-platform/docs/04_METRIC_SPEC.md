# 04 Metric Spec

Status: ACTIVE

## Run Validity

Valid analytical runs:

- `success`
- `partial_success`

`partial_success` is allowed for analysis but must remain visibly distinct from
full success. It must not be renamed or counted as fully successful parsing.

## Core Metrics

- `brand_mention_rate`: valid runs where the brand appears divided by valid
  sample count.
- `brand_recommendation_rate`: valid runs where
  `brand_recommendation_level >= 2` divided by valid sample count.
- `official_reference_rate`: valid runs with at least one official-domain
  citation divided by valid sample count.
- `avg_reference_count`: parsed/stored reference rows divided by valid sample
  count.
- `reference_complete_rate`: valid runs with complete reference chain divided by
  valid sample count.

## Target Page Retrieval Entry

The first real optimization experiment for Prompt 19 uses
`target_page_retrieval_rate` as the primary metric, because the target page has
not entered retrieval candidates at all.

Definitions:

- `valid_run_count`: valid Runs in the current statistical scope.
- `retrieved_run_count`: valid Runs where the target page appears in
  `RetrievalCandidate` after URL normalization. The same target URL counts at
  most once per Run.
- `target_page_retrieval_rate`: `retrieved_run_count / valid_run_count`.
- `delta_pp`: validation retrieval rate minus baseline retrieval rate,
  expressed in percentage points.

`0 / valid_run_count = 0%` is a valid baseline for "target page did not enter
retrieval candidates". It must not be treated as a failed experiment baseline.

## Target Page Retrieval-To-Citation

`target_page_conversion_rate` is the second funnel metric after the target page
has entered retrieval candidates.

Definitions:

- `target_page_retrieved_count`: number of valid Runs where the target page
  appears in `RetrievalCandidate` after URL normalization. The same target URL
  counts at most once per Run.
- `target_page_cited_count`: number of valid Runs where the same normalized
  target page appears in `ReferenceSource`. The same target URL counts at most
  once per Run.
- `target_page_conversion_rate`: `target_page_cited_count /
  target_page_retrieved_count`.
- `delta_pp`: validation conversion rate minus baseline conversion rate,
  expressed in percentage points.

If `target_page_retrieved_count = 0`, conversion is `null` / not applicable.
Do not show it as `0%`, because "not retrieved" and "retrieved but not cited"
are different problems.

The metric must reuse the same URL normalization as citation dedupe: protocol
differences, `www`, trailing slash, fragments, safe tracking parameters,
canonical URL, and resolved final URL should not create separate sources.

Experiment results must keep drilldown:

```text
overall -> per Prompt -> per environment -> raw Run IDs
```

## B1 Fact Matrices

Platform matrix, content type distribution, and time distribution are B1 rule
facts. B2/LLM may explain or propose hypotheses from these rows, but must not
invent platform counts, content categories, time buckets, or representative
URLs.

Platform conversion uses Run-level sets:

```text
platform_citation_conversion_rate = citation_run_count / candidate_run_count
retrieved_not_cited_run_count = candidate_run_ids - citation_run_ids
```

Occurrence counts are supporting evidence only. They must not replace Run-level
counts.

Content type classification is a reproducible heuristic. If rules do not match,
use `UNCATEGORIZED`; if a content type has citations but no comparable candidate
denominator, show conversion as `not_applicable`, not a percentage over 100%.

Time extraction must not treat a title year like "2026" as a publication date.
When no reliable date exists, use `UNKNOWN`.

Retrieval candidate coverage must be reported separately from target-page
retrieval rate:

```text
retrieval_coverage_status = COMPLETE / INCOMPLETE
retrieval_candidate_count
reference_count
common_candidate_count_per_run
suspected_fixed_collection_limit
run_rows[]
```

If `retrieval_coverage_status = INCOMPLETE` or the Run-level captured candidate
count is below `minimum_retrieval_candidate_count`, retrieval/funnel metrics are
not eligible:

- `target_page_retrieval_rate = null`
- `target_page_conversion_rate = null`
- `retrieved_not_cited = null`
- `platform_candidate_conversion_rate = null`
- content-type candidate conversion = `null`

Captured candidates may remain visible as `captured_candidates` for audit and
source-level inspection, but B1/B2 must not treat them as the complete AI
retrieval library.

## Data Quality

The four reference counts should stay visible:

```text
UI declared -> DOM items -> parsed titles -> resolved URLs
```

A real 100% success means all expected references are parsed and resolved where
the UI exposes them. Do not loosen the definition to make dashboards look green.
