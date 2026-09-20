# GEO 1.0 首批测试能力映射

Status: `IN_PROGRESS`
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

`ARCHIVE` 表示不属于 release suite，不表示删除原文件或掩盖共享缺陷。只有正式
入口和依赖已退出发布路径后，专属失败才不阻断 1.0；共享约束必须由表中替代测试
覆盖。
