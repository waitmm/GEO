# C1 第二平台离线纵向验收（2026-11-18）

## 结论

状态：`OFFLINE_ACCEPTED / PRODUCTION_NOT_ADMITTED`。

腾讯元宝合成契约探针已打通：

`CollectorResult → Run / ReferenceSource / RetrievalCandidate → 时间范围预览与冻结 → Agent Optimize 输入 → Evidence Pack`

本结论不代表真实元宝网页采集、登录、DOM 解析、平台许可或生产适配完成。

## 边界

- 全部输入为 `.invalid` URL 的 `SYNTHETIC_CONTRACT_PROBE`；没有真实平台内容或敏感数据。
- 没有登录、浏览器访问、外部请求、模型调用、来源正文抓取或付费操作。
- `yuanbao_web_audit` 未加入 collector registry；生产 API、定时任务和人工导入白名单均未放开。
- 文心历史路径、已有冻结 Analysis/Agent 结果及正式 Evidence/Truth Gate 未重解释。

## 已验证行为

- `UNKNOWN` 与 `PARSE_FAILED` 引用观察保持不完整，不能变成已确认零引用。
- `CONFIRMED_NONE` 仅在显式状态、零引用且计数一致时成立。
- `COMPLETE` 要求引用计数一致且存在实际引用；未解析目标继续以不完整状态保存。
- 引用展示平台名由服务端依据 Run 的平台身份映射，采集 payload 不能伪造为其他平台。
- 合成元宝 Run 的平台、adapter、PromptVersion、ProjectConfigurationVersion 与采样计划 lineage 通过正式范围 Gate；未使用 `latest` 或绕过校验。
- 冻结输入保留 Run 平台/adapter、引用、候选及完整性状态，随后进入现有唯一 Optimize/Evidence Pack 路径。

## 测试

定向命令：

```bash
cd geo-platform/backend
PYTHONPYCACHEPREFIX=/private/tmp/geo-c1-pycache PYTHONPATH=. \
  /Users/bmwqr/Desktop/python/GEO/geo-platform/backend/.venv/bin/python \
  -m pytest -q tests/test_c0_second_platform_probe.py \
  tests/test_c1_yuanbao_offline_projection.py --disable-warnings -rx
```

首次完整两文件运行得到 **16 passed、1 test-assertion failed**（470.21 秒）：唯一失败发生在全部
Run→freeze→Optimize→Evidence Pack 行为完成后，测试把整数 `run_id` 错误地预期为字符串；该断言已修正。
随后针对 UNKNOWN、平台归属及缺少服务端平台身份的 fail-closed 用例复跑为 **3 passed**（274.67 秒）。
2026-11-18 主控在修正后重新执行上述完整两文件集成 Gate，结果为 **18 passed**、904 条既有
依赖/ORM warning，耗时 478.11 秒；没有剩余 assertion 或 migration 失败。
测试覆盖 C0 两个原 strict-xfail 的修复、四种引用观察状态、registry fail-closed，以及完整离线纵向投影。
上述耗时不作为产品性能结论。

## 剩余真实 Gate

进入 C1 真实验收前仍需单独满足：当前适用平台许可与采集授权、登录会话、真实页面与引用 DOM 契约、
单条受控采集、脱敏原始 artifact 回读、错误/验证码/限流 fail-closed，以及独立生产准入审批。
本离线验收不自动开启立即采集或定时采集。
