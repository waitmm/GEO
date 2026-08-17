# 答案语义事实

状态：ACTIVE
日期：2026-08-12

## has_choice_slot

定义：Answer 中是否存在用户可以在多个可替代实体、产品、品牌、服务、平台或方案之间进行主动选择的决策位置。

不是“有没有解决办法”。纯操作步骤不构成选择空间。

示例：

- `进入抖音后台，点击分享，然后复制链接。` -> false
- `可以直接复制官方链接，也可以使用短链服务生成跳转链接。` -> true

## has_brand_mention

定义：Answer 中是否出现至少一个可解析的真实品牌、产品或服务品牌实体。

主题、能力、渠道、方法不是品牌，例如“短链”“第三方工具”“私域引流”不能当品牌。

## has_explicit_recommendation

定义：Answer 作者是否对某个实体执行正向选择行为。

不能只看“推荐”关键词。`可以优先考虑天天外链` 属于明确推荐；`网上很多人推荐天天外链，但风险较高` 不属于正向推荐。

## has_comparison

定义：Answer 是否出现品牌、方案、平台、工具之间的对比或优劣判断。

## 保存要求

每个事实必须保存：

```text
fact_type
fact_value
evidence_span
start_offset
end_offset
confidence
extractor
extractor_version
review_status
```
