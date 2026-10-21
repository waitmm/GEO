import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

test('scheduled collection is collection-only and exposes guarded controls', () => {
  const source = readFileSync(new URL('../src/SamplingSchedulePanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /采集自动化，分析手动化/);
  assert.match(source, /collection_only: true/);
  assert.match(source, /external_collection_authorized/);
  assert.match(source, /立即采集/);
  assert.match(source, /暂停/);
  assert.match(source, /恢复/);
  assert.doesNotMatch(source, /采样完成后自动生成优化建议与稿件/);
});

test('range analysis previews then freezes exact run ids', () => {
  const source = readFileSync(new URL('../src/AnalysisRangePanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /LAST_7_DAYS/);
  assert.match(source, /LAST_14_DAYS/);
  assert.match(source, /LAST_30_DAYS/);
  assert.match(source, /analysis-ranges/);
  assert.match(source, /preview_hash/);
  assert.match(source, /selected_run_ids/);
  assert.match(source, /不会静默混合/);
});
