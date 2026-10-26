# GEO Golden Semantic Cases

状态：ACTIVE
日期：2026-09-08

## 1. 规则

Golden Case 保护业务语义，不只是代码输出。每个 Case 必须绑定 `contract_id + contract_version`、完整前提、允许推断、禁止推断和可复现验收方式。

- Synthetic Case 不依赖本地数据库，前提必须完整且 contract-scoped。
- Real Case 必须读取不可变 Manifest，禁止查询 `latest` 后把结果称为同一 Case。
- 当前行为与候选定义并存时，必须分列 `current_expected` 与 `proposed_expected`。
- Golden Case 通过不等于 Contract 自动 FROZEN，也不授权 production cutover。

## 2. Synthetic Cases

### CASE-SYN-008 员工一键优化与服务端运行策略

```yaml
contracts:
  - SC-SERVER-MODEL-POLICY-001@1.0.0
verification_mode: AUTOMATED_TEST + BROWSER_ACCEPTANCE
premise:
  frozen_agent_input: valid
  authenticated_actor: employee-one
  server_model_policy: enabled_and_available
expected:
  - 一次“创建并运行 AI 优化”操作创建冻结任务并由服务端策略排队。
  - 页面不要求员工填写请求、Token、金额、单价、计费来源或日期。
  - 实际用量只作为审计结果记录。
boundary:
  server_model_policy: unavailable
boundary_expected:
  - 外部调用为零并返回业务可读阻断，不创建可误认为正在运行的新任务。
forbidden:
  - 客户端字段扩大服务端运行权限。
  - 回退使用历史实验余额。
automation:
  - backend/tests/test_agent_internal_beta.py
  - frontend/tests/agent-internal-beta.test.mjs
```

### CASE-SYN-001 Product Truth 与 Citation Intervention 分离

```yaml
contracts:
  - SC-PT-001@1.0.0
  - SC-GAP-001@1.0.0
  - SC-FOUNDATION-001@0.1.0
verification_mode: AUTOMATED_TEST + MANUAL_SEMANTIC_REVIEW
premise:
  target_brand_truth: TRUE, MANUAL_CONFIRMED
  same_reason_eligible_supports: 0
  competitor_claims: present
  target_brand_and_reason_scope: exact match
  first_party_authority_gate: fully passes
  intervention_fit: passes under current resolver
current_expected:
  - 允许形成 ANSWER_DECISION_EVIDENCE_GAP。
  - 当前 Resolver 可按既有 Path C 评估官网权威承载。
proposed_expected:
  - Product Truth 只建立 Foundation Requirement，不单独证明 Citation Intervention。
forbidden:
  - 将竞品 claim 写成目标品牌事实。
  - 将 proposed_expected 当成当前生产行为。
automation:
  - backend/tests/test_source_gap_v1.py
  - backend/tests/test_channel_resolution_shadow.py
```

### CASE-SYN-002 无 Phase 2A Lineage 的旧 Alignment

```yaml
contracts:
  - SC-EVIDENCE-002@1.0.0
  - SC-EVIDENCE-003@1.0.0
verification_mode: AUTOMATED_TEST
premise:
  alignment_verdict: SUPPORTS
  review_status: HUMAN_CONFIRMED
  observed_relation: PERIPHERAL_CITATION
  same_run_source: false
  citation_anchor: false
  answer_context: unavailable
expected:
  - 不进入正式 V1.1 evidence relation。
  - 保留历史原记录供审计。
forbidden:
  - 因 HUMAN_CONFIRMED 永久召回。
  - 删除或改写历史 verdict。
automation:
  - backend/tests/test_evidence_alignment.py
```

### CASE-SYN-003 Benchmark 不决定执行渠道

```yaml
contracts:
  - SC-BENCHMARK-001@1.0.0
  - SC-CHANNEL-001@1.1.0
verification_mode: AUTOMATED_TEST
premise:
  benchmark_channel: ZHIHU
  benchmark_eligible: true
  execution_eligibility: false
expected:
  - ZHIHU 可作为 Benchmark 证据来源。
  - ZHIHU 不因 Benchmark 身份自动获得 PRIMARY/SECONDARY/TEST。
forbidden:
  - benchmark_channel => execution_channel
automation:
  - backend/tests/test_strategy_step7_v1.py
```

### CASE-SYN-004 Retrieval / Reference 不是 Decision Citation

```yaml
contracts:
  - SC-EVIDENCE-003@1.0.0
  - SC-CHANNEL-001@1.1.0
verification_mode: AUTOMATED_TEST
premise:
  channel_reference_count: 40
  channel_retrieval_count: 16
  eligible_decision_citation_count: 0
  target_applicability: passes
  intervention_fit: passes
  remaining_path_d_gates: pass
expected:
  - 可描述 reference/retrieval exposure。
  - 在本 Case 已明确的完整 Path D 前提下，可形成非因果 TEST 假设。
forbidden:
  - 声称该渠道已支持决策理由。
  - 声称该渠道能够提升推荐率。
automation:
  - backend/tests/test_channel_evidence.py
  - backend/tests/test_channel_resolution_shadow.py
```

### CASE-SYN-005 LLM 不可改写 Strategy Truth

```yaml
contracts: [SC-STRATEGY-001@1.1.0]
verification_mode: AUTOMATED_TEST
premise:
  allowed_channels: [OFFICIAL_SITE, ZHIHU]
  resolver_roles: {OFFICIAL_SITE: PRIMARY, ZHIHU: TEST}
  llm_output: {new_channel: XIAOHONGSHU, ZHIHU: PRIMARY, unknown_reason_id: 999}
expected:
  - 整次 structural proposal REJECT。
  - final structure 等于 deterministic baseline 或进入 needs_human_*。
forbidden:
  - 宽松修正后部分采用非法输出。
automation:
  - backend/tests/test_strategy_synthesis_shadow.py
```

### CASE-SYN-006 Step 8 Overlay 越权

```yaml
contracts: [SC-STEP8-001@1.0.0]
verification_mode: AUTOMATED_TEST
premise:
  strategy_role: TEST
  human_overlay:
    role: PRIMARY
    baseline_run_ids: [999]
expected:
  - overlay 整体拒绝并返回明确错误。
  - 原 Proposal 与 Strategy Truth 不变。
forbidden:
  - 静默删除非法字段后继续提交。
automation:
  - backend/tests/test_execution_proposal_shadow.py
```

### CASE-SYN-007 Experiment 必须冻结完整快照

```yaml
contracts: [SC-EXPERIMENT-001@1.0.0]
verification_mode: AUTOMATED_TEST
premise:
  one_action: true
  strategy_snapshot: present
  gap_snapshot: present
  action_snapshot: present
  selected_asset_snapshot_or_ref: present
  baseline_run_ids: [101]
  baseline_metrics: present
expected:
  - 创建后历史快照不随当前 Candidate 或资产变化。
forbidden:
  - 缺少任一必需快照仍创建正式 Experiment。
  - 多渠道 Proposal 合并为一个 Experiment。
automation:
  - backend/tests/test_source_gap_v1.py
```

### CASE-SYN-008 FACT_ANCHOR 不等于官网 PRIMARY

```yaml
contracts: [SC-FOUNDATION-001@1.0.0, SC-CHANNEL-002@1.0.0, SC-ASSET-001@1.0.0]
verification_mode: AUTOMATED_TEST + MANUAL_SEMANTIC_REVIEW
premise:
  target_brand_truth: confirmed
  fact_anchor_need: present
  citation_channel_evidence: absent
  asset_inventory_complete: false
expected:
  - Foundation/FACT_ANCHOR 可为 REQUIRED。
  - Citation PRIMARY 保持 NONE。
  - asset_state=UNKNOWN，下一步为 VERIFY_ASSET_FIRST。
forbidden:
  - OFFICIAL_SITE PRIMARY
  - CREATE_NEW
  - 将 SourceSnapshot 当作 ManagedAsset
automation:
  - backend/tests/test_single_prompt_v2_citation_contribution.py
```

### CASE-SYN-009 Citation 处置与关系不可混淆

```yaml
contracts: [SC-CITATION-CONTRIBUTION-001@1.0.0]
verification_mode: AUTOMATED_TEST
premise:
  citation_a: source waived
  citation_b: analysis failed
  citation_c: completed with no correspondence
expected:
  - citation_a processing_status=WAIVED, disposition=SOURCE_WAIVED，且无 NO_MATCH 推断。
  - citation_b processing_status=FAILED, disposition=ANALYSIS_FAILED，且无 NO_MATCH 推断。
  - citation_c processing_status=DONE，可明确 correspondence_mode=NO_CORRESPONDENCE 与 evidence_relation=NO_MATCH。
forbidden:
  - 将前三者合并为 NO_SUPPORT。
  - 由内容对应推断 generation_influence=PROVEN。
automation:
  - backend/tests/test_single_prompt_v2_citation_contribution.py
```

## 3. Real Cases

### CASE-REAL-019

Manifest：`docs/semantics/snapshots/CASE-REAL-019.manifest.json`

当前固定输入：Project `3`、Prompt `19`、Evidence Package `12@v8`、Strategy Candidate `57`、Manifest 内 40 个明确 Run IDs。

```yaml
contracts:
  - SC-PT-001@1.0.0
  - SC-EVIDENCE-001@1.0.0
  - SC-GAP-001@1.0.0
  - SC-CHANNEL-001@1.1.0
  - SC-STRATEGY-001@1.1.0
  - SC-STEP7-001@1.0.0
  - SC-STEP8-001@1.0.0
  - SC-SCOPE-001@1.0.0
  - SC-RUNTIME-001@0.1.0
current_expected:
  - Candidate #57 保持 accepted/current lineage。
  - 5 Reasons 确定性归为 3 Themes，覆盖为 13/15、13/15、1/15。
  - OFFICIAL_SITE 为 PRIMARY；BAIJIAHAO/ZHIHU 为优先 TEST；BILIBILI/SOHU 为 deferred TEST。
  - Step 7 已确认；PR5-B 只达到 ready_for_freeze，不创建 Action/Experiment。
proposed_expected:
  - Foundation/Citation Split 仅作为 RFC Candidate 讨论，不改变上述 production 结果。
runtime_frozen_expected:
  - Root projection 为 PARTIAL，16 Stage 分布为 0 COMPLETE / 6 PARTIAL / 9 UNSAFE / 1 UNAVAILABLE。
  - Strategy lineage 为 UNSAFE，current projection 为 UNRESOLVED，所有 ContextStageSelection 为 null。
  - virtual projection 只作 Golden/比较，不进入 current、Review、Strategy、Action、Experiment 或 PR5。
verification_mode: MANUAL_SEMANTIC_REVIEW + QUERY_ASSERTION + AUTOMATED_TEST
manual_checks:
  - 核对 Candidate input/output hash 与 Manifest。
  - 核对 Theme coverage 使用 member Reason run-id union。
  - 核对当前 package/candidate lineage，不使用 latest。
automation:
  - backend/tests/test_runtime_projection_spike.py
```

### CASE-REAL-040

Manifest：`docs/semantics/snapshots/CASE-REAL-040.manifest.json`

当前固定输入：Project `3`、Prompt `40`、Evidence Package `15@v2`、Strategy Candidate `50`、Manifest 内 6 个明确 Run IDs。

```yaml
contracts:
  - SC-EVIDENCE-001@1.0.0
  - SC-EVIDENCE-002@1.0.0
  - SC-EVIDENCE-003@1.0.0
  - SC-BENCHMARK-001@1.0.0
  - SC-CHANNEL-001@1.1.0
  - SC-STRATEGY-001@1.1.0
  - SC-SCOPE-001@1.0.0
  - SC-RUNTIME-001@0.1.0
current_expected:
  - Candidate #50 保持 PENDING_REVIEW/PENDING，不能由 #19 或历史候选串线。
  - Benchmark-backed 兼容投影保留官网 PRIMARY、知乎 SECONDARY、无 TEST。
  - Step 7 待确认，Step 8 锁定；不创建 Action/Experiment。
proposed_expected:
  - 无；本轮不重新解释 #40 Benchmark 语义。
runtime_frozen_expected:
  - Root projection 为 PARTIAL，16 Stage 分布为 0 COMPLETE / 7 PARTIAL / 8 UNSAFE / 1 UNAVAILABLE。
  - Candidate #50 缺失的 PR4 lineage 字段保持 null；Strategy lineage 为 UNSAFE，current projection 为 UNRESOLVED。
  - 禁止使用 Candidate #57、最新 Candidate 或其它历史对象补齐。
verification_mode: MANUAL_SEMANTIC_REVIEW + QUERY_ASSERTION + AUTOMATED_TEST
manual_checks:
  - Manifest 中缺少的 PR4 candidate contract hash 必须保持 null + reason，不得猜测。
  - 核对 Evidence Package 与 Run scope hash。
automation:
  - backend/tests/test_runtime_projection_spike.py
```

### MANUAL_IMPORT synthetic cases

- `MANUAL-IMPORT-NORMAL`：明确 Project/Prompt、观察时有效的 Prompt/config 版本、完整回答和
  引用记录导入成功；Run 标记 `MANUAL_IMPORT` 与 `USER_ATTESTED_UNVERIFIED`，可进入明确范围，
  但导入本身不创建 AnalysisContext 或模型任务。
- `MANUAL-IMPORT-VERSION-TIME-REJECT`：`observed_at` 早于所选版本创建时间或落在下一版本生效后，
  整体拒绝且零 Run、零引用、零分析写入。
- `MANUAL-IMPORT-CITATION-UNKNOWN`：空引用且状态 `UNKNOWN` 不得被解释为
  `CONFIRMED_NONE`；范围可以保留回答，但引用完整性保持未知。
- `MANUAL-IMPORT-LEGACY-BLOCK`：既有 `LEGACY_UNBOUND` Run 不因新入口存在而被回填版本或获得
  分析资格。

### Business Run retry synthetic cases

- `RUN-RETRY-NORMAL`：未被消费、无回答的失败 Run 显式重试；Run ID 不变，新增内部 Attempt；
  成功后同一业务行保存新回答、引用、采集时间和 hash，Run 池业务样本数不增加。
- `RUN-RETRY-FAIL-AGAIN`：重试再次失败；同一 Run 更新失败原因并可再次人工重试，Attempt
  审计追加保存，不自动重放、不进入有效分析样本。
- `RUN-RETRY-CONSUMED-BLOCK`：Run 已出现在任一 AnalysisContext 或正式下游输入中；原位重试
  整体拒绝，重新采集必须创建新的业务 Run。
- `RUN-RETRY-PARTIAL-CONTENT-BLOCK`：失败 Run 仍保存真实回答或部分可用内容；禁止清空覆盖，
  必须保留该观测并另行采样。

## 4. 验收方式

1. 先验证 Manifest 的数据库文件 hash、固定对象 ID 与 Run scope hash。
2. 数据库不匹配时返回 `LOCAL_DB_REQUIRED` 或 `SNAPSHOT_IDENTITY_MISMATCH`，不能改查 latest。
3. 执行对应自动化测试；Real Case 还需人工读取固定对象 payload。
4. 将当前实现结果与 `current_expected` 比较；候选 RFC 只能与 `proposed_expected` 比较。
5. 发现偏差时登记 Conflict；若涉及 FROZEN Contract，停止生产语义变更并请求审查。
