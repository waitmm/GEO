import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const panel = new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url);

test('local delivery authorization is available only for a fully bound waiting task', async () => {
  const source = await readFile(panel, 'utf8');
  assert.match(source, /task\.status === "WAITING_AUTHORIZATION"/);
  assert.match(source, /typeof task\.revision === "number"/);
  assert.match(source, /!!task\.input_hash/);
  assert.match(source, /typeof count === "number" && Number\.isInteger\(count\) && count > 0/);
  assert.match(source, /授权局部稿件生成/);
});

test('authorization submits the exact bounded budget payload and adopts its returned task view', async () => {
  const source = await readFile(panel, 'utf8');
  assert.match(source, /\$\{encodeURIComponent\(deliveryRegeneration\.task_id\)\}\/authorization/);
  for (const field of [
    'project_id: projectId',
    'prompt_id: promptId',
    'expected_revision: deliveryRegeneration.revision',
    'input_hash: deliveryRegeneration.input_hash',
    'max_requests: 2 \* affectedCount',
    'max_tokens: values.max_tokens',
    'max_cost_cny: values.max_cost_cny',
    'conservative_cny_per_million_tokens: values.conservative_cny_per_million_tokens',
    'pricing_source: values.pricing_source',
    'pricing_checked_at: values.pricing_checked_at',
  ]) assert.ok(source.includes(field));
  assert.doesNotMatch(source, /actor\s*:/);
  assert.match(source, /setDeliveryRegeneration\(authorized\)/);
  const authorization = source.slice(source.indexOf('async function authorizeDeliveryRegeneration'), source.indexOf('return <>'));
  assert.doesNotMatch(authorization, /\/resume|\/execute|mutate\(/);
});

test('authorization makes the finite scope and non-execution boundary explicit', async () => {
  const source = await readFile(panel, 'utf8');
  for (const text of [
    '这是人工有限授权，不会自动执行或表示稿件已完成。',
    '每稿最多生成加 QA 两次请求',
    '不会抓取来源、重算上游或改动历史稿件。',
    '请求次数上限（固定为每稿生成加 QA 两次）',
    '总 token 上限',
    '人民币硬预算',
    '已核实计费依据',
    '计费核实日期',
  ]) assert.match(source, new RegExp(text));
  assert.match(source, /<InputNumber value=\{2 \* \(affectedDeliveryCount\(deliveryRegeneration\) \|\| 0\)\} disabled/);
});
