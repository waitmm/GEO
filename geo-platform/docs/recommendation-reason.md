# Recommendation Reason

状态：ACTIVE
日期：2026-08-12

## 关系模型

```text
Recommendation
↔
Reason
↔
Target Entity
```

Reason 不能做成答案级词池。必须绑定到具体 Recommendation、具体品牌和具体 Reason Span。

## 示例

```text
天天外链 -> 因为支持数据追踪
微客外链 -> 因为操作简单
```

这两条必须分别保存，不能合并成：

```text
Answer Reasons: 数据追踪、操作简单
```

## Reason 类型

第一版支持：

```text
CAPABILITY
USABILITY
COMPLIANCE
STABILITY
TRACKING
INTEGRATION
PRICE
AUTHORITY
SUITABILITY
CONVENIENCE
SAFETY
OTHER
```

项目当前枚举可保留兼容，但用户侧必须展示中文 label。
