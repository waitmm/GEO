import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const panel = new URL('../src/ObservationPanel.tsx', import.meta.url);

test('T22 report keeps counts, percentage points, and a non-causal small-sample limitation together', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /function?\s*comparisonObservation|const comparisonObservation/);
  assert.match(source, /正文提及本轮观察：基线/);
  assert.match(source, /变化 \$\{delta\}/);
  assert.match(source, /delta_percentage_points == null/);
  assert.match(source, /小样本和单轮变化不能自动判定策略有效/);
  assert.match(source, /不会自动晋升为策略规则/);
  assert.match(source, /未知条件及未计算语义不按零结果处理/);
});

test('T22 report makes citation observation and incomplete ranges visibly distinct', async () => {
  const source = await readFile(panel, 'utf8');

  for (const label of ['本范围首次观察到', '持续观察到', '对照范围未再观察到']) assert.match(source, new RegExp(label));
  assert.match(source, /引用采集范围不完整/);
  assert.match(source, /尚不能判为新增或消失/);
  assert.match(source, /不证明优化效果或生成因果/);
});

test('T22 report preserves all saved comparison history and refresh restoration', async () => {
  const source = await readFile(panel, 'utf8');

  assert.match(source, /setHistory\(current => \[next, \.\.\.current\.filter/);
  assert.match(source, /历史比较/);
  assert.match(source, /restoreComparison\(history\.find/);
  assert.match(source, /刷新当前页面/);
  assert.match(source, /observation_result/);
});
