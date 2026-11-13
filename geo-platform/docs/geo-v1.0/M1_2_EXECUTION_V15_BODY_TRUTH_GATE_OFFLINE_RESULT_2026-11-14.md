# GEO M1.2 Execution v15 正文 Product Truth Gate 离线结果

日期：2026-11-14（Asia/Shanghai）

分支：`codex/m1-2-multicontent`

状态：`OFFLINE_ACCEPTED / REAL_GATE_NOT_AUTHORIZED`

## 1. 分类与边界

本次分类为 `IMPLEMENTATION_CHANGE`。现有 `SC-PT-001`、答案观察与 Product Truth 分离规则以及
分级交付契约已经禁止把品牌关联目标、竞品能力或未核实回答改写成目标品牌事实，因此不新增语义 RFC。

离线反例证明，原 Validation v6 只在 `QA 与事实限制` 检查目标品牌能力，HELP_DOC、FAQ 和 legacy
`完整正文` 可写入“目标品牌支持跨域跳转”，即使冻结回答只证明竞品具备该能力且 Product Truth 为空，
仍可能得到 PASS。

## 2. 版本化实现

- 当前新执行：Prompt v11 / Execution v15 / Validation v6。
- 历史冻结：Execution v14 保持 `valid-run-eligibility.v2`、Run projection、Pack/hash 和原 Validation v6
  解释；旧结果不重验、不重标。
- v15 对每份正文独立检查目标品牌能力。能力谓词必须由同句有效 `truth` locator 支持，且 Truth 必须
  支持同一谓词与极性；回答或竞品能力不能替代 Product Truth。
- 问题归属精确 DraftArtifact，单稿失败不删除或降级另一份合格资产，父任务仍可真实部分成功。
- `VERIFY_FIRST` 不能洗白未经证实的能力。
- 极窄的未来内容行动边界不视为既有产品能力，例如“目标品牌可以在官网发布帮助文档”或“可以补充
  FAQ”；“目标品牌可以跨域跳转”仍必须有 Product Truth。

该 Gate 不扩展为通用内容评分器，也不改变 Evidence Set、Observation、QA Composition 或来源归属。

## 3. 离线验证

定向回归覆盖：

- 精确竞品能力转移反例在 v15 阻断，v14 历史解释保持原状。
- 纯第三方能力描述不误杀；精确 Product Truth 支持的目标品牌能力通过。
- `VERIFY_FIRST` 加在未经证实能力前仍阻断。
- HELP_DOC 失败、FAQ 合格时父结果为 `PARTIAL`。
- 两种明确的未来内容发布行动通过，而真实产品能力“可以跨域跳转”仍阻断。

验证命令与结果：

- `PYTHONPATH=. .venv/bin/pytest -q tests/test_agent_experiment.py tests/test_agent_draft_artifacts.py`：
  146 passed。
- `PYTHONPATH=. .venv/bin/pytest -q tests/test_agent_draft_artifacts.py -k 'current_draft'`：
  6 passed（包含最终行动边界正反例）。
- Agent、子资产、内部 Beta 与容量相关联合回归：177 passed。

全部为离线测试；文心、DeepSeek、网页抓取和其他外部调用均为 0。

## 4. 下一 Gate

下一次真实双稿必须单独授权并使用 Prompt v11 / Execution v15 / Validation v6。当前状态仍为
`BLOCKED`：没有第五次付费调用授权，不得因本次离线通过自动请求模型、发布 M1.2、升级 M1.1 数据库
或重标任何历史失败结果。服务端 PASS 后仍需运营人员逐稿评价事实准确性、修改量和采用价值。
