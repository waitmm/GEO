# RFC-RUNTIME-001: Analysis Context And Stage Lifecycle

```yaml
rfc_id: RFC-RUNTIME-001
status: FROZEN
semantic_maturity: FROZEN
implementation_status: PARTIAL
authors: [Product Owner, Codex]
created_at: 2026-09-08
definition_approved_by: Product Owner
definition_approved_at: 2026-09-09T15:25:02+08:00
definition_approval_reference: docs/semantics/approvals/RFC-RUNTIME-001.definition-freeze.md
effective_from: 2026-09-09T15:25:02+08:00
golden_case_ids: [CASE-REAL-019, CASE-REAL-040]
production_cutover_approved_by: null
production_cutover_approved_at: null
production_cutover_approval_reference: null
affected_contracts:
  - SC-HISTORY-001@1.0.0
  - SC-SCOPE-001@1.0.0
  - SC-PT-001@1.0.0
  - SC-UNKNOWN-001@1.0.0
  - SC-EVIDENCE-003@1.0.0
  - SC-STEP7-001@1.0.0
  - SC-STEP8-001@1.0.0
  - SC-EXPERIMENT-001@1.0.0
proposed_contract: SC-RUNTIME-001@0.1.0
supersedes: null
definition_review_status: APPROVED
final_author_status: DEFINITION_FROZEN
spike_authorization_status: AUTHORIZED_READ_ONLY_PROJECTION
spike_authorized_at: 2026-09-09T15:25:02+08:00
spike_status: COMPLETE
spike_result: SPIKE_PASS
spike_report_reference: docs/semantics/spikes/RFC-RUNTIME-001.read-only-projection-spike.md
phase_1a_status: COMPLETE
phase_1a_result: PASS
phase_1a_report_reference: docs/semantics/shadows/RFC-RUNTIME-001.phase-1a-persistence-spine.md
phase_1b_status: BLOCKED
phase_1b_result: BLOCKED_BY_FROZEN_STAGE_OUTPUT_AND_BINDING_LINEAGE_MAPPING_GAPS
phase_1b_report_reference: docs/semantics/shadows/RFC-RUNTIME-001.phase-1b-prospective-shadow-capture.md
revision: 004
review_001_reference: docs/semantics/reviews/RFC-RUNTIME-001.review-001.md
review_001_result: NEEDS_REVISION
review_002_reference: docs/semantics/reviews/RFC-RUNTIME-001.review-002.md
review_002_result: NEEDS_REVISION
review_003_reference: docs/semantics/reviews/RFC-RUNTIME-001.review-003.md
review_003_result: NEEDS_REVISION
review_004_reference: docs/semantics/reviews/RFC-RUNTIME-001.review-004.md
review_004_result: NEEDS_REVISION
review_005_reference: docs/semantics/reviews/RFC-RUNTIME-001.review-005.md
review_005_result: APPROVED
```

## 1. Problem

The Single Prompt product has a stable Step 1-8 order, but current runtime
objects do not share one immutable lineage identity. Workflow state is assembled
from a latest EvidencePackage, latest PromptAnalysisRun, latest completed
ShadowRun, current-state Product Truth and Evidence rows, mutable confirmation,
Candidate lists, Experiment lists and frontend fallbacks.

Consequently, the system cannot always prove:

```text
which exact Step 2-8 analysis is current;
which immutable inputs produced one output;
which exact output set a human reviewed;
which descendants became ineligible after a correction;
whether a historical replay consumed historical or current mutable state.
```

The problem is runtime identity and lifecycle integrity. It is not a proposal to
change GEO evidence, Benchmark, Gap, Channel, Strategy or Step 8 business
semantics.

## 2. Inputs And Status

Definition inputs:

- `docs/semantics/05_RUNTIME_SEMANTIC_MAP.md`
- Runtime Integrity Phase 0 investigation
- `docs/semantics/snapshots/CASE-REAL-019.manifest.json`
- `docs/semantics/snapshots/CASE-REAL-040.manifest.json`
- `docs/semantics/04_CONFLICT_REGISTER.md`
- current OBSERVED Semantic Contracts

```text
CURRENT OBSERVED RUNTIME
= docs/semantics/05_RUNTIME_SEMANTIC_MAP.md

PROPOSED RUNTIME SEMANTICS
= this RFC

PRODUCTION BEHAVIOR
= unchanged until independent cutover approval
```

## 3. Current Semantics

Applicable observed boundaries remain in force:

- accepted history must not be silently rewritten;
- current and historical Prompt/Package/Candidate/Experiment scopes must not
  mix;
- formal Evidence requires valid lineage;
- Step 7 creates and confirms StrategyCandidate, not Action/Experiment;
- Step 8 cannot mutate Strategy Truth and must freeze Experiment snapshots;
- Shadow, Golden and legacy outputs cannot become production current by
  fallback.

Current implementation does not fully enforce those boundaries through one
runtime identity. `UNIFIED_RUNTIME_IDENTITY = NONE` and
`PACKAGE_FREEZE = PARTIAL` are observed facts, not proposed semantics.

## 4. Current Production Behavior

Current production behavior is frozen only as observed evidence for this RFC:

```text
run-analysis
-> one background thread
-> sequential function calls with intermediate commits
-> one outer failure status

workflow/status
-> queries objects at several scopes and times
-> chooses current/latest independently

human review
-> updates mutable business rows
-> generally has no immutable output-set binding

frontend
-> combines backend status with independently loaded detail/list responses
-> derives additional ready/complete/current states
```

The detailed evidence and #19/#40 counts are maintained in the Runtime Semantic
Map and are not repeated as proposed truth.

## 5. Observed Failures

This RFC responds to observed, not hypothetical, failures:

```text
database locked during background/review writes;
repeated review and Step 7 spinners;
incorrect READY and NO_STRATEGY projections;
historical Candidate display as current;
review progress reset after Alignment rerun;
orphan RUNNING analysis state after restart;
partial outputs retained under a FAILED outer run;
read-only current reconstruction taking over 120 seconds or 3 minutes.
```

These incidents do not all share one implementation bug. They share missing
runtime identity, authority, immutability and dependency contracts.

## 6. Runtime Root Options

### Option A: PromptAnalysisRun As Root

Rejected.

```text
Pros:
  already represents a background invocation;
  already carries running/completed/failed status.

Blocking evidence:
  does not store exact run ids;
  does not bind EvidencePackage;
  does not bind root input snapshots or fingerprint;
  does not bind feature/contract profile;
  one outer status cannot represent the real DAG;
  restart and partial-commit behavior make it an attempt-like record.
```

Promoting this row would preserve identity ambiguity and confuse runtime attempt
with semantic lineage.

### Option B: EvidencePackage As Root

Rejected as the complete root; retained as a root input reference.

```text
Pros:
  versioned Package identity;
  fixed run-id list;
  environment and baseline information;
  existing Strategy binding.

Blocking evidence:
  package hash excludes report payload and semantic inputs;
  source content, Product Truth, Binding and Alignment can appear later;
  old packages remain active;
  package read can use current Prompt text;
  package is evidence projection, not execution/review lineage.
```

### Option C: New AnalysisContext

Selected candidate.

It is the only option that can identify an independent business analysis
lineage without redefining a cache, Package or execution attempt.

### Option D: Composite Existing-Object Tuple

Rejected.

A tuple such as `Package + AnalysisRun + Candidate` has no durable identity,
cannot represent pre-Candidate stages, retains latest-selection ambiguity and
cannot own review/invalidation/current-pointer history.

## 7. Proposed AnalysisContext Semantics

### 7.1 Definition

> AnalysisContext represents one immutable root analysis lineage for one
> workflow track. It freezes the analysis starting inputs. It is not a
> computation cache, stage result, Candidate, Package or aggregate status row.

### 7.2 Identity And Scope

```text
context_id
= independent business lineage identity

scope
= project_id
+ prompt_id
+ workflow_track
```

Candidate workflow tracks are:

```text
PRODUCTION
SHADOW
GOLDEN_REPLAY
LEGACY
```

The names may be mapped differently in implementation, but the separation is a
required semantic capability. A non-production track cannot become production
current through row age or shared object ids.

### 7.3 Context Fingerprint

```text
context_fingerprint
= deterministic Root Semantic Input Equivalence fingerprint

fingerprint_contract_version
= runtime_context_fingerprint.v1
```

`context_id` and `context_fingerprint` are orthogonal.

```text
same fingerprint + multiple context_ids = ALLOWED
same fingerprint -> reuse same Context row = FORBIDDEN
```

Separate user starts can have independent actor, time, review, attempt and
pointer histories while consuming equivalent cache/materialization results.

The fingerprint is SHA-256 over `semantic_manifest_canonicalization.v1` using
the Root member profiles below. Prompt content is hashed exactly as captured;
whitespace is not normalized.

The canonical fingerprint payload is exactly:

```text
fingerprint_contract_version;
manifest_canonicalization_version;
manifest_shape_semantics = OBJECT_WITH_NESTED_MANIFESTS;
project_id;
prompt_id;
prompt_content_hash;
acquisition_scope_hash;
run_scope_hash;
run_output_set_hash;
evidence_package_root_projection_hash;
root_runtime_contract_profile_version.
```

The following are excluded:

```text
context_id;
EvidencePackage row id/version/existing package hash;
workflow_track;
created_at, actor and creation reason;
review and pointer history;
all Stage outputs and Stage configuration;
Product Truth projection;
SourceDocument fetch/refetch content;
downstream model/provider;
Candidate Builder/Resolver/Synthesis versions;
Strategy and Execution Proposal output.
```

`workflow_track` is a lineage/current namespace, not Root semantic input. A
PRODUCTION and SHADOW Context may therefore have equal fingerprints while
remaining distinct Context IDs in distinct pointer namespaces.

The complete immutable Context manifest also has an integrity hash:

```text
context_manifest_hash
= SHA-256(semantic_manifest_canonicalization.v1({
    manifest_canonicalization_version,
    manifest_contract_version = runtime_context_manifest.v1,
    manifest_shape_semantics = OBJECT_WITH_NESTED_MANIFESTS,
    context_id,
    project_id,
    prompt_id,
    workflow_track,
    evidence_package_ref,
    evidence_package_root_projection_ref_and_hash,
    context_fingerprint,
    root_runtime_contract_profile_version,
    creation_actor,
    creation_reason,
    created_at
  }))
```

`context_manifest_hash != context_fingerprint`: the former protects one
historical lineage manifest; the latter compares Root semantic input.

#### Canonical Manifest Contract

Every semantic manifest hash in this RFC uses
`semantic_manifest_canonicalization.v1`. Root manifests additionally use the
closed member profiles in `root_manifest_canonicalization.v1`; Stage manifests
use `stage_manifest_canonicalization.v1`. The canonicalization version is an
explicit field inside every hashed payload, including:

```text
context_fingerprint;
EvidencePackageRootProjection and nested Root manifests;
Stage input_set_hash and output_set_hash;
review output/partition hash;
legacy source_ref_set_hash and virtual projection identity.
```

Changing any canonicalization contract creates a different hash namespace.
Old/new hashes are never silently equivalent.

The canonical bytes contract is
`semantic_manifest_canonical_bytes.v1`. It is part of
`semantic_manifest_canonicalization.v1`, not an implementation choice.

```text
text encoding = UTF-8 without BOM
Unicode normalization = NO_UNICODE_NORMALIZATION
line-ending normalization = NO_LINE_ENDING_NORMALIZATION
object-key order = ascending unsigned lexicographic order of exact UTF-8 bytes
hash algorithm = SHA-256
hash text form = 64 lowercase hexadecimal characters
```

The exact captured string, including CR, LF, whitespace and Unicode code-point
sequence, is semantic input. Platform encodings, locale collation, Python
`repr`, JavaScript `JSON.stringify` and database return order are forbidden
canonicalization sources.

Canonical bytes are generated by the following prefix grammar. Literal grammar
characters are ASCII. `n` is a base-10 unsigned byte/member count with no
leading zero except `0`; concatenation has no implicit whitespace.

```text
STRING(v)    = s<byte_length_of_UTF8(v)>:<exact_UTF8_bytes(v)>
INTEGER(v)   = i<base10_integer>;
DECIMAL(v)   = d<canonical_decimal>;
FLOAT64(v)   = f<16_lowercase_hex_digits_of_big_endian_IEEE754_binary64>;
BOOLEAN      = b0; | b1;
TIMESTAMP(v) = t27:<UTC_RFC3339_YYYY-MM-DDTHH:MM:SS.ffffffZ>
ARRAY(v)     = a<member_count>:[<canonical_node_0>...<canonical_node_n>]
OBJECT(v)    = o<field_count>:{<STRING(key_0)><field_state_0>...
                               <STRING(key_n)><field_state_n>}
```

Object keys use the byte ordering above. Raw null is not a canonical node;
null/missing/empty are represented only by these exact field-state bytes:

```text
FIELD_ABSENT       = x0;
FIELD_PRESENT_NULL = x1;
EMPTY_COLLECTION   = x2;
VALUE(v)           = x3:<canonical_node(v)>
```

Therefore `FIELD_ABSENT`, `FIELD_PRESENT_NULL`, and `EMPTY_COLLECTION` always
hash differently. Every contract-declared field appears exactly once in its
owning canonical object with one state. An undeclared field is invalid; a
declared field omitted by a serializer is also invalid.

Integer zero has one representation, `i0;`; `-0` is invalid integer input.
Canonical decimal input uses grammar
`-?(0|[1-9][0-9]*)(\.[0-9]+)?`, forbids exponent notation, removes trailing
fractional zeros and the now-empty decimal point, and normalizes every negative
zero to `0`. A binary floating-point value is never converted through a decimal
string: finite IEEE-754 binary64 bits use `FLOAT64`; positive and negative zero
both use the positive-zero bits; NaN and infinities are invalid. An owning
schema must declare INTEGER, DECIMAL or FLOAT64 and cannot switch types while
retaining its contract version.

An offset-bearing timestamp is converted to UTC before `TIMESTAMP` encoding. A
timestamp without an offset is invalid unless its owning source contract names
one fixed source timezone. `browser_monitor_run_root_snapshot.v1` names UTC for
the existing UTC-naive SQL `DateTime` fields; future acquisition snapshots must
capture an offset or explicitly use that same source contract.

Collection rules are exact:

```text
SET_SEMANTICS
-> canonicalize each member and its contract-declared member identity
-> sort by the member identity's canonical bytes
-> serialize the sorted members as ARRAY

ORDER_SIGNIFICANT
-> every member contains a zero-based contiguous business ordinal
-> reject missing, negative, duplicate or gapped ordinals
-> serialize in ascending ordinal order
-> never use query/input order as the ordinal
```

For either collection, equal member identity plus byte-identical canonical
member content collapses as `IDENTICAL_DUPLICATE`. Equal identity plus different
canonical semantic content is `MANIFEST_IDENTITY_CONFLICT`; neither first nor
last wins. A new formal manifest is invalid; a legacy projection is `UNSAFE`.
Database row ID participates only when the owning contract explicitly declares
it as the member identity.

Every semantic hash is SHA-256 over the canonical bytes of exactly this hash
envelope:

```text
{
  canonicalization_version: VALUE("semantic_manifest_canonicalization.v1"),
  canonical_bytes_contract: VALUE("semantic_manifest_canonical_bytes.v1"),
  hash_algorithm: VALUE("SHA-256"),
  manifest_contract_version: VALUE(<exact owning contract version>),
  manifest_type: VALUE(<exact manifest type>),
  payload: VALUE(<owning contract's canonical semantic object>)
}
```

The envelope itself is encoded with the grammar above. No delimiters are added
outside its canonical bytes. A canonicalization, byte-contract, manifest-type,
manifest-contract or member-identity-contract change creates a different hash
universe and requires a new version.

The exact `manifest_type` / `manifest_contract_version` registry is:

| Hash use | `manifest_type` | `manifest_contract_version` |
| --- | --- | --- |
| Context semantic fingerprint | `AnalysisContextFingerprint` | `runtime_context_fingerprint.v1` |
| Context integrity manifest | `AnalysisContextManifest` | `runtime_context_manifest.v1` |
| Root projection | `EvidencePackageRootProjection` | `evidence_package_root_projection.v1` |
| Fixed Run set | `RunScopeManifest` | `run_scope_manifest.v1` |
| Run original output | `BrowserMonitorRunRootSnapshot` | `browser_monitor_run_root_snapshot.v1` |
| Reference observations | `ReferenceObservationRootManifest` | `reference_observation_root.v1` |
| Retrieval observations | `RetrievalObservationRootManifest` | `retrieval_observation_root.v1` |
| Acquisition scope | `AcquisitionScopeManifest` | `acquisition_scope.v1` |
| Acquisition artifacts | `AcquisitionArtifactManifest` | `acquisition_artifacts.v1` |
| Target URLs | `TargetUrlManifest` | `target_url_identity.exact_utf8.v1` |
| Stage input | `StageInputManifest/<STAGE_TYPE>` | `<exact runtime_stage.*.v1>/input` |
| Stage configuration | `StageConfigurationManifest/<STAGE_TYPE>` | `<exact runtime_stage.*.v1>/configuration` |
| Stage output | `StageOutputManifest/<STAGE_TYPE>` | `<exact runtime_stage.*.v1>/output` |
| Review full output target | `ReviewTargetManifest/STAGE_OUTPUT` | `review_target_manifest.v1` |
| Review partition target | `ReviewTargetManifest/STAGE_PARTITION` | `review_target_manifest.v1` |
| Review reusable fact target | `ReviewTargetManifest/REUSABLE_FACT_VERSION` | `review_target_manifest.v1` |
| Legacy Stage source set | `LegacyStageSourceManifest` | `legacy_stage_source_manifest.v1` |
| Legacy fixed selector scope | `LegacyFixedScopeValues` | `LegacyFixedScopeValues.v1` |
| Virtual Context identity | `VirtualRuntimeIdentity/CONTEXT` | `virtual_runtime_identity.v1` |
| Virtual Stage identity | `VirtualRuntimeIdentity/STAGE` | `virtual_runtime_identity.v1` |
| Cache compatibility signature | `SemanticCacheCompatibilitySignature` | `semantic_cache_compatibility_signature.v1` |

`<STAGE_TYPE>` is the exact uppercase enum token in RuntimeStageProfile v1;
`<exact runtime_stage.*.v1>` is its one contract identity from Section 9.1.
The literal slash and suffix are part of the registered strings. No
implementation may substitute class names, localized labels or storage table
names.

Audit refs, storage row IDs and timestamps excluded by the owning manifest
contract remain in its non-hashed envelope. They are never appended to the hash
bytes by an implementation.

### 7.4 Root Input Manifest

The immutable root manifest must include or reference enough data to prove and
replay:

```text
project identity;
prompt id plus exact prompt content snapshot/hash;
collection/acquisition scope identity/hash;
fixed Run ids and deterministic run-scope hash;
per-Run immutable output refs and hashes;
answer payload snapshot/ref;
Reference/Citation member manifest and hash;
Retrieval member manifest and hash;
all fixed-Run RunArtifact members and frozen content hashes under acquisition_artifacts.v1;
EvidencePackage id/version/existing package hash as audit ref;
EvidencePackageRootProjection snapshot/ref and semantic hash;
root runtime contract profile/version;
workflow track;
creation actor, reason and timestamp;
context fingerprint and context manifest hash.
```

Hash without retrievable immutable content is integrity evidence, not replay
evidence. Root manifests must retain immutable payloads or references to durable
immutable payloads.

`root_runtime_contract_profile_version = runtime_root_profile.v1`. It binds:

```text
EvidencePackageRootProjection contract = evidence_package_root_projection.v1;
Run original-output snapshot contract = browser_monitor_run_root_snapshot.v1;
Reference observation snapshot contract = reference_observation_root.v1;
Retrieval observation snapshot contract = retrieval_observation_root.v1;
canonical manifest contract = semantic_manifest_canonicalization.v1;
Root member profile = root_manifest_canonicalization.v1;
hash algorithm = SHA-256;
Run eligibility contract = run_root_eligibility.v1;
acquisition scope contract = acquisition_scope.v1;
required acquisition artifact contract = acquisition_artifacts.v1;
target URL identity contract = target_url_identity.exact_utf8.v1;
```

`run_root_eligibility.v1` accepts only fixed Package Runs whose captured status
is `success` or `partial_success`. `partial_success` remains explicit and never
becomes full success; each downstream metric/Stage applies its own eligibility
rules. Zero accepted Runs cannot create an executable Context.

`acquisition_scope.v1` hashes the canonical per-Run set of task/batch identity,
platform, source type, adapter, run/sample sequence, collection/sampling mode,
collector/browser/OS/profile/conversation/network identity and
collector/parser versions. `acquisition_artifacts.v1` includes every
`RunArtifact` row captured for a fixed Run at the creation boundary. Each member
requires the exact artifact bytes' SHA-256 hash in addition to its type, storage
ref, MIME type and size. No artifact rows is `EMPTY_COLLECTION`; a row whose
bytes cannot be frozen makes a new formal Root manifest invalid.

The artifact manifest uses `SET_SEMANTICS`; member identity is
`run_id + artifact_type + content_hash`. Equal type/content duplicates collapse,
while same identity with conflicting MIME/size metadata is
`MANIFEST_IDENTITY_CONFLICT`. Storage path and legacy artifact row id are audit
refs outside semantic member identity.

Root membership is intrinsic and must satisfy all five conditions:

```text
the fact exists at AFTER_ACQUISITION_ROOT_PROJECTION_FREEZE;
it belongs to Prompt/Acquisition/Run original-output lineage;
an immutable value/ref/hash can be captured at Context creation;
it does not depend on a Step 2-8 StageExecution output;
it does not require current mutable derived state.
```

Failure of any condition means `NOT_ROOT_SAFE`. Downstream consumption must not
determine or promote Root membership. A baseline or Stage consumes its own
formal input manifest; “used by a later metric” is never a Root qualification
rule.

Only Acquisition and Root snapshot rules belong to this profile. Any algorithm,
model, prompt, schema or flag for a node in `RuntimeStageProfile v1` belongs to
that Stage configuration manifest and cannot force `NEW_CONTEXT` by itself.

### 7.5 EvidencePackageRootProjection

`EvidencePackageRootProjection` is a logical immutable snapshot, not a new
approved database object or table and not a query recipe.

> It contains only the acquisition facts already available at Context creation
> that are legal Root inputs. It never treats the full current
> `package_payload_json` or a live Package API response as Root input.

After creation, every consumer reads the fixed values/refs/member manifests and
hashes captured in this projection. Re-querying the Package, Prompt, Run,
Reference, Retrieval or artifact tables to rebuild an existing projection is
forbidden.

The projection schema is exactly:

```text
projection_contract_version = evidence_package_root_projection.v1;
project_id;
prompt_id;
prompt_content_snapshot_ref + exact prompt_content_hash;
acquisition_scope_identity + acquisition_scope_hash;
canonical fixed run_ids + run_scope_hash;
RunOriginalOutputSnapshot manifest/ref + run_output_set_hash;
ReferenceObservationSnapshot manifest/ref + reference_output_set_hash;
RetrievalObservationSnapshot manifest/ref + retrieval_output_set_hash;
required acquisition artifact manifest/ref/hash;
target_page_urls snapshot;
filtered acquisition environment snapshot under `acquisition_scope.v1`;
Package root-source schema_version;
metric_spec_version as lineage audit only, excluded from Root semantic hash;
projection member refs/count/hash;
source EvidencePackage audit ref.
```

The semantic hash payload for `evidence_package_root_projection.v1` is exactly:

```text
manifest_canonicalization_version = semantic_manifest_canonicalization.v1;
root_member_profile_version = root_manifest_canonicalization.v1;
projection_contract_version;
manifest_shape_semantics = OBJECT_WITH_NESTED_MANIFESTS;
project_id;
prompt_id;
prompt_content_hash;
acquisition_scope_hash;
run_scope_hash;
run_output_set_hash;
reference_output_set_hash;
retrieval_output_set_hash;
acquisition_artifact_set_hash;
target_url_manifest_hash;
package_root_source_schema_version.
```

The source EvidencePackage audit ref, metric spec version, Package row IDs,
database row IDs, projection storage ref, created time and projection member
storage refs are envelope-only and excluded. The fixed values/payload refs
behind every included nested hash remain in the immutable projection snapshot.

`browser_monitor_run_root_snapshot.v1` uses `SET_SEMANTICS` and member identity
`run_id`. It unconditionally captures these fields from the existing
`BrowserMonitorRun` schema for every fixed eligible Run:

```text
id, task_id, project_id, batch_id, prompt_id;
platform, source_type, adapter, run_sequence, sample_index, collection_mode;
collector_id, browser, browser_version, os, profile_identifier,
conversation_id, sampling_mode, network_region;
collector_version, parser_version;
status, stage;
original_query, page_query, retrieval_query;
started_at, finished_at, created_at;
answer_text, answer_html, answer_char_count;
expected_reference_count, detected_reference_count, resolved_reference_count,
ui_declared_count, dom_reference_count, parsed_reference_count,
resolved_url_count, unresolved_reference_count, reference_complete;
brand_mentioned, brand_mention_count, brand_first_position,
brand_recommendation_level;
error_stage, error_type, error_message, outcome_category, blocked_type,
blocked_reason.
```

`duration_ms`, `retry_count` and `updated_at` are operational and excluded.
Their exclusion is unconditional in profile v1.

`reference_observation_root.v1` uses `ORDER_SIGNIFICANT` within each Run. Its
member identity is:

```text
run_id + reference_index + canonical_reference_identity

canonical_reference_identity
= canonicalization_version + canonical_url_hash
```

Both canonicalization fields are mandatory. Empty/unknown canonical identity
makes a new formal Root invalid; raw URL is retained as captured content but is
not an identity fallback. The member captures `display_title`, `matched_title`,
`url`, `canonical_url`, `canonical_url_hash`, `canonicalization_version`,
`domain`, `platform_name`, `resolution_method`, `match_confidence`,
`evidence_path` and `created_at`. Post-acquisition classification fields
`relevance_label`, `quality_label`, `is_official_domain` and
`is_competitor_domain` are excluded rather than preserved as semantic
annotations.

`retrieval_observation_root.v1` uses `ORDER_SIGNIFICANT` within each Run. Its
member identity is:

```text
run_id + SHA-256(exact retrieval_query UTF-8) + rank
+ canonicalization_version + canonical_url_hash
```

It captures `retrieval_query`, `rank`, `title`, `url`, `canonical_url`,
`canonical_url_hash`, `canonicalization_version`, `domain`, `snippet`,
`evidence_path` and `created_at`. Empty/unknown canonical identity invalidates a
new formal Root. Database row IDs are audit refs only.

The fixed Run id manifest uses `SET_SEMANTICS`, member identity `run_id`, numeric
ascending order and duplicate collapse only for identical ids. The target URL
manifest uses `ORDER_SIGNIFICANT` and
`target_url_identity.exact_utf8.v1`. That contract performs no trimming, URL
parsing, case folding, percent decoding, Unicode normalization or line-ending
normalization. Identity is SHA-256 of the exact captured UTF-8 URL string.
Byte-identical URL strings retain the first declared business occurrence before
contiguous zero-based ordinals are assigned; non-identical strings are never
deduplicated by an implementation. Member identity is the post-dedupe ordinal
plus exact-string hash. This conservative rule preserves the first target as
primary and guarantees identity without relying on mutable URL-normalizer code
or database order.

The acquisition environment manifest uses `SET_SEMANTICS` over the exact
per-Run tuples already named by `acquisition_scope.v1`, keyed by `run_id`, plus
the captured Package `source_note` as a scalar. Package-derived baseline
windows, content/time classifiers, metric versions and live Prompt fields are
excluded. `Package.schema_version` enters only as
`package_root_source_schema_version` to interpret captured Package root fields.

When a required immutable snapshot/ref/hash is unavailable, a new formal
Context cannot be declared executable. A read-only legacy projection instead
uses the completeness rules in Section 20.

### 7.6 Current EvidencePackage Field Classification

The current Package schema is mixed and is classified as follows.

| Current field/payload area | Classification | Runtime rule |
| --- | --- | --- |
| `project_id`, `prompt_id` | `ROOT_SAFE` | Root business scope identities. |
| `source_run_ids_json` | `ROOT_SAFE` | Canonicalize and hash; row list alone does not freeze Run outputs. |
| stored Package-payload `prompt.prompt_text` | `ROOT_SAFE_IF_CAPTURE_PROVEN` | May supply exact prompt snapshot; the live Prompt row may not replace it. |
| `target_page_urls_json` / stored payload target URLs | `ROOT_SAFE` | Frozen acquisition/baseline scope input. |
| acquisition fields in `environment_snapshot_json` | `ROOT_SAFE` | Only platform/source type/adapter/collection mode/browser/profile/collector/parser/network/source note fields selected by `acquisition_scope.v1`; no live re-read. |
| `schema_version` | `ROOT_SAFE` | Interprets Package fields used by the Root projection. |
| `metric_spec_version`, content/time classifier versions | `STAGE_DERIVED_CONFIG` | Belong to `RUN_METRICS` or their consuming Stage configuration; excluded from Root semantic hash. |
| Reference/Retrieval rows for fixed Runs | `ROOT_SAFE_IF_SNAPSHOTTED` | Enter only through immutable observation manifests. |
| Package `id`, `version`, existing `package_hash` | `LINEAGE_AUDIT_ONLY` | Kept in `evidence_package_ref`; excluded from semantic fingerprint. |
| payload `summary`, `metrics`, `metric_snapshot`, eligibility lists | `STAGE_DERIVED` | Metric/eligibility facts belong to `RUN_METRICS`; presentation summary is downstream, never Root truth. |
| payload source/channel/content/time distributions and drilldowns | `STAGE_DERIVED` | Not part of Root fingerprint. |
| payload `source_level_evidence`, `representative_sources` | `STAGE_DERIVED` | May include SourceDocument/Alignment semantics; exclude from Root. |
| payload Benchmark/Gap/action/channel recommendation fields | `STAGE_DERIVED` | Carried by BENCHMARK/GAP/CHANNEL/STRATEGY Stages. |
| payload project name/brand/website and presentation labels | `STAGE_DERIVED_OR_PRESENTATION` | Project identity is Root; mutable project configuration is a versioned Stage/reusable input. |
| `status`, `superseded_by_id`, `updated_at` | `CURRENT_MUTABLE` | Package lifecycle only; never historical Root semantic input. |
| API `prompt_text` that prefers the live Prompt row | `CURRENT_MUTABLE` | Forbidden as a historical Context snapshot. |
| live SourceDocument/Product Truth/Alignment/metadata re-queries | `CURRENT_MUTABLE` | Must not be injected into an old Context; use exact Stage/reusable versions. |

The stored full `package_payload_json` can remain historical product evidence,
but it is not hashed wholesale into a Context and cannot silently supply a
Stage-derived input.

### 7.7 Objects Excluded From Root Fingerprint

The following are progressive Stage inputs/outputs:

```text
Product Truth review/result projection;
project/brand mutable configuration used by downstream rules;
SourceDocument fetched/refetched content;
Passage;
SourceClaim;
Candidate Builder result;
EvidenceAlignment;
Benchmark;
Gap;
Channel Evidence and Resolver output;
Strategy Synthesis;
Execution Proposal.
```

They cannot be required before Context creation and therefore cannot form a
circular Root fingerprint.

### 7.8 Creation Boundary

```text
Collection / Acquisition
-> fixed Run scope, immutable Run/Reference/Retrieval/artifact manifests available
-> EvidencePackageRootProjection complete and atomically visible
-> CREATE AnalysisContext
-> execute Step 2-8 runtime stages
```

Collection is upstream Acquisition, not an internal mutable Stage of this
Context. The precise boundary is
`AFTER_ACQUISITION_ROOT_PROJECTION_FREEZE`; `AFTER_RUN_SCOPE_FREEZE` is only a
short label and is insufficient when Run output or observation manifests are
not yet frozen.

An implementation cannot declare the Context executable until the complete root
manifest, projection, fingerprint and manifest hash are atomically visible.
Allocation of a future storage id has no semantic meaning before that condition.

### 7.9 EvidencePackage Boundary

```text
EvidencePackage
= source/audit reference for a Root-safe projection

AnalysisContext
= runtime lineage root consuming EvidencePackageRootProjection
```

The Context freezes exact Run/observation outputs, the Root-safe projection and
root contract profile. The complete Package payload is not a Root input.
EvidencePackage remains a product evidence object and is not deprecated.

### 7.10 Context Reuse And New Context

Resume requires an explicit existing `context_id`; fingerprint equality alone
never selects a Context.

The following require `NEW_CONTEXT`:

```text
exact Prompt content changes;
Run scope changes;
any frozen Run/Reference/Retrieval/acquisition artifact changes;
the chosen EvidencePackage audit reference changes, even if projection-equivalent;
EvidencePackageRootProjection semantic content changes;
workflow track changes;
root runtime contract profile changes;
an independent business lineage is explicitly started.
```

A different Package id/version has an equivalent semantic fingerprint only when
its `evidence_package_root_projection.v1` canonical semantic payload is equal.
Package IDs are not compared for semantic equivalence. A different Package ref
still creates a distinct Context lineage.

The following create a new StageExecution under the same Context:

```text
Product Truth correction/projection change;
successful source refetch;
Passage regeneration;
model/prompt/schema change;
Candidate Builder policy change;
normalization or deterministic Stage algorithm change;
Resolver/Synthesis/Execution Proposal compiler change.
```

## 8. StageExecution

### 8.1 Definition

> StageExecution is one logical computation identity under a fixed Context,
> fixed Stage input set and fixed Stage Contract/configuration.

It is not a Product Step card, worker attempt, progress row or semantic cache
entry.

### 8.2 Required Identity

```text
stage_execution_id;
context_id;
stage_type and stage_scope_key (`WHOLE_CONTEXT` in profile v1);
stage_contract_version;
input manifest/ref;
input_set_hash;
input manifest canonicalization/version;
configuration/version manifest;
dependency StageExecution ids and output/partition hashes;
output manifest/ref;
output member count;
output_set_hash;
output manifest canonicalization/version;
logical lifecycle state;
supersedes/superseded-by relation when applicable;
current eligibility metadata maintained outside immutable output content.
```

Output partition IDs belong to the immutable output manifest and review target;
they do not alter the profile-v1 StageExecution selection scope.

Two executions with equal semantic input may consume the same materialization,
but remain separately identifiable StageExecutions when separately requested.

### 8.3 StageAttempt

> StageAttempt records one physical attempt to complete a StageExecution. It
> does not redefine semantic execution identity.

Required attempt information:

```text
attempt_id;
stage_execution_id;
attempt number;
monotonic attempt_authority_generation;
trigger actor/reason;
executor/worker identity;
owner and lease metadata;
started/finished timestamps;
attempt outcome;
error code/detail;
retryability;
runtime metrics.
```

Attempts are append-only. Updating only an aggregate attempt counter is not
sufficient audit history.

Every initial claim and every lease reclaim assigns a new monotonically
increasing `attempt_authority_generation` for that StageExecution. An Attempt
may publish authoritative StageExecution completion only when:

```text
attempt.authority_generation
== StageExecution.current_active_authority_generation

AND

StageExecution has not already reached immutable successful completion.
```

An Attempt whose lease/generation was superseded may finish physical work, but
its result is `LATE_OR_SUPERSEDED_ATTEMPT`: it cannot publish or replace the
StageExecution output manifest/hash or completion. If retained, its output is
Attempt audit only and has no semantic output identity.

### 8.4 Lifecycle Requirements

The storage enum is deferred, but the model must distinguish:

```text
not started;
active computation;
successful immutable completion;
failed attempt with retry allowed;
failed logical execution with no further retry;
incomplete/partial output that cannot satisfy full consumers;
superseded execution;
execution no longer eligible because a consumed dependency changed;
explicitly skipped execution with deterministic reason.
```

Legitimate transitions include:

```text
not started -> active -> successful completion
not started -> active -> failed attempt -> retry attempt -> successful completion
not started -> active -> terminal logical failure
successful completion -> remains immutable; replacement uses RECOMPUTE
successful completion -> loses current eligibility through dependency invalidation
```

The last transition does not alter historical output content.

### 8.5 Retry, Resume, Recompute, Replay

```text
RETRY
= same StageExecution semantic identity
+ new StageAttempt after transient failure

RESUME
= explicit same AnalysisContext
+ continue missing/incomplete/retryable StageExecutions
+ do not recalculate successful eligible stages by default

RECOMPUTE
= new StageExecution under the same Context
+ fixed new contract/config or explicit replacement reason
+ old successful output remains immutable

REPLAY
= execute from explicitly selected historical root/stage manifests
+ exact historical versions/configuration
+ never becomes current automatically

NEW_CONTEXT
= root analysis lineage changed or an independent lineage was explicitly started
```

### 8.6 Successful Output Invariant

Once successfully completed, these fields cannot change:

```text
Context binding;
input manifest/hash;
dependency refs/hashes;
contract/config manifest;
output manifest/member refs/member count/hash.
```

A zero-member output is a first-class successful result with a deterministic
empty-manifest hash. Missing rows cannot represent both not-run and successful
zero output.

### 8.7 Atomic Completion

> A StageExecution cannot become successfully complete until its entire
> review-owned output set, immutable member manifest, member count and output
> hash are atomically visible through the one currently fenced Attempt.

Exactly one Attempt can publish the one authoritative successful completion of
a StageExecution. After that publication, no Attempt generation can publish a
second output or change the output hash. The compare-and-swap/locking mechanism
is Implementation Design; the fencing and single-publication result are
Definition requirements.

This is storage-independent. It does not prescribe SQLite SQL or a future job
technology.

## 9. Product Steps And Runtime DAG

Product Step cards are workflow projections over runtime stages; they are not
StageExecution rows by definition.

### 9.1 RuntimeStageProfile v1

The read-only Projection Spike uses exactly
`runtime_stage_profile.single_prompt.v1`. It contains the 16 Stage types below.
The Spike Implementer cannot merge, split, add, remove or rename a semantic node
without a new profile version and Definition Review.

Every Stage uses `stage_scope_key = WHOLE_CONTEXT` in this profile. Large output
sets may use immutable review/computation partitions, but partitions do not
create a second selected StageExecution for the same Stage type.

| Stage type | Product Step | Depends on Stage outputs | Required direct input manifest classes | Output manifest class | Completion projection | Reviewable / review unit |
| --- | --- | --- | --- | --- | --- | --- |
| `RUN_METRICS` | 1 read-model | none | Root Run/Reference/Retrieval/target-page manifests; metric eligibility/spec config | `RunMetricManifest` containing eligible Run sets and baseline metric values | Every declared metric has value/numerator/denominator or explicit NOT_APPLICABLE/UNAVAILABLE; zero eligible denominator is explicit | NO |
| `ANSWER_SEMANTIC` | 2 | none | Root Prompt + Run answer snapshots; answer extractor contract/config | `AnswerSemanticManifest` containing Recommendation/Decision Reasons and AnswerUnits | Every eligible Run has a frozen member or explicit deterministic skip; zero Reasons is legal | YES; immutable per-Run Answer/Decision partition |
| `PRODUCT_TRUTH_PROJECTION` | 3 | `ANSWER_SEMANTIC` | target-brand identity/version; exact Reason manifest; formal Reason/ProductTruth binding manifest; exact reusable ProductTruth fact-value versions plus explicit UNKNOWN/UNRESOLVED members | `ProductTruthProjectionManifest` | Every Reason has exact bound fact-version refs, or one explicit UNRESOLVED/CONFLICT member; member set frozen | YES; one immutable fact-value/binding member or Reason partition |
| `BINDING` | 2/4 | `ANSWER_SEMANTIC` | AnswerUnit manifest; Root Reference/Retrieval observations; binding rules/config | `BindingManifest` | Every eligible AnswerUnit has frozen bindings or explicit NONE/LOW result | YES; immutable AnswerUnit binding partition |
| `SOURCE_QUALIFICATION` | 4 | none | Root Reference/Retrieval identity manifests; exact project/source-mapping input versions; qualification config | `SourceQualificationManifest` | Every observed source identity is qualified, rejected or explicitly UNKNOWN | NO formal main-chain review in profile v1 |
| `SOURCE_FETCH` | 4 | `SOURCE_QUALIFICATION` | selected qualified source refs; canonicalization/fetch config | `SourceContentVersionManifest` | Every required source has immutable content version, explicit fetch failure or deterministic skip | NO |
| `SEGMENTATION` | 4 | `SOURCE_FETCH` | immutable content-version refs/hashes; segmentation config | `PassageManifest` | Every successful content version has frozen passages, including legal zero passages | NO |
| `SOURCE_CLAIM` | 4 | `SEGMENTATION`, `SOURCE_QUALIFICATION` | Passage manifest; source context refs required by extractor; exact extraction/cache contract | `SourceClaimManifest` | Every required semantic input has DONE including zero claims, terminal failure or explicit block | NO formal Stage review; legacy member labels remain annotations only |
| `ALIGNMENT_CANDIDATE_BUILD` | 4 | `BINDING`, `SOURCE_CLAIM`, `SOURCE_QUALIFICATION` | exact binding/claim/source/run scope; recall/scoring/TopK/tie policy | `AlignmentCandidateManifest` with selected and omitted members | Every considered pair is selected or omitted with reason; manifests frozen | NO |
| `EVIDENCE_ALIGNMENT` | 4 | `ALIGNMENT_CANDIDATE_BUILD` | selected pair manifest and exact AnswerUnit/Claim semantic refs; judge/cache contract | `EvidenceAlignmentManifest` | Every selected pair has DONE verdict including negative, terminal failure or explicit block | YES; immutable completed relation-group partition or full manifest |
| `BENCHMARK` | 5 | `EVIDENCE_ALIGNMENT`, `SOURCE_QUALIFICATION` | exact eligible authoritative Alignment review refs; source qualification; Benchmark rules | `BenchmarkManifest` | Every Reason has frozen eligible Benchmark members or successful zero result | NO |
| `GAP` | 6 | `RUN_METRICS`, `ANSWER_SEMANTIC`, `PRODUCT_TRUTH_PROJECTION`, `EVIDENCE_ALIGNMENT`, `BENCHMARK` | exact authoritative Evidence reviews; metric/Reason/Truth/Benchmark refs; Gap rules | `GapManifest` | Every Reason has one frozen Gap/UNKNOWN outcome | YES; immutable per-Reason partition or full Gap manifest |
| `CHANNEL_EVIDENCE` | 7 | `SOURCE_QUALIFICATION`, `SOURCE_CLAIM`, `EVIDENCE_ALIGNMENT` | Root Reference/Retrieval observations; exact source/claim/alignment refs; aggregation rules | `ChannelEvidenceManifest` | Every in-scope channel has a frozen profile or explicit exclusion | NO |
| `CHANNEL_RESOLUTION` | 7 | `PRODUCT_TRUTH_PROJECTION`, `GAP`, `CHANNEL_EVIDENCE` | exact Reason/Truth/Gap/channel profiles; eligibility/Resolver config | `ChannelResolutionManifest` | Every considered channel has frozen Role/OBSERVE/exclusion/UNKNOWN | NO; reviewed through Strategy output |
| `STRATEGY_SYNTHESIS` | 7 | `RUN_METRICS`, `ANSWER_SEMANTIC`, `PRODUCT_TRUTH_PROJECTION`, `BENCHMARK`, `GAP`, `CHANNEL_RESOLUTION` | exact metric/Reasons/Themes inputs, authoritative Gap reviews, Roles and synthesis config | `StrategyManifest` containing StrategyCandidate truth | Complete deterministic structure or explicit needs-human ambiguity; zero executable channel is legal when contract allows | YES; exact full Strategy manifest |
| `EXECUTION_PROPOSAL` | 8 | `RUN_METRICS`, `STRATEGY_SYNTHESIS`, `PRODUCT_TRUTH_PROJECTION` | authoritative accepted Strategy review; exact baseline metric/run manifest; exact ManagedAsset/NewAsset input snapshot; compiler config | `ExecutionProposalManifest` | Every selected Strategy channel has proposal/defer/block result; ready does not create Action/Experiment | YES; immutable per-asset/channel proposal partition and portfolio decision set |

Stage contract identities are fixed by this profile as:

```text
runtime_stage.answer_semantic.v1
runtime_stage.run_metrics.v1
runtime_stage.product_truth_projection.v1
runtime_stage.binding.v1
runtime_stage.source_qualification.v1
runtime_stage.source_fetch.v1
runtime_stage.segmentation.v1
runtime_stage.source_claim.v1
runtime_stage.alignment_candidate_build.v1
runtime_stage.evidence_alignment.v1
runtime_stage.benchmark.v1
runtime_stage.gap.v1
runtime_stage.channel_evidence.v1
runtime_stage.channel_resolution.v1
runtime_stage.strategy_synthesis.v1
runtime_stage.execution_proposal.v1
```

#### Stage Manifest Canonicalization Profile

Every Stage input manifest uses
`stage_manifest_canonicalization.v1`. An input member identity is exactly:

```text
input_role
+ source type
+ exact reusable-object identity/version or StageExecution/output/partition ref
+ consumed semantic hash
```

Inputs have `SET_SEMANTICS` unless the Stage table below explicitly names an
ordinal. Equal identity/equal payload collapses; equal identity/different
payload is `MANIFEST_IDENTITY_CONFLICT` and the Stage cannot start. Configuration
is a separately named input role whose exact manifest hash is mandatory.

Every output manifest uses the same canonical scalar/null/collection rules.
The table below is the complete future-Runtime member identity registry for
profile v1. `ref` always means an immutable object/manifest identity plus exact
version and semantic hash; a mutable row id alone is not a formal `ref`.

The common input member identity is exactly:

```text
input_role
+ source_manifest_type
+ immutable source identity/ref
+ source contract/version
+ consumed semantic hash
```

`stage_input_member_identity.v1` is the exact tuple above. Its `input_role`
field accepts only the following literals from `StageInputRole.v1`:

```text
ROOT_MANIFEST
UPSTREAM_STAGE_OUTPUT
REUSABLE_INPUT
AUTHORITATIVE_REVIEW
CONFIGURATION
```

There are no aliases. Display labels, localized labels, legacy labels and
unregistered strings cannot enter canonical bytes. `ROOT_MANIFEST` means an
immutable Root manifest or one exact member/partition of it;
`UPSTREAM_STAGE_OUTPUT` means an immutable output/member/partition of a Stage
named as a dependency in RuntimeStageProfile v1; `REUSABLE_INPUT` means an
immutable non-Stage semantic object/version; `AUTHORITATIVE_REVIEW` means the
exact authoritative ReviewDecision/target lineage required by the consuming
Stage; and `CONFIGURATION` means the one exact configuration manifest for the
owning Stage.

Every Stage input payload contains:

```text
input_role_contract_version = StageInputRole.v1
```

Changing a literal, its meaning, or a Stage-to-role assignment requires both a
new `StageInputRole` version and a new owning `runtime_stage.*` input-contract
version. A reader never translates an alias at the hash boundary. An input that
cannot be assigned by the matrix below is invalid for a new Runtime manifest;
a legacy projection reports PARTIAL only when the source lineage remains
unique but role metadata is absent, otherwise UNSAFE. It never emits OTHER,
CUSTOM or UNKNOWN_ROLE.

The following is the complete Stage/Input Role matrix for
`runtime_stage_profile.single_prompt.v1`. `COMMON` means the full
`stage_input_member_identity.v1` tuple, including the exact immutable source
ref/version/hash named in the source-class column. Every row is REQUIRED and
uses SET semantics; no Stage input collection in profile v1 is ordered.

| Stage type | Input source class | Canonical `input_role` | Member identity contract | Required/optional | Set/ordered |
| --- | --- | --- | --- | --- | --- |
| `RUN_METRICS` | Root Run snapshot manifest | `ROOT_MANIFEST` | COMMON + exact Run manifest ref/hash | REQUIRED | SET |
| `RUN_METRICS` | Root Reference observation manifest | `ROOT_MANIFEST` | COMMON + exact Reference manifest ref/hash | REQUIRED | SET |
| `RUN_METRICS` | Root Retrieval observation manifest | `ROOT_MANIFEST` | COMMON + exact Retrieval manifest ref/hash | REQUIRED | SET |
| `RUN_METRICS` | Root TargetUrl manifest | `ROOT_MANIFEST` | COMMON + exact TargetUrl manifest ref/hash | REQUIRED | SET |
| `RUN_METRICS` | `StageConfigurationManifest/RUN_METRICS` | `CONFIGURATION` | COMMON + `runtime_stage.run_metrics.v1/configuration` ref/hash | REQUIRED | SET |
| `ANSWER_SEMANTIC` | Root Prompt snapshot member | `ROOT_MANIFEST` | COMMON + exact Root Prompt member ref/hash | REQUIRED | SET |
| `ANSWER_SEMANTIC` | Root Run answer snapshot member | `ROOT_MANIFEST` | COMMON + exact Run answer member ref/hash | REQUIRED | SET |
| `ANSWER_SEMANTIC` | `StageConfigurationManifest/ANSWER_SEMANTIC` | `CONFIGURATION` | COMMON + `runtime_stage.answer_semantic.v1/configuration` ref/hash | REQUIRED | SET |
| `PRODUCT_TRUTH_PROJECTION` | `ANSWER_SEMANTIC` Reason output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Reason output ref/hash | REQUIRED | SET |
| `PRODUCT_TRUTH_PROJECTION` | target-brand identity/version | `REUSABLE_INPUT` | COMMON + exact target-brand version ref/hash | REQUIRED | SET |
| `PRODUCT_TRUTH_PROJECTION` | `reason_product_truth_binding.v1` manifest/member | `REUSABLE_INPUT` | COMMON + exact binding ref/hash | REQUIRED | SET |
| `PRODUCT_TRUTH_PROJECTION` | ProductTruthFactValueVersion | `REUSABLE_INPUT` | COMMON + exact fact-value ref/hash | REQUIRED | SET |
| `PRODUCT_TRUTH_PROJECTION` | authoritative ProductTruth fact review | `AUTHORITATIVE_REVIEW` | COMMON + exact ReviewTarget/decision lineage ref/hash | REQUIRED | SET |
| `PRODUCT_TRUTH_PROJECTION` | `StageConfigurationManifest/PRODUCT_TRUTH_PROJECTION` | `CONFIGURATION` | COMMON + `runtime_stage.product_truth_projection.v1/configuration` ref/hash | REQUIRED | SET |
| `BINDING` | `ANSWER_SEMANTIC` AnswerUnit/Reason output member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact AnswerUnit/Reason ref/hash | REQUIRED | SET |
| `BINDING` | Root Reference observation member | `ROOT_MANIFEST` | COMMON + exact Reference member ref/hash | REQUIRED | SET |
| `BINDING` | Root Retrieval observation member | `ROOT_MANIFEST` | COMMON + exact Retrieval member ref/hash | REQUIRED | SET |
| `BINDING` | `StageConfigurationManifest/BINDING` | `CONFIGURATION` | COMMON + `runtime_stage.binding.v1/configuration` ref/hash | REQUIRED | SET |
| `SOURCE_QUALIFICATION` | Root Reference observation member | `ROOT_MANIFEST` | COMMON + exact Reference member ref/hash | REQUIRED | SET |
| `SOURCE_QUALIFICATION` | Root Retrieval observation member | `ROOT_MANIFEST` | COMMON + exact Retrieval member ref/hash | REQUIRED | SET |
| `SOURCE_QUALIFICATION` | project/source-mapping input version | `REUSABLE_INPUT` | COMMON + exact mapping version ref/hash | REQUIRED | SET |
| `SOURCE_QUALIFICATION` | `StageConfigurationManifest/SOURCE_QUALIFICATION` | `CONFIGURATION` | COMMON + `runtime_stage.source_qualification.v1/configuration` ref/hash | REQUIRED | SET |
| `SOURCE_FETCH` | `SOURCE_QUALIFICATION` selected source output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact qualification member ref/hash | REQUIRED | SET |
| `SOURCE_FETCH` | `StageConfigurationManifest/SOURCE_FETCH` | `CONFIGURATION` | COMMON + `runtime_stage.source_fetch.v1/configuration` ref/hash | REQUIRED | SET |
| `SEGMENTATION` | `SOURCE_FETCH` content-version output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact content-version ref/hash | REQUIRED | SET |
| `SEGMENTATION` | `StageConfigurationManifest/SEGMENTATION` | `CONFIGURATION` | COMMON + `runtime_stage.segmentation.v1/configuration` ref/hash | REQUIRED | SET |
| `SOURCE_CLAIM` | `SEGMENTATION` Passage output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Passage ref/hash | REQUIRED | SET |
| `SOURCE_CLAIM` | `SOURCE_QUALIFICATION` source-context output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact qualification context ref/hash | REQUIRED | SET |
| `SOURCE_CLAIM` | `StageConfigurationManifest/SOURCE_CLAIM` | `CONFIGURATION` | COMMON + `runtime_stage.source_claim.v1/configuration` ref/hash | REQUIRED | SET |
| `ALIGNMENT_CANDIDATE_BUILD` | `BINDING` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Binding ref/hash | REQUIRED | SET |
| `ALIGNMENT_CANDIDATE_BUILD` | `SOURCE_CLAIM` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact SourceClaim ref/hash | REQUIRED | SET |
| `ALIGNMENT_CANDIDATE_BUILD` | `SOURCE_QUALIFICATION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact qualification ref/hash | REQUIRED | SET |
| `ALIGNMENT_CANDIDATE_BUILD` | Root Run-scope manifest | `ROOT_MANIFEST` | COMMON + exact RunScope manifest ref/hash | REQUIRED | SET |
| `ALIGNMENT_CANDIDATE_BUILD` | `StageConfigurationManifest/ALIGNMENT_CANDIDATE_BUILD` | `CONFIGURATION` | COMMON + `runtime_stage.alignment_candidate_build.v1/configuration` ref/hash | REQUIRED | SET |
| `EVIDENCE_ALIGNMENT` | `ALIGNMENT_CANDIDATE_BUILD` selected-pair output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact candidate-pair ref/hash | REQUIRED | SET |
| `EVIDENCE_ALIGNMENT` | `ANSWER_SEMANTIC` AnswerUnit/Reason output member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact AnswerUnit/Reason ref/hash | REQUIRED | SET |
| `EVIDENCE_ALIGNMENT` | `SOURCE_CLAIM` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact SourceClaim ref/hash | REQUIRED | SET |
| `EVIDENCE_ALIGNMENT` | `StageConfigurationManifest/EVIDENCE_ALIGNMENT` | `CONFIGURATION` | COMMON + `runtime_stage.evidence_alignment.v1/configuration` ref/hash | REQUIRED | SET |
| `BENCHMARK` | `EVIDENCE_ALIGNMENT` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Alignment ref/hash | REQUIRED | SET |
| `BENCHMARK` | `SOURCE_QUALIFICATION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact qualification ref/hash | REQUIRED | SET |
| `BENCHMARK` | authoritative Evidence Alignment review | `AUTHORITATIVE_REVIEW` | COMMON + exact ReviewTarget/decision lineage ref/hash | REQUIRED | SET |
| `BENCHMARK` | `StageConfigurationManifest/BENCHMARK` | `CONFIGURATION` | COMMON + `runtime_stage.benchmark.v1/configuration` ref/hash | REQUIRED | SET |
| `GAP` | `RUN_METRICS` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact metric ref/hash | REQUIRED | SET |
| `GAP` | `ANSWER_SEMANTIC` Reason output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Reason ref/hash | REQUIRED | SET |
| `GAP` | `PRODUCT_TRUTH_PROJECTION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Truth projection ref/hash | REQUIRED | SET |
| `GAP` | `EVIDENCE_ALIGNMENT` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Alignment ref/hash | REQUIRED | SET |
| `GAP` | `BENCHMARK` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Benchmark ref/hash | REQUIRED | SET |
| `GAP` | authoritative Evidence Alignment review | `AUTHORITATIVE_REVIEW` | COMMON + exact ReviewTarget/decision lineage ref/hash | REQUIRED | SET |
| `GAP` | `StageConfigurationManifest/GAP` | `CONFIGURATION` | COMMON + `runtime_stage.gap.v1/configuration` ref/hash | REQUIRED | SET |
| `CHANNEL_EVIDENCE` | Root Reference observation member | `ROOT_MANIFEST` | COMMON + exact Reference member ref/hash | REQUIRED | SET |
| `CHANNEL_EVIDENCE` | Root Retrieval observation member | `ROOT_MANIFEST` | COMMON + exact Retrieval member ref/hash | REQUIRED | SET |
| `CHANNEL_EVIDENCE` | `SOURCE_QUALIFICATION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact qualification ref/hash | REQUIRED | SET |
| `CHANNEL_EVIDENCE` | `SOURCE_CLAIM` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact SourceClaim ref/hash | REQUIRED | SET |
| `CHANNEL_EVIDENCE` | `EVIDENCE_ALIGNMENT` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Alignment ref/hash | REQUIRED | SET |
| `CHANNEL_EVIDENCE` | `StageConfigurationManifest/CHANNEL_EVIDENCE` | `CONFIGURATION` | COMMON + `runtime_stage.channel_evidence.v1/configuration` ref/hash | REQUIRED | SET |
| `CHANNEL_RESOLUTION` | `PRODUCT_TRUTH_PROJECTION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Truth projection ref/hash | REQUIRED | SET |
| `CHANNEL_RESOLUTION` | `GAP` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Gap ref/hash | REQUIRED | SET |
| `CHANNEL_RESOLUTION` | `CHANNEL_EVIDENCE` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact ChannelEvidence ref/hash | REQUIRED | SET |
| `CHANNEL_RESOLUTION` | authoritative Gap review | `AUTHORITATIVE_REVIEW` | COMMON + exact ReviewTarget/decision lineage ref/hash | REQUIRED | SET |
| `CHANNEL_RESOLUTION` | `StageConfigurationManifest/CHANNEL_RESOLUTION` | `CONFIGURATION` | COMMON + `runtime_stage.channel_resolution.v1/configuration` ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `RUN_METRICS` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact metric ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `ANSWER_SEMANTIC` Reason output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Reason ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `PRODUCT_TRUTH_PROJECTION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Truth projection ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `BENCHMARK` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Benchmark ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `GAP` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Gap ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `CHANNEL_RESOLUTION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact ChannelResolution ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | authoritative Gap review | `AUTHORITATIVE_REVIEW` | COMMON + exact ReviewTarget/decision lineage ref/hash | REQUIRED | SET |
| `STRATEGY_SYNTHESIS` | `StageConfigurationManifest/STRATEGY_SYNTHESIS` | `CONFIGURATION` | COMMON + `runtime_stage.strategy_synthesis.v1/configuration` ref/hash | REQUIRED | SET |
| `EXECUTION_PROPOSAL` | `RUN_METRICS` baseline output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact baseline ref/hash | REQUIRED | SET |
| `EXECUTION_PROPOSAL` | `STRATEGY_SYNTHESIS` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Strategy ref/hash | REQUIRED | SET |
| `EXECUTION_PROPOSAL` | `PRODUCT_TRUTH_PROJECTION` output/member | `UPSTREAM_STAGE_OUTPUT` | COMMON + exact Truth projection ref/hash | REQUIRED | SET |
| `EXECUTION_PROPOSAL` | authoritative accepted Strategy review | `AUTHORITATIVE_REVIEW` | COMMON + exact ReviewTarget/decision lineage ref/hash | REQUIRED | SET |
| `EXECUTION_PROPOSAL` | immutable ManagedAsset/NewAsset input snapshot | `REUSABLE_INPUT` | COMMON + exact asset-input ref/hash | REQUIRED | SET |
| `EXECUTION_PROPOSAL` | `StageConfigurationManifest/EXECUTION_PROPOSAL` | `CONFIGURATION` | COMMON + `runtime_stage.execution_proposal.v1/configuration` ref/hash | REQUIRED | SET |

If a Stage source class is not a row in this matrix, it cannot enter that
Stage's input manifest under profile v1. The owning Stage Contract determines
cardinality within the REQUIRED class, including legal empty semantic sets; the
matrix does not make a required class optional.

The following synthetic `RUN_METRICS` input is a normative
cross-implementation vector. Every member payload is exactly its five-field
`stage_input_member_identity.v1`; the SET order shown is the ascending canonical
identity-byte order.

```text
member 1 = ROOT_MANIFEST | BrowserMonitorRunRootSnapshot |
           root-run-set:synthetic-001 |
           browser_monitor_run_root_snapshot.v1 | "a" repeated 64
member 2 = ROOT_MANIFEST | ReferenceObservationRootManifest |
           root-reference-set:synthetic-001 |
           reference_observation_root.v1 | "b" repeated 64
member 3 = ROOT_MANIFEST | RetrievalObservationRootManifest |
           root-retrieval-set:synthetic-001 |
           retrieval_observation_root.v1 | "c" repeated 64
member 4 = ROOT_MANIFEST | TargetUrlManifest |
           root-target-url-set:synthetic-001 |
           target_url_identity.exact_utf8.v1 | "d" repeated 64
member 5 = CONFIGURATION | StageConfigurationManifest/RUN_METRICS |
           config:run-metrics:synthetic-001 |
           runtime_stage.run_metrics.v1/configuration | "e" repeated 64
```

The exact hashed payload is:

```text
stage_type = RUN_METRICS
input_role_contract_version = StageInputRole.v1
members = [member 1, member 2, member 3, member 4, member 5]
```

using envelope:

```text
manifest_type = StageInputManifest/RUN_METRICS
manifest_contract_version = runtime_stage.run_metrics.v1/input
```

Exact canonical bytes (one line, no trailing LF):

```text
o6:{s24:canonical_bytes_contractx3:s36:semantic_manifest_canonical_bytes.v1s24:canonicalization_versionx3:s37:semantic_manifest_canonicalization.v1s14:hash_algorithmx3:s7:SHA-256s25:manifest_contract_versionx3:s34:runtime_stage.run_metrics.v1/inputs13:manifest_typex3:s30:StageInputManifest/RUN_METRICSs7:payloadx3:o3:{s27:input_role_contract_versionx3:s17:StageInputRole.v1s7:membersx3:a5:[o5:{s22:consumed_semantic_hashx3:s64:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaas10:input_rolex3:s13:ROOT_MANIFESTs23:source_contract_versionx3:s36:browser_monitor_run_root_snapshot.v1s19:source_identity_refx3:s26:root-run-set:synthetic-001s20:source_manifest_typex3:s29:BrowserMonitorRunRootSnapshot}o5:{s22:consumed_semantic_hashx3:s64:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbs10:input_rolex3:s13:ROOT_MANIFESTs23:source_contract_versionx3:s29:reference_observation_root.v1s19:source_identity_refx3:s32:root-reference-set:synthetic-001s20:source_manifest_typex3:s32:ReferenceObservationRootManifest}o5:{s22:consumed_semantic_hashx3:s64:ccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccs10:input_rolex3:s13:ROOT_MANIFESTs23:source_contract_versionx3:s29:retrieval_observation_root.v1s19:source_identity_refx3:s32:root-retrieval-set:synthetic-001s20:source_manifest_typex3:s32:RetrievalObservationRootManifest}o5:{s22:consumed_semantic_hashx3:s64:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddds10:input_rolex3:s13:ROOT_MANIFESTs23:source_contract_versionx3:s33:target_url_identity.exact_utf8.v1s19:source_identity_refx3:s33:root-target-url-set:synthetic-001s20:source_manifest_typex3:s17:TargetUrlManifest}o5:{s22:consumed_semantic_hashx3:s64:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeees10:input_rolex3:s13:CONFIGURATIONs23:source_contract_versionx3:s42:runtime_stage.run_metrics.v1/configurations19:source_identity_refx3:s32:config:run-metrics:synthetic-001s20:source_manifest_typex3:s38:StageConfigurationManifest/RUN_METRICS}]s10:stage_typex3:s11:RUN_METRICS}}
```

```text
SHA-256 = dba2155c917c74e7f297ad0e5fe9a8639ef3f2f8289e3511fcc84e0d96cce10e
```

The specialization column names the exact source key placed in the common
identity; it does not replace any common component. Configuration is one input
member with `input_role = CONFIGURATION` and its exact config manifest hash.

| Stage | Input member identity specialization | Output member identity | Set/order semantics | Canonical contract |
| --- | --- | --- | --- | --- |
| `RUN_METRICS` | Root Run/Reference/Retrieval/target manifest type + hash; metric config ref | `metric_name + metric_scope_type + metric_scope_key + denominator_class` | SET | `runtime_stage.run_metrics.v1` |
| `ANSWER_SEMANTIC` | `run_id + answer_snapshot_hash`; extractor config ref | `run_id + member_kind + source_span_start + source_span_end + member_ordinal` | SET | `runtime_stage.answer_semantic.v1` |
| `PRODUCT_TRUTH_PROJECTION` | `reason_identity + binding_version_ref/hash + fact_value_version_ref/hash` | `reason_identity + binding_status + (fact_value_version_ref | UNRESOLVED | CONFLICT) + binding_ordinal` | SET | `runtime_stage.product_truth_projection.v1` |
| `BINDING` | `answer_unit_identity + reason_identity + observation_manifest_hash`; binding config ref | `answer_unit_identity + reason_identity + binding_scope_type + binding_ordinal` | SET | `runtime_stage.binding.v1` |
| `SOURCE_QUALIFICATION` | Root observation member identity + project/source-rule input ref | `root_observation_identity + qualification_subject_type + qualification_rule_key` | SET | `runtime_stage.source_qualification.v1` |
| `SOURCE_FETCH` | canonical source identity + fetch request/config ref | `canonical_source_identity` | SET | `runtime_stage.source_fetch.v1` |
| `SEGMENTATION` | `source_content_version_ref + content_hash`; segmentation config ref | `source_content_version_ref + passage_ordinal` | ORDER_SIGNIFICANT within each content version | `runtime_stage.segmentation.v1` |
| `SOURCE_CLAIM` | `passage_member_identity + passage_semantic_input_hash + required_source_context_hash`; extraction config ref | `passage_member_identity + claim_ordinal` | ORDER_SIGNIFICANT within each passage | `runtime_stage.source_claim.v1` |
| `ALIGNMENT_CANDIDATE_BUILD` | `answer_unit_or_reason_member_identity + source_claim_member_identity + scope_policy_hash` | `answer_unit_or_reason_member_identity + source_claim_member_identity` | SET | `runtime_stage.alignment_candidate_build.v1` |
| `EVIDENCE_ALIGNMENT` | exact selected candidate-pair member ref/hash; judge config ref | `answer_unit_or_reason_member_identity + source_claim_member_identity` | SET | `runtime_stage.evidence_alignment.v1` |
| `BENCHMARK` | `reason_identity + authoritative_evidence_partition_ref/hash + qualification_member_ref/hash` | `reason_identity + canonical_source_identity` | SET | `runtime_stage.benchmark.v1` |
| `GAP` | `reason_identity + metric/truth/evidence/benchmark manifest refs/hashes` | `reason_identity` | SET; one member per Reason | `runtime_stage.gap.v1` |
| `CHANNEL_EVIDENCE` | `channel_key + observation/source/claim/alignment member refs/hashes` | `channel_key + signal_type + signal_source_ref_type + signal_source_ref + signal_source_hash` | SET | `runtime_stage.channel_evidence.v1` |
| `CHANNEL_RESOLUTION` | `channel_key + truth/gap/channel_profile refs/hashes`; Resolver config ref | `channel_key` | SET; one member per considered channel | `runtime_stage.channel_resolution.v1` |
| `STRATEGY_SYNTHESIS` | exact Reason/Truth/Benchmark/Gap/Role member refs/hashes; synthesis config ref | discriminated key defined below | SET; priority is a member scalar, not collection order | `runtime_stage.strategy_synthesis.v1` |
| `EXECUTION_PROPOSAL` | accepted Strategy/review ref/hash + baseline ref/hash + asset-input ref/hash; compiler config ref | discriminated key defined below | SET; nested section order is ORDER_SIGNIFICANT | `runtime_stage.execution_proposal.v1` |

Identity fields such as `member_kind`, `binding_scope_type`,
`qualification_subject_type`, `qualification_rule_key`, `signal_type` and
`signal_source_ref_type` are required closed enums in the named owning Stage
Contract. An unknown enum value is invalid input, not a free-text extension.
`member_ordinal`, `binding_ordinal`, `passage_ordinal`, `claim_ordinal` and
section ordinal are zero-based contiguous business ordinals frozen in the
owning output; query order and row id cannot supply them.

`STRATEGY_SYNTHESIS` output keys form this exact discriminated union:

```text
STRATEGY_HEADER -> member_kind + singleton key STRATEGY;
THEME -> member_kind + theme_id;
CHANNEL_PORTFOLIO -> member_kind + channel_key.
```

`theme_id` and `channel_key` must already be fields in the validated structural
output and unique within that output. They cannot be generated from title text
or presentation order.

`EXECUTION_PROPOSAL` output keys form this exact discriminated union:

```text
PROPOSAL_HEADER -> member_kind + singleton key PROPOSAL;
CHANNEL_ASSET_PROPOSAL -> member_kind + channel_key + proposal_ordinal;
PORTFOLIO_DECISION -> member_kind + singleton key PORTFOLIO.
```

Sections are nested under one `CHANNEL_ASSET_PROPOSAL`, keyed by that parent
member identity plus `section_ordinal`, and serialized in ascending contiguous
ordinal order. Asset URL/title/text is payload, never a fallback identity.

Every table row uses `IDENTICAL_DUPLICATE` collapse and
`MANIFEST_IDENTITY_CONFLICT` rejection from the common canonical contract. No
unresolved phrase such as “normalized semantic-content,” “matching source,”
“strategy structural identity,” or “proposal asset logical key” is an identity
component in profile v1.

`input_set_hash`, `output_set_hash`, completed review partition hashes and
successful empty-manifest hashes all include
`semantic_manifest_canonicalization.v1` and the exact owning Stage Contract
version. A random storage row id cannot enter semantic output identity.

#### Whole-stage Completion And Partial Consumption

In `runtime_stage_profile.single_prompt.v1`, a Stage reaches `SUCCEEDED` only
after every required input member has one frozen terminal output member/status.
Legal semantic terminal outcomes include explicit zero, NONE/LOW/UNKNOWN,
rejection, deterministic skip, external fetch failure, final materialization
failure or explicit block only where the Stage row in Section 9.1 names that
outcome. Such outcomes remain distinct data and may never be normalized to an
empty/negative result.

Missing or still-active required members make the whole Stage
`INCOMPLETE/PARTIAL`, not `SUCCEEDED`. Profile v1 permits immutable partitions
for speculative computation/review, but no formal current Stage selection or
formal whole-context downstream consumption of a partial StageExecution.
Downstream Stages may consume a successfully completed manifest containing
explicit terminal failure/block members only when their own input contract
accepts those exact statuses; otherwise they are deterministically blocked.

The Product Truth reusable object is not Root input. The
`PRODUCT_TRUTH_PROJECTION` Stage freezes the exact Reason-scoped subset and
fact-value versions consumed by this Context, including explicit UNKNOWN. A
later Project-level fact such as PT#4 cannot enter an old projection without a
new `PRODUCT_TRUTH_PROJECTION` StageExecution and explicit Stage selection.

#### Product Truth Projection Selector

The current database has no persisted formal Reason-to-ProductTruth binding.
Read-only audit found this actual production path:

```text
RecommendationEvent Reason text
-> service.py capability-label/token heuristic
-> current mutable TargetBrandCapabilityTruth rows
-> product_truth_ids copied into Gap/StrategyCandidate payload
-> PR4 consumers read those copied ids.
```

Current-source classification is therefore:

```text
E. temporary derivation with no formal Source of Truth
```

Candidate payload ids are frozen historical hints only. The heuristic and those
hints are not retroactively renamed as a formal binding.

Revision 003 defines the candidate reusable-input Contract
`reason_product_truth_binding.v1` with:

```yaml
maturity: CANDIDATE
implementation_status: NOT_IMPLEMENTED
persistence_status: NONE_IN_CURRENT_SCHEMA
source_of_truth: immutable Step 3 human binding confirmation created under this contract
producer: STEP_3_REASON_PRODUCT_TRUTH_BINDING_CONFIRMATION
allowed_consumer: PRODUCT_TRUTH_PROJECTION only
```

This is a proposed logical Contract, not a claim that an existing table/object
already satisfies it. It does not add a seventeenth Runtime Stage. A future
storage representation requires separate authorization after the read-only
Spike.

One human-confirmed binding version has exactly:

```text
binding_contract_version = reason_product_truth_binding.v1;
binding_version_id;
Reason semantic member ref + exact output hash;
target brand identity/version;
ProductTruth object identity;
ProductTruthFactValueVersion ref/hash;
binding assertion = BINDS;
confirmation source = HUMAN_CONFIRMED_STEP_3;
confirmation actor and timestamp as audit fields;
supersedes binding version ref or null.
```

Its semantic identity is:

```text
binding_contract_version
+ binding_version_id
+ Reason semantic member ref/hash
+ target brand identity/version
+ ProductTruth object identity
+ ProductTruthFactValueVersion ref/hash.
```

`binding_version_id` is an immutable business lineage identifier allocated by
the Step 3 confirmation command, not a mutable ProductTruth row id or text hash.
The binding manifest uses `SET_SEMANTICS`; member identity is the complete tuple
above. Its input hash and manifest hash use
`semantic_manifest_canonicalization.v1` and include every selected binding
version. Same identity/different payload is `MANIFEST_IDENTITY_CONFLICT`.

Formal validity requires all exact refs/hashes to resolve, the target brand to
equal the Context target brand, the Reason to belong to the selected
`ANSWER_SEMANTIC` output, the fact version to belong to the named ProductTruth
object, and `confirmation_source = HUMAN_CONFIRMED_STEP_3` with actor/time
present. There is no label, keyword, fuzzy, LLM or project-wide discovery path.
Invalid records cannot produce `BOUND`.

`runtime_stage.product_truth_projection.v1` is the unique producer of the
Reason-scoped projection consumed by the Runtime DAG. It consumes:

```text
the exact selected ANSWER_SEMANTIC Reason manifest;
the exact reason_product_truth_binding.v1 input manifest;
the exact immutable ProductTruthFactValueVersion refs/hashes named by bindings;
the authoritative reviews required for those fact versions;
target brand identity/version;
its exact Stage config/version.
```

For every Reason in the selected Answer manifest:

```text
one or more valid binding versions
-> emit every named ProductTruth fact-value version, including
   PARTIALLY_SUPPORTED/FALSE/UNKNOWN;

no valid binding version
-> emit exactly one member with product_truth_ref = null,
   binding_status = UNRESOLVED;

two selected binding versions assert incompatible fact versions for the same
Reason + ProductTruth object, or an identity/payload conflict exists
-> emit binding_status = CONFLICT and block formal downstream consumption.
```

The Stage may not query all project ProductTruth rows. It may dereference only
fact versions named by valid input bindings. An unresolved Reason cannot be
omitted or replaced by the closest label. Strategy-created Theme identity is
not an input to this earlier Stage; later Themes may only union the already
frozen Reason projection.

The `PRODUCT_TRUTH_PROJECTION` output manifest records Reason identity,
ProductTruth identity, exact fact-value version/ref/hash, value/status,
provenance ref, binding version identity/status, member count and output hash.
Its formal downstream consumers are `GAP`, `CHANNEL_RESOLUTION`,
`STRATEGY_SYNTHESIS`, and `EXECUTION_PROPOSAL`; none may recompute or repair the
binding.

Correction never mutates a binding or fact in place. A Reason correction creates
a new `ANSWER_SEMANTIC` output; a truth correction creates a new
`ProductTruthFactValueVersion`; a binding correction creates a new immutable
binding version that may supersede the old one. Selecting any changed input
creates a new `PRODUCT_TRUTH_PROJECTION` StageExecution. Old projection and
descendant history remain immutable.

For the fixed #19/#40 legacy cases, no current row qualifies under this Candidate
Contract. Candidate `product_truth_ids` remain hints, binding status is never
upgraded to `BOUND`, and the frozen legacy expectation remains `UNSAFE` with
formal binding/version absent.

### 9.2 Review Gate Profile

Compute scheduling and formal current consumption are separate. A Stage may
materialize a speculative output before human review when its contract permits,
but a PRODUCTION downstream selection must satisfy these exact review gates:

| Producer output | Formal consumer gate in profile v1 |
| --- | --- |
| `ANSWER_SEMANTIC` | Every review-required Decision partition has one authoritative CONFIRM or REJECT. The downstream input manifest records both accepted and rejected decisions; PENDING/REOPENED/CONFLICT blocks formal GAP/STRATEGY consumption. BINDING may compute speculatively and is invalidated if authority changes. |
| reusable ProductTruth fact + `PRODUCT_TRUTH_PROJECTION` | Every BOUND fact-value, including an acknowledged UNKNOWN, has authoritative confirmation. UNRESOLVED/CONFLICT binding, absent fact version or review conflict blocks GAP/CHANNEL_RESOLUTION/STRATEGY. |
| `BINDING` | No universal human gate. Machine VERIFIED/NONE/LOW states allowed by the binding contract are explicit outputs; any human-corrected partition must use its authoritative review. |
| `EVIDENCE_ALIGNMENT` | Every SUPPORTS or CONTRADICTS partition consumed as formal eligible Evidence has authoritative confirmation/rejection. Machine-final negative/non-support outcomes may be consumed when the Evidence contract marks them non-review-required. PENDING/REOPENED/CONFLICT formal relation partitions block BENCHMARK/GAP. |
| `GAP` | Authoritative CONFIRM permits Strategy consumption. REJECT/REOPEN/CONFLICT blocks it. SHELVE is an authoritative product stop decision, not a confirmed Gap input. |
| `STRATEGY_SYNTHESIS` | Authoritative CONFIRM/ACCEPT permits EXECUTION_PROPOSAL. REJECT/REOPEN/DEFER/CONFLICT blocks it. |
| `EXECUTION_PROPOSAL` | Review can establish a ready/defer decision only for the exact immutable proposal target. Action/Experiment consumption remains outside this RFC and requires the separate Step 8 lifecycle contract. |

All other profile-v1 stages are non-review-gated. Their exact compute outcome,
lineage completeness, eligibility and selected execution still must pass.

### 9.3 Fixed Dependency Edges

The normative DAG is:

```text
ROOT -> ANSWER_SEMANTIC
ROOT -> RUN_METRICS
ROOT -> SOURCE_QUALIFICATION

ANSWER_SEMANTIC -> PRODUCT_TRUTH_PROJECTION
ANSWER_SEMANTIC -> BINDING
ROOT Reference/Retrieval -> BINDING

SOURCE_QUALIFICATION -> SOURCE_FETCH
SOURCE_FETCH -> SEGMENTATION
SEGMENTATION + SOURCE_QUALIFICATION -> SOURCE_CLAIM

BINDING + SOURCE_CLAIM + SOURCE_QUALIFICATION
-> ALIGNMENT_CANDIDATE_BUILD
-> EVIDENCE_ALIGNMENT

EVIDENCE_ALIGNMENT + SOURCE_QUALIFICATION -> BENCHMARK

RUN_METRICS + ANSWER_SEMANTIC + PRODUCT_TRUTH_PROJECTION
+ EVIDENCE_ALIGNMENT + BENCHMARK
-> GAP

ROOT Reference/Retrieval
+ SOURCE_QUALIFICATION + SOURCE_CLAIM + EVIDENCE_ALIGNMENT
-> CHANNEL_EVIDENCE

PRODUCT_TRUTH_PROJECTION + GAP + CHANNEL_EVIDENCE
-> CHANNEL_RESOLUTION

RUN_METRICS + ANSWER_SEMANTIC + PRODUCT_TRUTH_PROJECTION + BENCHMARK
+ GAP + CHANNEL_RESOLUTION
-> STRATEGY_SYNTHESIS

STRATEGY_SYNTHESIS authoritative accepted review
+ RUN_METRICS + PRODUCT_TRUTH_PROJECTION
+ exact asset-input snapshot
-> EXECUTION_PROPOSAL
```

An authoritative review consumed by a downstream Stage is a direct reusable
input ref/version/hash in that Stage's input manifest, even though it is not a
Stage node. The same applies to exact project/brand and ManagedAsset reusable
object versions.

### 9.4 Product Projection

| Product Step | Runtime producers/consumers |
| --- | --- |
| Step 1 Collection | upstream Acquisition and Root manifest input; downstream `RUN_METRICS` read model |
| Step 2 Answer/Decision | Answer Semantic, AnswerUnit, Binding |
| Step 3 Product Truth | Product Truth projection and human review output |
| Step 4 Evidence | Source Qualification, Fetch, Segmentation, SourceClaim, Candidate Builder, Alignment, Evidence Review |
| Step 5 Benchmark | eligible-evidence Benchmark derivation |
| Step 6 Gap | reason/truth/evidence/Benchmark Gap derivation and review |
| Step 7 Strategy | Channel Evidence, Resolver, Synthesis, Strategy review |
| Step 8 Execution | Execution Proposal/review and separately approved Action/Experiment persistence |

The runtime DAG must use exact dependency refs, not only the Product Step number
or row existence.

Each Stage Contract must declare:

```text
required dependencies;
acceptable dependency completion/review states;
parallelizable partitions;
deterministic skip conditions;
blocking reasons;
partial-output consumer policy;
completion predicate.
```

Step readiness can only be projected from those contracts and selected current
StageExecutions.

### 9.5 Runtime Object Governance

| Object | Semantic Source of Truth | Owner | Allowed consumers |
| --- | --- | --- | --- |
| `AnalysisContext` | immutable Root manifest + fingerprint/profile | authorized Context creation action | backend Runtime projection and its StageExecutions |
| `StageExecution` | immutable input/config/dependency/output manifests plus separate eligibility relation | named Stage Contract | dependent Stages, reviews and backend Runtime projection |
| `StageAttempt` | append-only attempt record | Stage executor/retry action | StageExecution lifecycle/audit only |
| `ReviewDecision` | append-only exact-target supersession chain | authorized human review action | Stage eligibility and downstream input manifests explicitly permitting that review |
| `CurrentContextPointer` | versioned pointer transition history | authorized pointer action | backend current projection only |
| `ContextStageSelection` | versioned selection transition history | authorized Stage promotion/reactivation action | backend current projection and dependent Stage scheduling |

Frontend, cache rows, row timestamps and Product Step cards are not Sources of
Truth for these objects.

## 10. Version And Configuration Lineage

Every semantic-affecting component belongs to the Stage configuration manifest,
including deterministic components:

```text
URL canonicalization;
source mapping;
primary-content extraction;
segmentation;
normalization/tokenization;
binding rules;
candidate recall/scoring/TopK/tie policy;
eligibility validators;
Benchmark and Gap rules;
Channel Resolver;
Strategy Synthesis;
Execution Proposal compiler;
LLM provider/model/system prompt/prompt/schema/contract versions.
```

Runtime feature flags must be resolved to explicit values in the relevant
Context root profile or Stage configuration manifest. Historical replay cannot
read today's config as a substitute.

## 11. Candidate Builder Contract

Candidate Builder is a first-class Stage input/output contract for Alignment.
It must freeze:

```text
reason/AnswerUnit input manifest;
SourceClaim consideration scope;
binding/source/run scope;
builder contract and deterministic versions;
recall ladder and fallback level;
score/rank policy where relevant;
TopK, threshold and boundary-tie policy;
selected candidate manifest and hash;
omitted candidate manifest and hash;
per-pair selected/omitted reason.
```

At minimum, every pair entering deterministic recall consideration must be
explainable as:

```text
SELECTED_FOR_JUDGMENT
or
OMITTED_BY_CANDIDATE_POLICY with explicit reason
```

Omission must never be serialized as `NO_SUPPORT`. A judged negative verdict
and a pair never sent to the judge are different semantic outcomes.

## 12. Stage Review Decision

### 12.1 Options

Option A, mutable review status inside StageExecution, is rejected because it
cannot retain reopen/correction history and mixes compute state with human
decision state.

Option B, append-only review decisions bound to immutable outputs, is selected.

### 12.2 Review Binding Invariant

> Human review binds to an immutable Stage output manifest, immutable completed
> partition, or an explicitly permitted immutable reusable fact-value version,
> never merely to a mutable row or moving query result.

Required review identity includes:

```text
review decision id;
review target type = STAGE_OUTPUT | STAGE_PARTITION | REUSABLE_FACT_VERSION;
reviewed StageExecution id for Stage targets, otherwise null;
reviewed output/partition id or reusable-object identity + exact version;
reviewed manifest ref;
exact member refs;
member count;
output/partition hash;
decision;
actor and timestamp;
review contract/version;
review note/reason;
supersedes prior review decision when applicable.
```

### 12.3 Immutable Partitions

Large stages may expose completed immutable partitions before the whole Stage
finishes. A review partition must have a fixed id, fixed member manifest/count,
hash and completed status. Background writers cannot add, remove or mutate its
members after it becomes reviewable.

The moving query “all current SUPPORTS” is not a review target. Later outputs
must form a new partition or a new StageExecution.

Downstream stages requiring the full Alignment set remain blocked until their
Stage Contract's full-input condition is satisfied, even if some partitions are
already reviewed.

### 12.4 Review Lifecycle

```text
first CONFIRM/REJECT/REOPEN or Stage-permitted DEFER/SHELVE decision -> append ReviewDecision
new decision for the same exact target -> must supersede the one authoritative terminal decision
new decision -> uses expected review state version and references the superseded decision
old decision/output -> retained for audit
```

A review cannot become actionable before its target manifest/partition is
immutable and complete.

For one exact immutable `ReviewTarget`, decisions form one append-only linear
supersession chain, not a general graph. ReviewTarget identity is exactly:

```text
Context id + StageExecution id for Stage targets,
or reusable fact scope/identity/version for reusable targets;
review unit type = STAGE_OUTPUT | STAGE_PARTITION | REUSABLE_FACT_VERSION;
output/partition manifest identity;
reviewed output_set_hash/partition hash;
review contract/version.
```

A new decision has zero predecessors only when it is the first decision for
that target; otherwise it has exactly one direct predecessor and that
predecessor must be the current authoritative terminal decision. Cross-Context,
cross-StageExecution, cross-partition, cross-output-hash, cross-unit-type and
cross-review-contract supersession are invalid.

The predecessor must already exist and be older in append-only lineage. Self,
future and cyclic references are invalid. Existing ReviewDecision records can
never be mutated to manufacture or repair a chain.

### 12.5 AuthoritativeReviewDecision

The authority scope key is the exact ReviewTarget identity above. For one valid
linear chain:

```text
review_authority_scope = exact ReviewTarget identity
```

For that exact scope:

```text
0 non-superseded terminal decisions
-> UNREVIEWED/PENDING

1 non-superseded terminal decision
-> that decision is AuthoritativeReviewDecision

more than 1 non-superseded terminal decision
-> REVIEW_CONFLICT
-> no decision is authoritative
-> downstream review-gated consumption is blocked
```

Created time and greatest row ID never break a tie. A decision can supersede
only the current authoritative decision in the same scope and must submit its
expected `review_state_version`. A stale expected version fails without
appending an effective branch. If historical import already contains multiple
leaf decisions, the projection reports `REVIEW_CONFLICT`; it does not repair the
chain by sorting.

Any imported self edge, cycle, future predecessor, missing predecessor,
cross-target edge or node with more than one direct predecessor is
`REVIEW_CONFLICT_INVALID_GRAPH`. It has no authoritative decision and blocks
review-gated consumption. A review contract version change creates a distinct
ReviewTarget lineage. It cannot supersede the old version without a separately
approved explicit migration/compatibility contract. Every consuming Stage
Contract names the exact review contract/version it accepts; a decision from a
parallel version scope cannot silently qualify it.

`REOPEN` is a pure review decision. When authoritative, it returns the target to
review-pending eligibility and supersedes the previous CONFIRM/REJECT while
retaining both records. Stage-permitted DEFER/SHELVE is also a pure decision and
cannot masquerade as CONFIRM. None of these decisions mutates reviewed output.
Downstream executions that consumed the superseded decision become stale by
their exact review input edge; the reviewed output itself remains immutable.

## 13. Human Override Classification

Human changes are not one generic operation.

### 13.1 Review Is Not Edit

```text
ReviewDecision
= CONFIRM / REJECT / REOPEN, or Stage-permitted DEFER/SHELVE,
  for an exact immutable target
= never changes semantic output content

Correction/Edit
= human-authored semantic content change
= new immutable reusable-object version or new StageExecution output
= never mutates the reviewed output in place
```

If a correction needs acceptance, the new output/version is created first and a
separate ReviewDecision binds to that new target.

### 13.2 Normative Operation Mapping

| Human action | Required new lineage | Review behavior | Direct descendants that can become stale through actual consumed edges |
| --- | --- | --- | --- |
| Confirm/reject/reopen existing Decision Reason output | no new semantic output | append ReviewDecision for exact `ANSWER_SEMANTIC` output/partition | only consumers of the superseded authoritative review |
| Edit Decision Reason/AnswerUnit content | new human-authored `ANSWER_SEMANTIC` StageExecution output | optional/required review per Stage Contract targets the new output | Binding, Product Truth projection, Gap and later actual descendants consuming the old output/review |
| Confirm/reject/reopen Product Truth fact version | no fact-value mutation | append ReviewDecision for exact fact-value version | consumers of the superseded authoritative fact review |
| Change Product Truth value, for example UNKNOWN to TRUE | new immutable reusable `ProductTruthFactValueVersion`, then new `PRODUCT_TRUTH_PROJECTION` StageExecution when selected for this Context | review binds to the new fact-value version; TRUE/FALSE/UNKNOWN is data, not the ReviewDecision enum | consumers of old Product Truth projection/review |
| Confirm/reject/reopen existing Evidence relation | no relation mutation | append ReviewDecision for exact `EVIDENCE_ALIGNMENT` member/partition | consumers of superseded authoritative Evidence review |
| Change Evidence relation, for example NO_SUPPORT to SUPPORTS | new human-authored corrected relation in a new `EVIDENCE_ALIGNMENT` StageExecution output/partition | separate review targets corrected output | Benchmark, Gap, Channel Evidence and later actual descendants consuming old relation/review |
| Correct Binding content | new human-authored `BINDING` StageExecution output | separate review targets new binding partition | Candidate Builder, Alignment and actual descendants |
| Confirm/reject/reopen existing Gap | no Gap mutation | append ReviewDecision for exact `GAP` output/partition | consumers of superseded authoritative Gap review |
| Edit Gap classification/content | new human-authored `GAP` StageExecution output | separate review targets new Gap output | Channel Resolution/Strategy descendants that consume it |
| Confirm/reject/reopen Strategy | no Strategy mutation | append ReviewDecision for exact `STRATEGY_SYNTHESIS` output | Execution Proposal consumers of superseded authoritative Strategy review |
| Edit Strategy content | new human-authored, fully validated `STRATEGY_SYNTHESIS` StageExecution output | separate review targets new Strategy output | Execution Proposal descendants consuming old Strategy/review |
| Confirm/reject/reopen Execution Proposal | no Proposal mutation | append ReviewDecision for exact proposal partition/portfolio target | only separately approved persistence consumers |
| Edit Execution Proposal content | canonical rebuild/revalidation creates new human-authored `EXECUTION_PROPOSAL` StageExecution output | separate review targets new output | consumers of old proposal/review; no Action/Experiment is implied |

Changing a reusable fact does not mutate an old analysis projection. Changing a
current projection does not rewrite its reusable source fact. Each Stage
Contract must say which form it consumes.

“Human-authored StageExecution” identifies output provenance; it does not mean a
worker LLM ran. It has the same immutable manifest, configuration/validator and
selection rules as a machine-produced replacement.

## 14. Dependency-Based Invalidation

### 14.1 Invariant

Compute outcome and current eligibility are independent dimensions.

```text
compute_outcome
= NOT_STARTED | ACTIVE | SUCCEEDED | TERMINAL_FAILED | SKIPPED
= historical fact; SUCCEEDED never becomes FAILED because validity changed

current_eligibility
= ELIGIBLE | STALE | INVALIDATED | SUPERSEDED | BLOCKED
= versioned/audited relation outside immutable output content
```

> Dependency-propagated `STALE` may occur only when an exact input ref, version
> or hash actually consumed by that StageExecution is superseded, invalidated or
> replaced in the selected lineage.

Invalidation follows frozen dependency edges. It is not a project-wide reset.

### 14.2 Required Input Manifest

Every StageExecution records:

```text
upstream StageExecution and output/partition refs/hashes;
consumed reusable-object refs/versions/hashes;
Stage contract/configuration manifest.
```

This permits deterministic descendant discovery.

### 14.3 Required Examples

```text
Product Truth A changed
-> invalidate only descendants that consumed Product Truth A's old projection

Decision Reason changed
-> invalidate dependent Binding/Alignment and their descendants

Alignment authority changed
-> invalidate dependent Benchmark/Gap/Strategy

Gap authority changed
-> invalidate dependent Strategy

Strategy authority changed
-> invalidate dependent Execution Proposal and any not-yet-released current execution selection
```

Existing released or historical Action/Experiment records are not deleted or
rewritten. Their continuing operational eligibility is a Step 8 lifecycle
decision outside this RFC.

### 14.4 STALE

`STALE` means an execution is no longer eligible as current downstream input.
It is generated because at least one exact consumed dependency/reusable input or
authoritative review ref/hash is no longer the selected valid version. It does
not mutate output, erase success or deny that computation occurred.

Propagation is edge-driven:

```text
input A1 superseded/invalid
-> every StageExecution whose manifest directly consumed A1 becomes STALE
-> continue only to executions that directly consumed those stale outputs
-> stop at any execution that consumed a different replacement output A2/B2
```

Stage type adjacency alone cannot propagate staleness. A Stage C that consumed
B2 is not made stale merely because a different B1 is stale.

### 14.5 INVALIDATED

`INVALIDATED` is not a failed compute outcome and is not inferred from an input
edge. It is an explicit privileged semantic decision that an exact Context,
StageExecution, output manifest or immutable partition must no longer be
consumed even if its inputs have not naturally changed.

The independent validity event/relation must record:

```text
target exact id/ref/hash;
previous eligibility state/version;
decision = INVALIDATE;
reason code and note;
actor/source and authorization evidence;
timestamp;
expected validity state version.
```

The physical table/event representation is deferred, but the independent
relation is mandatory. A direct invalidation is a propagation root. Executions
that consumed its target become `STALE` through exact manifest edges; they are
not relabeled `INVALIDATED` unless separately targeted by their own event.

An invalidated Context cannot be the target of an effective production
CurrentContextPointer. An invalidated selected Stage leaves its historical
selection event intact but makes the authoritative current projection blocked
until an eligible Stage is explicitly selected.

### 14.6 Reactivation

Reactivation is an explicit privileged validity event, never an in-place status
rewrite. It records target, previous state/version, reason, actor, timestamp and
compatibility validation evidence.

Reactivation is legal only when:

```text
the direct invalidation reason is explicitly resolved/revoked;
the exact immutable output still exists;
its contract/profile is allowed in the target workflow track;
every consumed dependency/ref/hash is again selected and eligible;
every required authoritative review is still effective;
optimistic validity state precondition succeeds.
```

A `STALE` execution caused by superseded input cannot be reactivated merely by
changing its label. Its exact old dependency chain must first be explicitly
restored/selected and pass compatibility; reactivation and Stage selection are
then separately audited. Otherwise recompute creates a new StageExecution.

## 15. Source Content And Product Truth Versioning

### 15.1 Source Content

A successful refetch produces a new immutable content-version output containing
or referencing:

```text
source identity and canonicalization version;
fetch time/status/method;
raw response/artifact ref where retained;
clean body snapshot/ref and content hash;
fetch/extraction contract version used to produce clean body.
```

Passage members, positions and segmentation contract belong only to the
downstream `SEGMENTATION` Stage output. They are not folded into SOURCE_FETCH.

The old content version and its dependent Claims remain historical. A Context
can retain the same root while a new SourceFetch/Segmentation StageExecution
replaces current eligibility and invalidates actual descendants.

### 15.2 Product Truth

A Product Truth value correction creates a new immutable reusable
`ProductTruthFactValueVersion`; it never edits the old value. A separate
ReviewDecision binds to that exact fact-value version. When the corrected value
is selected for an existing Context, a new `PRODUCT_TRUTH_PROJECTION`
StageExecution freezes the exact Reason-scoped fact set. Existing Contexts and
historical Strategy/Experiment snapshots retain their consumed old versions.
Only actual descendants of the replaced projection/review lose current
eligibility.

The current mutable unique row cannot by itself satisfy this proposed contract;
this statement is a future implementation requirement, not migration approval.

## 16. Cache And Materialization

AnalysisContext is not part of semantic cache identity by default.

### 16.1 Exact Compatibility Signature

Every cacheable Stage uses
`semantic_cache_compatibility_signature.v1`. The signature is SHA-256 over the
canonical payload below, and every field is required:

```text
signature contract version;
stage_type;
normalized semantic input hash;
normalization contract version;
semantic/materialization contract version;
prompt-template version or explicit NO_PROMPT;
output schema version;
provider identity or explicit DETERMINISTIC;
model identity and immutable model revision or explicit NO_MODEL;
all deterministic semantic configuration manifest hash;
tool/parser/extractor versions consumed by that Stage;
required upstream materialization/output semantic hashes.
```

Exact signature equality is the only transparent reuse rule in v1:

```text
exact required signature match -> FULLY_COMPATIBLE -> reuse allowed
any required field differs -> INCOMPATIBLE -> cache miss
any required field absent/unverifiable -> UNKNOWN -> cache miss
```

Provider/model identity is never conditionally omitted. Deterministic Stages use
the explicit sentinels above. `context_id`, workflow track, actor, pointer and
review history are excluded because they do not alter semantic computation. If
a future Stage Contract proves that Context lineage itself changes computation,
that requires a new cache signature contract version; an Implementer cannot add
`context_id` ad hoc.

Changing a materialization contract cannot recover an older LLMCallCache result
unless an independently approved, versioned compatibility adapter emits the
complete v1 signature and audit reason. v1 defines no relaxed equivalence.

### 16.2 RuntimeStageProfile v1 Cache Policy

| Stage type | Cache policy | Required normalized semantic inputs in addition to the common signature |
| --- | --- | --- |
| `RUN_METRICS` | `EXACT_SIGNATURE_REUSE` | Root Run/Reference/Retrieval/target-page hashes + metric eligibility/spec config |
| `ANSWER_SEMANTIC` | `EXACT_SIGNATURE_REUSE` | exact Prompt and Run answer hashes |
| `PRODUCT_TRUTH_PROJECTION` | `EXACT_SIGNATURE_REUSE` | Reason manifest hash + exact fact-value/review version manifest |
| `BINDING` | `EXACT_SIGNATURE_REUSE` | AnswerUnit + same-Run observation manifest hashes |
| `SOURCE_QUALIFICATION` | `EXACT_SIGNATURE_REUSE` | source identity manifest + project/source-rule input versions |
| `SOURCE_FETCH` | `NO_TRANSPARENT_CACHE` | an explicitly selected immutable content version may be reused as an input, but a time-sensitive fetch attempt is not a semantic cache hit |
| `SEGMENTATION` | `EXACT_SIGNATURE_REUSE` | immutable source content hash |
| `SOURCE_CLAIM` | `EXACT_SIGNATURE_REUSE` | complete passage semantic input, including source context required by extractor |
| `ALIGNMENT_CANDIDATE_BUILD` | `EXACT_SIGNATURE_REUSE` | Binding/Claim/scope hashes + recall/scoring/TopK/tie config |
| `EVIDENCE_ALIGNMENT` | `EXACT_SIGNATURE_REUSE` | AnswerUnit semantic hash + SourceClaim semantic hash + candidate lineage |
| `BENCHMARK` | `EXACT_SIGNATURE_REUSE` | authoritative eligible Evidence + qualification manifest hashes |
| `GAP` | `EXACT_SIGNATURE_REUSE` | Reason/Truth/Evidence/Benchmark manifest and review hashes |
| `CHANNEL_EVIDENCE` | `EXACT_SIGNATURE_REUSE` | observation/source/claim/alignment manifest hashes |
| `CHANNEL_RESOLUTION` | `EXACT_SIGNATURE_REUSE` | Truth/Gap/channel profile hashes + eligibility/Resolver config |
| `STRATEGY_SYNTHESIS` | `EXACT_SIGNATURE_REUSE` | Reasons/Truth/Benchmark/Gap/Role manifests + authoritative review refs |
| `EXECUTION_PROPOSAL` | `EXACT_SIGNATURE_REUSE` | accepted Strategy/review, baseline, asset-input and compiler hashes |

The Runtime Projection must classify each observed cache/materialization binding
as `FULLY_COMPATIBLE`, `INCOMPATIBLE` or `UNKNOWN`, even when it does not execute
the cache.

### 16.3 Legacy Cache

If a historical cache/materialization record lacks any required contract,
schema, provider/model revision, normalized input or deterministic config field,
its status is `LEGACY_COMPATIBILITY_UNKNOWN`. It cannot be a transparent Formal
Runtime HIT. Only a separately approved compatibility adapter/recovery contract
may convert it, and that conversion identity/reason must be recorded.

On cache/materialization reuse, StageExecution still records the exact consumed
materialization identity/output hash. A cache hit does not erase Stage lineage.

## 17. Concurrency And Atomicity

Required invariants, independent of storage technology:

```text
one active owner per StageExecution/attempt lease;
lease ownership and expiry are explicit;
initial claim and every reclaim allocate a unique monotonic authority generation;
expired ownership can be reclaimed with an audit event and higher generation;
retry creates a new Attempt and preserves old error history;
only the current authority generation may publish completion;
late/superseded Attempt output cannot alter StageExecution semantic output;
exactly one successful completion publishes output manifest/hash atomically;
review requires target output immutability;
review, validity, Context pointer and ContextStageSelection writes use optimistic state preconditions;
conflicting writes fail rather than silently overwrite.
```

Existing materialization claim/lease logic is implementation evidence for some
primitives, not automatic proof that a generic Stage executor is ready.

## 18. Current State Authority

### 18.1 CurrentContextPointer

Current is an explicit pointer, not a latest-row competition.

```text
pointer scope
= project_id + prompt_id + workflow_track

pointer target
= exactly one context_id or explicit empty state

pointer concurrency
= state_version optimistic precondition
```

Pointer changes record previous/new Context, actor, reason, timestamp and prior
state version.

### 18.2 ContextStageSelection

A Context may contain multiple StageExecutions after recomputation. Therefore
the backend authority maintains an explicit, versioned logical relation:

```text
selection scope key
= context_id + RuntimeStageProfile version + stage_type + stage_scope_key

selection target
= exactly zero or one StageExecution id/output ref

stage_scope_key in RuntimeStageProfile v1
= WHOLE_CONTEXT

selection concurrency
= selection_state_version optimistic precondition
```

This relation can be implemented through pointers, activation events or an
equivalent projection, but it cannot use greatest id/time. Selection changes
are audited and use optimistic concurrency.

Every initial selection, replacement, rollback and reactivation is an explicit
promotion/selection transition with previous/new target, actor/source, reason,
timestamp and expected prior state version. A successful RECOMPUTE is only an
eligible proposal and never automatically replaces the selected execution.

A StageExecution may be selected only when:

```text
Context and workflow track match the selection scope;
compute outcome is SUCCEEDED or the Stage Contract's explicit selectable zero result;
output manifest is atomically complete and immutable;
current eligibility is ELIGIBLE;
all exact required dependency selections still match its consumed refs/hashes;
all AuthoritativeReviewDecisions required by the exact Stage Contract's named
review contract/version are present and acceptable;
lineage completeness satisfies that Stage Contract;
optimistic selection state precondition succeeds.
```

If promotion fails, the previous selection remains unchanged. If a selected
execution becomes STALE or INVALIDATED, selection history remains, but the
authoritative current Stage projection is blocked and cannot supply downstream
input until an eligible execution is explicitly selected.

Completed immutable partitions can be reviewed early but cannot independently
become the selected StageExecution. The Stage Contract may let a downstream
partitioned consumer name an exact completed partition as input; that does not
mean the full Stage is selected/complete.

### 18.3 Derived Current Objects

```text
CurrentContextPointer
-> selected StageExecutions
-> AuthoritativeReviewDecisions for exact selected outputs/partitions
-> current Strategy output
-> current Execution Proposal/Action/Experiment state
```

Package, Candidate and Experiment rows no longer independently declare current
through `latest`, status alone or frontend fallback.

For a review-gated selected output, `REVIEW_CONFLICT`, UNREVIEWED, REOPENED or an
unacceptable authoritative decision blocks the dependent current projection.
No ReviewDecision from another execution/partition can be inherited.

### 18.4 Backend Projection

The authoritative backend projection must express at least:

```text
Context id/fingerprint/root version/track;
projection state version;
per-stage compute state;
per-stage review state;
selected output/partition refs and hashes;
blocking reasons;
allowed semantic actions;
current Strategy ref/status;
current Execution Proposal/Action/Experiment refs/status;
legacy or partial-lineage warnings.
```

Backend owns these business facts.

## 19. Frontend Boundary

Frontend may own:

```text
selected tab;
expanded panel;
loading/presentation state;
unsubmitted local form edits;
presentation sorting/filtering.
```

Frontend may not independently reconstruct:

```text
current Context/Package/Candidate/Experiment;
Stage ready/complete/blocked;
allowed semantic action;
historical object eligibility.
```

If the authority projection is unavailable, the UI reports unavailable/stale
authority. It cannot replace it with empty defaults, latest local rows or a
different endpoint's historical payload.

## 20. Legacy Compatibility And Isolation

### 20.1 Lineage Completeness Contract

Every virtual Context, Stage and review/selection projection has exactly one
`lineage_completeness` value:

```text
COMPLETE
= every Runtime Contract-required input/ref/hash exists, is uniquely mapped and verifies

PARTIAL
= the lineage mapping is unique and honestly projectable,
  but one or more required historical metadata fields are absent
+ missing fields remain null and are listed
+ not fully replayable

UNSAFE
= conflicting or multiple plausible mappings prevent one legal lineage
+ no winner is selected
+ latest/time/id fallback is forbidden

UNAVAILABLE
= a fixed Manifest-required object/ref is missing or unreadable
+ no substitute object is queried
```

Roll-up is calculated within one explicitly named projection objective and its
current-critical closure. The objective-specific algorithm in Section 20.4 is
normative; there is no context-free `UNAVAILABLE > UNSAFE` shortcut. A missing
fixed Root object, an ambiguous critical Stage and an unavailable non-critical
future Stage have different effects. CurrentContextPointer and review authority
are separate domains; an unavailable historical Pointer does not relabel an
otherwise projectable Context as UNAVAILABLE.

Every level must output:

```text
lineage_completeness;
missing_fields[];
unsafe_reasons[];
source_refs[];
```

For COMPLETE both diagnostic arrays are empty. PARTIAL requires non-empty
`missing_fields`; UNSAFE requires non-empty `unsafe_reasons`; UNAVAILABLE names
the missing/unreadable fixed refs in `missing_fields`. A PARTIAL or UNSAFE
projection is a successful honest Spike result, not an implementation failure.

### 20.2 Backfill Options

Historical Context backfill is allowed only when exact root inputs, immutable
payload refs/hashes, Stage dependencies and review targets can be proven.

Otherwise historical state is represented through a Legacy Compatibility
Projection with explicit classification such as:

```text
PARTIALLY_MAPPABLE = lineage_completeness PARTIAL
UNSAFE_TO_BACKFILL = lineage_completeness UNSAFE or UNAVAILABLE
```

These are state requirements, not approved storage enum values.

No persisted lineage id, output hash, review target, feature profile or current
selection may be fabricated from current code or latest rows.

### 20.3 Path Isolation Requirements

| Path | Proposed classification before separate cutover |
| --- | --- |
| current Optimization production APIs | unchanged production |
| old Step 8 persistence service/API | legacy production-capable, explicitly isolated |
| PR5-A/B | shadow/read-only proposal and revalidation |
| planner/readiness tools | diagnostic/read-only |
| Golden replay | fixed-manifest GOLDEN_REPLAY track |
| legacy historical views | read-only LEGACY track/projection |

No path may silently fall back from PRODUCTION to SHADOW, GOLDEN_REPLAY or
LEGACY output.

### 20.4 LegacyStageProjectionProfile v1

`legacy_stage_projection.single_prompt.v1` defines only how Spike B interprets
the fixed historical database. It does not assign future Runtime ownership to
legacy tables and cannot be consumed by production selection.

The projection scope is exactly the fixed case Manifest:

```text
snapshot id and snapshot schema version;
exact database relative path and SHA-256;
fixed project_id and prompt_id;
fixed EvidencePackage id/version/hash;
fixed Run id set and run-scope hash;
fixed StrategyCandidate id/status;
explicit fixed contract/hash fields or FIELD_ABSENT.
```

No source selector may use greatest id/time, `active`, current package,
latest-completed run or a current frontend/API selection. A source ref is
`legacy:<table>:<primary-key>` inside the exact database identity. Row id is
permitted here as snapshot-local source identity; it never becomes future
semantic output identity.

Every legacy Stage source set is a
`legacy_stage_source_manifest.v1` under
`semantic_manifest_canonicalization.v1`. Its fixed selector scope is first
constructed under `LegacyFixedScopeValues.v1`; no Stage may supply a free-form
scope object.

`LegacyScopeKey.v1` is the complete scope-key and value-kind registry:

| Exact scope key | Exact value kind | Canonical value rule |
| --- | --- | --- |
| `CASE_ID` | `STRING` | exact Manifest `case_id` UTF-8 string |
| `SNAPSHOT_ID` | `STRING` | exact Manifest `snapshot_id` UTF-8 string |
| `EXACT_DATABASE_SHA256` | `SHA256` | 64 lowercase hexadecimal string from Manifest |
| `PROJECT_ID` | `SCALAR_ID` | positive INTEGER from Manifest |
| `PROMPT_ID` | `SCALAR_ID` | positive INTEGER from Manifest |
| `EVIDENCE_PACKAGE_ID` | `SCALAR_ID` | positive INTEGER from Manifest |
| `EVIDENCE_PACKAGE_VERSION` | `VERSION_INTEGER` | non-negative INTEGER from Manifest |
| `EVIDENCE_PACKAGE_HASH` | `SHA256` | 64 lowercase hexadecimal string from Manifest |
| `RUN_IDS` | `SET_ID_LIST` | duplicate-free positive INTEGER members from Manifest Run scope |
| `RUN_SCOPE_HASH` | `SHA256` | 64 lowercase hexadecimal string from Manifest |
| `STRATEGY_CANDIDATE_ID` | `SCALAR_ID` | positive INTEGER from Manifest |
| `STRATEGY_CANDIDATE_STATUS` | `STRING` | exact Manifest status UTF-8 string |
| `CANDIDATE_DOCUMENT_COLUMN` | `STRING` | exact case-bound column literal named below |
| `JSON_PATH_SET_ID` | `STRING` | exact path-set registry literal named below |
| `STEP_KEY` | `STRING` | exact selector literal; profile v1 permits only `gap` |

The value-kind registry is closed:

```text
SCALAR_ID       = positive INTEGER
VERSION_INTEGER = non-negative INTEGER
SET_ID_LIST     = ARRAY of unique positive INTEGER values, sorted ascending
SHA256          = STRING matching [0-9a-f]{64}
STRING          = exact UTF-8 STRING with no normalization
```

No other scope key or value kind is legal. `SET_ID_LIST` uses the existing
INTEGER and ARRAY byte grammar; input duplicates are invalid and are not
silently deduplicated. Every key has exactly the one value kind above.

The one canonical `LegacyFixedScopeValues.v1` semantic object is:

```text
{
  fixed_scope_contract_version: VALUE("LegacyFixedScopeValues.v1"),
  scope_key_contract_version: VALUE("LegacyScopeKey.v1"),
  scope_profile_id: VALUE(<exact profile id from the matrix below>),
  scope_entries: VALUE([
    {
      scope_key: VALUE(<exact LegacyScopeKey.v1 literal>),
      value_kind: VALUE(<the key's registered value kind>),
      canonical_value: VALUE(<typed canonical node>)
    }
  ])
}
```

`scope_entries` has SET semantics with member identity `scope_key` and is
serialized in ascending `STRING(scope_key)` canonical-byte order. Duplicate
keys, a wrong value kind, a value violating its kind, a missing required key or
an extra key make the fixed scope invalid. Profile v1 has no optional scope
keys. If a required Manifest value is missing/unreadable, the fixed legacy Stage
is UNAVAILABLE; an otherwise valid fixed scope that returns competing lineage
keeps the existing UNSAFE rule. No null wildcard, current/latest lookup or
inferred replacement is permitted.

The `fixed_scope_hash` uses the common hash envelope with:

```text
manifest_type = LegacyFixedScopeValues
manifest_contract_version = LegacyFixedScopeValues.v1
payload = the exact four-field semantic object above
```

The 16 selector scope profiles are normative. The required-key column is the
complete key set; `optional keys = NONE` for every row. The exact source filter
is the selector registry row later in this section and cannot be widened by the
scope object.

| Stage | Selector contract | Scope profile id | Required `LegacyScopeKey.v1` keys | Optional keys | Source member identity / exact filter |
| --- | --- | --- | --- | --- | --- |
| `RUN_METRICS` | `legacy_selector.run_metrics.v1` | `legacy_scope.run_metrics.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `EVIDENCE_PACKAGE_VERSION`, `EVIDENCE_PACKAGE_HASH`, `RUN_IDS`, `RUN_SCOPE_HASH`, `JSON_PATH_SET_ID`=`PACKAGE_METRIC_PATHS` | NONE | exact source-member tuple below / selector registry `RUN_METRICS` predicate |
| `ANSWER_SEMANTIC` | `legacy_selector.answer_semantic.v1` | `legacy_scope.answer_semantic.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `ANSWER_SEMANTIC` predicate |
| `PRODUCT_TRUTH_PROJECTION` | `legacy_selector.product_truth.v1` | `legacy_scope.product_truth.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS`, `CANDIDATE_DOCUMENT_COLUMN`, `JSON_PATH_SET_ID`=`CANDIDATE_TRUTH_PATHS` | NONE | exact source-member tuple below / selector registry `PRODUCT_TRUTH_PROJECTION` predicate |
| `BINDING` | `legacy_selector.binding.v1` | `legacy_scope.binding.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `BINDING` predicate |
| `SOURCE_QUALIFICATION` | `legacy_selector.source_qualification.v1` | `legacy_scope.source_qualification.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `SOURCE_QUALIFICATION` predicate |
| `SOURCE_FETCH` | `legacy_selector.source_fetch.v1` | `legacy_scope.source_fetch.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `SOURCE_FETCH` predicate |
| `SEGMENTATION` | `legacy_selector.segmentation.v1` | `legacy_scope.segmentation.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `SEGMENTATION` predicate |
| `SOURCE_CLAIM` | `legacy_selector.source_claim.v1` | `legacy_scope.source_claim.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `SOURCE_CLAIM` predicate |
| `ALIGNMENT_CANDIDATE_BUILD` | `legacy_selector.alignment_candidates.v1` | `legacy_scope.alignment_candidates.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `ALIGNMENT_CANDIDATE_BUILD` predicate |
| `EVIDENCE_ALIGNMENT` | `legacy_selector.evidence_alignment.v1` | `legacy_scope.evidence_alignment.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `RUN_IDS`, `RUN_SCOPE_HASH` | NONE | exact source-member tuple below / selector registry `EVIDENCE_ALIGNMENT` predicate |
| `BENCHMARK` | `legacy_selector.benchmark.v1` | `legacy_scope.benchmark.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS`, `CANDIDATE_DOCUMENT_COLUMN`, `JSON_PATH_SET_ID`=`CANDIDATE_BENCHMARK_PATHS` | NONE | exact source-member tuple below / selector registry `BENCHMARK` predicate |
| `GAP` | `legacy_selector.gap.v1` | `legacy_scope.gap.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS`, `CANDIDATE_DOCUMENT_COLUMN`, `JSON_PATH_SET_ID`=`CANDIDATE_GAP_PATHS`, `STEP_KEY`=`gap` | NONE | exact source-member tuple below / selector registry `GAP` predicate |
| `CHANNEL_EVIDENCE` | `legacy_selector.channel_evidence.v1` | `legacy_scope.channel_evidence.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS`, `CANDIDATE_DOCUMENT_COLUMN`, `JSON_PATH_SET_ID`=`CANDIDATE_CHANNEL_EVIDENCE_PATHS` | NONE | exact source-member tuple below / selector registry `CHANNEL_EVIDENCE` predicate |
| `CHANNEL_RESOLUTION` | `legacy_selector.channel_resolution.v1` | `legacy_scope.channel_resolution.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS`, `CANDIDATE_DOCUMENT_COLUMN`, `JSON_PATH_SET_ID`=`CANDIDATE_CHANNEL_RESOLUTION_PATHS` | NONE | exact source-member tuple below / selector registry `CHANNEL_RESOLUTION` predicate |
| `STRATEGY_SYNTHESIS` | `legacy_selector.strategy_synthesis.v1` | `legacy_scope.strategy_synthesis.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS`, `CANDIDATE_DOCUMENT_COLUMN`, `JSON_PATH_SET_ID`=`CANDIDATE_STRATEGY_PATHS` | NONE | exact source-member tuple below / selector registry `STRATEGY_SYNTHESIS` predicate |
| `EXECUTION_PROPOSAL` | `legacy_selector.execution_proposal.v1` | `legacy_scope.execution_proposal.v1` | `CASE_ID`, `SNAPSHOT_ID`, `EXACT_DATABASE_SHA256`, `PROJECT_ID`, `PROMPT_ID`, `EVIDENCE_PACKAGE_ID`, `STRATEGY_CANDIDATE_ID`, `STRATEGY_CANDIDATE_STATUS` | NONE | exact source-member tuple below / fixed empty-source assertion |

For all Candidate-document profiles, `CANDIDATE_DOCUMENT_COLUMN` is exactly
`effective_payload_json` for CASE-REAL-019 and exactly
`structured_payload_json` for CASE-REAL-040. No other case or column is valid in
profile v1. `JSON_PATH_SET_ID` is exactly the literal path-set name shown in the
matrix; the path members remain the frozen registry later in this section.

The exact source member schema is:

```text
source_ref = legacy:<table>:<primary-key>
  or legacy-json:<table>:<primary-key>:<json-column>:<exact-json-path>;
source_kind = ROW | JSON_SLICE;
legacy_projection_profile_version = legacy_stage_projection.single_prompt.v1;
stage_type;
table_name;
primary_key;
selector_contract_id;
fixed_snapshot_id;
fixed_scope_contract_version = LegacyFixedScopeValues.v1;
scope_key_contract_version = LegacyScopeKey.v1;
scope_profile_id;
fixed_scope_hash;
json_column/path/state/value for JSON_SLICE, otherwise FIELD_ABSENT;
required_version_hash_states = exact named column/path states and values.
```

Its member identity is exactly:

```text
legacy_projection_profile_version
+ stage_type
+ selector_contract_id
+ scope_profile_id
+ fixed_scope_hash
+ source_ref
+ source_kind
```

Equal identity/equal canonical content collapses; equal identity/different
content is MANIFEST_IDENTITY_CONFLICT and makes the legacy Stage UNSAFE. The
scope object itself appears once in the outer source manifest and every member
binds its exact hash; a source row cannot choose a per-row scope representation.

The primary key is part of this snapshot-local legacy identity only. Each JSON
slice is parsed from the one column named below and canonicalized as a semantic
node; raw JSON key order is not semantic. A missing path still emits its
`JSON_SLICE` member with `FIELD_ABSENT`; JSON null emits
`FIELD_PRESENT_NULL`; an empty array/object emits `EMPTY_COLLECTION`. Invalid
JSON makes that Stage source projection `UNAVAILABLE` and is never repaired
from another column.

For legacy JSON slices, a JSON number token without fraction/exponent is
INTEGER. A finite fraction/exponent token is converted by exact base-10
mathematics to the non-exponent DECIMAL form above; binary floating-point
rounding is forbidden. JSON booleans remain BOOLEAN and never become integers.

Members use `SET_SEMANTICS` and the common duplicate/conflict rule. The exact
`legacy_stage_source_manifest.v1` hash payload is:

```text
manifest_type = LegacyStageSourceManifest
manifest_contract_version = legacy_stage_source_manifest.v1
payload = {
  legacy_projection_profile_version:
    VALUE("legacy_stage_projection.single_prompt.v1"),
  fixed_snapshot_id: VALUE(<exact Manifest snapshot_id>),
  exact_database_sha256: VALUE(<exact Manifest database SHA-256>),
  stage_type: VALUE(<exact RuntimeStageProfile v1 stage token>),
  selector_contract_id: VALUE(<exact selector registry id>),
  fixed_scope_contract_version: VALUE("LegacyFixedScopeValues.v1"),
  scope_key_contract_version: VALUE("LegacyScopeKey.v1"),
  scope_profile_id: VALUE(<exact selector scope profile id>),
  fixed_scope_values: VALUE(<exact four-field scope semantic object>),
  fixed_scope_hash: VALUE(<64-lowercase-hex scope hash>),
  source_members: EMPTY_COLLECTION or VALUE(<canonical source member ARRAY>)
}
```

`source_ref_set_hash` is SHA-256 of the common canonical hash envelope and this
payload. It does not use `hash(str(ids))`, raw JSON bytes, query order, or a
second hash convention. SQL text, free-form dictionaries, unregistered scope
keys, created/id ordering and current/latest winner logic never enter it.

The fixed symbols used by every selector are:

```text
M = the exact CASE Manifest;
P = the one optimization_evidence_packages row with
    id=M.evidence_package_id, project_id=M.project_id,
    prompt_id=M.prompt_id, version=M.evidence_package_version and
    package_hash=M.evidence_package_hash;
R = M.source_run_ids as a set of unique integers;
C = the one optimization_strategy_candidates row with
    id=M.strategy_candidate_id, project_id=M.project_id,
    evidence_package_id=M.evidence_package_id and
    review_status=M.strategy_candidate_status;
O = reference_sources UNION retrieval_candidates whose run_id is in R;
S = answer_evidence_shadow_runs whose project_id=M.project_id,
    prompt_id=M.prompt_id, evidence_package_id=M.evidence_package_id and whose
    parsed source_run_ids_json is a duplicate-free integer set exactly equal R;
D = source_documents whose non-empty
    (canonicalization_version, canonical_url_hash) tuple equals a non-empty
    tuple from O;
Q = source_quality rows whose source_document_id is a primary key in D.
```

Every selector JSON array (`source_run_ids_json` and observed
document/prompt/run id arrays) must be valid JSON, have array type, and contain only
base-10 integer JSON tokens. Boolean, decimal, string, object and null members
are invalid. Duplicate members in a selector array make the owning legacy Stage
`UNSAFE`; invalid JSON/type makes it `UNAVAILABLE`. Set equality/intersection is
then performed on the canonical integer set, never on serialized JSON text.

`P`, every Run id in `R`, and `C` must exist exactly once and pass every stated
equality. Failure is `UNAVAILABLE`. For all other selectors, zero rows is an
explicit empty source set; multiple rows are all retained. A uniqueness
requirement appears only where the Stage row explicitly says so. No created/id
ordering may select one row from a multi-row set.

The fixed JSON documents are:

```text
Package document for both cases = P.package_payload_json;
CASE-REAL-019 Candidate document = C.effective_payload_json;
CASE-REAL-040 Candidate document = C.structured_payload_json.
```

For #19, `effective_payload_version` must equal `effective_payload.v1`. For #40,
`effective_payload_json`, `effective_payload_version`, and absent PR4 hash fields
remain audit evidence only; they cannot replace the explicitly selected
`structured_payload_json`. There is no cross-column fallback.

Exact path sets are:

```text
PACKAGE_METRIC_PATHS =
  $.metrics
  $.metric_snapshot
  $.run_metric_eligibility
  $.answer_eligible_run_ids
  $.citation_eligible_run_ids
  $.retrieval_eligible_run_ids
  $.retrieval_metrics_status
  $.metric_spec_version

CANDIDATE_TRUTH_PATHS =
  $.decision_reasons
  $.evidence_summary.gap_items
  $.target_capabilities
  $.product_truth_refs

CANDIDATE_BENCHMARK_PATHS =
  $.benchmark_source
  $.benchmark_evidence_ids
  $.citation_decision_values
  $.citation_value_summary
  $.evidence_summary.gap_items

CANDIDATE_GAP_PATHS =
  $.evidence_summary.gap_items
  $.target_capabilities
  $.gap_item_ids
  $.evidence_gap_reason
  $.evidence_gap_cause
  $.observed_problem
  $.product_truth_gate

CANDIDATE_CHANNEL_EVIDENCE_PATHS =
  $.channel_aggregation
  $.citation_decision_values
  $.citation_value_summary

CANDIDATE_CHANNEL_RESOLUTION_PATHS =
  $.channel_roles
  $.planned_channels
  $.strategy_channel_resolver
  $.channel_resolution_state
  $.channels

CANDIDATE_STRATEGY_PATHS =
  $.strategy_synthesis
  $.decision_reasons
  $.intervention_themes
  $.strategy_portfolio
  $.strategy_decision_view
  $.strategy_audit_view
  $.strategy_context
  $.strategy_phase
  $.strategy_schema_version
  $.strategy_basis
  $.primary_intervention_path
  $.planned_channels
```

ProductTruth hint ids are the duplicate-free integer union of
`product_truth_ids` arrays directly inside members of
`$.decision_reasons`, `$.evidence_summary.gap_items`, and
`$.target_capabilities`, plus integer members of `$.product_truth_refs.ids`.
Non-integer values make the Product Truth legacy Stage `UNSAFE`; missing paths
contribute no ids and remain explicit path-state members. Only
`target_brand_capability_truths.id` in that union and with
`project_id=M.project_id` enters the source set. A missing named id is listed as
a missing fixed hint ref; no project-wide scan occurs.

`required_version_hash_states` contains exactly these named fields for each row
type; a schema lacking a named field records `FIELD_ABSENT` rather than dropping
the field or deriving it:

| Legacy row/JSON source | Exact version/hash state fields |
| --- | --- |
| `optimization_evidence_packages` | `schema_version`, `metric_spec_version`, `package_hash`, `version` |
| `browser_monitor_runs` | `collector_version`, `parser_version`, `status`, `reference_complete` |
| `reference_sources`, `retrieval_candidates` | `canonicalization_version`, `canonical_url_hash` |
| `prompt_analysis_runs` | `status`; extractor/input/output contract/hash = FIELD_ABSENT |
| `recommendation_events` | `answer_hash`, `provider`, `model`, `prompt_version`, `schema_version`, `review_status` |
| `optimization_strategy_candidates` | `effective_payload_version`, `review_status`; Strategy contract/input/output hash states come only from M |
| Candidate/Package `JSON_SLICE` | selected JSON column, exact JSONPath, field state, canonical slice hash |
| `target_brand_capability_truths` | `product_truth_status`, `truth_source`, `reviewed_at`; fact-value version/hash and binding version/hash = FIELD_ABSENT |
| `answer_evidence_shadow_runs` | `pipeline_version`, `status`, `formal_output_impact`; Stage input/output hash = FIELD_ABSENT |
| `answer_units` | `extraction_version`, `extraction_method`, `review_status`; immutable member hash = FIELD_ABSENT |
| `answer_decision_bindings` | `pipeline_version`, `binding_method`, `review_status`; immutable partition hash = FIELD_ABSENT |
| `source_documents` | `canonicalization_version`, `canonical_url_hash`, `clean_text_hash`, `fetch_status`, `fetch_time`; immutable content-version ref/hash = FIELD_ABSENT |
| `source_quality` | `clean_text_hash`, `extractor_version`, `content_quality_status`, `quality_source` |
| `source_claim_materializations` | `contract_version`, `output_hash`, `extractor_impl_version`, `prompt_version`, `schema_version`, `provider`, `model`, `status` |
| `source_claims` | `provider`, `model`, `prompt_version`, `schema_version`, `review_status`; owning Stage output hash = FIELD_ABSENT |
| `answer_evidence_shadow_results` | `pipeline_version`, `formal_output_impact`, `review_status`; candidate manifest hash = FIELD_ABSENT |
| `evidence_alignment_materializations` | `contract_version`, `output_hash`, `judge_impl_version`, `prompt_version`, `schema_version`, `provider`, `model`, `status` |
| `evidence_alignments` | `provider`, `model`, `prompt_version`, `schema_version`, `review_status`; candidate manifest/output hash = FIELD_ABSENT |
| `workflow_confirmations` | `decision_status`, `reviewed_at`; immutable review target/hash = FIELD_ABSENT |

Legacy review binding classifications are:

```text
IMMUTABLE_HASH_BOUND
= exact immutable target/version/hash and review source exist;

OBJECT_ID_ONLY
= review points to a fixed row but no immutable output/version hash exists;

CURRENT_STATE_BOUND
= review fields are mutable state on the reviewed row;

UNBOUND
= no exact review target can be proven;

NONE
= Stage has no profile-v1 review requirement.
```

Only `IMMUTABLE_HASH_BOUND` can project a formal Runtime
AuthoritativeReviewDecision. The other values report
`authoritative_review = UNRESOLVED_LEGACY`, even when a legacy status says
CONFIRMED/ACCEPTED.

Selection source for all 16 legacy Stages is `NONE`: the fixed database has no
persisted `ContextStageSelection`. A unique fixed source set may produce a
virtual display Stage identity, but `selected StageExecution ref` remains null.

The selector registry below is normative. `JSON(path-set)` emits the exact slice
members above. `ROWS(table, predicate)` emits every row satisfying the complete
predicate; “best,” “closest,” implicit current state, and winner selection do
not exist.

| Stage | Selector contract | Fixed scope contract/profile | Exact source-set derivation | Required version/hash evidence | Review / selection | Completeness / ambiguity rule |
| --- | --- | --- | --- | --- | --- | --- |
| `RUN_METRICS` | `legacy_selector.run_metrics.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.run_metrics.v1` | `{P} + browser_monitor_runs.id IN R + reference_sources.run_id IN R + retrieval_candidates.run_id IN R + JSON(PACKAGE_METRIC_PATHS)` | P schema/metric/package hash; Run/observation captured versions; independent Stage hashes absent | NONE / NONE | PARTIAL after all Manifest-required rows verify; missing P/Run is UNAVAILABLE |
| `ANSWER_SEMANTIC` | `legacy_selector.answer_semantic.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.answer_semantic.v1` | recommendation_events where project/prompt equal M and run_id IN R; prompt_analysis_runs where project/prompt equal M | Event answer/provider/model/prompt/schema fields; no Stage hash | CURRENT_STATE_BOUND or OBJECT_ID_ONLY / NONE | exactly one PromptAnalysisRun envelope is PARTIAL; zero is UNAVAILABLE; more than one is UNSAFE and all are listed |
| `PRODUCT_TRUTH_PROJECTION` | `legacy_selector.product_truth.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.product_truth.v1` | `{C} + JSON(CANDIDATE_TRUTH_PATHS) + truth rows selected only by the exact hint-id union rule above` | Candidate Manifest fields; fact-value/binding versions absent | CURRENT_STATE_BOUND / NONE | always UNSAFE for fixed cases; hints never become BOUND |
| `BINDING` | `legacy_selector.binding.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.binding.v1` | all S; answer_units and answer_decision_bindings whose shadow_run_id IN primary-key set S | ShadowRun and child pipeline/extraction versions; no Stage hash | CURRENT_STATE_BOUND or OBJECT_ID_ONLY / NONE | one terminal S envelope is PARTIAL; zero is UNAVAILABLE; multiple or mixed terminal states are UNSAFE |
| `SOURCE_QUALIFICATION` | `legacy_selector.source_qualification.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.source_qualification.v1` | all O + all D + all Q, using only the exact canonical tuple equality defining D/Q | observation/document canonicalization fields; current clean-text/quality hashes retained as legacy state | NONE / NONE | one document per observation tuple with immutable proof absent is PARTIAL; zero document for a tuple is PARTIAL with missing ref; more than one/conflicting document or mutable quality/content interpretation is UNSAFE |
| `SOURCE_FETCH` | `legacy_selector.source_fetch.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.source_fetch.v1` | exactly D; no other source_documents row is admitted | document canonical tuple, fetch status/time, clean_text_hash; immutable historical content-version ref absent | NONE / NONE | fixed current rows without Package-time content versions are UNSAFE; no D rows is UNAVAILABLE |
| `SEGMENTATION` | `legacy_selector.segmentation.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.segmentation.v1` | one `legacy-json:source_documents:<D.id>:content_blocks_json:$` member for every D row | exact JSON state plus document clean_text_hash; segmentation/content-version hashes absent | NONE / NONE | mutable blocks without immutable content-version lineage are UNSAFE; invalid JSON is UNAVAILABLE |
| `SOURCE_CLAIM` | `legacy_selector.source_claim.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.source_claim.v1` | source_claim_materializations where `source_document_id IN D.id` OR parsed duplicate-free integer `observed_source_document_ids_json` intersects D.id; plus source_claims where project_id=M.project_id and source_document_id IN D.id | every selected ledger contract/output/provider/model field and Claim provider/model/prompt/schema fields exactly as stored | NONE / NONE | all selected rows remain visible; absent Stage boundary or competing content/passage lineage is UNSAFE; zero rows is PARTIAL, never successful zero |
| `ALIGNMENT_CANDIDATE_BUILD` | `legacy_selector.alignment_candidates.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.alignment_candidates.v1` | answer_evidence_shadow_results where shadow_run_id IN S.id, project/prompt equal M and run_id IN R; rows are audit hints only | retrieval score/pipeline fields; candidate policy/selected/omitted manifest absent | NONE / NONE | output manifest is null and Stage is UNSAFE; hint rows cannot reconstruct selection or omission |
| `EVIDENCE_ALIGNMENT` | `legacy_selector.evidence_alignment.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.evidence_alignment.v1` | evidence_alignments where project/prompt equal M and run_id IN R; the exact shadow-result set from prior selector; evidence_alignment_materializations whose parsed `observed_prompt_ids_json` contains M.prompt_id and parsed `observed_run_ids_json` intersects R | judge/ledger/provider/model/prompt/schema values as stored; candidate manifest absent | CURRENT_STATE_BOUND or OBJECT_ID_ONLY / NONE | every admitted row is listed; multiple S/candidate scopes or mutable review targets make fixed cases UNSAFE |
| `BENCHMARK` | `legacy_selector.benchmark.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.benchmark.v1` | `{C} + JSON(CANDIDATE_BENCHMARK_PATHS)` only | Candidate Manifest versions/hashes and exact path states; independent Stage hash absent | NONE / NONE | PARTIAL; absent paths remain absent and no database Benchmark query is allowed |
| `GAP` | `legacy_selector.gap.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.gap.v1` | `{C} + JSON(CANDIDATE_GAP_PATHS) + workflow_confirmations where project/prompt equal M and step_key exactly 'gap'` | Candidate path states; mutable confirmation values; independent Stage/review hash absent | CURRENT_STATE_BOUND or UNBOUND / NONE | PARTIAL; confirmation is audit only and no DecisionGapDiagnosis row is admitted without an exact numeric row id path |
| `CHANNEL_EVIDENCE` | `legacy_selector.channel_evidence.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.channel_evidence.v1` | `{C} + JSON(CANDIDATE_CHANNEL_EVIDENCE_PATHS)` only | exact path states; independent Stage hash absent | NONE / NONE | PARTIAL; no source aggregation is rerun |
| `CHANNEL_RESOLUTION` | `legacy_selector.channel_resolution.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.channel_resolution.v1` | `{C} + JSON(CANDIDATE_CHANNEL_RESOLUTION_PATHS)` only | exact path states and persisted resolver version where present | NONE / NONE | PARTIAL; #40 missing PR4 fields remain FIELD_ABSENT |
| `STRATEGY_SYNTHESIS` | `legacy_selector.strategy_synthesis.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.strategy_synthesis.v1` | `{C} + JSON(CANDIDATE_STRATEGY_PATHS)` using the case-specific Candidate document only | exact Manifest strategy version/hash states; #40 null/absent states preserved | CURRENT_STATE_BOUND / NONE | PARTIAL; Candidate is historical projection target, never selected/current/authoritative |
| `EXECUTION_PROPOSAL` | `legacy_selector.execution_proposal.v1` | `LegacyFixedScopeValues.v1` / `legacy_scope.execution_proposal.v1` | empty source set by fixed Manifest assertion; no database table or JSON column is queried | proposal manifest/hash absent | UNBOUND / NONE | UNAVAILABLE with exact missing proposal ref class; Action/Experiment/PR5 substitution forbidden |

`legacy_stage_projection.single_prompt.v1` uses Stage output member identities
from `stage_manifest_canonicalization.v1`; it never invents a missing semantic
output hash. Legacy source-set identity and projected Runtime output identity are
different values.

The following CASE-REAL-019 `EXECUTION_PROPOSAL` scope is a normative
cross-implementation vector. Its `scope_entries` order is the exact ascending
`STRING(scope_key)` canonical-byte order, including the STRING length prefix:

```text
scope_profile_id = legacy_scope.execution_proposal.v1
scope_entries =
  PROJECT_ID                 | SCALAR_ID | 3
  SNAPSHOT_ID                | STRING    | CASE-REAL-019@2026-09-08
  EVIDENCE_PACKAGE_ID        | SCALAR_ID | 12
  EXACT_DATABASE_SHA256      | SHA256    | fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3
  STRATEGY_CANDIDATE_ID      | SCALAR_ID | 57
  STRATEGY_CANDIDATE_STATUS  | STRING    | ACCEPTED
  CASE_ID                    | STRING    | CASE-REAL-019
  PROMPT_ID                  | SCALAR_ID | 19
```

Exact `LegacyFixedScopeValues.v1` envelope canonical bytes (one line, no
trailing LF):

```text
o6:{s24:canonical_bytes_contractx3:s36:semantic_manifest_canonical_bytes.v1s24:canonicalization_versionx3:s37:semantic_manifest_canonicalization.v1s14:hash_algorithmx3:s7:SHA-256s25:manifest_contract_versionx3:s25:LegacyFixedScopeValues.v1s13:manifest_typex3:s22:LegacyFixedScopeValuess7:payloadx3:o4:{s28:fixed_scope_contract_versionx3:s25:LegacyFixedScopeValues.v1s13:scope_entriesx3:a8:[o3:{s15:canonical_valuex3:i3;s9:scope_keyx3:s10:PROJECT_IDs10:value_kindx3:s9:SCALAR_ID}o3:{s15:canonical_valuex3:s24:CASE-REAL-019@2026-09-08s9:scope_keyx3:s11:SNAPSHOT_IDs10:value_kindx3:s6:STRING}o3:{s15:canonical_valuex3:i12;s9:scope_keyx3:s19:EVIDENCE_PACKAGE_IDs10:value_kindx3:s9:SCALAR_ID}o3:{s15:canonical_valuex3:s64:fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3s9:scope_keyx3:s21:EXACT_DATABASE_SHA256s10:value_kindx3:s6:SHA256}o3:{s15:canonical_valuex3:i57;s9:scope_keyx3:s21:STRATEGY_CANDIDATE_IDs10:value_kindx3:s9:SCALAR_ID}o3:{s15:canonical_valuex3:s8:ACCEPTEDs9:scope_keyx3:s25:STRATEGY_CANDIDATE_STATUSs10:value_kindx3:s6:STRING}o3:{s15:canonical_valuex3:s13:CASE-REAL-019s9:scope_keyx3:s7:CASE_IDs10:value_kindx3:s6:STRING}o3:{s15:canonical_valuex3:i19;s9:scope_keyx3:s9:PROMPT_IDs10:value_kindx3:s9:SCALAR_ID}]s26:scope_key_contract_versionx3:s17:LegacyScopeKey.v1s16:scope_profile_idx3:s34:legacy_scope.execution_proposal.v1}}
```

```text
fixed_scope_hash = d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66
```

For the same vector, `source_members` is `EMPTY_COLLECTION` because the fixed
selector forbids querying any proposal/Action/Experiment substitute. The exact
`LegacyStageSourceManifest` canonical bytes are:

```text
o6:{s24:canonical_bytes_contractx3:s36:semantic_manifest_canonical_bytes.v1s24:canonicalization_versionx3:s37:semantic_manifest_canonicalization.v1s14:hash_algorithmx3:s7:SHA-256s25:manifest_contract_versionx3:s31:legacy_stage_source_manifest.v1s13:manifest_typex3:s25:LegacyStageSourceManifests7:payloadx3:o11:{s21:exact_database_sha256x3:s64:fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3s28:fixed_scope_contract_versionx3:s25:LegacyFixedScopeValues.v1s16:fixed_scope_hashx3:s64:d361f0132ee1ab4ba8a89d5a6793d6f291b6bf8b413d51d5c91da2e47e24be66s18:fixed_scope_valuesx3:o4:{s28:fixed_scope_contract_versionx3:s25:LegacyFixedScopeValues.v1s13:scope_entriesx3:a8:[o3:{s15:canonical_valuex3:i3;s9:scope_keyx3:s10:PROJECT_IDs10:value_kindx3:s9:SCALAR_ID}o3:{s15:canonical_valuex3:s24:CASE-REAL-019@2026-09-08s9:scope_keyx3:s11:SNAPSHOT_IDs10:value_kindx3:s6:STRING}o3:{s15:canonical_valuex3:i12;s9:scope_keyx3:s19:EVIDENCE_PACKAGE_IDs10:value_kindx3:s9:SCALAR_ID}o3:{s15:canonical_valuex3:s64:fb24d2f074912415219397e7325007439644432cbfa6250b694137d1834900d3s9:scope_keyx3:s21:EXACT_DATABASE_SHA256s10:value_kindx3:s6:SHA256}o3:{s15:canonical_valuex3:i57;s9:scope_keyx3:s21:STRATEGY_CANDIDATE_IDs10:value_kindx3:s9:SCALAR_ID}o3:{s15:canonical_valuex3:s8:ACCEPTEDs9:scope_keyx3:s25:STRATEGY_CANDIDATE_STATUSs10:value_kindx3:s6:STRING}o3:{s15:canonical_valuex3:s13:CASE-REAL-019s9:scope_keyx3:s7:CASE_IDs10:value_kindx3:s6:STRING}o3:{s15:canonical_valuex3:i19;s9:scope_keyx3:s9:PROMPT_IDs10:value_kindx3:s9:SCALAR_ID}]s26:scope_key_contract_versionx3:s17:LegacyScopeKey.v1s16:scope_profile_idx3:s34:legacy_scope.execution_proposal.v1}s17:fixed_snapshot_idx3:s24:CASE-REAL-019@2026-09-08s33:legacy_projection_profile_versionx3:s40:legacy_stage_projection.single_prompt.v1s26:scope_key_contract_versionx3:s17:LegacyScopeKey.v1s16:scope_profile_idx3:s34:legacy_scope.execution_proposal.v1s20:selector_contract_idx3:s37:legacy_selector.execution_proposal.v1s14:source_membersx2;s10:stage_typex3:s18:EXECUTION_PROPOSAL}}
```

```text
source_ref_set_hash = 543fa710799ecc38c9382b3646643a6b8fddcd807fcd8e43cbe1d3f942b5a483
```

#### Projection Objective And Overall Completeness

Completeness roll-up is projection-objective-specific. Both fixed cases request
`STRATEGY_LINEAGE`, whose current-critical set is Root plus the 15 Stage types
through `STRATEGY_SYNTHESIS`; `EXECUTION_PROPOSAL` is displayed but is not an
ancestor of the fixed Strategy target.

The exact `STRATEGY_LINEAGE` roll-up is:

```text
fixed Manifest/database/Package/Run/Root-required object unreadable
-> UNAVAILABLE

else any current-critical Stage UNSAFE
-> UNSAFE

else any current-critical Stage UNAVAILABLE
-> UNAVAILABLE

else any Root/current-critical Stage PARTIAL
-> PARTIAL

else
-> COMPLETE
```

This objective rule replaces a context-free severity sort. A non-critical Stage
still reports its own completeness and blocking reason but cannot relabel an
upstream fixed target. A future Execution Proposal projection has a different
current-critical closure and contract version.

When overall is `UNSAFE`, Spike may display fixed known Root facts, safe/partial
Stage mappings, all ambiguous source refs, null missing fields and warnings. It
must output no authoritative current Strategy, READY/COMPLETE state, allowed
semantic action, selected historical winner, current Pointer or Stage selection.
`PARTIAL` may expose uniquely known refs and null fields with `missing_fields`,
but cannot claim full replayability. `UNAVAILABLE` names the exact unreadable
fixed object and never substitutes another row.

### 20.5 Read-only Spike Projection Contract

For every fixed Manifest target, Spike B outputs:

```text
projection identity and VIRTUAL_RUNTIME_PROJECTION marker;
virtual Context id;
EvidencePackage audit ref;
EvidencePackageRootProjection fields/ref/hash or explicit null;
Root manifest and context fingerprint/manifest hash or explicit null;
Context lineage completeness + missing/unsafe/source refs;
RuntimeStageProfile version and complete 16-node Stage graph;

for every Stage:
  stage_type and WHOLE_CONTEXT scope;
  selected virtual StageExecution ref or null;
  all plausible fixed source refs when selection is unsafe;
  input manifest refs/hash or null;
  output manifest refs/hash/count or null;
  lineage completeness;
  exact review binding or null;
  AuthoritativeReviewDecision or UNREVIEWED/REVIEW_CONFLICT/
    REVIEW_CONFLICT_INVALID_GRAPH/UNRESOLVED_LEGACY;
  compute outcome projection;
  current eligibility projection;
  blocking reasons[];

CurrentContextPointer projection or explicit unavailable/null;
ContextStageSelection projection for every Stage or explicit unavailable/null;
legacy warnings and prohibited-inference list.
```

Missing hashes are null, not empty strings or reconstructed values. A fixed
Manifest selects the Golden projection target; it does not prove that a
production CurrentContextPointer or ContextStageSelection historically existed.

### 20.6 Virtual Projection Identity

The read-only Spike uses deterministic, namespaced projection-local identities:

```text
virtual Context id
= virtual-context:<SHA-256(canonical {
    identity_contract_version = virtual_runtime_identity.v1,
    manifest_canonicalization_version,
    manifest_shape_semantics = OBJECT_WITH_NESTED_MANIFESTS,
    snapshot_schema_version,
    snapshot_id,
    exact_database_sha256,
    legacy_projection_profile_version,
    root_projection_hash_or_exact_completeness_marker
  })>

virtual Stage id, only for one uniquely mapped source set
= virtual-stage:<SHA-256(canonical {
    identity_contract_version = virtual_runtime_identity.v1,
    manifest_canonicalization_version,
    manifest_shape_semantics = OBJECT_WITH_NESTED_MANIFESTS,
    virtual_context_id,
    stage_type,
    runtime_stage_contract_version,
    legacy_projection_profile_version,
    source_ref_set_hash
  })>
```

If source mapping is ambiguous, `selected StageExecution ref = null`; candidate
source refs are listed and no virtual winner ID is minted. For a PARTIAL but
unique mapping, missing semantic output hashes remain null while the virtual ID
is stable from fixed source refs. The exact markers are
`ROOT_PARTIAL`, `ROOT_UNSAFE` and `ROOT_UNAVAILABLE`; they are not empty strings.

The canonical function above is `semantic_manifest_canonicalization.v1`.
Therefore the same fixed case/database/profile/source set produces the same
virtual identity across requests. Every virtual identity uses the `virtual:`
namespace, is marked `VIRTUAL_RUNTIME_PROJECTION`, and may be used only for display,
comparison and Golden validation. Strategy, Review, Action, Experiment, Pointer,
cache or production APIs are forbidden consumers.

### 20.7 Fixed #19/#40 Projection Expectations

Both cases use only their immutable snapshot Manifest and exact database file
identity. The fixed Candidate is a projection target, not proof of historical
Runtime Stage selection.

`CASE-REAL-019.missing_immutable_inputs = []` belongs to the pre-Runtime snapshot
schema and only states that its then-required Golden Strategy fields were
captured. It does not assert the later `runtime_root_profile.v1` or 16 Stage
manifests exist. Runtime completeness is therefore evaluated by this contract,
not inferred from that empty legacy list.

```yaml
CASE-REAL-019:
  root_projection: PARTIAL
  evidence_package_root_projection_hash: null
  context_fingerprint: null
  context_manifest_hash: null
  root_reason:
    - Package/Run IDs are fixed, but no historical runtime_root_profile.v1
      immutable per-Run/Reference/Retrieval snapshot manifests were persisted.
  overall_context_projection: UNSAFE
  unsafe_reason:
    - Package 12 has multiple same-scope completed AnswerEvidenceShadowRuns and
      multiple historical Candidates without persisted dependency/selection edges.
  strategy_projection: PARTIAL
  strategy_source_ref: candidate:57
  strategy_virtual_stage_ref: permitted, marked VIRTUAL_RUNTIME_PROJECTION
  strategy_selected_by_context_stage_selection: false
  strategy_authoritative_review: UNRESOLVED_LEGACY
  strategy_known:
    - accepted status and persisted PR4 input/output hashes from the fixed Manifest
  strategy_missing:
    - StageExecution identity, exact upstream dependency manifest,
      ContextStageSelection and immutable append-only review target
  current_context_pointer: null
  current_context_pointer_completeness: UNAVAILABLE
  context_stage_selections: all null
  latest_substitution: FORBIDDEN

CASE-REAL-040:
  root_projection: PARTIAL
  evidence_package_root_projection_hash: null
  context_fingerprint: null
  context_manifest_hash: null
  root_reason:
    - Package/Run IDs are fixed, but no historical runtime_root_profile.v1
      immutable per-Run/Reference/Retrieval snapshot manifests were persisted.
  overall_context_projection: UNSAFE
  unsafe_reason:
    - Package 15 has multiple interrupted/completed AnswerEvidenceShadowRuns and
      multiple historical Candidates without persisted dependency/selection edges.
  strategy_projection: PARTIAL
  strategy_source_ref: candidate:50
  strategy_virtual_stage_ref: permitted, marked VIRTUAL_RUNTIME_PROJECTION
  strategy_selected_by_context_stage_selection: false
  strategy_authoritative_review: UNRESOLVED_LEGACY
  strategy_known:
    - PENDING_REVIEW status and fixed Package/Run association
  strategy_missing:
    - candidate input contract hash, PR4 synthesis contract/version/output hash,
      StageExecution identity, exact upstream dependency manifest,
      ContextStageSelection and immutable append-only review target
  current_context_pointer: null
  current_context_pointer_completeness: UNAVAILABLE
  context_stage_selections: all null
  latest_substitution: FORBIDDEN
```

The Stage-by-Stage expectations below are part of
`legacy_stage_projection.single_prompt.v1`, not illustrative examples.

#### CASE-REAL-019 Stage Expectations

| Stage | Fixed legacy mapping | Expected | Allowed projection | Forbidden interpretation |
| --- | --- | --- | --- | --- |
| `RUN_METRICS` | `legacy_selector.run_metrics.v1` over Package 12 and R | PARTIAL | fixed metric path slices plus admitted row refs; independent manifest/hash null | formal Runtime metric output or recomputation |
| `ANSWER_SEMANTIC` | `legacy_selector.answer_semantic.v1` | UNSAFE | all 99 Event refs and all 13 PromptAnalysisRun envelopes | choose or union PromptAnalysisRuns as one legal execution |
| `PRODUCT_TRUTH_PROJECTION` | `legacy_selector.product_truth.v1` over Candidate 57 effective document | UNSAFE | exact truth-path slices, hint ids/rows, and null formal bindings/versions | text/label selection, all-project truth scan or formal BOUND projection |
| `BINDING` | `legacy_selector.binding.v1` | UNSAFE | all 13 exact-scope S envelopes and child refs; 12 completed + 1 running | select one S envelope by status/time/id |
| `SOURCE_QUALIFICATION` | `legacy_selector.source_qualification.v1` | UNSAFE | all O/D/Q refs admitted by exact canonical tuple and FK predicates | mutable SourceQuality as historical qualification output |
| `SOURCE_FETCH` | `legacy_selector.source_fetch.v1` | UNSAFE | all D refs/hashes as legacy evidence only | current clean text as Package-time immutable content version |
| `SEGMENTATION` | `legacy_selector.segmentation.v1` | UNSAFE | exact `content_blocks_json:$` slice for every D row | immutable historical Passage manifest |
| `SOURCE_CLAIM` | `legacy_selector.source_claim.v1` | UNSAFE | all ledger/claim refs admitted by the exact D predicates and stored hashes | one Package-scoped Claim Stage or current ledger HIT as selection |
| `ALIGNMENT_CANDIDATE_BUILD` | `legacy_selector.alignment_candidates.v1` | UNSAFE | exact ShadowResult hint refs; null candidate output | reconstruct candidates from judged Alignment rows |
| `EVIDENCE_ALIGNMENT` | `legacy_selector.evidence_alignment.v1` | UNSAFE | 32,997 fixed-run Alignment refs plus exact admitted shadow/materialization refs | one candidate-scoped immutable Alignment Stage or formal review |
| `BENCHMARK` | `legacy_selector.benchmark.v1` over Candidate 57 effective document | PARTIAL | exact benchmark path slices with null independent manifest/dependencies | current Benchmark recomputation or executable Benchmark Stage |
| `GAP` | `legacy_selector.gap.v1` over Candidate 57 effective document | PARTIAL | exact gap path slices and exact `step_key='gap'` audit ref | WorkflowConfirmation as immutable authoritative Gap review |
| `CHANNEL_EVIDENCE` | `legacy_selector.channel_evidence.v1` over Candidate 57 effective document | PARTIAL | exact channel-evidence path slices and missing independent hash | rerun aggregation or infer channel effectiveness |
| `CHANNEL_RESOLUTION` | `legacy_selector.channel_resolution.v1` over Candidate 57 effective document | PARTIAL | exact resolver path slices and persisted version states | Role mutation, resolver winner fallback or Benchmark-to-channel inference |
| `STRATEGY_SYNTHESIS` | `legacy_selector.strategy_synthesis.v1` over Candidate 57 effective document | PARTIAL | accepted legacy status and exact strategy path/hash states | selected/current/authoritative Runtime Strategy |
| `EXECUTION_PROPOSAL` | `legacy_selector.execution_proposal.v1` empty source set | UNAVAILABLE | explicit null, missing proposal ref class and Step 8 warning | query PR5 response, Action or Experiment as substitute |

```text
CASE-REAL-019 Stage counts:
COMPLETE = 0
PARTIAL = 6
UNSAFE = 9
UNAVAILABLE = 1

STRATEGY_LINEAGE overall = UNSAFE
reason = at least one current-critical Stage is UNSAFE
```

#### CASE-REAL-040 Stage Expectations

| Stage | Fixed legacy mapping | Expected | Allowed projection | Forbidden interpretation |
| --- | --- | --- | --- | --- |
| `RUN_METRICS` | `legacy_selector.run_metrics.v1` over Package 15 and R | PARTIAL | fixed metric path slices plus admitted row refs; independent manifest/hash null | formal Runtime metric output or recomputation |
| `ANSWER_SEMANTIC` | `legacy_selector.answer_semantic.v1` | PARTIAL | all 24 Event refs and the one PromptAnalysisRun envelope | fully replayable Answer Stage or mutable review as immutable review |
| `PRODUCT_TRUTH_PROJECTION` | `legacy_selector.product_truth.v1` over Candidate 50 structured document | UNSAFE | exact truth-path slices, hint ids/rows, and null formal binding | heuristic/text selection or project-wide truth projection |
| `BINDING` | `legacy_selector.binding.v1` | UNSAFE | all 7 exact-scope S envelopes and child refs; 2 completed + 1 warning + 4 interrupted | select one S envelope by status/time/id |
| `SOURCE_QUALIFICATION` | `legacy_selector.source_qualification.v1` | UNSAFE | all O/D/Q refs admitted by exact canonical tuple and FK predicates | mutable SourceQuality as historical Stage truth |
| `SOURCE_FETCH` | `legacy_selector.source_fetch.v1` | UNSAFE | all D refs/hashes as legacy evidence only | immutable Package-time content version |
| `SEGMENTATION` | `legacy_selector.segmentation.v1` | UNSAFE | exact `content_blocks_json:$` slice for every D row | immutable historical Passage manifest |
| `SOURCE_CLAIM` | `legacy_selector.source_claim.v1` | UNSAFE | all ledger/claim refs admitted by the exact D predicates and stored hashes | selected Package-scoped Claim Stage |
| `ALIGNMENT_CANDIDATE_BUILD` | `legacy_selector.alignment_candidates.v1` | UNSAFE | exact ShadowResult hint refs; null candidate output | infer omitted pairs or reconstruct candidates |
| `EVIDENCE_ALIGNMENT` | `legacy_selector.evidence_alignment.v1` | UNSAFE | 660 fixed-run Alignment refs plus exact admitted shadow/materialization refs | one immutable Alignment Stage or formal authoritative review |
| `BENCHMARK` | `legacy_selector.benchmark.v1` over Candidate 50 structured document | PARTIAL | exact benchmark path states and null independent lineage | current Benchmark recomputation |
| `GAP` | `legacy_selector.gap.v1` over Candidate 50 structured document | PARTIAL | exact gap path states; no `step_key='gap'` row | mutable Gap confirmation as authoritative |
| `CHANNEL_EVIDENCE` | `legacy_selector.channel_evidence.v1` over Candidate 50 structured document | PARTIAL | exact channel-evidence path slices and missing independent hash | rerun aggregation or promote Benchmark platform automatically |
| `CHANNEL_RESOLUTION` | `legacy_selector.channel_resolution.v1` over Candidate 50 structured document | PARTIAL | exact resolver path slices; absent PR4 fields remain absent | rewrite Candidate 50 into v1.1/PR4 result |
| `STRATEGY_SYNTHESIS` | `legacy_selector.strategy_synthesis.v1` over Candidate 50 structured document | PARTIAL | PENDING_REVIEW, Package association and exact absent PR4 path/hash states | selected/current Strategy or Candidate 57 substitution |
| `EXECUTION_PROPOSAL` | `legacy_selector.execution_proposal.v1` empty source set | UNAVAILABLE | explicit null proposal ref class and Step 8 locked warning | query current PR5/Action/Experiment as substitute |

```text
CASE-REAL-040 Stage counts:
COMPLETE = 0
PARTIAL = 7
UNSAFE = 8
UNAVAILABLE = 1

STRATEGY_LINEAGE overall = UNSAFE
reason = at least one current-critical Stage is UNSAFE
```

If the exact database file, Package, Candidate or any fixed Run required by a
Manifest is unreadable, that case is `UNAVAILABLE`, not UNSAFE/PARTIAL. The
expected UNSAFE roll-up above can become COMPLETE/PARTIAL only under a future
new fixed Manifest or proven immutable mapping, never because a latest row was
chosen.

### 20.8 Step 8 Boundary

This RFC defines only current authority, Context/Stage binding and legacy path
isolation for Step 8. It does not decide:

```text
ExecutionProposal persistence;
NewAssetSpec -> ManagedAsset lifecycle;
Action cardinality/identity;
Experiment cardinality/identity;
release/retest lifecycle.
```

Those require `RFC-STEP8-LIFECYCLE-001`. Existing snapshot semantics are not
discarded or silently redefined.

## 21. Audit Trail And Privileged Actions

The runtime audit trail must identify:

```text
Context creator and reason;
Stage start/retry/resume/recompute trigger;
every StageAttempt owner/outcome/error;
review actor, target manifest/hash and superseded review;
current Context and Stage-selection changes;
dependency invalidation and reactivation;
legacy compatibility classification;
cache/materialization compatibility decision.
```

The following are privileged semantic actions even before full RBAC design:

```text
create a Context;
change production CurrentContextPointer;
retry/recompute a Stage;
confirm/reject/reopen/correct review;
invalidate/reactivate Context or Stage eligibility;
select a current Strategy or execution output.
```

Actor identity, authorization policy, IP/session retention and role assignment
are implementation/security design concerns, but anonymous semantic mutation is
not compliant with the proposed contract.

## 22. Rollback

Rollback never deletes a new output or rewrites history.

Candidate mechanisms are:

```text
audited CurrentContextPointer switch;
audited current Stage-selection switch;
Context/stage eligibility invalidation;
explicit reactivation of a still-compatible historical Context/output;
new superseding Context or StageExecution.
```

Reactivation requires compatibility validation against the target workflow
track and cannot be inferred from old success status alone.

## 23. Storage Growth

Append-only lineage grows through:

```text
Contexts;
StageExecutions;
StageAttempts;
output/partition manifests;
ReviewDecisions;
pointer/selection history;
audit/invalidation events.
```

Future implementation design must define retention and archive policy without
breaking immutable references. This RFC does not perform capacity engineering
or authorize deletion.

## 24. UNKNOWN And Failure Semantics

The runtime projection must distinguish:

```text
not executed;
successful zero output;
input unavailable;
partial/incomplete output;
retryable attempt failure;
terminal logical failure;
blocked by dependency/review;
historical output no longer current-eligible;
legacy lineage not safely reconstructable.
```

Unknown or unavailable lineage cannot be upgraded through latest fallback,
row existence, human review on a different output, or current configuration.

The final state enum is deferred. These distinctions are required semantics.

## 25. Contract Diff

```text
old contract/version:
  no unified Runtime Contract; SC-HISTORY/SC-SCOPE and stage boundaries are observed separately

new candidate contract/version:
  SC-RUNTIME-001@0.1.0, proposed only

allowed inference diff:
  explicit Context and selected Stage lineage may determine current workflow state
  exact dependency edges may determine downstream invalidation

forbidden inference diff:
  latest row cannot determine current
  mutable row id cannot prove reviewed output
  cache identity cannot substitute for business lineage
  omitted candidate cannot be treated as judged negative
  successful output cannot be overwritten by recompute

unknown behavior diff:
  incomplete, unsafe legacy and unavailable authority remain explicit

step boundary diff:
  no Product Step order change
  runtime stages become explicit dependencies beneath existing Steps
```

## 26. Golden Runtime Cases

### RT-SYN-001 Same Fingerprint, Independent Contexts

```yaml
given:
  root_manifest_a: X
  root_manifest_b: X
  independent_start_events: 2
expected:
  context_ids_are_distinct: true
  fingerprints_are_equal: true
  semantic_cache_reuse_allowed_by_its_own_contract: true
forbidden:
  - merging review or pointer history
  - selecting an old Context by fingerprint alone
```

### RT-SYN-002 Successful Zero Output

```yaml
given:
  stage_input_manifest: fixed
  produced_members: []
expected:
  output_count: 0
  output_manifest: present
  output_set_hash: deterministic
  logical_completion: successful
forbidden:
  - interpreting no member rows as not executed
```

### RT-SYN-003 Review Moving Set

```yaml
given:
  completed_partition_members: [A, B]
  completed_partition_hash: H1
  later_alignment: C
expected:
  review_target_members: [A, B]
  C_requires_new_partition_or_execution: true
forbidden:
  - adding C to the reviewed partition
  - claiming the review covered current all SUPPORTS
```

### RT-SYN-004 Candidate Omission

```yaml
given:
  considered_pair: P
  candidate_policy_result: omitted
expected:
  omission_reason: present
  judge_verdict: absent
forbidden:
  - relation: NO_SUPPORT
```

### RT-SYN-005 Dependency Invalidation

```yaml
given:
  ProductTruth_A_v1_consumers: [Gap_A, Strategy_A]
  ProductTruth_B_v1_consumers: [Gap_B]
  superseded_input: ProductTruth_A_v1
expected:
  loses_current_eligibility: [Gap_A, Strategy_A]
  remains_eligible: [Gap_B]
forbidden:
  - global downstream reset without consumed edge
  - deletion of historical outputs
```

### RT-SYN-006 Review Concurrency

```yaml
given:
  state_version: 7
  reviewer_A_expected_version: 7
  reviewer_B_expected_version: 7
when:
  reviewer_A_commits_first: true
expected:
  reviewer_B_write: conflict
  previous_review_history: retained
forbidden:
  - silent last-write-wins
```

### RT-SYN-007 Root-safe Package Projection

```yaml
given:
  package_root_fields: fixed acquisition Runs/References/Retrievals
  package_payload_stage_fields: SourceDocument/Alignment/Benchmark/Gap
expected:
  root_projection_contains: package_root_fields
  root_projection_excludes: package_payload_stage_fields
  entire_package_payload_hashed: false
forbidden:
  - requiring a downstream Stage output to create its own Context
  - treating current Package API prompt text as historical Prompt snapshot
```

### RT-SYN-008 Authoritative Review Chain

```yaml
given:
  exact_review_target: StageExecution S output partition P
  review_1: CONFIRM
  review_2: REOPEN supersedes review_1
  review_3: CONFIRM supersedes review_2
expected:
  authoritative_review: review_3
  retained_history: [review_1, review_2, review_3]
forbidden:
  - choosing by created time without a supersession chain
  - applying the decision to another output partition
boundary:
  two_non_superseded_leaf_decisions: REVIEW_CONFLICT
```

### RT-SYN-009 Direct Invalidation And Propagation Stop

```yaml
given:
  execution_A: SUCCEEDED, directly INVALIDATED
  execution_B1_consumes: A
  execution_B2_consumes: A2
  execution_C_consumes: B2
expected:
  execution_A_compute_outcome: SUCCEEDED
  execution_A_current_eligibility: INVALIDATED
  execution_B1_current_eligibility: STALE
  execution_B2_current_eligibility: ELIGIBLE
  execution_C_current_eligibility: ELIGIBLE
forbidden:
  - relabeling A as FAILED
  - propagating by stage type from B1 through B2 to C
```

### RT-SYN-010 Legacy Completeness

```yaml
given:
  fixed_manifest_package: present
  fixed_manifest_candidate: present
  candidate_input_hash: null
  multiple_plausible_upstream_shadow_runs: true
expected:
  candidate_stage_completeness: PARTIAL
  candidate_input_hash: null
  overall_context_projection: UNSAFE
  selected_upstream_stage: null
  unsafe_reasons: non_empty
forbidden:
  - computing the missing hash with current code
  - selecting latest completed ShadowRun
```

### RT-SYN-011 Canonical Manifest Identity

```yaml
given:
  manifest_contract: reference_observation_root.v1
  canonicalization: semantic_manifest_canonicalization.v1
  members_A: [reference_2, reference_1, duplicate_of_reference_1]
  members_B: [reference_1, reference_2]
  duplicate_payloads_identical: true
expected:
  hash_A_equals_hash_B: true
  db_return_order_irrelevant: true
boundary:
  same_identity_different_payload: MANIFEST_IDENTITY_CONFLICT
  FIELD_ABSENT_equals_FIELD_PRESENT_NULL: false
forbidden:
  - hash(str(row_ids))
  - using database order as semantic order
```

### RT-SYN-012 Fenced Attempt Completion

```yaml
given:
  StageExecution: S20
  attempt_A_generation: 4
  attempt_A_lease_expired: true
  attempt_B_generation: 5
when:
  attempt_B_publishes_output_hash: X
  attempt_A_late_output_hash: Y
expected:
  StageExecution_output_hash: X
  attempt_A_result: LATE_OR_SUPERSEDED_ATTEMPT
  authoritative_success_count: 1
forbidden:
  - replacing X with Y
  - treating Y as a competing Stage output
```

### RT-SYN-013 Review Linear Chain

```yaml
given:
  exact_review_target: T
  review_1: CONFIRM
  review_2: REOPEN supersedes review_1
expected:
  authoritative_review: review_2
  review_state: REOPENED
boundary:
  concurrent_review_3_and_review_4_supersede_review_2: one commits, one conflicts
  cross_contract_supersede: INVALID
  cyclic_import: REVIEW_CONFLICT_INVALID_GRAPH
forbidden:
  - latest-created review wins
  - mutating review_1
```

### RT-SYN-014 Product Truth Unresolved Binding

```yaml
given:
  Reason_manifest: [R1, R2]
  formal_bindings:
    R1: [ProductTruth_3_UNKNOWN_v2]
    R2: []
expected:
  projection_members:
    - R1 -> ProductTruth_3_UNKNOWN_v2, BOUND
    - R2 -> null, UNRESOLVED
  output_count: 2
forbidden:
  - omitting R2
  - scanning project Product Truth by label similarity
  - dropping UNKNOWN because it is not TRUE
```

### RT-SYN-015 Canonical Bytes Cross-implementation

```yaml
given:
  manifest_contract: canonical_fixture.v1
  object_A_source_order: [z, a]
  object_B_source_order: [a, z]
  a: FIELD_PRESENT_NULL
  z: VALUE("line1\r\nline2")
expected:
  canonical_bytes_A_equals_B: true
  key_order: [a, z]
  line_endings_preserved: true
  hash_algorithm: SHA-256
boundary:
  z_with_LF_only_has_different_hash: true
  a_FIELD_ABSENT_has_different_hash: true
forbidden:
  - JSON library default serialization
  - newline or Unicode normalization
```

### RT-SYN-016 Product Truth Binding Authority

```yaml
given:
  Reason: R1
  current_mutable_truth_row: PT1
  Candidate_hint_product_truth_ids: [PT1]
  formal_reason_product_truth_binding_versions: []
expected:
  projection_member: R1 -> null, UNRESOLVED
  Candidate_hint_authority: NONE
when:
  Step_3_human_binding_confirmation_creates: B1(R1, PT1_fact_v2)
expected_after_new_stage_execution:
  projection_member: R1 -> PT1_fact_v2, BOUND
forbidden:
  - treating Candidate hint or capability text match as B1
  - mutating the old unresolved projection
```

### CASE-REAL-019 Runtime Expectation

Uses only `CASE-REAL-019.manifest.json` fixed ids and database identity.

```text
fixed Package = 12@v8
fixed Candidate = 57
fixed Runs = manifest 40 ids
legacy selectors = exact legacy_selector.*.v1 registry
Candidate JSON document = Candidate 57 effective_payload_json only
legacy source_ref_set_hash = semantic_manifest_canonicalization.v1
latest substitution = FORBIDDEN
root projection = PARTIAL
formal root projection hash/context fingerprint/context manifest hash = null
overall Context projection = UNSAFE
Strategy projection = PARTIAL, fixed Candidate 57 only
Strategy virtual Stage may be shown but is not selected and has no authoritative Runtime review
selected upstream Stage refs = null where multiple same-scope historical rows exist
historical mutable SourceDocument/Product Truth/Alignment consumption = missing/unsafe fields with source refs
CurrentContextPointer projection = null/unavailable, not inferred
PR5-B readiness -> Action/Experiment inference = FORBIDDEN
```

### CASE-REAL-040 Runtime Expectation

Uses only `CASE-REAL-040.manifest.json` fixed ids and database identity.

```text
fixed Package = 15@v2
fixed Candidate = 50
fixed Runs = manifest 6 ids
legacy selectors = exact legacy_selector.*.v1 registry
Candidate JSON document = Candidate 50 structured_payload_json only
legacy source_ref_set_hash = semantic_manifest_canonicalization.v1
missing PR4 hashes = remain null
root projection = PARTIAL
formal root projection hash/context fingerprint/context manifest hash = null
overall Context projection = UNSAFE
Strategy projection = PARTIAL, fixed Candidate 50 only
Strategy virtual Stage may be shown but is not selected and has no authoritative Runtime review
selected upstream Stage refs = null where multiple same-scope historical rows exist
CurrentContextPointer projection = null/unavailable, not inferred
#19 or historical accepted Candidate fallback = FORBIDDEN
Step 8 current state = LOCKED in fixed observed snapshot
```

## 27. Counterexamples

### Counterexample A: Latest Candidate Has A Newer Timestamp

```text
Given fixed production CurrentContextPointer C1
And C1 selects Strategy StageExecution S1 containing Candidate 57
And historical/legacy Candidate 99 has a later timestamp
When current Strategy is requested
Expected Candidate 57
Forbidden Candidate 99 by latest fallback
```

### Counterexample B: Reviewed Alignment Set Grows

```text
Given reviewed immutable partition P1 contains 42 members with hash H1
And a background execution later produces 5 additional SUPPORTS
When review state is projected
Expected P1 remains 42 reviewed members and new members remain separately pending
Forbidden 47/47 confirmed under the old review decision
```

### Counterexample C: Refetch Changes Source Body

```text
Given SourceFetch execution F1 produced content hash A and Claim execution C1 consumed A
And refetch execution F2 produces content hash B
When current descendants are evaluated
Expected C1 remains historical and loses current eligibility; recompute creates C2
Forbidden rewriting F1/C1 or letting C1 silently read body B
```

### Counterexample D: Retry After Transient Failure

```text
Given StageExecution S has fixed input hash I
And Attempt 1 failed retryably
When retried with the same semantic input
Expected Attempt 2 belongs to S and Attempt 1 remains auditable
Forbidden creating an unrelated semantic execution or erasing Attempt 1
```

### Counterexample E: Stage Contract Changes

```text
Given successful StageExecution S1 contract v1 output A
And contract v2 is selected under the same Context
When recomputed
Expected new StageExecution S2 contract v2 output B
Forbidden overwriting S1 or forcing NEW_CONTEXT solely because a Stage algorithm changed
```

### Counterexample F: Full Package Payload Contains Derived State

```text
Given Package P stores acquisition fields and a report payload containing current Gap data
And Gap is a Stage output under RuntimeStageProfile v1
When Context C is created from P
Expected only EvidencePackageRootProjection enters C's Root
Forbidden hashing or consuming P's Gap/report derivation as Root truth
```

### Counterexample G: Recompute Does Not Promote Itself

```text
Given StageExecution S1 is selected
And recompute produces eligible successful S2
When no ContextStageSelection transition is committed
Expected S1 remains selected
Forbidden selecting S2 by success, row id or created time
```

### Counterexample H: Human Edit Is Not Review

```text
Given immutable Evidence relation R1 says NO_SUPPORT
When a human changes relation content to SUPPORTS
Expected a new corrected Evidence output R2 and a separate ReviewDecision for R2
Forbidden mutating R1 or encoding SUPPORTS only as ReviewDecision content
```

### Counterexample I: Legacy Cache Missing Model Revision

```text
Given cache C has matching input/prompt hashes but no model revision
When a Formal Runtime Stage checks reuse
Expected LEGACY_COMPATIBILITY_UNKNOWN and cache miss
Forbidden transparent HIT based on partial signature or current model config
```

## 28. Spike Options And Recommendation

### Spike A: Storage-Only Model

Useful for schema feasibility, but cannot prove that the proposed identities
express #19/#40 or current workflow decisions. Not recommended first.

### Spike B: #19/#40 Read-only Runtime Projection

Recommended after Definition Review and Product Owner approval.

It must project without writes:

```text
VIRTUAL_RUNTIME_PROJECTION identity;
EvidencePackageRootProjection and Context root manifest/fingerprint;
Context lineage completeness/missing/unsafe/source refs;
the exact 16-node RuntimeStageProfile v1 graph;
per-Stage virtual selection/input/output/completeness/review/eligibility/blocking;
selected/omitted Candidate manifests;
review target bindings and AuthoritativeReviewDecision/conflict projection;
CurrentContextPointer and ContextStageSelection projection or explicit null;
dependency stale projection;
cache compatibility classification;
legacy COMPLETE/PARTIAL/UNSAFE/UNAVAILABLE classification.
```

It must use fixed Manifest ids, never latest substitution. It does not replace
the executor, migrate data, write a Candidate or affect frontend state.

### Spike C: Full Stage Executor

Rejected as the first Spike. It combines storage, lease, execution, migration
and cutover before identity expressiveness has been validated.

## 29. Implementation Plan After Approval

The Definition is Frozen and the separately authorized read-only Spike is
recorded in `docs/semantics/spikes/RFC-RUNTIME-001.read-only-projection-spike.md`.
The implementation sequence remains:

1. Run Independent Runtime Definition Review.
2. Obtain Product Owner Definition Freeze approval.
3. Execute only Spike B as a read-only projection.
4. Review #19/#40 projection completeness and unresolved lineage.
5. Produce a separate storage and migration design.
6. Implement Shadow/runtime recording without frontend authority cutover.
7. Validate Golden Runtime cases, concurrency and legacy isolation.
8. Request independent production cutover approval.

`RT-FIX-001` and `RT-FIX-002` are separate direct-fix candidates and are not
implemented by, nor blockers to definition review of, this RFC.

## 30. Non-Goals

- No production code, schema, migration or database changes.
- No production Runtime implementation in this RFC; the separately authorized
  read-only Projection Spike remains isolated from production consumers.
- No Product Step 1-8 reorder and no Step 9.
- No Evidence, Benchmark, Gap, Resolver, Strategy or PR5 semantic change.
- No Step 8 asset/Action/Experiment lifecycle decision.
- No generic job platform, queue, Redis/Celery or database-technology decision.
- No automatic historical backfill.
- No frontend cutover.

## 31. Risks And Conflicts

- `SEM-CONFLICT-001` Foundation/Citation Split remains open and independent.
- `SEM-CONFLICT-002` Step 8 asset lifecycle remains open and blocks PR5-C.
- Current Domain Model language describes some objects as immutable/versioned
  aspirations while Phase 0 proves the current rows are mutable. Until this RFC
  is approved and implemented, the Runtime Semantic Map is authoritative for
  observed runtime behavior; neither source is a production cutover approval.
- A generic Stage model can become over-broad. Spike B must prove the minimum
  object set before storage design.
- Complete immutable manifests increase storage. Retention cannot break audit
  references.

## 32. Rollback Boundary

This RFC is documentation-only and has no production behavior to roll back.
Future production rollback must switch explicit pointers/selections to a
compatible historical implementation lineage. It cannot delete Contexts,
StageExecutions, Attempts, reviews or approved semantic definitions.

## 33. Approval Gates

1. **Definition Review:** independent Runtime Reviewer evaluates object
   identity, Root/Stage boundary, review manifest, current authority and
   invalidation.
2. **Definition Freeze:** Product Owner separately approves the proposed
   semantics. Only then may `semantic_maturity` become FROZEN.
3. **Read-only Spike authorization:** approval permits Spike B only; it does not
   authorize schema or production code.
4. **Implementation authorization:** requires accepted Spike evidence and a
   separate implementation scope.
5. **Production Cutover:** requires independent approval after Shadow/replay,
   migration and rollback evidence.

## 34. Definition Review Gate Answers

### Gate A: Root / Stage Boundary

```text
root inputs = immutable Prompt + Acquisition/Run outputs + Package projection + root profile
Package projection = EvidencePackageRootProjection only; entire package payload excluded
stage inputs = exact upstream outputs + reusable object versions + Stage config
circular dependency = NONE
```

### Gate B: Execution / Attempt Boundary

```text
StageExecution = fixed logical computation identity
StageAttempt = append-only physical execution attempt
retry = same Execution + new Attempt
recompute = new Execution
attempt authority = monotonic fenced generation
late/superseded Attempt publication = FORBIDDEN
authoritative successful completion per StageExecution = exactly one
```

### Gate C: Review Binding

```text
review target = immutable output/partition manifest
member refs/count/hash = REQUIRED
partition support = YES
review history = append-only
review chain = exact-target append-only linear supersession
authoritative review = unique terminal decision; 0 pending; >1 or invalid graph conflict
human edit = new output lineage, never ReviewDecision mutation
```

### Gate D: Current Authority

```text
pointer identity = project + prompt + workflow track
workflow tracks = production/shadow/golden/legacy separation required
optimistic state version = REQUIRED
explicit current Stage selection = REQUIRED
recompute automatic promotion = FORBIDDEN
latest fallback allowed = NO
```

### Gate E: Dependency Invalidation

```text
dependency-based = YES
direct INVALIDATED event is distinct from propagated STALE
propagation follows exact consumed edges and stops at replacement branches
historical outputs immutable = YES
global reset = FORBIDDEN DEFAULT
```

## 35. RFC Summary

### Root Vs Stage

```text
root inputs = EvidencePackageRootProjection available after Acquisition Root freeze
root membership = intrinsic acquisition lineage only
downstream-driven Root promotion = forbidden
entire EvidencePackage payload in Root = NO
manifest canonicalization = semantic_manifest_canonicalization.v1
stage inputs = progressively consumed immutable refs/hashes and versioned config
circular dependency = NONE
```

### Execution Model

```text
StageExecution = semantic computation identity
StageAttempt = physical attempt history
retry = same StageExecution, new Attempt
recompute = new StageExecution
attempt publish authority = monotonic fenced generation
successful completion = exactly one authoritative publication
```

### Review Manifest

```text
review target = immutable output set or completed partition
partition support = required
append-only review = required
supersession = one exact-target linear chain
authoritative terminal decision = exactly one or REVIEW_CONFLICT
edit/correction = new immutable output lineage
```

### Candidate Audit

```text
selected manifest = required
omitted manifest = required for considered pairs
omission reasons = required
```

### Current

```text
pointer identity = project + prompt + workflow track
ContextStageSelection = explicit, zero-or-one per Context + Stage type
recompute auto-promotion = forbidden
optimistic state version = required
latest fallback allowed = NO
```

### Invalidation

```text
dependency-based = YES
compute outcome and current eligibility = separate
STALE and INVALIDATED = separate
historical outputs immutable = YES
```

### Spike

```text
recommended = #19/#40 read-only Runtime Projection
profile = runtime_stage_profile.single_prompt.v1, 16 nodes
legacy profile = legacy_stage_projection.single_prompt.v1
virtual IDs = display/compare/Golden only
legacy result = explicit COMPLETE/PARTIAL/UNSAFE/UNAVAILABLE
authorization = READ_ONLY PROJECTION SPIKE ONLY
```

## 36. Review-001 Blocking Closure

```yaml
B1_ROOT_STAGE_LEAKAGE:
  status: CLOSED
  resolved_in_section: 7.5-7.9
  semantic_rule: Only EvidencePackageRootProjection may enter Root; the entire
    Package payload and every Stage-derived/current-mutable field are excluded.

B2_CONTEXT_FINGERPRINT_GAP:
  status: CLOSED
  resolved_in_section: 7.3-7.4
  semantic_rule: runtime_context_fingerprint.v1 has an exact canonical field set;
    lineage-only fields and workflow track are excluded, while context manifest
    integrity has a separate hash.

B3_MINIMUM_STAGE_DAG_GAP:
  status: CLOSED
  resolved_in_section: 9
  semantic_rule: runtime_stage_profile.single_prompt.v1 freezes exactly 16 Stage
    types, their Step owners, dependencies, input/output manifests, completion,
    review units, Source of Truth and consumers.

B4_CURRENT_REVIEW_SELECTION_GAP:
  status: CLOSED
  resolved_in_section: 12.5, 18.1-18.3
  semantic_rule: ContextStageSelection is explicit zero-or-one and recompute never
    auto-promotes; review authority is the unique terminal decision in one exact
    target's valid linear chain, with 0 pending and branch/invalid graph conflict.

B5_HUMAN_EDIT_LINEAGE_GAP:
  status: CLOSED
  resolved_in_section: 13, 15.2
  semantic_rule: ReviewDecision never changes output; every semantic edit creates
    a new immutable fact-value or named Stage output before separate review.

B6_INVALIDATION_REACTIVATION_GAP:
  status: CLOSED
  resolved_in_section: 14
  semantic_rule: Compute outcome is immutable; STALE is exact-edge propagation,
    INVALIDATED is a direct privileged validity event, and reactivation is a
    separate audited event requiring compatibility and explicit selection.

B7_CACHE_COMPATIBILITY_GAP:
  status: CLOSED
  resolved_in_section: 16
  semantic_rule: semantic_cache_compatibility_signature.v1 requires exact common
    and per-Stage fields including provider/model revision; mismatch or unknown
    is a miss, and context_id is excluded by default.

B8_LEGACY_LINEAGE_PROJECTION_GAP:
  status: CLOSED
  resolved_in_section: 20, 26
  semantic_rule: Spike output uses explicit COMPLETE/PARTIAL/UNSAFE/UNAVAILABLE,
    fixed null/missing/unsafe/source fields and non-production virtual IDs; #19
    and #40 expectations are fixed without latest fallback.
```

All Review-001 blocking items are CLOSED in Revision 002. This is the RFC
Author's closure claim, not an independent Definition Review or Product Owner
Freeze.

## 37. Review-002 Blocking Closure

```yaml
B1_ROOT_PROJECTION_SELECTION_LEAKAGE:
  status: CLOSED
  resolved_in_section: 7.3-7.5
  semantic_rule: Root membership is intrinsic to the fixed acquisition lineage;
    downstream consumption cannot promote a field, and RootProjection is an
    immutable snapshot rather than a current query recipe.

B2_DETERMINISTIC_MANIFEST_IDENTITY_GAP:
  status: CLOSED
  resolved_in_section: 7.3, 9.1, 20.4-20.6
  semantic_rule: semantic_manifest_canonicalization.v1 defines scalar,
    null/missing, set/order, duplicate and hash rules; Root, Stage, review and
    legacy source manifests declare exact member identities and bind versions.

B3_PRODUCT_TRUTH_PROJECTION_SELECTION_GAP:
  status: CLOSED
  resolved_in_section: 9.1 Product Truth Projection Selector, 15.2, 20.4
  semantic_rule: Projection consumes only formal Reason-to-ProductTruth bindings
    and exact fact-value versions; no binding emits UNRESOLVED, and FALSE/UNKNOWN
    remain explicit members.

B4_STAGE_ATTEMPT_COMPLETION_AUTHORITY_GAP:
  status: CLOSED
  resolved_in_section: 8.3, 8.7, 17
  semantic_rule: Initial claim/reclaim allocates a monotonic fencing generation;
    only the current generation may publish the one immutable successful
    StageExecution completion, and late attempts are audit-only.

B5_REVIEW_SUPERSESSION_CONTRACT_GAP:
  status: CLOSED
  resolved_in_section: 12.4-12.5
  semantic_rule: One exact immutable ReviewTarget has one append-only linear
    supersession chain; branches use optimistic conflict, cycles/cross-target
    edges are invalid, and review contract versions are separate lineages.

B6_LEGACY_STAGE_PROJECTION_GAP:
  status: CLOSED
  resolved_in_section: 20.4-20.7
  semantic_rule: legacy_stage_projection.single_prompt.v1 freezes selectors,
    source identities, review risks, completeness rules, virtual identity and
    16 Stage expectations for both fixed cases without latest substitution.
```

The entries above preserve the Revision 002 Author claim. Independent Review
003 reopened B2, B3 and B6; their Revision 003 closure is recorded below.

## 38. Review-003 Blocking Closure

```yaml
B2_DETERMINISTIC_MANIFEST_IDENTITY_GAP:
  status: CLOSED
  resolved_in_section: 7.3-7.5, 9.1, 20.4-20.6
  semantic_rule: semantic_manifest_canonical_bytes.v1 freezes exact UTF-8 byte
    grammar, field-state tags, scalar representations, collection ordering,
    duplicate conflict, hash envelope and SHA-256. All 16 Stage output member
    identities now use formal fields, refs, hashes, enums or ordinals under an
    exact owning Stage Contract; target URLs use exact_utf8 identity v1.

B3_PRODUCT_TRUTH_BINDING_SOURCE_GAP:
  status: CLOSED
  resolved_in_section: 9.1 Product Truth Projection Selector, 15.2, 20.4
  semantic_rule: Current behavior is honestly classified as heuristic temporary
    derivation, not formal binding. reason_product_truth_binding.v1 is explicitly
    a NOT_IMPLEMENTED Candidate reusable-input Contract produced only by Step 3
    human binding confirmation; PRODUCT_TRUTH_PROJECTION is its sole Runtime
    projection producer and downstream consumers cannot rematch.

B6_LEGACY_STAGE_PROJECTION_GAP:
  status: CLOSED
  resolved_in_section: 20.4-20.7
  semantic_rule: The legacy profile now defines exact fixed symbols, case-specific
    Candidate JSON columns, JSONPath sets, 16 mechanical selector contracts,
    row/join/set predicates, zero/multiple-row behavior, source member schema and
    source_ref_set_hash payload. #19/#40 tables reference those selectors and no
    historical winner fallback exists.
```

All three Independent Review 003 blockers are CLOSED by the RFC Author in
Revision 003. This is an Author closure claim, not Independent Review 004,
Definition Freeze, Spike authorization, implementation authorization or
production cutover.

## 39. Review-004 Blocking Closure

```yaml
B2_DETERMINISTIC_MANIFEST_IDENTITY_GAP:
  status: CLOSED
  resolved_in_section: 7.3 Canonical Manifest Contract; 9.1 StageInputRole.v1
  normative_contract_refs:
    - semantic_manifest_canonical_bytes.v1
    - semantic_manifest_canonicalization.v1
    - StageInputRole.v1
    - stage_input_member_identity.v1
    - runtime_stage_profile.single_prompt.v1 Stage/Input Role matrix
  golden_vector_refs:
    - RUN_METRICS StageInputManifest canonical bytes and SHA-256
  semantic_rule: The only five legal input_role literals and every 16-Stage
    source-class assignment are frozen. input_role is part of canonical member
    identity and input_set_hash; aliases and implementation-selected names are
    invalid and any change creates a new contract version.

B6_LEGACY_STAGE_PROJECTION_GAP:
  status: CLOSED
  resolved_in_section: 20.4 LegacyFixedScopeValues.v1 and selector scope matrix
  normative_contract_refs:
    - LegacyScopeKey.v1
    - LegacyFixedScopeValues.v1
    - legacy_stage_source_manifest.v1
    - legacy_stage_projection.single_prompt.v1
  golden_vector_refs:
    - CASE-REAL-019 EXECUTION_PROPOSAL fixed_scope_hash
    - CASE-REAL-019 EXECUTION_PROPOSAL source_ref_set_hash
  semantic_rule: Every selector uses one exact scope profile, closed key/kind
    registries, one canonical scope-entry structure and one source-member
    identity. Free-form scope objects, extra keys, aliases and winner logic are
    excluded from source_ref_set_hash.
```

Both Independent Review 004 blockers are CLOSED by the RFC Author in Revision
004. This is an Author closure claim, not Independent Review 005, Definition
Freeze, Spike authorization, implementation authorization or production
cutover. B3 and every previously verified Runtime definition are unchanged.

## 40. Stop Gate

```text
RFC-RUNTIME-001 Revision 004 = DEFINITION FROZEN
SC-RUNTIME-001@0.1.0 = FROZEN
production/shadow implementation = NOT AUTHORIZED
Spike B = COMPLETE / SPIKE_PASS
schema/migration/DB writes = 0
production cutover = NOT STARTED
```
