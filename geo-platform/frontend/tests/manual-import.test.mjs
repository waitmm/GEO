import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';

test('manual import requires explicit versions, preview and provenance warning', () => {
  const source = readFileSync(new URL('../src/ManualImportPanel.tsx', import.meta.url), 'utf8');
  assert.match(source, /人工来源声明，不是平台真实性认证/);
  assert.match(source, /prompt_version_id/);
  assert.match(source, /configuration_version_id/);
  assert.match(source, /observed_at/);
  assert.match(source, /citation_observation_status/);
  assert.match(source, /UNKNOWN/);
  assert.match(source, /CONFIRMED_NONE/);
  assert.match(source, /PARSE_FAILED/);
  assert.match(source, /预览导入/);
  assert.match(source, /确认冻结并导入/);
  assert.match(source, /manual-imports/);
  assert.doesNotMatch(source, /\/latest|prompts\[0\]|configs\[0\]/i);
});

test('monitor exposes manual import and range shows manual provenance', () => {
  const observation = readFileSync(new URL('../src/ObservationPanel.tsx', import.meta.url), 'utf8');
  const range = readFileSync(new URL('../src/AnalysisRangePanel.tsx', import.meta.url), 'utf8');
  assert.match(observation, /人工导入回答/);
  assert.match(range, /人工导入/);
  assert.match(range, /平台未独立核实/);
});
