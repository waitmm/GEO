# Semantic Definition Review Checklist

状态：ACTIVE
日期：2026-09-08

## 1. 变更分类

每次核心业务改动开始前必须选择一类：

```text
IMPLEMENTATION_CHANGE
SEMANTIC_CHANGE
SEMANTIC_RISK
```

- `IMPLEMENTATION_CHANGE`：不改变任何 Contract 定义、允许/禁止推断、未知行为或步骤边界。
- `SEMANTIC_CHANGE`：明确提出业务定义变化；必须先有 Semantic RFC。
- `SEMANTIC_RISK`：尚不能证明是否改变语义；只允许调查、Shadow、Replay 和 Conflict 登记，不得 cutover。

## 2. Definition Review

- [ ] Object 是什么？
- [ ] Object 不是什么；aliases 是否明确？
- [ ] Identity / Scope key 是什么？
- [ ] Source of Truth 是什么？
- [ ] 合法 inputs 和 outputs 是什么？
- [ ] A 为什么能推出 B？
- [ ] 哪些 Evidence 可以升级状态？
- [ ] 哪些 Evidence 不能单独升级状态？
- [ ] UNKNOWN 如何处理？
- [ ] Counterexample 是否包含全部其他合法 Gate？
- [ ] Step Owner 是谁？
- [ ] Allowed Consumers 是谁？
- [ ] 是否改变历史对象解释？
- [ ] 变更对象和 `contract_id/version` 明确。
- [ ] maturity 与 implementation_status 分开填写。
- [ ] definition 能用业务语言独立理解。
- [ ] allowed_inferences 完整。
- [ ] forbidden_inferences 完整。
- [ ] unknown_behavior 明确，不以 fallback 猜测替代。
- [ ] Step 1-8 ownership/boundary 明确。
- [ ] source、observed implementation、enforcement 三类引用未混用。
- [ ] 至少一个 normal、boundary、unknown/failure Golden Case。
- [ ] Real Case 使用固定 Manifest，不读取 latest。
- [ ] 与现有 FROZEN Contract/RFC/ACTIVE Product Definition 的冲突已登记。
- [ ] Product Owner 已明确执行 Definition Freeze 批准。

只有最后一项获得独立批准后，才可将 maturity 改为 `FROZEN`，填写 `approved_by/approved_at/approval_reference/effective_from`。

必须逐项审计以下错误类型：

```text
CATEGORY_ERROR
CAUSAL_REVERSAL
PARTIAL_PREMISE_FALLACY
HIDDEN_FALLBACK
MAGIC_THRESHOLD
CROSS_STEP_LEAKAGE
UNKNOWN_UPGRADE
HISTORICAL_MUTATION
IDENTITY_SCOPE_DRIFT
SHADOW_PRODUCTION_LEAK
EVIDENCE_TO_ACTION_JUMP
```

Definition Review 的固定输出格式：

```text
Status: APPROVED | NEEDS_REVISION | REJECTED | BLOCK
Contracts Referenced:
Golden Snapshot IDs:
Blocking Issues:
Non-blocking Issues:
Category Error Audit:
Causal Audit:
Identity / Scope Audit:
Forbidden Inference Audit:
Golden Cases:
Counterexamples:
Step Boundary:
Historical Compatibility:
Contract Gaps:
Freeze Recommendation: YES | NO
```

Reviewer 只能基于 Contract 和 Case 给出上述结果，不能修改 production code、自行 Freeze 或自行 Cutover。若现有 Contract 无法回答，返回 `CONTRACT_GAP`。

权限边界：

```text
Reviewer:
  can = APPROVED | NEEDS_REVISION | REJECTED | BLOCK
  cannot = modify production code | freeze | cutover

Implementer:
  can = implement an approved/frozen definition within authorized scope
  cannot = change semantics | infer cutover approval

Product Owner:
  owns = definition approval | freeze approval | production cutover approval
```

## 3. Implementation Review

- [ ] 实现严格对应已批准 RFC 或 FROZEN Contract。
- [ ] `implementation_status` 与真实路径一致。
- [ ] Validator、API Guard、Invariant 或自动化测试能够实际阻止越界。
- [ ] Shadow 与 production 路径清晰分离。
- [ ] LLM 只处理明确歧义，且 Closed World、Schema、fallback 均验证。
- [ ] 历史数据、current lineage 和固定 scope 未串线。
- [ ] 数据迁移、写库、Candidate/Action/Experiment 影响明确。
- [ ] 文档、日志、风险和 Product Outline 已同步。

## 4. Production Cutover Review

Definition Freeze 或 `RFC APPROVED` 都不自动授权 production cutover。切换前必须另行满足：

- [ ] Product Owner 给出独立 Production Cutover 批准及引用。
- [ ] Golden Cases 与专门测试全部通过。
- [ ] Shadow/Replay 对比无未解释 critical regression。
- [ ] Conflict Register 无阻断该 cutover 的 OPEN 冲突。
- [ ] 回滚目标是旧 implementation，不是删除新 Contract。
- [ ] 生产状态源、API、前端显示和数据库写入范围已列明。
- [ ] Cutover 后更新 implementation_status 和 last_verified_at。

## 5. Agent Guard

```text
SEMANTIC_CHANGE without APPROVED RFC
=> SEMANTIC_CONTRACT_REVIEW_REQUIRED

implementation conflicts with FROZEN Contract
=> SEMANTIC_CONTRACT_CONFLICT

SEMANTIC_RISK
=> investigation/shadow only
```

紧急 hotfix 只能恢复已知正确的 FROZEN 行为；若无法证明不改语义，按 SEMANTIC_RISK 停止 cutover，并在同一检查点登记 Conflict 和补充 RFC。任何语义相关 hotfix 后续状态必须标为 `RETROACTIVE_SEMANTIC_REVIEW_REQUIRED`，不得在代码中硬编码时间 SLA。
