import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const panel = new URL('../src/ObservationPanel.tsx', import.meta.url);

test('T21 compare restores the saved two scopes and answer versions without silently changing samples', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /observation-scopes/);
  assert.match(source, /observation-comparisons/);
  assert.match(source, /setLeft\(saved\.input\.baseline\.context_id\); setRight\(saved\.input\.comparison\.context_id\);/);
  assert.match(source, /setLeftAnswer\(saved\.input\.baseline\.answer_result_version \|\| undefined\);/);
  assert.match(source, /setRightAnswer\(saved\.input\.comparison\.answer_result_version \|\| undefined\);/);
  assert.match(source, /baseline: ref\(left, leftAnswer\), comparison: ref\(right, rightAnswer\)/);
  assert.match(source, /change\(v\); answerChange\(undefined\); setResult\(undefined\);/);
  assert.match(source, /answerChange\(v\); setResult\(undefined\);/);
});

test('T21 compare explicitly labels incompatible collection entries and retains both observations', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /条件不可比/);
  for (const label of ['采样平台', '采样来源类型', '采集器', '问题原文', '采样模式']) assert.match(source, new RegExp(label));
  assert.match(source, /delta_percentage_points \?\? "不可比\/不可计算"/);
  assert.match(source, /仅报告观察变化，不证明优化效果或生成因果/);
  assert.match(source, /<AnswerDetails measurement=\{output\.baseline\} \/>/);
  assert.match(source, /<AnswerDetails measurement=\{output\.comparison\} \/>/);
  assert.match(source, /当前展示的是保存时的测量身份；项目配置更新不会改写此结果。/);
});
