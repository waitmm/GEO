export type DeliveryLevel =
  | "L1_FULLY_GROUNDED"
  | "L2_PARTIALLY_GROUNDED"
  | "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS"
  | "L4_RECOVERY_PACKAGE";

export type QualificationPlan = {
  contract_version?: string;
  plan_id?: string;
  plan_version?: string;
  plan_hash?: string;
  qualification?: { qualification_version?: string; qualification_hash?: string; direction_id?: string | null };
  planned_delivery_level?: DeliveryLevel;
  product_outcome?: string;
  delivery_type?: string;
  evidence_qualification?: string;
  public_claim_eligibility?: string;
  publication_eligibility?: string;
  allowed_block_kinds?: string[];
  limitations?: unknown[];
};

export type QualificationResult = {
  contract_version?: string;
  result_id?: string;
  result_version?: string;
  result_hash?: string;
  plan_id?: string;
  plan_version?: string;
  plan_hash?: string;
  qualification_version?: string;
  qualification_hash?: string;
  admitted_delivery_level?: DeliveryLevel | "REJECTED" | "NOT_APPLICABLE";
  delivery_type?: string;
  qa_status?: string;
  product_outcome?: string;
  public_claim_eligibility?: string;
  publication_eligibility?: string;
};

export type RecoveryDelivery = QualificationResult & {
  missing_objects?: unknown[];
  reasons?: unknown[];
  recovery_actions?: unknown[];
  reentry_conditions?: unknown[];
  downstream_content_delivery_dependency_satisfied?: boolean;
  external_model_calls?: number;
};

export type DeliveryQualificationState =
  | { kind: "ABSENT" }
  | { kind: "UNKNOWN"; reason: string }
  | { kind: "NORMAL"; plans: QualificationPlan[]; results: QualificationResult[]; outcome: Record<string, unknown> }
  | { kind: "RECOVERY"; plan?: QualificationPlan; recovery: RecoveryDelivery; outcome: Record<string, unknown> };

const levels = new Set<DeliveryLevel>([
  "L1_FULLY_GROUNDED",
  "L2_PARTIALLY_GROUNDED",
  "L3_ACTIONABLE_WITHOUT_FACT_CLAIMS",
  "L4_RECOVERY_PACKAGE",
]);

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function text(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function samePlan(result: QualificationResult, plan: QualificationPlan) {
  return text(result.plan_id) && result.plan_id === plan.plan_id
    && text(result.plan_version) && result.plan_version === plan.plan_version
    && text(result.plan_hash) && result.plan_hash === plan.plan_hash
    && text(result.qualification_version) && result.qualification_version === plan.qualification?.qualification_version
    && text(result.qualification_hash) && result.qualification_hash === plan.qualification?.qualification_hash;
}

function validPlan(value: unknown): value is QualificationPlan {
  const plan = record(value) as QualificationPlan | undefined;
  return !!plan && text(plan.contract_version) && text(plan.plan_id) && text(plan.plan_version) && text(plan.plan_hash)
    && !!plan.qualification && text(plan.qualification.qualification_version) && text(plan.qualification.qualification_hash)
    && !!plan.planned_delivery_level && levels.has(plan.planned_delivery_level) && plan.product_outcome === "NONE";
}

function validResult(value: unknown): value is QualificationResult {
  const result = record(value) as QualificationResult | undefined;
  return !!result && text(result.contract_version) && text(result.result_id) && text(result.result_version) && text(result.result_hash)
    && text(result.plan_id) && text(result.plan_version) && text(result.plan_hash)
    && text(result.qualification_version) && text(result.qualification_hash)
    && (levels.has(result.admitted_delivery_level as DeliveryLevel) || result.admitted_delivery_level === "REJECTED")
    && text(result.product_outcome);
}

function validRecovery(value: unknown): value is RecoveryDelivery {
  const recovery = value as RecoveryDelivery;
  return validResult(recovery)
    && recovery.admitted_delivery_level === "L4_RECOVERY_PACKAGE"
    && recovery.delivery_type === "RECOVERY_ACTIONS"
    && recovery.product_outcome === "RECOVERY_REQUIRED"
    && recovery.downstream_content_delivery_dependency_satisfied === false
    && recovery.external_model_calls === 0
    && Array.isArray(recovery.recovery_actions)
    && Array.isArray(recovery.reentry_conditions);
}

function coherentOutcome(outcome: Record<string, unknown>, plans: QualificationPlan[], results: QualificationResult[]) {
  const directions = outcome.direction_results;
  if (!Array.isArray(directions) || typeof outcome.product_outcome !== "string" || typeof outcome.all_directions_l1 !== "boolean") return false;
  return directions.every(value => {
    const direction = record(value);
    if (!direction || !text(direction.plan_id) || !text(direction.plan_version) || !text(direction.plan_hash)
      || !text(direction.product_outcome)) return false;
    const plan = plans.find(item => item.plan_id === direction.plan_id && item.plan_version === direction.plan_version && item.plan_hash === direction.plan_hash);
    if (!plan) return false;
    if (direction.result_id === undefined && direction.result_version === undefined && direction.result_hash === undefined) return true;
    return results.some(result => result.plan_id === direction.plan_id && result.plan_version === direction.plan_version
      && result.plan_hash === direction.plan_hash && result.result_id === direction.result_id
      && result.result_version === direction.result_version && result.result_hash === direction.result_hash
      && result.product_outcome === direction.product_outcome);
  });
}

/**
 * Read only frozen, append-only qualification projections.  Deliberately do
 * not infer a tier from selected evidence, task status, or legacy blockers.
 */
export function readDeliveryQualification(objects: Record<string, unknown> | undefined): DeliveryQualificationState {
  const source = objects || {};
  const hasAny = ["delivery_qualification_plans", "delivery_qualification_results", "delivery_outcome", "recovery_delivery"]
    .some(key => Object.prototype.hasOwnProperty.call(source, key));
  if (!hasAny) return { kind: "ABSENT" };

  const outcome = record(source.delivery_outcome);
  const rawPlans = source.delivery_qualification_plans;
  const rawResults = source.delivery_qualification_results;
  const plans = Array.isArray(rawPlans) ? rawPlans : [];
  const results = Array.isArray(rawResults) ? rawResults : [];
  const recovery = source.recovery_delivery;

  if (!outcome) return { kind: "UNKNOWN", reason: "缺少冻结交付汇总，不能推断交付等级。" };
  if (recovery !== undefined) {
    if (!validRecovery(recovery)) return { kind: "UNKNOWN", reason: "恢复包身份或边界不完整，不能将其展示为 L4。" };
    if (!Array.isArray(rawPlans) || !plans.every(validPlan)) return { kind: "UNKNOWN", reason: "恢复包缺少冻结资格计划。" };
    const recoveryPlan = (plans as QualificationPlan[]).find(plan => plan.planned_delivery_level === "L4_RECOVERY_PACKAGE");
    if (!recoveryPlan || !samePlan(recovery, recoveryPlan)) return { kind: "UNKNOWN", reason: "恢复包与冻结资格计划不匹配。" };
    if (outcome.product_outcome !== "RECOVERY_REQUIRED" || outcome.highest_level !== "L4_RECOVERY_PACKAGE"
      || outcome.lowest_level !== "L4_RECOVERY_PACKAGE" || outcome.all_directions_l1 !== false
      || !coherentOutcome(outcome, plans as QualificationPlan[], [recovery])) {
      return { kind: "UNKNOWN", reason: "恢复包与任务交付汇总不一致。" };
    }
    return { kind: "RECOVERY", plan: recoveryPlan, recovery, outcome };
  }

  if (!Array.isArray(rawPlans) || !plans.length || !plans.every(validPlan) || !Array.isArray(rawResults) || !results.every(validResult)) {
    return { kind: "UNKNOWN", reason: "冻结交付计划或结果格式不完整，不能显示为已交付。" };
  }
  const typedPlans = plans as QualificationPlan[];
  const typedResults = results as QualificationResult[];
  if (typedResults.some(result => !typedPlans.some(plan => samePlan(result, plan)))) {
    return { kind: "UNKNOWN", reason: "交付结果未精确绑定当前冻结资格计划。" };
  }
  if (!coherentOutcome(outcome, typedPlans, typedResults)) {
    return { kind: "UNKNOWN", reason: "交付汇总没有精确引用当前冻结计划与结果。" };
  }
  return { kind: "NORMAL", plans: typedPlans, results: typedResults, outcome };
}

export const deliveryLevelLabel: Record<DeliveryLevel, string> = {
  L1_FULLY_GROUNDED: "L1 事实块已完整归属",
  L2_PARTIALLY_GROUNDED: "L2 受约束交付",
  L3_ACTIONABLE_WITHOUT_FACT_CLAIMS: "L3 行动交付",
  L4_RECOVERY_PACKAGE: "L4 恢复交付",
};

export function listText(value: unknown): string[] {
  return Array.isArray(value) ? value.filter(text) : [];
}
