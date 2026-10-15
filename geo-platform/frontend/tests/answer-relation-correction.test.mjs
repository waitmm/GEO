import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import { api } from '../src/api/client.ts';

test('correction client binds reads and writes to the selected formal task', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init = {}) => {
    calls.push({ url, method: init.method || 'GET', body: init.body && JSON.parse(init.body) });
    return Response.json({ preview_hash: 'a'.repeat(64) });
  });
  await api.getAnswerRelationCorrections('task/fixed', 1, 44);
  await api.previewAnswerRelationCorrection('task/fixed', { base_result_version: 'diag-v1' });
  await api.saveAnswerRelationCorrection('task/fixed', { preview_hash: 'a'.repeat(64), human_confirmed: true });
  assert.equal(calls[0].url, '/api/v2/single-prompt/optimization-tasks/task%2Ffixed/answer-relation-corrections?project_id=1&prompt_id=44');
  assert.equal(calls[1].url.endsWith('/answer-relation-corrections/preview'), true);
  assert.equal(calls[1].method, 'POST');
  assert.equal(calls[2].url.endsWith('/answer-relation-corrections'), true);
  assert.deepEqual(calls[2].body, { preview_hash: 'a'.repeat(64), human_confirmed: true });
});

test('formal Optimize panel exposes Chinese preview, immutable history, and no-recompute notice', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  const optimize = await readFile(new URL('../src/AutomaticOptimizePanel.tsx', import.meta.url), 'utf8');
  for (const text of ['纠正答案或证据关系', '预览影响范围', '受影响理由', '不受影响理由',
    '受影响策略方向', '不受影响策略方向', '受影响稿件', '不受影响稿件', '操作者：',
    '本纠错版本尚未重算或升级既有策略与稿件']) assert.match(source, new RegExp(text));
  assert.match(source, /human_confirmed: true/);
  assert.doesNotMatch(source, /actor\s*:/);
  assert.match(optimize, /task\.task_kind === "AUTOMATIC_OPTIMIZE"/);
  assert.match(optimize, /\["COMPLETED", "COMPLETED_WITH_LIMITATIONS"\]\.includes\(task\.status\)/);
  assert.match(optimize, /Array\.isArray\(task\.objects\.deliveries\)/);
  assert.match(optimize, /task\.objects\.deliveries\.length > 0/);
  assert.match(optimize, /answerRelationCorrectionReady\(task\) && <AnswerRelationCorrectionPanel/);
  assert.match(optimize, /AnswerRelationCorrectionPanel/);
});
