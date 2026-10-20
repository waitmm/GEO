type BrandAssociationValues = {
  association_goals?: string;
  verified_capabilities?: string;
  verified_sources?: string;
  pending_capabilities?: string;
  prohibited_claims?: string;
  content_assets?: string;
  channels?: string;
};

export function brandAssociationContent(values: BrandAssociationValues) {
  const section = (title: string, body?: string) => `## ${title}\n${body?.trim() || "未提供"}`;
  return [
    section("希望建立的品牌关联（仅为优化目标，不是产品事实）", values.association_goals),
    section("项目组声明为已核实的产品能力（仍须通过 Product Truth 与来源资格校验）", values.verified_capabilities),
    section("上述能力的来源与维护依据", values.verified_sources),
    section("待核实能力与资料缺口", values.pending_capabilities),
    section("禁止使用的品牌表述", values.prohibited_claims),
    section("可供考虑的内容资产", values.content_assets),
    section("可供考虑的发布渠道", values.channels),
  ].join("\n\n");
}
