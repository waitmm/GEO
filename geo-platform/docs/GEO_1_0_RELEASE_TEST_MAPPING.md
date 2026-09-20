# GEO 1.0 首批测试能力映射

Status: `FIRST_SLICE_ENGINEERING_ACCEPTED / REAL_INPUT_PARTIAL`
Date: 2026-09-20

| 旧测试/能力 | 1.0 是否保留 | 共享约束 | 处置 | 首批替代或验收 |
| --- | --- | --- | --- | --- |
| 文心独立会话重置 | 是 | 旧会话不得继续提交 | RETAIN | 修复 reset fail-closed；保留原专项测试并补实际环境验收 |
| Legacy Step 8 两项 | 否 | Product Truth 不能被绕过 | ARCHIVE | release 不注册 Step 8；Truth 权限由 V2 Gate 测试保留 |
| Runtime Projection Spike 两项 | 否 | exact version/no latest | ARCHIVE | release 不加载 Runtime；由 Manifest/Review 精确绑定测试替代 |
| Legacy 批量删除两项 | 否 | 历史不可变、跨 Project 隔离 | ARCHIVE | release 不注册批量删除；新快照不可变与归属测试保留约束 |
| V2 Answer strict admission | 是 | 失败/零结果/待审核分离 | RETAIN | 现有 V2 Safety tests |
| V2 Diagnosis exact Review | 是 | Review 绑定结果/hash/set | RETAIN | 双输入 Gate 错版与跨 Context 测试 |
| Legacy bundled Diagnosis source fetch | 否 | 外部授权分阶段 | REPLACE | Source Preparation + explicit Evidence continuation |
| 旧 Diagnosis-owned SourceSnapshot | 否 | 正文不可变和内容 Gate | REPLACE | Analysis-owned PreparedSourceSnapshot/API/UI |
| GET 只读 | 是 | 不计算、不抓取、不写入 | RETAIN | Source status/Evidence readiness GET 行数与 hash 不变 |
| UNKNOWN != NO_SUPPORT | 是 | 未执行/失败不得变负结论 | RETAIN | Evidence Gate 与 legal-zero 专项测试 |
| API 内联后台任务 | 否 | 请求返回不代表重任务完成 | REPLACE | 正式 API 只入队，release worker 单并发消费 |
| 服务重启任务恢复 | 是 | queued 保留、running fail closed | RETAIN | `test_release_restart_preserves_queued_work_and_fails_only_running_work` |
| SQLite 任意系统版本 | 否 | WAL-reset 安全版本 | REPLACE | `test_sqlite_version_policy_accepts_only_patched_branches` + 正式启动校验 |
| Snapshot/Review/Result 重启绑定 | 是 | 文件与版本不可变 | RETAIN | 迁移库完整链关闭连接并重开后复核 ID/hash/path |

`ARCHIVE` 表示不属于 release suite，不表示删除原文件或掩盖共享缺陷。只有正式
入口和依赖已退出发布路径后，专属失败才不阻断 1.0；共享约束必须由表中替代测试
覆盖。

## 2026-09-20 执行结果

- `tests/test_release_first_slice.py`：11 passed；
- release + 文心会话 + V2 Analysis/Diagnosis/Safety 相关组合：95 passed；
- frontend `npm run build` 与 `npm run build:release`：通过；
- backend `compileall`、`git diff --check`：通过；
- 新空库及正式库实际迁移：revision `20260920_02`、SQLite `3.51.3`、WAL、
  外键、26/26 白名单表通过；
- 正式 worker 空队列启动：`IDLE`；正式 API health/release status 与 release
  首屏通过。

这些结果与首轮真实验收共同证明 release 工程链、真实 Wenxin 采样、一个真实
Snapshot 及双输入负向 Gate。SourceClaim/Alignment 尚未调用，因为 37 个来源和
精确 Answer Review 仍未完成人工处置；不能把当前 409 阻断报告为正向消费通过。

全仓基线为 `598 passed / 6 failed`。6 个失败均在 release 路径之外：

| 失败组 | 数量 | release 是否消费 | 处置 |
| --- | ---: | --- | --- |
| `test_b2_gate.py` legacy prompt batch delete | 2 | 否；release catalog 不注册 batch-delete | ARCHIVE；不可删除测试来凑绿 |
| `test_recommendation_intelligence.py` legacy Strategy -> Experiment | 2 | 否；release 不含 Strategy/Step 8 | ARCHIVE；共享 Product Truth Gate 由 V2 测试保留 |
| `test_runtime_projection_spike.py` Runtime projection | 2 | 否；Runtime 表/入口被 allowlist 排除 | ARCHIVE；exact version/no-latest 由 Manifest Gate 替代 |

此前文心会话重置失败在本轮 full suite 中已经消失。该结果证明 fail-closed 代码和
测试一致，但没有新的真实浏览器采样授权，因此仍不能宣称线上独立会话已重新验证。
