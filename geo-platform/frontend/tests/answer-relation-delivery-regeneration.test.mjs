import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('affected draft regeneration is available only from a complete, fully bound reprojection', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /重新生成受影响稿件/);
  assert.match(source, /status\.startsWith\("COMPLETED"\)/);
  assert.match(source, /reprojection\.objects\?\.answer_relation_reprojection/);
  assert.match(source, /manifest\?\.new_strategy_result_version/);
  assert.match(source, /manifest\?\.new_strategy_result_hash/);
  assert.match(source, /manifest\?\.affected_delivery_set_hash/);
  assert.match(source, /reprojection\.revision \?\? reprojection\.expected_revision/);
  assert.match(source, /pending_delivery_updates/);
  assert.match(source, /unchanged_deliveries/);
});

test('affected draft regeneration sends exactly the frozen scoped request and does not claim historical drafts changed', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /affected-draft-regenerations/);
  assert.match(source, /\$\{encodeURIComponent\(task\.task_id\)\}\/affected-draft-regenerations/);
  assert.doesNotMatch(source, /\$\{encodeURIComponent\(taskId\)\}\/affected-draft-regenerations/);
  for (const field of ['project_id', 'prompt_id', 'expected_revision', 'strategy_result_version', 'strategy_result_hash', 'affected_delivery_set_hash', 'idempotency_key']) {
    assert.match(source, new RegExp(`${field}:`));
  }
  assert.doesNotMatch(source, /actor\s*:/);
  assert.doesNotMatch(source, /budget\s*:/);
  assert.match(source, /历史稿件保持不变/);
  assert.match(source, /未受影响稿件保持不变/);
});

test('completed reprojection and regeneration statuses can be refreshed from their task views', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /刷新重投影状态/);
  assert.match(source, /刷新局部再生成状态/);
  assert.match(source, /encodeURIComponent\(reprojection\.task_id\)\}\?project_id=\$\{projectId\}&prompt_id=\$\{promptId\}/);
  assert.match(source, /encodeURIComponent\(deliveryRegeneration\.task_id\)\}\?project_id=\$\{projectId\}&prompt_id=\$\{promptId\}/);
});

test('delivery regeneration states and optional manifest are shown in Chinese', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.ok(source.includes('objects?.answer_relation_delivery_regeneration'));
  for (const text of ['局部稿件再生成任务已创建', '正在重新生成受影响稿件', '缺少已授权生成能力', '受影响稿件已生成新版本',
    'affected_deliveries', 'regenerated_deliveries', 'pending_deliveries', 'failed_deliveries', 'unchanged_deliveries',
    '受影响稿件', '已重新生成稿件', '待处理稿件', '失败稿件', '保持不变稿件']) {
    assert.match(source, new RegExp(text));
  }
});

test('completed reprojection summary reads the actual task-view manifest first', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /function reprojectionStrategyResultVersion/);
  assert.match(source, /manifest\?\.new_strategy_result_version/);
  assert.match(source, /reprojectionStrategyResultVersion\(reprojection\) \|\| "未返回"/);
});
