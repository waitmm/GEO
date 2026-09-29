# GEO Model B: SiliconFlow Qwen

Status: SYNTHETIC TRANSPORT VERIFIED / REAL BUSINESS SHADOW AWAITING DATA AUTHORIZATION

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
issues[]
counterexample
rationale
```

Unknown fields are rejected. A non-null counterexample must be a verbatim span
from the frozen input. The immutable Shadow Result keeps the single-model
baseline and explicitly records that formal Qualification and Strategy were not
changed.

## Not Yet Activated

- No Qualification or Strategy mutation from Model B.
- No quality-based cutover policy.
- No gain measurement until the P1 Human Gold set exists.
- No real business-payload replay: the exact Answer/source excerpt and Strategy
  dependency export scope still requires explicit authorization.

## Verification Record

One synthetic, non-business canary completed against SiliconFlow with model
`Qwen/Qwen3.6-35B-A3B`. Provider Structured Output and local strict validation
both passed. The call used 72 total tokens. No project text, Answer excerpt,
Source passage, Product Truth or Strategy dependency was included.

Therefore:

```text
endpoint/key/model/schema transport = SYNTHETIC_VERIFIED
real seven-object Shadow execution = NOT_STARTED
business judgment quality = NOT_VERIFIED
formal Qualification/Strategy effect = NONE
```

These are intentionally separate from provider transport readiness. A future
bounded Critic Signal must consume an exact frozen object set and remain unable
to invent IDs, facts, channels, roles or public claims.

## Official References

- SiliconFlow Chat Completions: https://docs.siliconflow.cn/docs/api/chat-completions-post
- SiliconFlow JSON mode: https://docs.siliconflow.cn/docs/userguide/guides/json-mode
- SiliconFlow release notes/model changes: https://docs.siliconflow.cn/docs/release-notes/overview
