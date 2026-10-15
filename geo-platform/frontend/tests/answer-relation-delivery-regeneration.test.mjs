import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('affected draft regeneration is available only from a complete, fully bound reprojection', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /重新生成受影响稿件/);
  assert.match(source, /status\.startsWith\("COMPLETED"\)/);
  for (const field of ['expected_revision', 'strategy_result_version', 'strategy_result_hash', 'affected_delivery_set_hash']) {
    assert.match(source, new RegExp(`!reprojection\\.${field}|${field}: result\\.${field}`));
  }
});

test('affected draft regeneration sends exactly the frozen scoped request and does not claim historical drafts changed', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /affected-draft-regenerations/);
  for (const field of ['project_id', 'prompt_id', 'expected_revision', 'strategy_result_version', 'strategy_result_hash', 'affected_delivery_set_hash', 'idempotency_key']) {
    assert.match(source, new RegExp(`${field}:`));
  }
  assert.doesNotMatch(source, /actor\s*:/);
  assert.doesNotMatch(source, /budget\s*:/);
  assert.match(source, /历史稿件保持不变/);
  assert.match(source, /未受影响稿件保持不变/);
});

test('delivery regeneration states and optional manifest are shown in Chinese', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  for (const text of ['局部稿件再生成任务已创建', '正在重新生成受影响稿件', '缺少已授权生成能力', '受影响稿件已生成新版本', 'affected', 'regenerated', 'pending', 'failed', 'unchanged']) {
    assert.match(source, new RegExp(text));
  }
});
