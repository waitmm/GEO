# Citation Context

状态：ACTIVE
日期：2026-08-12

## 核心边界

Citation coexistence does not equal Evidence Support.

中文产品口径：

> Citation 与 Recommendation / Reason 在同一回答中出现，只能说明存在引用上下文，不能说明 Citation 支撑该推荐理由。

## 当前阶段

正文抓取和段落验证完成前，只允许输出：

```text
Recommendation Reason
↓
Citation Context
↓
Platform / Domain / URL / Title
```

不能输出：

```text
Citation 支撑 Recommendation
```

## evidence_status

- `LINKED`：Reason 与外显 Citation 有较明确关联。
- `PARTIALLY_LINKED`：部分 Reason 可与 Citation 关联。
- `UNLINKED`：当前可观测数据中未找到外显 Citation 关联。
- `UNCERTAIN`：存在 Citation，但不能可靠判断关系。

`UNLINKED` 不能推断为模型训练知识或内部知识。
