import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const app = new URL('../src/App.tsx', import.meta.url);
const client = new URL('../src/api/client.ts', import.meta.url);
const types = new URL('../src/types.ts', import.meta.url);
const observation = new URL('../src/ObservationPanel.tsx', import.meta.url);
const schedule = new URL('../src/SamplingSchedulePanel.tsx', import.meta.url);

test('new sampling and selected-run analyses submit an exact PromptVersion binding', async () => {
  const [appSource, clientSource] = await Promise.all([readFile(app, 'utf8'), readFile(client, 'utf8')]);
  for (const field of ['prompt_version_id: v2SelectedPromptVersion.prompt_version_id', 'snapshot_hash: v2SelectedPromptVersion.snapshot_hash']) {
    assert.equal((appSource.match(new RegExp(field, 'g')) || []).length, 2, `${field} belongs to both create paths`);
  }
  assert.match(clientSource, /listPromptVersions:/);
  assert.match(clientSource, /getPromptVersion:/);
  assert.match(clientSource, /createSinglePromptV2Analysis: \(payload: \{[^}]*prompt_version_id: string; snapshot_hash: string;/);
  assert.match(clientSource, /createSinglePromptV2AnalysisFromRuns: \(payload: \{[\s\S]*prompt_version_id: string; snapshot_hash: string;/);
});

test('the UI obtains the selected version by exact ID and exposes immutable/legacy identity', async () => {
  const [appSource, typeSource] = await Promise.all([readFile(app, 'utf8'), readFile(types, 'utf8')]);
  assert.match(appSource, /api\.getPromptVersion\(projectId, activePromptId, promptVersionId\)/);
  assert.match(appSource, /不会隐式使用 latest/);
  assert.match(appSource, /LEGACY_UNBOUND：历史 Analysis 未绑定 Prompt 版本/);
  assert.match(appSource, /不会被当前 Prompt 重新解释，也不会伪造版本归属/);
  assert.match(typeSource, /binding_status: "BOUND"/);
  assert.match(typeSource, /binding_status: "LEGACY_UNBOUND"/);
});

test('Monitor to Analysis opens only a selection proven bound by the backend', async () => {
  const source = await readFile(observation, 'utf8');
  assert.match(source, /promptVersion\?\.binding_status !== "BOUND"/);
  assert.match(source, /JSON\.stringify\(\{ scope_hash: selection\.scope_hash \}\)/);
  assert.doesNotMatch(source, /prompt_version_id: promptVersion\.prompt_version_id/);
  assert.match(source, /不能用当前或 latest Prompt 替代建立分析/);
  assert.match(source, /disabled=.*binding_status !== "BOUND"/);
});

test('daily sampling schedules bind an exact selected PromptVersion', async () => {
  const source = await readFile(schedule, 'utf8');
  assert.match(source, /api\.listPromptVersions\(projectId, promptId\)/);
  assert.match(source, /api\.getPromptVersion\(projectId, promptId, promptVersionId\)/);
  assert.match(source, /prompt_version_id: selectedPromptVersion\.prompt_version_id/);
  assert.match(source, /snapshot_hash: selectedPromptVersion\.snapshot_hash/);
  assert.match(source, /不会使用 latest/);
  assert.match(source, /disabled=\{!selectedPromptVersion/);
});
