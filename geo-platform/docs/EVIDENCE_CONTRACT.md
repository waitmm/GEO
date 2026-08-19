# Evidence Contract — 证据数据契约

**状态**: ACTIVE  
**适用**: Single Case Evidence 管道全部语义 Judge

六条正式数据契约。任何语义 Judge 违反任一契约即视为无效输出。

---

## Contract 1：Grounding 与 Normalization 必须分离

LLM 可以抽象语义，但不能捏造证据。

- `evidence_span` / `answer_span` / `source_span` 必须能够定位回原始 Answer 或 Source Passage。
- `normalized_claim` / `normalized_reason` 可以概括，但 Grounded Span 必须存在。
- Grounding 判定为确定性字符串定位（unicode 归一化 + 空白移除 + 偏移映射），**不得用 Embedding 相似度代替**。
- Embedding 仅允许用于 Passage Retrieval，禁止用于 SUPPORTS/CONTRADICTS 判断。

**实现**: `answer_semantic.locate_span` / `normalize_for_grounding`（Layer 1），Layer 4 复用。

---

## Contract 2：Reason-driven Pruning

禁止"只取 Citation 前 3 / 前 5"。

流程必须是：

```text
Recommendation Event → Recommendation Reason → Reason-Relevant Source
→ Reason-Relevant Passage → Source Claim
```

Citation 排名只能作为辅助特征。

**实现**: `passage_retrieval.run_reason_driven_retrieval`（BM25 + entity-first enhancement）。

---

## Contract 3：LLM numeric confidence 不得成为生产真值

- `confidence_raw` 仅存档。
- 生产状态来自：schema valid + grounded span valid + entity scope valid + semantic relation valid + 必要人工审核。
- 状态枚举：`MACHINE_CANDIDATE / MACHINE_GROUNDED / NEEDS_HUMAN_REVIEW / HUMAN_CONFIRMED / HUMAN_REJECTED / UNRESOLVED / VALIDATION_FAILED`。

---

## Contract 4：Golden Truth 必须服从真实分布

- Runs 173–184 必须全量人工审核。
- 真实 `POSITIVE_RECOMMENDATION = 0` 就保存 0，禁止为训练凑数。
- 机器结果与人工结果分离存储（machine_payload_json / human_payload_json）。

---

## Contract 5：三个 Semantic Judge 必须物理隔离

| Judge | 可见输入 | 禁止看到 |
|-------|---------|---------|
| AnswerSemanticJudge | Prompt + Answer + Target brand metadata | 竞品预设列表 |
| SourceClaimJudge | Source Passage（盲评） | Prompt / Answer / Reason / 目标品牌 |
| EvidenceAlignmentJudge | SourceClaim + RecommendationReason + entity scope | Strategy / Action / Experiment Outcome |

三者不共享 conversation history / reasoning。

**实现**: `answer_semantic.py` / `source_claim.py` / `evidence_alignment.py` 三个独立模块、独立 System Prompt。

---

## Contract 6：严格区分 Entity Scope

Source 分类：`TARGET_FIRST_PARTY / COMPETITOR_FIRST_PARTY / INDEPENDENT_EDITORIAL / UGC_COMMUNITY / PLATFORM_NATIVE / UNKNOWN`。

- `source_owner_entity` 是 provenance（域名归属，确定性规则）。
- `SourceClaim.subject_entity` 是语义主体（Judge 从正文识别，回指词归一化为 owner）。
- 竞品 Source Claim 可以 SUPPORT 竞品自己的 Reason 或 MARKET_CRITERION，**不能 SUPPORT 目标品牌的 ENTITY_SPECIFIC capability**。
- 目标品牌 Evidence Gap 必须经 `Market Criterion → Target Product Truth → Target Evidence` 比较产生，禁止"竞品有 Claim → 品牌缺 Evidence"直接推导。

**实现**: `source_qualification.resolve_ownership` + `evidence_alignment.entity_scope_precheck`。
