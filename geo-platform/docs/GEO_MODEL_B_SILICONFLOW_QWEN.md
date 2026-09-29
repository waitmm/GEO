# GEO Model B: SiliconFlow Qwen

Status: SHADOW PHASE A EXECUTED / HUMAN GOLD COMPARISON PENDING

Date: 2026-09-29

## Decision

The optional second semantic model uses:

```text
Provider: SiliconFlow
API: https://api.siliconflow.cn/v1/chat/completions
Default model: Qwen/Qwen3.6-35B-A3B
Role: Model B critic
```

This Product Owner decision supersedes the earlier temporary instruction not to
connect a second provider. The provider is enabled locally and the bounded
Critic Signal business contract is implemented in Shadow mode.

Model A remains DeepSeek. Existing Answer Semantic, SourceClaim, Alignment and
Citation Contribution calls are not rerouted to SiliconFlow.

## Runtime Boundary

The Model B client is available only through `create_model_b_client()`.

- `MODEL_B_ENABLED=false` by default.
- External construction is rejected while disabled.
- `cache_only=true` never reads an API key or starts an HTTP request.
- API keys are read only from `SILICONFLOW_API_KEY`.
- Automatic retries default to zero (`max_attempts=1`).
- The client accepts typed Pydantic response models only.
- SiliconFlow `json_schema` Structured Outputs and local strict validation must
  both pass before a result can be consumed or cached.
- Provider, requested/effective model, prompt/schema/transport versions,
  input hash, provider trace ID, response model and token usage are auditable.
- Unknown fields, malformed JSON, empty/truncated responses and model identity
  mismatches are rejected.

## Configuration

```dotenv
MODEL_B_ENABLED=false
MODEL_B_PROVIDER=siliconflow
SILICONFLOW_API_KEY=
SILICONFLOW_MODEL=Qwen/Qwen3.6-35B-A3B
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
SILICONFLOW_TIMEOUT_SECONDS=120
```

The model is configurable because SiliconFlow periodically changes its model
catalog. Changing the model changes the cache identity; an old Qwen result
cannot be consumed as though it came from the new model.

## Qualification Critic Shadow

The first product path freezes the current single-model
`QualificationProjection` and selects only:

```text
CONSUMABLE Strategy Directions
positive SUPPORTS_FULL / SUPPORTS_PARTIAL Citation bindings
```

The current real case produces seven candidates: one Strategy Direction and six
`SUPPORTS_PARTIAL` Citation relations. Each candidate is sent independently,
with zero automatic retries, through an explicit POST and the single-concurrency
release worker. GET, refresh and polling never call the provider.

The response contract is limited to:

```text
critic_verdict = AGREE | DISAGREE | INSUFFICIENT_CONTEXT
issue_types[]
counterexample
rationale
```

Unknown fields are rejected. A non-null counterexample must be a verbatim span
from the frozen input. The immutable Shadow Result keeps the single-model
baseline and explicitly records that formal Qualification and Strategy were not
changed.

The first real Phase A execution froze all seven tasks before the first model
response. Each task records its router reason, impact, downstream dependency,
required use, Model A baseline, rule signals, input object IDs and input hash.
The Strategy task includes the actual Reason, four Truth statements and their
eligibility, the Run 1 Citation limitation and the Runs 1-9 Answer scope.

```text
Execution = qualification-critic-907d6ec8-48c7-45d1-a720-c3a0653a6fd4
Plan hash = ee9b3e85da28c1b5cf462155f1738408421d5fdb1892d9290531822a2fe19fb8
Result = critic-v1:d9f8b0fd5f1c89ad
Requests = 7
Admitted / failed = 6 / 1
AGREE / DISAGREE / INSUFFICIENT_CONTEXT = 2 / 4 / 0
Tokens = 16,437
Estimated cost = RMB 0.057865, not billed amount
Formal business changes = 0
```

The failed task returned an incomplete response at the 1,200-token output
ceiling and was not retried. All seven complete provider artifacts, including
the rejected response, are retained outside Git with mode `0600` and verified
SHA-256 hashes.

## Critic Contract Recovery

The incomplete response was caused by one Critic response expanding to the
1,200-token ceiling, not by an oversized input or by a Schema/admission defect.
The original Phase A execution and `critic-v1:d9f8b0fd5f1c89ad` remain
immutable at six admitted and one failed object.

The recovery contract is deliberately smaller:

```text
contract = single_prompt_v2.qualification_critic_shadow.v3
prompt = single_prompt_v2.qualification_critic.qwen.v3
schema = single_prompt_v2.qualification_critic.strict.v3
provider payload = single_prompt_v2.qualification_critic.provider_payload.v1
max output tokens = 1600
normal target = about 500 tokens or fewer
```

`issue_types` is limited to three values and `primary_issue` identifies the
single strongest issue. `counterexample` is limited to 200 characters and
`rationale` to 300 characters and two sentences. The same bounds exist in the
provider JSON Schema and the local validator. Any provider completion other
than `finish_reason=stop` is rejected as `FAILED_INCOMPLETE_RESPONSE` before
JSON parsing and is never cached or emitted as a Critic Signal.

The complete frozen Plan/Audit still retains router, Model A and rule details.
The provider payload sends the required semantic object once, without duplicate
top-level baseline/rule copies. Business task identity, semantic input identity
and actual provider-payload identity are independently recorded as `input_hash`,
`semantic_input_hash` and `provider_payload_hash`.

The exact failed object has a deterministic, one-object Supplemental plan ready
for a later separately authorized call:

```text
object = ccb-79840d3699c3c11b2700
task = critic-supplemental-971b4de28c1522644dde
plan hash = 56c0a8381a1914fffd513057a4e524cc48921067c2f379bd3966402b223470e3
semantic input hash = 1112a1aa5209cb7cc4ea96569e85d921aebbc180ecd6a4a41b07f0cd1d920dcc
provider payload hash = 573dc2e22c0dcb777e139a3f94fd2788955ed04a2ce22b0df9fa706865673aaf
maximum requests = 1
automatic retries = 0
token ceiling = 2,555
estimated cost ceiling = RMB 0.018999, not billed amount
```

This plan has not been queued or executed. A new explicit external-call
authorization is required. Human Gold Phase B can proceed immediately with the
six valid Phase A objects; the failed object remains an incomplete-response
diagnostic case and does not block calibration.

## Not Yet Activated

- No Qualification or Strategy mutation from Model B.
- No quality-based cutover policy.
- No gain measurement until the P1 Human Gold set exists.
- No Production Critic routing. Phase A is behavior observation only.
- No quality claim until Phase A disagreements and failure are compared with
  Human Gold.

## Verification Record

One synthetic, non-business canary completed against SiliconFlow with model
`Qwen/Qwen3.6-35B-A3B`. Provider Structured Output and local strict validation
both passed. The call used 72 total tokens. No project text, Answer excerpt,
Source passage, Product Truth or Strategy dependency was included.

Therefore:

```text
endpoint/key/model/schema transport = SYNTHETIC_VERIFIED
real seven-object Shadow execution = COMPLETED_WITH_LIMITATIONS
business judgment quality = AWAITING_HUMAN_GOLD
formal Qualification/Strategy effect = NONE
```

These are intentionally separate from provider transport readiness. A future
bounded Critic Signal must consume an exact frozen object set and remain unable
to invent IDs, facts, channels, roles or public claims.

## Official References

- SiliconFlow Chat Completions: https://docs.siliconflow.cn/docs/api/chat-completions-post
- SiliconFlow JSON mode: https://docs.siliconflow.cn/docs/userguide/guides/json-mode
- SiliconFlow release notes/model changes: https://docs.siliconflow.cn/docs/release-notes/overview
