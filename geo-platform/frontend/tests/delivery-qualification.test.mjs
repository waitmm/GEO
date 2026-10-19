import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { readDeliveryQualification } from '../src/deliveryQualification.ts';

const plan = {
  contract_version: 'DeliveryQualificationPlan.v1', plan_id: 'plan-1', plan_version: 'plan-v1', plan_hash: 'plan-hash',
  qualification: { qualification_version: 'qualification-v1', qualification_hash: 'qualification-hash', direction_id: 'direction-1' },
  planned_delivery_level: 'L3_ACTIONABLE_WITHOUT_FACT_CLAIMS', product_outcome: 'NONE', delivery_type: 'ACTION_PLAN',
  public_claim_eligibility: 'NOT_CONSUMABLE', publication_eligibility: 'VERIFY_FIRST', allowed_block_kinds: ['INSTRUCTION'],
};

const result = {
  contract_version: 'DeliveryQualificationResult.v1', result_id: 'result-1', result_version: 'result-v1', result_hash: 'result-hash',
  plan_id: 'plan-1', plan_version: 'plan-v1', plan_hash: 'plan-hash', qualification_version: 'qualification-v1', qualification_hash: 'qualification-hash',
  admitted_delivery_level: 'L3_ACTIONABLE_WITHOUT_FACT_CLAIMS', delivery_type: 'ACTION_PLAN', qa_status: 'READY_INTERNAL',
  product_outcome: 'CONTENT_DELIVERED', public_claim_eligibility: 'NOT_CONSUMABLE', publication_eligibility: 'VERIFY_FIRST',
};

test('uses only a coherent frozen plan/result projection and never infers a tier from evidence', () => {
  assert.equal(readDeliveryQualification({}).kind, 'ABSENT');
  const state = readDeliveryQualification({
    delivery_qualification_plans: [plan], delivery_qualification_results: [result],
    delivery_outcome: { product_outcome: 'CONTENT_DELIVERED', highest_level: 'L3_ACTIONABLE_WITHOUT_FACT_CLAIMS', all_directions_l1: false,
      direction_results: [{ direction_id: 'direction-1', plan_id: 'plan-1', plan_version: 'plan-v1', plan_hash: 'plan-hash', result_id: 'result-1', result_version: 'result-v1', result_hash: 'result-hash', product_outcome: 'CONTENT_DELIVERED' }] },
  });
  assert.equal(state.kind, 'NORMAL');
  if (state.kind === 'NORMAL') assert.equal(state.results[0].admitted_delivery_level, 'L3_ACTIONABLE_WITHOUT_FACT_CLAIMS');
});

test('refuses a result whose frozen plan identity does not match', () => {
  const state = readDeliveryQualification({
    delivery_qualification_plans: [plan], delivery_qualification_results: [{ ...result, plan_hash: 'other-plan-hash' }],
    delivery_outcome: { product_outcome: 'CONTENT_DELIVERED', all_directions_l1: false, direction_results: [] },
  });
  assert.equal(state.kind, 'UNKNOWN');
});

test('recognizes L4 only as a zero-call recovery package that cannot unlock content delivery', () => {
  const recovery = {
    ...result, admitted_delivery_level: 'L4_RECOVERY_PACKAGE', delivery_type: 'RECOVERY_ACTIONS',
    product_outcome: 'RECOVERY_REQUIRED', downstream_content_delivery_dependency_satisfied: false, external_model_calls: 0,
    recovery_actions: ['补充有效采样'], reentry_conditions: ['形成固定有效回答'], missing_objects: ['有效回答'], reasons: ['当前输入不可分析'],
  };
  const recoveryPlan = { ...plan, planned_delivery_level: 'L4_RECOVERY_PACKAGE', delivery_type: 'RECOVERY_ACTIONS' };
  const state = readDeliveryQualification({
    delivery_qualification_plans: [recoveryPlan], delivery_qualification_results: [], recovery_delivery: recovery,
    delivery_outcome: { product_outcome: 'RECOVERY_REQUIRED', highest_level: 'L4_RECOVERY_PACKAGE', lowest_level: 'L4_RECOVERY_PACKAGE', all_directions_l1: false,
      direction_results: [{ direction_id: 'direction-1', plan_id: 'plan-1', plan_version: 'plan-v1', plan_hash: 'plan-hash', result_id: 'result-1', result_version: 'result-v1', result_hash: 'result-hash', admitted_delivery_level: 'L4_RECOVERY_PACKAGE', product_outcome: 'RECOVERY_REQUIRED' }] },
  });
  assert.equal(state.kind, 'RECOVERY');
  assert.equal(readDeliveryQualification({
    delivery_qualification_plans: [recoveryPlan], delivery_qualification_results: [], recovery_delivery: { ...recovery, external_model_calls: 1 },
    delivery_outcome: { product_outcome: 'RECOVERY_REQUIRED', highest_level: 'L4_RECOVERY_PACKAGE', lowest_level: 'L4_RECOVERY_PACKAGE', all_directions_l1: false,
      direction_results: [{ direction_id: 'direction-1', plan_id: 'plan-1', plan_version: 'plan-v1', plan_hash: 'plan-hash', result_id: 'result-1', result_version: 'result-v1', result_hash: 'result-hash', admitted_delivery_level: 'L4_RECOVERY_PACKAGE', product_outcome: 'RECOVERY_REQUIRED' }] },
  }).kind, 'UNKNOWN');
});

test('formal Optimize UI renders all four levels conservatively and keeps history selection separate', async () => {
  const [panel, card, helper, selection] = await Promise.all([
    readFile(new URL('../src/AutomaticOptimizePanel.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/DeliveryQualificationCard.tsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/deliveryQualification.ts', import.meta.url), 'utf8'),
    readFile(new URL('../src/optimizationSelection.ts', import.meta.url), 'utf8'),
  ]);
  assert.match(panel, /<DeliveryQualificationCard objects=\{task\.objects\}/);
  for (const text of ['L1 完整证据交付', 'L2 受约束交付', 'L3 行动交付', 'L4 恢复交付']) {
    assert.match(helper, new RegExp(text));
  }
  assert.match(card, /不声明品牌能力、平台规则、数字效果或 Citation 支持/);
  assert.match(card, /不会生成 Draft\/QA 成功结果，也不会解锁内容交付依赖/);
  assert.match(selection, /optimization_task/);
  assert.match(selection, /v2_execution_result/);
});
