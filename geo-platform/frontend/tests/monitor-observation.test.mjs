import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const panel = new URL('../src/ObservationPanel.tsx', import.meta.url);

test('T07 project summary keeps Prompt Macro Average and run-weighted metrics distinct', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /按问题平均/);
  assert.match(source, /prompt_macro_average/);
  assert.match(source, /参与 \/ 全部问题/);
  assert.match(source, /participating_prompt_count/);
  assert.match(source, /按样本加权/);
  assert.match(source, /run_weighted_average/);
  assert.match(source, /row\.data\.hit_count\}\/\$\{row\.data\.evaluable_count/);
});

test('T07 retains evaluated denominators, zero results, N\/A, and Run-level detail separately', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /m\?\.value == null \? "不可计算"/);
  assert.match(source, /\$\{m\.hit_count\}\/\$\{m\.evaluable_count\}/);
  assert.match(source, /可评估 \/ 有效原始 \/ 计划/);
  assert.match(source, /UnknownMembers/);
  assert.match(source, /回答计算失败，未按零计入/);
  assert.match(source, /Run \$\{run\.run_id\}/);
});

test('T07 trend makes frozen Run scope and prompt-version isolation visible across refreshes', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /按日期观察（北京时间）/);
  assert.match(source, /从这里开始：选择一段时间内的回答/);
  assert.match(source, /defaultActiveKey=\{\["range"\]\}/);
  assert.match(source, /title: "固定范围"/);
  assert.match(source, /趋势按各日期各自冻结的 Run 范围/);
  assert.match(source, /历史问题版本的回答（\$\{pool\.historical_query_runs\.length\}），不混入当前问题指标/);
  assert.match(source, /const controller = new AbortController\(\)/);
  assert.match(source, /controller\.abort\(\)/);
});
