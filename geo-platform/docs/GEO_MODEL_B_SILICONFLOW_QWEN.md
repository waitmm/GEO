# GEO Model B: SiliconFlow Qwen

Status: TRANSPORT READY / PRODUCT PATH DISABLED

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
connect a second provider. It does not authorize an external call and does not
define the later Critic Signal business contract.

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

## Not Yet Implemented

- No Model B Critic prompt or response contract.
- No automatic comparison with Model A.
- No Qualification or Strategy mutation from Model B.
- No external-call authorization, canary or cost budget.
- No real SiliconFlow API verification.

These are intentionally separate from provider transport readiness. A future
bounded Critic Signal must consume an exact frozen object set and remain unable
to invent IDs, facts, channels, roles or public claims.

## Official References

- SiliconFlow Chat Completions: https://docs.siliconflow.cn/docs/api/chat-completions-post
- SiliconFlow JSON mode: https://docs.siliconflow.cn/docs/userguide/guides/json-mode
- SiliconFlow release notes/model changes: https://docs.siliconflow.cn/docs/release-notes/overview
