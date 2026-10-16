import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const panel = new URL('../src/ObservationPanel.tsx', import.meta.url);

test('T21 comparison preserves two saved scope and answer-version identities', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /observation-scopes/);
  assert.match(source, /observation-comparisons/);
  assert.match(source, /baseline: ref\(left, leftAnswer\), comparison: ref\(right, rightAnswer\)/);
  assert.match(source, /setLeft\(saved\.input\.baseline\.context_id\); setRight\(saved\.input\.comparison\.context_id\);/);
  assert.match(source, /setLeftAnswer\(saved\.input\.baseline\.answer_result_version \|\| undefined\);/);
  assert.match(source, /setRightAnswer\(saved\.input\.comparison\.answer_result_version \|\| undefined\);/);
  assert.match(source, /固定范围身份/);
  assert.match(source, /comparisonInput\.baseline/);
  assert.match(source, /comparisonInput\.comparison/);
});

test('T21 changing a scope never leaves an old history selection to be restored as current', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /function clearComparisonSelection\(\)/);
  assert.match(source, /params\.delete\("observation_result"\)/);
  assert.match(source, /change\(v\); answerChange\(undefined\); clearComparisonSelection\(\);/);
  assert.match(source, /answerChange\(v\); clearComparisonSelection\(\);/);
  assert.match(source, /onChange=\{e => \{ setTarget\(e\.target\.value\); clearComparisonSelection\(\); \}\}/);
  assert.match(source, /指定的历史比较不存在或不属于当前问题，未替换为其他范围。/);
});

test('T21 displays incompatibility instead of presenting an unsupported effect conclusion', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /条件不可比/);
  for (const label of ['采样平台', '采样来源类型', '采集器', '问题原文', '采样模式']) assert.match(source, new RegExp(label));
  assert.match(source, /delta_percentage_points \?\? "不可比\/不可计算"/);
  assert.match(source, /仅报告观察变化，不证明优化效果或生成因果/);
  assert.match(source, /<AnswerDetails measurement=\{output\.baseline\} \/>/);
  assert.match(source, /<AnswerDetails measurement=\{output\.comparison\} \/>/);
});
