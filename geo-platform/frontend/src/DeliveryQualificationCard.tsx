import { Alert, Collapse, Descriptions, Empty, Space, Tag, Typography } from "antd";
import { deliveryLevelLabel, listText, readDeliveryQualification, type QualificationPlan, type QualificationResult } from "./deliveryQualification";

function planDescription(plan: QualificationPlan) {
  const level = plan.planned_delivery_level;
  if (level === "L1_FULLY_GROUNDED") return "仅固定且可消费的证据/品牌事实可支撑正文事实表述。";
  if (level === "L2_PARTIALLY_GROUNDED") return "仅独立支持的内容可作事实表述；其余内容必须删除或作为待核验事项。";
  if (level === "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS") return "仅提供行动、研究与核验内容，不声明品牌能力、平台规则、数字效果或 Citation 支持。";
  return "不生成正文或 QA 成功结果；仅提供恢复动作，且不会解锁内容交付依赖。";
}

function resultDescription(result: QualificationResult) {
  if (result.admitted_delivery_level === "REJECTED") return "本次输出未被接纳；不会将失败正文降级后保留。";
  if (result.product_outcome !== "CONTENT_DELIVERED") return "尚未形成已接纳的内容交付。";
  return result.admitted_delivery_level === "L1_FULLY_GROUNDED" ? "已接纳为完整证据交付。"
    : result.admitted_delivery_level === "L2_PARTIALLY_GROUNDED" ? "已接纳为受约束交付；请逐项查看待核验内容。"
      : "已接纳为行动交付；不包含可当作事实使用的内容。";
}

function PlanView({ plan, result }: { plan: QualificationPlan; result?: QualificationResult }) {
  const limitations = listText(plan.limitations);
  const label = plan.planned_delivery_level ? deliveryLevelLabel[plan.planned_delivery_level] : "未知等级";
  return <section aria-label={`交付分级 ${plan.qualification?.direction_id || plan.plan_id}`}>
    <Space wrap><Tag color={plan.planned_delivery_level === "L1_FULLY_GROUNDED" ? "green" : plan.planned_delivery_level === "L4_RECOVERY_PACKAGE" ? "orange" : "blue"}>{label}</Tag>
      <Typography.Text type="secondary">固定计划 {plan.plan_version}</Typography.Text></Space>
    <Typography.Paragraph style={{ margin: "8px 0" }}>{planDescription(plan)}</Typography.Paragraph>
    <Descriptions size="small" column={{ xs: 1, md: 2 }}>
      <Descriptions.Item label="事实使用边界">{plan.public_claim_eligibility || "未返回"}</Descriptions.Item>
      <Descriptions.Item label="发布边界">{plan.publication_eligibility || "未返回"}</Descriptions.Item>
      <Descriptions.Item label="允许内容类型">{listText(plan.allowed_block_kinds).join("、") || "未返回"}</Descriptions.Item>
      <Descriptions.Item label="证据资格">{plan.evidence_qualification || "未返回"}</Descriptions.Item>
    </Descriptions>
    {limitations.length > 0 && <Typography.Paragraph type="secondary">限制：{limitations.join("；")}</Typography.Paragraph>}
    {result && <Alert type={result.admitted_delivery_level === "REJECTED" ? "warning" : "success"} showIcon
      message={resultDescription(result)} description={<Space direction="vertical" size={0}>
        <span>实际等级：{result.admitted_delivery_level || "未返回"}；产品结果：{result.product_outcome || "未返回"}</span>
        {result.admitted_delivery_level !== "L4_RECOVERY_PACKAGE" && <span>文本检查：{result.qa_status || "未返回"}</span>}
      </Space>} style={{ marginTop: 8 }} />}
  </section>;
}

/** Displays only backend-frozen qualification projections; no evidence-count inference. */
export function DeliveryQualificationCard({ objects }: { objects?: Record<string, unknown> }) {
  const state = readDeliveryQualification(objects);
  if (state.kind === "ABSENT") return <Alert type="info" showIcon style={{ marginTop: 12 }} message="尚未形成冻结交付分级"
    description="历史任务保留原记录；系统不会根据证据数量、任务状态或旧失败信息推断 L1–L4。" />;
  if (state.kind === "UNKNOWN") return <Alert type="warning" showIcon style={{ marginTop: 12 }} message="交付分级无法安全确认" description={state.reason} />;
  if (state.kind === "RECOVERY") {
    const actions = listText(state.recovery.recovery_actions);
    const conditions = listText(state.recovery.reentry_conditions);
    const missing = listText(state.recovery.missing_objects);
    const reasons = listText(state.recovery.reasons);
    return <Alert type="warning" showIcon style={{ marginTop: 12 }} message="L4 恢复交付：当前范围尚不能形成内容交付"
      description={<Space direction="vertical" size={6} style={{ width: "100%" }}>
        <span>仅在固定身份、权限、版本与范围完整时提供恢复包；本包不会生成 Draft/QA 成功结果，也不会解锁内容交付依赖。</span>
        <span>模型调用：0；下游内容交付依赖：不满足。</span>
        {missing.length > 0 && <span>缺失对象：{missing.join("、")}</span>}
        {reasons.length > 0 && <span>原因：{reasons.join("；")}</span>}
        {actions.length > 0 && <div><Typography.Text strong>恢复动作：</Typography.Text><ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>{actions.map(item => <li key={item}>{item}</li>)}</ul></div>}
        {conditions.length > 0 && <div><Typography.Text strong>重新进入条件：</Typography.Text><ul style={{ margin: "4px 0 0", paddingLeft: 20 }}>{conditions.map(item => <li key={item}>{item}</li>)}</ul></div>}
      </Space>} />;
  }
  const resultFor = (plan: QualificationPlan) => state.results.find(result => result.plan_id === plan.plan_id);
  return <Collapse style={{ marginTop: 12 }} items={[{
    key: "delivery-qualification", label: `冻结交付分级（${state.plans.length} 个方向）`, children: <Space direction="vertical" style={{ width: "100%" }} size={16}>
      <Typography.Paragraph type="secondary">交付等级仅来自固定资格计划与实际接纳结果；L2/L3 不表示 L1 Evidence 或专项 E1/E2/E3 验收通过。</Typography.Paragraph>
      {state.plans.map(plan => <PlanView key={plan.plan_id} plan={plan} result={resultFor(plan)} />)}
      {!state.results.length && <Empty description="资格计划已固定，尚未形成实际接纳结果" />}
    </Space>,
  }]} />;
}
