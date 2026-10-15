import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('answer/relation correction offers one scoped strategy reprojection action', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  for (const text of [
    '更新受影响策略',
    '策略已重新投影',
    '稿件尚未重新生成',
    '受影响稿件待更新',
    '未受影响稿件保持不变',
  ]) assert.match(source, new RegExp(text));
  assert.match(source, /answer-relation-reprojections/);
  assert.match(source, /correction_result_version/);
  assert.match(source, /correction_result_hash/);
  assert.match(source, /idempotency_key/);
  assert.doesNotMatch(source, /actor\s*:/);
});

test('reprojection UI does not claim manuscript generation or trigger a broad rerun', async () => {
  const source = await readFile(new URL('../src/AnswerRelationCorrectionPanel.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /重新生成全部/);
  assert.doesNotMatch(source, /全量重算/);
  assert.doesNotMatch(source, /source_fetch_authorized\s*:\s*true/);
  assert.doesNotMatch(source, /ALLOW_EXTERNAL/);
});
