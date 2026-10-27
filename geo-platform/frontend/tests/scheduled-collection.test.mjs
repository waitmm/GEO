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
  assert.match(source, /编辑采集计划/);
  assert.match(source, /method: "PUT"/);
  assert.match(source, /避免重复创建同一问题的计划/);
  assert.match(source, /formatBeijingDateTime/);
  assert.match(source, /Asia\/Shanghai/);
  assert.doesNotMatch(source, /new Date\(row\.next_due_at\)/);
  assert.doesNotMatch(source, /采样完成后自动生成优化建议与稿件/);
});

test('range analysis confirms an exact immutable answer set in business language', () => {
  const source = readFileSync(new URL('../src/AnalysisRangePanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /LAST_7_DAYS/);
  assert.match(source, /LAST_14_DAYS/);
  assert.match(source, /LAST_30_DAYS/);
  assert.match(source, /analysis-ranges/);
  assert.match(source, /preview_hash/);
  assert.match(source, /selected_run_ids/);
  assert.match(source, /不会把不兼容的数据混在一起/);
  assert.match(source, /选择本次要分析的回答/);
  assert.match(source, /确认使用这/);
  assert.match(source, /beijingLocalDateTimeToIso/);
  assert.match(source, /开始（北京时间）/);
  assert.doesNotMatch(source, /new Date\(values\.start_at\)/);
});

test('Optimize consumes a Monitor selection and no longer creates samples', () => {
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.match(source, /前往 Monitor 选择回答/);
  assert.match(source, /采集、人工导入和时间范围筛选都在 Monitor 完成/);
  assert.match(source, /当前数据范围/);
  assert.match(source, /analysisRangeLabel/);
  assert.match(source, /selector\.start_at/);
  assert.match(source, /selector\.end_at/);
  assert.doesNotMatch(source, /新建采样必须绑定明确的 Prompt 冻结版本/);
  assert.doesNotMatch(source, />新增采样</);
  assert.doesNotMatch(source, />开始首次采样</);
  assert.doesNotMatch(source, /用所选 Run 建立分析版本/);
});
